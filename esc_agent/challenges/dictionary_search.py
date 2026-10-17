"""Recherche de prefixe UART — moteur DFS caractere-par-caractere GRATUIT
(code), avec retour en arriere automatique sur les leurres, cloud en filet
de secours rare.

Historique des deux bugs empiriques qui ont motive cette version (runs du
17/10, modele gemini-flash-lite-latest):

1) Demander au cloud des DICTIONNAIRES DE MOTS ENTIERS a devine 19 mots de
   suite sans qu'aucun ne marche. Raison structurelle, pas de la malchance:
   sur un ORACLE DE PREFIXE, si prefixe+MOT est valide pour un mot entier,
   alors prefixe+MOT[0] (son 1er caractere seul) est TOUJOURS valide aussi
   -- avancer un caractere a la fois est donc GARANTI de trouver la suite
   si elle existe, alors que deviner un mot entier est un pari qui peut
   echouer indefiniment. -> moteur caractere-par-caractere (quick_extend,
   version 1).

2) Cette version 1 s'arretait au PREMIER caractere qui prolonge un niveau
   et ne revenait JAMAIS en arriere. Resultat observe en live: 'h' prolonge
   en 'help', qui s'avere etre un leurre ('This help menu is outdated...')
   -- mais comme le code ne testait plus JAMAIS 'l', 's', 'm', etc. au
   niveau racine (il s'etait arrete au premier 'h' qui marchait), l'AGENT
   (LLM) a du deviner lui-meme d'autres lettres de depart ('s', 'c', 'f',
   'd') pour continuer a chercher -- gaspillant des dizaines de requetes a
   chaque mauvaise lettre devinee (si la lettre elle-meme n'etait pas un
   prefixe valide, TOUT l'alphabet etait quand meme teste en vain derriere).

Architecture retenue (DFS complet, backtrack automatique, zero appel LLM
intermediaire):
  - A chaque niveau, on teste TOUS les candidats de `_PRIORITY_CHARS` dans
    l'ordre de priorite; pour CHAQUE candidat valide, on descend
    recursivement. Si la branche s'avere un cul-de-sac (leurre explicite,
    ou aucune sortie), on CONTINUE la boucle du niveau courant avec le
    candidat SUIVANT au lieu de remonter a l'agent -- exactement ce qu'un
    humain ferait ("ok 'help' c'est du vent, je retourne essayer autre
    chose depuis la racine", sans avoir besoin qu'on le lui dise).
  - Le cloud (rare, cher mais intelligent) n'intervient QUE dans le cas
    pathologique ou meme l'alphabet complet ne prolonge rien depuis le
    prefixe vide ET qu'aucune branche n'a produit le moindre contenu.
  - On ne remonte a l'agent QUE sur: un flag detecte, OU une sortie
    'executee' qui n'a pas le vocabulaire d'un leurre explicite (quelque
    chose a potentiellement interpreter), OU un epuisement total.

Cout attendu: 0 appel LLM pour tout le graphe de recherche (peu importe sa
taille ou son nombre de leurres); le nombre de requetes UART reste le seul
cout, et chaque requete fait soit progresser une branche, soit l'elimine
definitivement (jamais retestee).
"""
from __future__ import annotations

import json
import re

from ..llm.base import LLMClient, Message, ToolSpec

# Patterns connus de l'oracle (observes sur le firmware reel).
_VALID_RE = re.compile(r"one or more commands start with", re.IGNORECASE)
_INVALID_RE = re.compile(r"no command starts? with", re.IGNORECASE)
# Forme JSON generique observee en pratique sur ce firmware pour un rejet:
# {"event":"error","reason":"unknown_command"} (ou variantes proches).
_JSON_ERROR_HINTS = ("unknown_command", "unknown command", "invalid_command")

# Vocabulaire explicite de LEURRE observe sur le firmware reel ('help' dit
# "this help menu is outdated... reorganized"). Quand une sortie "executee"
# contient ces mots ET qu'aucune extension ne la prolonge, on backtrack en
# SILENCE (zero appel agent) plutot que de considerer la branche terminee.
_DECOY_WORDS = ("outdated", "legacy", "deprecated", "reorganized", "obsolete")

# Ordre de priorite (frequence d'usage reelle en CLI/Linux/BusyBox, PAS
# alphabetique) pour le balayage caractere-par-caractere, PLUS les chiffres
# (le firmware reel utilise des commandes comme 'log37'). Les separateurs
# passent en dernier (ils marquent plutot une fin/transition de commande).
_PRIORITY_CHARS: list[str] = (
    list("hlsmcrditevpabuwnogqkfjxyz") + list("0123456789") + [" ", "!", "@", "-", "_"]
)

# Combien d'echecs consecutifs avant un reboot GRATUIT (ne compte pas comme
# requete) pour eviter que la penalite de rate-limit ne plafonne pendant
# tout le balayage, qui peut couvrir un grand nombre de niveaux/branches.
_REBOOT_EVERY = 8


def _is_decoy(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in _DECOY_WORDS)


def _has_extra_output(resp_text: str) -> bool:
    """Vrai si la reponse contient du texte EN PLUS de la simple ligne de
    confirmation d'oracle ('one or more commands start with ...').

    Observe sur le firmware reel: 'help' renvoie A LA FOIS la confirmation
    de prefixe valide ET un vrai texte explicatif derriere (menu d'aide
    perime). C'est le signe qu'on vient d'EXECUTER une commande COMPLETE,
    pas juste confirme un prefixe intermediaire.
    """
    lines = [l for l in resp_text.splitlines() if l.strip()]
    if not lines or not _VALID_RE.search(lines[0]):
        return False
    return len(lines) > 1


def classify_oracle_response(resp_text: str) -> str:
    """Renvoie 'valid' | 'invalid' | 'executed'.

    Une reponse VIDE (ou faite uniquement de blancs) est traitee comme
    'invalid', pas 'executed': observe en pratique, une reponse vide
    correspond a un glitch de lecture UART (carte qui redemarre, etc.),
    jamais a une vraie commande qui "s'execute silencieusement". La traiter
    comme 'executed' creait des branches fantomes (ex: 'mode developeh')
    construites sur du bruit, jamais de vraies commandes.

    'executed' couvre aussi le cas "double nature": prefixe confirme valide
    MAIS avec un vrai texte de sortie derriere (voir `_has_extra_output`).
    """
    if not resp_text.strip():
        return "invalid"
    if _VALID_RE.search(resp_text):
        return "executed" if _has_extra_output(resp_text) else "valid"
    if _INVALID_RE.search(resp_text):
        return "invalid"
    # essaie de parser du JSON generique d'erreur (le firmware ne suit pas
    # toujours le format texte documente)
    stripped = resp_text.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except Exception:  # noqa: BLE001
            data = None
        if isinstance(data, dict):
            blob = json.dumps(data).lower()
            if any(h in blob for h in _JSON_ERROR_HINTS):
                return "invalid"
            if data.get("event") == "error":
                return "invalid"
    return "executed"


_DICTIONARY_TOOL = ToolSpec(
    name="propose_dictionary",
    description=(
        "Propose une liste de mots/chaines candidats a tester contre un oracle "
        "de prefixe UART (console de diagnostic embarquee), du plus probable au "
        "moins probable."
    ),
    parameters={
        "type": "object",
        "properties": {
            "words": {
                "type": "array",
                "items": {"type": "string"},
                "description": "10 a 20 candidats: mots complets, commandes "
                               "Linux/BusyBox/CLI courantes, options (--xxx), etc.",
            },
            "rationale": {"type": "string", "description": "justification breve"},
        },
        "required": ["words"],
    },
)

_PLANNER_SYSTEM = (
    "Tu es sollicite en DERNIER RECOURS: une recherche caractere-par-caractere "
    "EXHAUSTIVE (gratuite, deterministe, avec retour en arriere automatique) "
    "vient d'echouer a trouver QUOI QUE CE SOIT depuis le prefixe vide sur un "
    "ORACLE DE PREFIXE UART embarque (ESP32, style CTF) -- situation tres rare "
    "et anormale. Propose des idees DIFFERENTES (mots entiers varies, pas des "
    "lettres isolees deja testees) qui pourraient debloquer la recherche. "
    "NE REPETE JAMAIS un mot deja tente (liste fournie). "
    "Reponds UNIQUEMENT en appelant l'outil propose_dictionary."
)


def propose_dictionary(
    cloud: LLMClient,
    prefix: str,
    tried: list[str],
    attempts_log: list[str],
    n_words: int = 15,
) -> tuple[list[str], str]:
    """Un SEUL appel cloud: demande un dictionnaire de candidats (secours rare).

    Renvoie (mots, rationale). En cas d'echec du parsing/appel, renvoie une
    liste vide (l'appelant decidera d'abandonner ou de relancer).
    """
    ctx = (
        f"Prefixe actuellement confirme: {prefix!r} (chaine vide = rien de confirme).\n"
        f"Mots DEJA TENTES a ce niveau de prefixe (NE PAS REPETER): {sorted(tried)!r}\n"
        f"Historique recent des tentatives (le plus recent en dernier):\n"
        + ("\n".join(attempts_log[-20:]) or "(aucun)")
        + f"\n\nPropose {n_words} nouveaux mots candidats, varies, non deja tentes."
    )
    history = [Message(role="user", text=ctx)]
    try:
        resp = cloud.step(_PLANNER_SYSTEM, history, [_DICTIONARY_TOOL])
    except Exception as exc:  # noqa: BLE001
        return [], f"erreur cloud: {exc}"
    for tc in resp.tool_calls:
        if tc.name == "propose_dictionary":
            words = tc.arguments.get("words") or []
            words = [w for w in (str(w).strip() for w in words) if w]
            return words, str(tc.arguments.get("rationale", ""))
    return [], "le cloud n'a pas appele propose_dictionary"


class _RebootBudget:
    """Compteur d'echecs consecutifs partage sur tout le DFS (une seule
    pile d'appels recursifs): declenche un reboot gratuit tous les
    `_REBOOT_EVERY` echecs, peu importe a quelle profondeur ils arrivent."""

    def __init__(self, reg):
        self._reg = reg
        self._fails = 0

    def fail(self) -> None:
        self._fails += 1
        if self._fails >= _REBOOT_EVERY:
            self._reg.execute("reboot", {})
            self._fails = 0

    def ok(self) -> None:
        pass  # le compteur n'est remis a zero QUE par un vrai reboot


def _dfs(reg, prefix: str, confirmed_text: str | None, budget: _RebootBudget,
          log) -> dict | None:
    """Explore recursivement depuis `prefix` (deja confirme valide par
    l'appelant). `confirmed_text` est la derniere reponse connue POUR CE
    PREFIXE EXACT si elle contenait une sortie reelle (double nature),
    sinon None (simple marqueur de prefixe intermediaire sans sortie propre).

    Renvoie un dict FINAL a remonter a l'agent (flag, ou sortie 'executed'
    non-leurre), ou None si TOUTE cette branche est morte (leurre ou vide)
    -- dans ce cas l'appelant doit continuer SON PROPRE balayage avec le
    candidat suivant (backtrack automatique, zero appel agent).
    """
    for ch in _PRIORITY_CHARS:
        candidate = prefix + ch
        result = reg.execute("uart_send", {"command": candidate})
        resp_text = result.get("response", "") if isinstance(result, dict) else ""
        if isinstance(result, dict) and result.get("flag_detected"):
            log(f"{candidate!r} -> FLAG: {resp_text[:120]!r}")
            return {"status": "flag", "flag": result["flag_detected"], "command": candidate}
        kind = classify_oracle_response(resp_text)
        log(f"{candidate!r} -> {kind}: {resp_text[:120]!r}")
        if kind == "invalid":
            budget.fail()
            continue
        budget.ok()
        sub = _dfs(reg, candidate, resp_text if kind == "executed" else None, budget, log)
        if sub is not None:
            return sub  # flag ou sortie interessante plus profond: on remonte tout de suite
        # sub is None: cette branche est MORTE (leurre/vide) -> backtrack
        # SILENCIEUX, on continue la boucle avec le candidat suivant.
        log(f"{candidate!r}: branche morte (leurre/vide) -> retour en arriere, "
            f"essai du candidat suivant")

    # Plus aucun candidat ne prolonge `prefix`.
    if confirmed_text is not None:
        if _is_decoy(confirmed_text):
            log(f"{prefix!r}: sortie 'leurre' (vocabulaire outdated/legacy/...), "
                f"backtrack silencieux")
            return None  # rien d'interessant ici, l'appelant continue son balayage
        return {"status": "executed", "command": prefix, "output": confirmed_text}
    # `prefix` n'a lui-meme produit aucune sortie (simple marqueur de
    # prefixe intermediaire) ET rien ne le prolonge -> cul-de-sac silencieux.
    return None


def run_dictionary_search(
    reg,  # ToolRegistry (import circulaire si type-hinte depuis tools.base)
    cloud: LLMClient,
    start_prefix: str = "",
    max_rounds: int = 6,
    n_words_per_round: int = 15,
    verbose: bool = True,
) -> dict:
    """Point d'entree. Renvoie un dict structure pour l'agent appelant.

    Statuts possibles:
      - 'executed'      : une commande COMPLETE a produit une vraie sortie
                           NON-LEURRE (output = cette sortie, a INTERPRETER
                           cote appelant: elle peut contenir un indice/flag).
      - 'flag'          : un flag a ete detecte directement dans une reponse.
      - 'invalid_prefix': le `prefix` DONNE PAR L'APPELANT n'est lui-meme pas
                           un prefixe valide -- inutile de chercher a le
                           prolonger (un prefixe d'un prefixe valide est
                           toujours valide: si celui-ci ne l'est pas, rien
                           ne le prolongera). Rappelle avec un AUTRE prefixe
                           (ou vide, pour une recherche complete depuis le
                           debut).
      - 'exhausted'     : recherche COMPLETE depuis `start_prefix` (tout
                           l'arbre atteignable a ete explore avec retour en
                           arriere automatique) sans rien trouver d'autre
                           qu'eventuellement des leurres explicites.
    """
    def log(msg: str) -> None:
        if verbose:
            print(f"      [dict-search] {msg}", flush=True)

    confirmed_text: str | None = None
    if start_prefix:
        # Le prefixe donne par l'appelant doit D'ABORD etre confirme valide:
        # s'il ne l'est pas, tout balayage de ses extensions est garanti
        # inutile (un prefixe d'un prefixe valide est toujours valide).
        result = reg.execute("uart_send", {"command": start_prefix})
        resp_text = result.get("response", "") if isinstance(result, dict) else ""
        if isinstance(result, dict) and result.get("flag_detected"):
            return {"ok": True, "status": "flag", "flag": result["flag_detected"],
                    "command": start_prefix}
        kind = classify_oracle_response(resp_text)
        if kind == "invalid":
            log(f"prefixe donne {start_prefix!r} -> invalid: abandon immediat "
                f"(aucune extension n'a de sens)")
            return {"ok": True, "status": "invalid_prefix", "prefix": start_prefix,
                    "note": "Ce prefixe n'est lui-meme pas valide (l'oracle dit "
                            "'no command starts with ...'): inutile d'en tester les "
                            "extensions, un prefixe d'un prefixe valide est toujours "
                            "valide. Rappelle avec prefix='' pour une recherche complete "
                            "(elle explore tout l'arbre et revient en arriere toute "
                            "seule), ou avec un prefixe DEJA confirme valide."}
        if kind == "executed":
            confirmed_text = resp_text

    budget = _RebootBudget(reg)
    result = _dfs(reg, start_prefix, confirmed_text, budget, log)

    if result is not None:
        if result["status"] == "flag":
            log(f"FLAG detecte sur {result['command']!r}")
            return {"ok": True, **result}
        note = ("Commande COMPLETE executee (recherche exhaustive, retour en "
                "arriere automatique sur les leurres deja fait cote code): lis "
                "cette sortie attentivement, elle peut contenir un indice ou la "
                "suite a suivre.")
        return {"ok": True, "status": "executed", "command": result["command"],
                "output": result["output"], "note": note}

    # Toute la branche depuis start_prefix est morte (leurres/vide partout).
    if not start_prefix:
        # Cas pathologique rarissime: meme l'arbre COMPLET depuis le prefixe
        # vide n'a rien donne d'autre que des leurres. Secours cloud.
        log("recherche exhaustive depuis le prefixe vide: rien d'autre que des "
            "leurres -> secours cloud")
        tried: set[str] = set()
        attempts_log: list[str] = []
        rounds_without_progress = 0
        while rounds_without_progress < max_rounds:
            words, rationale = propose_dictionary(
                cloud, "", sorted(tried), attempts_log, n_words_per_round
            )
            if not words:
                log(f"cloud n'a propose aucun mot ({rationale}); abandon")
                break
            log(f"dictionnaire secours ({len(words)} mots) — {rationale}")
            progressed = False
            for word in words:
                if word in tried:
                    continue
                tried.add(word)
                res = reg.execute("uart_send", {"command": word})
                resp_text = res.get("response", "") if isinstance(res, dict) else ""
                if isinstance(res, dict) and res.get("flag_detected"):
                    log(f"FLAG detecte sur {word!r}")
                    return {"ok": True, "status": "flag",
                            "flag": res["flag_detected"], "command": word}
                kind = classify_oracle_response(resp_text)
                attempts_log.append(f"{word!r} -> {kind}: {resp_text[:120]!r}")
                if kind in ("valid", "executed"):
                    sub = _dfs(reg, word, resp_text if kind == "executed" else None,
                               budget, log)
                    if sub is not None:
                        if sub["status"] == "flag":
                            return {"ok": True, **sub}
                        return {"ok": True, "status": "executed",
                                "command": sub["command"], "output": sub["output"],
                                "note": "Commande COMPLETE executee (trouvee via le "
                                        "secours cloud apres une recherche exhaustive "
                                        "infructueuse): lis cette sortie attentivement."}
                    progressed = True  # au moins un prefixe confirme, meme si mort derriere
            if progressed:
                break
            rounds_without_progress += 1
        return {"ok": True, "status": "exhausted", "prefix": "",
                "note": "Recherche EXHAUSTIVE (tout l'arbre, retour en arriere "
                        "automatique) et secours cloud: rien trouve d'autre que des "
                        "leurres explicites. Essaie une autre piste (ex: wifi_scan)."}

    return {"ok": True, "status": "exhausted", "prefix": start_prefix,
            "note": f"Recherche exhaustive depuis {start_prefix!r} (retour en "
                    "arriere automatique): rien trouve d'autre que des leurres "
                    "explicites sous ce prefixe. Essaie un AUTRE prefixe (ou "
                    "prefix='' pour repartir d'une recherche complete)."}
