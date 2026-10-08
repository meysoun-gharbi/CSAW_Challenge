"""Recherche de prefixe UART par dictionnaire genere par le cloud.

Idee (proposee par l'equipe): au lieu de faire deviner le modele caractere par
caractere (cher, lent, bete), on separe clairement deux roles:

  - LE CLOUD (rare, cher mais intelligent) PROPOSE un dictionnaire de mots
    candidats (inspires des commandes Linux/CLI/consoles de diagnostic
    courantes), informe de ce qui a deja ete tente et de ce qui a deja ete
    confirme comme prefixe valide.
  - LE CODE (gratuit, instantane) TESTE chaque mot du dictionnaire un par un
    contre l'oracle UART. Tester un mot ne demande AUCUN raisonnement (c'est
    juste "prendre le mot suivant de la liste et l'envoyer"), donc on ne
    paie ni temps ni tokens pour ca.
  - Si AUCUN mot du dictionnaire ne marche, on redemande au cloud un AUTRE
    dictionnaire (different angle, pas de repetition des mots deja testes).
  - Des qu'une commande COMPLETE s'execute (reponse qui n'est ni "one or
    more..." ni "no command..." ni une erreur generique), on s'ARRETE et on
    renvoie cette sortie telle quelle: c'est un indice CTF a interpreter,
    pas a nous d'en decider ici -- la boucle agent principale (qui recoit
    ce resultat comme reponse d'outil) s'en charge au tour suivant.

Cout: au pire 1 appel cloud par dictionnaire epuise (quelques dizaines de
mots testes gratuitement entre deux appels), au lieu d'1 appel LLM par
caractere teste.
"""
from __future__ import annotations

import json
import re

from ..llm.base import LLMClient, Message, ToolSpec

# Patterns connus de l'oracle (observes sur le firmware reel). On reste
# tolerant: si la reponse ne correspond a AUCUN pattern connu d'echec/oracle,
# on la traite comme une execution COMPLETE (hypothese la plus utile: mieux
# vaut remonter une fausse sortie "executee" a l'agent, qui saura dire que ca
# ne ressemble a rien, que de rater une vraie sortie en la classant a tort
# comme 'invalide').
_VALID_RE = re.compile(r"one or more commands start with", re.IGNORECASE)
_INVALID_RE = re.compile(r"no command starts? with", re.IGNORECASE)
# Forme JSON generique observee en pratique sur ce firmware pour un rejet:
# {"event":"error","reason":"unknown_command"} (ou variantes proches).
_JSON_ERROR_HINTS = ("unknown_command", "unknown command", "invalid_command")


def classify_oracle_response(resp_text: str) -> str:
    """Renvoie 'valid' | 'invalid' | 'executed'."""
    if _VALID_RE.search(resp_text):
        return "valid"
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
    "Tu es le STRATEGE d'une recherche de commandes cachees sur une console de "
    "diagnostic embarquee (ESP32, style CTF). La console est un ORACLE DE "
    "PREFIXE: pour une entree X, elle dit si une commande valide COMMENCE par "
    "X ou non. Un execution EN CODE teste tes propositions une par une et te "
    "rapporte ce qui a marche ou non: tu ne dialogues jamais directement avec "
    "la carte, tu proposes seulement des LISTES DE MOTS CANDIDATS via l'outil "
    "propose_dictionary.\n"
    "Inspire-toi des commandes Linux/Unix/BusyBox/CLI de diagnostic reseau et "
    "systeme courantes (ex: help, status, mode, log, config, reset, debug, "
    "admin, info, version, ping, scan, connect, monitor, system, service, "
    "network, wifi, auth, unlock, boot, test, menu, set, get, show, list, "
    "clear, exit, reboot, update, flash, secure, key, token, user, pass, "
    "device, sensor, relay, gpio, adc, i2c, spi, uart, rfid, eeprom, lock, "
    "door, gate, access, grant, deny), ainsi que des options style '--help', "
    "'-h', '-v'. Propose des mots VARIES (pas juste des synonymes les uns des "
    "autres) pour couvrir un large espace. NE REPETE JAMAIS un mot deja tente "
    "(liste fournie). Si un prefixe est deja confirme (fourni), tes mots "
    "doivent ETRE LA SUITE du prefixe (pas le prefixe lui-meme), sauf pour "
    "proposer un espace ' ' (sous-commande) ou un tiret '-'/'--' (option) si "
    "pertinent.\n"
    "Reponds UNIQUEMENT en appelant l'outil propose_dictionary."
)


def propose_dictionary(
    cloud: LLMClient,
    prefix: str,
    tried: list[str],
    attempts_log: list[str],
    n_words: int = 15,
) -> tuple[list[str], str]:
    """Un SEUL appel cloud: demande un dictionnaire de candidats.

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


def probe_extensions(reg, candidate: str) -> dict:
    """Teste structurellement si une commande COMPLETE accepte une sous-commande
    ou une option, selon la grammaire usuelle 'cmd <sous-commande> <--option>'.

    AUCUN appel LLM: ce ne sont pas des mots a deviner (contenu), juste la
    syntaxe generique (espace -> sous-commande, '-'/'--' -> option) que toute
    CLI respecte. Cout: jusqu'a 3 requetes UART de plus par commande trouvee.
    """
    extensions: dict[str, dict] = {}
    for ext, label in ((" ", "subcommand"), (" -", "short_option"), (" --", "long_option")):
        candidate_ext = candidate + ext
        result = reg.execute("uart_send", {"command": candidate_ext})
        resp_text = result.get("response", "") if isinstance(result, dict) else ""
        kind = classify_oracle_response(resp_text)
        extensions[label] = {"prefix": candidate_ext, "available": kind == "valid"}
    return extensions


def run_dictionary_search(
    reg,  # ToolRegistry (import circulaire si type-hinte depuis tools.base)
    cloud: LLMClient,
    start_prefix: str = "",
    max_rounds: int = 6,
    n_words_per_round: int = 15,
    verbose: bool = True,
) -> dict:
    """Boucle principale. Renvoie un dict structure pour l'agent appelant.

    Statuts possibles:
      - 'executed'  : une commande COMPLETE a produit une vraie sortie
                       (output = cette sortie, a INTERPRETER cote appelant:
                       elle peut contenir un indice/flag).
      - 'flag'      : un flag a ete detecte directement dans une reponse.
      - 'exhausted' : plus aucune idee apres max_rounds dictionnaires sans
                       confirmer de nouveau prefixe (suggere p.ex. de tenter
                       wifi_scan/l'authentification avant de reessayer).
    """
    def log(msg: str) -> None:
        if verbose:
            print(f"      [dict-search] {msg}", flush=True)

    prefix = start_prefix
    tried: set[str] = set()
    attempts_log: list[str] = []
    rounds_without_progress = 0

    while rounds_without_progress < max_rounds:
        words, rationale = propose_dictionary(
            cloud, prefix, sorted(tried), attempts_log, n_words_per_round
        )
        if not words:
            log(f"cloud n'a propose aucun mot ({rationale}); abandon")
            break
        log(f"dictionnaire ({len(words)} mots) — {rationale}")

        progressed_this_round = False
        for word in words:
            if word in tried:
                continue
            tried.add(word)
            candidate = prefix + word
            result = reg.execute("uart_send", {"command": candidate})
            resp_text = result.get("response", "") if isinstance(result, dict) else ""

            if isinstance(result, dict) and result.get("flag_detected"):
                log(f"FLAG detecte sur {candidate!r}")
                return {"ok": True, "status": "flag",
                        "flag": result["flag_detected"], "command": candidate}

            kind = classify_oracle_response(resp_text)
            log(f"{candidate!r} -> {kind} ({resp_text[:80]!r})")
            attempts_log.append(f"{candidate!r} -> {kind}: {resp_text[:120]!r}")

            if kind == "valid":
                prefix = candidate
                tried = set()
                progressed_this_round = True
                rounds_without_progress = 0
                log(f"PREFIXE CONFIRME -> {prefix!r}")
                break  # nouveau dictionnaire pour ce prefixe plus profond
            elif kind == "executed":
                extensions = probe_extensions(reg, candidate)
                available = [v["prefix"] for v in extensions.values() if v["available"]]
                note = ("Commande COMPLETE executee: lis cette sortie attentivement, "
                        "elle peut contenir un indice ou la suite a suivre.")
                if available:
                    note += (" ATTENTION: cette commande accepte AUSSI une suite "
                             f"(sous-commande/option) -- grammaire 'cmd <sous-commande> "
                             f"<--option>' -- prefixes detectes comme valides: "
                             f"{available!r}. Rappelle oracle_dictionary_search avec "
                             f"prefix=l'un de ces prefixes pour explorer plus loin "
                             f"AVANT de considerer cette commande comme terminale.")
                else:
                    note += (" Aucune sous-commande/option detectee juste apres "
                             "(espace/-/-- testes): cette commande semble terminale.")
                log(f"extensions testees pour {candidate!r}: {extensions}")
                return {
                    "ok": True, "status": "executed",
                    "command": candidate, "output": resp_text,
                    "extensions": extensions, "note": note,
                }
            # 'invalid' -> on continue avec le mot suivant du dictionnaire

        if not progressed_this_round:
            rounds_without_progress += 1

    return {
        "ok": True, "status": "exhausted", "prefix": prefix,
        "tried_count": len(tried),
        "note": "Aucun nouveau prefixe confirme apres plusieurs dictionnaires. "
                "Peut-etre qu'une etape prealable est requise (ex: "
                "authentification via wifi_scan) avant que l'oracle ne "
                "reponde normalement.",
    }
