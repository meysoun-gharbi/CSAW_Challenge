"""Backend hybride: local (gratuit) en primaire, cloud en secours (fiable).

Principe (cascade de confiance, pas de vote ni de parallele):
  - chaque pas tente d'abord le client LOCAL (ex: Ollama) -> cout zero ;
  - si le local echoue (serveur injoignable, exception) OU renvoie une reponse
    "faible" (aucun appel d'outil -> signe classique qu'un petit modele local
    decroche sur un pas difficile), on ESCALADE ce pas au client CLOUD
    (Gemini/Claude), plus fiable mais payant ;
  - apres plusieurs echecs locaux consecutifs, on arrete d'essayer le local
    pour le reste du run (evite de perdre du temps sur un serveur mort) et on
    reste sur le cloud jusqu'a la fin.

Resultat attendu: la majorite des pas (exploration, requetes repetitives)
restent gratuits; seuls les pas qui comptent vraiment (deduction finale,
format d'appel d'outil complexe) consomment du budget API. A mesurer dans le
rapport via le champ `model` de chaque evenement `llm_call` du JSONL: il
reflete le backend REELLEMENT utilise a chaque pas (local ou cloud), donc
`grep '"type": "llm_call"'` + comptage par `model` donne le ratio local/cloud
d'un run.

Le cloud "dicte" au local (sans appel supplementaire dedie): agent.py
partage UN SEUL historique entre les deux backends. Quand le cloud
escalade, son raisonnement ET son appel d'outil rejoignent cet
historique commun; au pas suivant, le local VOIT ce que le cloud vient
de decider et pourquoi, et n'a qu'a continuer dans cette direction
plutot que de re-deduire seul. On rend ce mecanisme explicite en
demandant au cloud, uniquement quand il escalade, de laisser une note
de suite courte a l'attention du modele plus faible qui reprend la
main.

ISOLE A DESSEIN: ce fichier ne fait QUE de l'orchestration entre deux
LLMClient deja construits; aucune logique specifique a un fournisseur ici.
"""
from __future__ import annotations

from typing import Callable

from .base import LLMClient, LLMResponse, Message, ToolSpec

# Ajoute au system prompt UNIQUEMENT pour l'appel cloud d'escalade. Le but:
# le cloud ne doit pas juste "faire le travail et repartir" -- il doit laisser
# une trace de raisonnement exploitable, car un modele local plus faible
# reprendra la main au pas suivant via l'historique partage (voir agent.py).
_HANDOFF_SUFFIX = (
    "\n\n[Mode hybride] Tu interviens car un modele local plus simple a echoue "
    "sur ce pas. En plus d'appeler l'outil necessaire, explique en 1-2 phrases "
    "COURTES ton raisonnement et ce qu'il faut tenter ensuite: un modele plus "
    "faible reprendra la main au pas suivant et doit pouvoir suivre ton plan "
    "sans re-deduire seul."
)


class HybridClient(LLMClient):
    name = "hybrid"

    def __init__(
        self,
        local: LLMClient,
        cloud_factory: Callable[[], LLMClient],
        max_consecutive_local_failures: int = 3,
        verbose: bool = True,
    ):
        self._local = local
        # construction PARESSEUSE: si le local suffit pour tout le run, on ne
        # construit jamais le client cloud (pas besoin du SDK/cle API installes).
        self._cloud_factory = cloud_factory
        self._cloud: LLMClient | None = None
        self._max_fail = max_consecutive_local_failures
        self._verbose = verbose
        self._consecutive_failures = 0
        self._local_disabled = False  # bascule definitive si le local meurt
        # label composite, visible dans les metriques/transcripts
        self.model = f"hybrid[local={local.model}|cloud=lazy]"

        # compteurs pour le resume de fin de run (pas dans RunSummary standard,
        # donc on les expose ici; run_challenge1.py peut les lire apres coup)
        self.local_steps = 0
        self.cloud_steps = 0

    def _get_cloud(self) -> LLMClient:
        if self._cloud is None:
            self._log("premiere escalade -> construction du client cloud")
            self._cloud = self._cloud_factory()
            self.model = f"hybrid[local={self._local.model}|cloud={self._cloud.model}]"
        return self._cloud

    def _log(self, msg: str) -> None:
        if self._verbose:
            print(f"      [hybride] {msg}", flush=True)

    def _try_local(self, system: str, history: list[Message], tools: list[ToolSpec]):
        try:
            resp = self._local.step(system, history, tools)
        except Exception as exc:  # noqa: BLE001 - le local doit pouvoir echouer sans casser le run
            self._consecutive_failures += 1
            self._log(f"local en echec ({exc}); "
                      f"echecs consecutifs={self._consecutive_failures}/{self._max_fail}")
            if self._consecutive_failures >= self._max_fail:
                self._local_disabled = True
                self._log("local desactive pour le reste du run -> bascule 100% cloud")
            return None

        if not resp.tool_calls:
            # reponse "faible": le petit modele local n'a pas suivi la consigne
            # d'appeler un outil -> on prefere escalader plutot que de gaspiller
            # un pas de max_steps sur une reponse inexploitable.
            self._consecutive_failures += 1
            self._log(f"local sans appel d'outil (reponse faible); "
                      f"echecs consecutifs={self._consecutive_failures}/{self._max_fail}")
            if self._consecutive_failures >= self._max_fail:
                self._local_disabled = True
                self._log("local desactive pour le reste du run -> bascule 100% cloud")
            return None

        self._consecutive_failures = 0
        return resp

    def step(self, system: str, history: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        if not self._local_disabled:
            resp = self._try_local(system, history, tools)
            if resp is not None:
                self.local_steps += 1
                return resp
            self._log("escalade ce pas vers le cloud")

        cloud = self._get_cloud()
        resp = cloud.step(system + _HANDOFF_SUFFIX, history, tools)
        self.cloud_steps += 1
        return resp
