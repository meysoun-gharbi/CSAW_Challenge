"""Recherche de prefixe UART — moteur caractere-par-caractere GRATUIT (code),
cloud en filet de secours rare.

Constat empirique (run du 17/10, modele gemini-flash-lite-latest): demander
au cloud des DICTIONNAIRES DE MOTS ENTIERS a devine' 19 mots de suite sans
qu'aucun ne marche, en faisant grimper la penalite de rate-limit pour rien.

Raison structurelle (pas juste de la malchance): sur un ORACLE DE PREFIXE,
si "help"+MOT est une commande valide pour un mot entier MOT, alors
"help"+MOT[0] (son seul 1er caractere) est TOUJOURS valide aussi — un
prefixe d'un prefixe valide reste un prefixe valide. Deviner un mot entier
d'un coup est donc un PARI qui peut echouer indefiniment, alors qu'avancer
UN SEUL CARACTERE a la fois, dans un bon ordre de priorite (lettres les
plus frequentes en CLI/Linux, puis separateurs), est GARANTI de trouver la
suite si elle existe (au plus ~32 essais par niveau, l'alphabet autorise
etant petit: a-z + espace + ! @ - _).

Architecture retenue (fusion des deux approches precedentes):
  - MOTEUR PRINCIPAL = extension caractere-par-caractere, en CODE (fonction
    `quick_extend`), ZERO appel LLM, peu importe le nombre de caracteres
    testes. C'est la methode qu'un humain ferait en CTF (teste les lettres
    les plus evidentes, verrouille la bonne, prolonge), mais executee en
    boucle par le code au lieu de couter 1 appel cloud par caractere.
  - LE CLOUD (rare, cher mais intelligent) n'intervient QUE dans le cas
    pathologique ou meme l'alphabet complet ne prolonge rien depuis le
    prefixe vide (situation qui ne devrait normalement jamais arriver sur
    cet oracle) — comme idee de secours, pas comme strategie principale.
  - Des qu'une commande COMPLETE s'execute (plus aucun caractere ne la
    prolonge), on teste sa grammaire 'cmd <sous-commande> <--option>'
    (`probe_extensions`, deja gratuite) puis on remonte sa sortie telle
    quelle a l'agent appelant: c'est un indice CTF a interpreter, pas a
    nous d'en decider ici.

Cout attendu: 0 appel LLM dans l'immense majorite des cas (le cloud ne sert
plus que de filet de secours quasi jamais sollicite); le nombre de requetes
UART reste petit car chaque caractere teste fait soit progresser le prefixe,
soit elimine definitivement une piste.
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

# Ordre de priorite (frequence d'usage reelle en CLI/Linux/BusyBox, PAS
# alphabetique) pour le balayage caractere-par-caractere. Repris du system
# prompt de serial_gateway.py, PLUS les chiffres: le firmware reel utilise
# des commandes comme 'log37' (observe lors d'un run precedent) -- les
# oublier rendrait ce moteur INCOMPLET. Les chiffres passent apres les
# lettres (moins frequents en 1ere position de mot) mais avant les
# separateurs (qui marquent plutot une fin/transition de commande).
_PRIORITY_CHARS: list[str] = (
    list("hlsmcrditevpabuwnogqkfjxyz") + list("0123456789") + [" ", "!", "@", "-", "_"]
)


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
    "Tu es sollicite en DERNIER RECOURS: une recherche caractere-par-caractere "
    "(gratuite, deterministe) vient d'echouer a prolonger un prefixe sur un "
    "ORACLE DE PREFIXE UART embarque (ESP32, style CTF) -- situation rare et "
    "anormale, car normalement tout caractere valide prolonge un prefixe deja "
    "confirme. Propose des idees DIFFERENTES (mots entiers varies, pas des "
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


def quick_extend(reg, prefix: str) -> tuple[dict | None, list[str]]:
    """Essaie de prolonger `prefix` d'UN caractere, en code, ZERO appel LLM.

    Teste les candidats de `_PRIORITY_CHARS` (lettres les plus frequentes en
    CLI/Linux d'abord, puis separateurs) dans l'ordre, s'arrete au premier
    qui prolonge effectivement le prefixe (reponse 'valid' ou 'executed').

    Renvoie (resultat, log_des_tentatives):
      - resultat=None               : AUCUN caractere ne prolonge `prefix`
                                       (donc `prefix` est deja une commande
                                       COMPLETE: plus rien a y ajouter).
      - resultat={'flag': ...}      : flag trouve directement.
      - resultat={'prefix','kind','text'} : nouveau prefixe plus profond
                                       ('kind' == 'valid' -> continuer a
                                       prolonger; 'kind' == 'executed' ->
                                       commande complete trouvee directement).
    """
    # Balayer jusqu'a ~31 caracteres par niveau peut faire grimper la penalite
    # de rate-limit du firmware au plafond. `reboot` ne compte PAS comme une
    # requete (voir register_tools): on en profite pour la remettre a zero
    # regulierement, ce qui garde le balayage rapide sans jamais fausser le
    # compteur de requetes utilise pour la metrique d'efficacite.
    _REBOOT_EVERY = 8
    attempts: list[str] = []
    fails_since_reboot = 0
    for ch in _PRIORITY_CHARS:
        candidate = prefix + ch
        result = reg.execute("uart_send", {"command": candidate})
        resp_text = result.get("response", "") if isinstance(result, dict) else ""
        if isinstance(result, dict) and result.get("flag_detected"):
            attempts.append(f"{candidate!r} -> FLAG: {resp_text[:120]!r}")
            return {"flag": result["flag_detected"], "command": candidate}, attempts
        kind = classify_oracle_response(resp_text)
        attempts.append(f"{candidate!r} -> {kind}: {resp_text[:120]!r}")
        if kind in ("valid", "executed"):
            return {"prefix": candidate, "kind": kind, "text": resp_text}, attempts
        fails_since_reboot += 1
        if fails_since_reboot >= _REBOOT_EVERY:
            reg.execute("reboot", {})
            fails_since_reboot = 0
    return None, attempts


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
      - 'exhausted' : le prefixe vide lui-meme ne se prolonge par AUCUN
                       caractere ET le cloud n'a pas eu de meilleure idee
                       (situation pathologique, ne devrait pas arriver en
                       pratique sur un oracle de prefixe classique).
    """
    def log(msg: str) -> None:
        if verbose:
            print(f"      [dict-search] {msg}", flush=True)

    prefix = start_prefix
    last_text = ""

    # Si on reprend depuis un prefixe deja confirme (rappel de l'outil apres
    # une 'extension' detectee par probe_extensions), on n'a pas encore sa
    # sortie textuelle propre a ce run: on la recapture une fois pour avoir
    # un `last_text` coherent si jamais aucun caractere ne le prolonge plus.
    if prefix:
        result = reg.execute("uart_send", {"command": prefix})
        last_text = result.get("response", "") if isinstance(result, dict) else ""

    while True:
        outcome, attempts = quick_extend(reg, prefix)
        for a in attempts:
            log(a)

        if outcome is not None and "flag" in outcome:
            log(f"FLAG detecte sur {outcome['command']!r}")
            return {"ok": True, "status": "flag", "flag": outcome["flag"],
                    "command": outcome["command"]}

        if outcome is not None:
            prefix = outcome["prefix"]
            last_text = outcome["text"]
            log(f"prefixe prolonge (gratuit, char-par-char) -> {prefix!r}")
            if outcome["kind"] == "executed":
                break  # commande complete trouvee directement
            continue  # kind == 'valid': on retente de prolonger encore

        # Aucun caractere ne prolonge `prefix`.
        if not prefix:
            # Cas pathologique: meme l'alphabet complet ne donne rien depuis
            # le prefixe vide. Secours rare: demander au cloud des idees de
            # mots entiers differents (peut-etre un caractere hors alphabet
            # standard, ou une commande tres inhabituelle).
            log("aucun caractere ne prolonge le prefixe vide -> secours cloud")
            tried: set[str] = set()
            attempts_log: list[str] = list(attempts)
            rounds_without_progress = 0
            found = False
            while rounds_without_progress < max_rounds:
                words, rationale = propose_dictionary(
                    cloud, prefix, sorted(tried), attempts_log, n_words_per_round
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
                    result = reg.execute("uart_send", {"command": word})
                    resp_text = result.get("response", "") if isinstance(result, dict) else ""
                    if isinstance(result, dict) and result.get("flag_detected"):
                        log(f"FLAG detecte sur {word!r}")
                        return {"ok": True, "status": "flag",
                                "flag": result["flag_detected"], "command": word}
                    kind = classify_oracle_response(resp_text)
                    attempts_log.append(f"{word!r} -> {kind}: {resp_text[:120]!r}")
                    if kind in ("valid", "executed"):
                        prefix = word
                        last_text = resp_text
                        progressed = True
                        found = True
                        log(f"PREFIXE CONFIRME (secours cloud) -> {prefix!r}")
                        break
                if progressed:
                    break
                rounds_without_progress += 1
            if not found:
                return {"ok": True, "status": "exhausted", "prefix": prefix,
                        "note": "Ni l'alphabet complet ni les dictionnaires de secours "
                                "du cloud n'ont trouve de commande depuis le prefixe vide. "
                                "Essaie une autre piste (ex: wifi_scan) avant de reessayer."}
            continue  # on a trouve un prefixe via le secours: retente de le prolonger gratuitement

        # prefix non vide, aucune extension possible -> commande COMPLETE
        break

    extensions = probe_extensions(reg, prefix)
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
    log(f"extensions testees pour {prefix!r}: {extensions}")
    return {
        "ok": True, "status": "executed",
        "command": prefix, "output": last_text,
        "extensions": extensions, "note": note,
    }
