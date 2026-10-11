"""Backend 'cloud_fallback': Gemini (gratuit, quota limite) en primaire,
DeepSeek (payant mais tres bon marche) en secours.

Principe (cascade de confiance, meme esprit que hybrid.py mais entre DEUX
backends cloud au lieu de local/cloud):
  - chaque pas tente d'abord Gemini -> gratuit (tier gratuit AI Studio) ;
  - gemini.py retente deja lui-meme en interne (429/500/502/503) avant de
    lever une exception: si l'exception remonte ici, c'est que le quota est
    VRAIMENT epuise (ou panne prolongee), pas la peine de reessayer encore ;
  - on ESCALADE alors ce pas vers DeepSeek, qui prend le relais ;
  - apres plusieurs echecs Gemini consecutifs, on arrete d'essayer Gemini
    pour le reste du run (evite de perdre du temps a retenter un quota mort)
    et on reste sur DeepSeek jusqu'a la fin.

Objectif budget: la quasi-totalite des appels restent gratuits (Gemini);
DeepSeek n'est sollicite (et facture, ~$0.14/M tokens input) que lorsque le
quota gratuit est epuise -- ce qui, avec le role de 'stratege' peu sollicite
du mode hybride (voir hybrid.py / oracle_dictionary_search), devrait rester
rare. A mesurer dans le rapport via le champ `model` de chaque evenement
`llm_call` du JSONL, comme pour hybrid.py.

ISOLE A DESSEIN: ce fichier ne fait QUE de l'orchestration entre deux
LLMClient deja construits; aucune logique specifique a un fournisseur ici.
"""
from __future__ import annotations

from typing import Callable

from .base import LLMClient, LLMResponse, Message, ToolSpec


class CloudFallbackClient(LLMClient):
    name = "cloud_fallback"

    def __init__(
        self,
        primary: LLMClient,
        fallback_factory: Callable[[], LLMClient],
        max_consecutive_primary_failures: int = 2,
        verbose: bool = True,
    ):
        self._primary = primary
        # construction PARESSEUSE: si le quota gratuit suffit pour tout le run,
        # on ne construit jamais le client DeepSeek (pas besoin de sa cle API).
        self._fallback_factory = fallback_factory
        self._fallback: LLMClient | None = None
        self._max_fail = max_consecutive_primary_failures
        self._verbose = verbose
        self._consecutive_failures = 0
        self._primary_disabled = False  # bascule definitive si le quota est mort
        self.model = f"cloud_fallback[primary={primary.model}|fallback=lazy]"

        # compteurs pour le resume de fin de run (meme convention que hybrid.py)
        self.local_steps = 0   # alias: pas servis par le primaire (gratuit)
        self.cloud_steps = 0   # alias: pas servis par le secours (payant)

    def _get_fallback(self) -> LLMClient:
        if self._fallback is None:
            self._log("quota primaire epuise -> construction du client de secours")
            self._fallback = self._fallback_factory()
            self.model = f"cloud_fallback[primary={self._primary.model}|fallback={self._fallback.model}]"
        return self._fallback

    def _log(self, msg: str) -> None:
        if self._verbose:
            print(f"      [cloud-fallback] {msg}", flush=True)

    def _try_primary(self, system: str, history: list[Message], tools: list[ToolSpec]):
        try:
            resp = self._primary.step(system, history, tools)
        except Exception as exc:  # noqa: BLE001 - le primaire doit pouvoir echouer sans casser le run
            self._consecutive_failures += 1
            self._log(f"primaire en echec ({exc}); "
                      f"echecs consecutifs={self._consecutive_failures}/{self._max_fail}")
            if self._consecutive_failures >= self._max_fail:
                self._primary_disabled = True
                self._log("primaire desactive pour le reste du run -> bascule 100% secours")
            return None
        self._consecutive_failures = 0
        return resp

    def step(self, system: str, history: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        if not self._primary_disabled:
            resp = self._try_primary(system, history, tools)
            if resp is not None:
                self.local_steps += 1
                return resp
            self._log("escalade ce pas vers le secours (DeepSeek)")

        fallback = self._get_fallback()
        resp = fallback.step(system, history, tools)
        self.cloud_steps += 1
        return resp
