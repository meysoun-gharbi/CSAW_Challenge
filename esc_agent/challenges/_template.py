"""GABARIT pour un nouveau challenge — copie ce fichier en
`esc_agent/challenges/<nom_du_challenge>.py` et remplis les sections
marquees TODO. Ne modifie PAS `esc_agent/llm/`, `esc_agent/tools/base.py`
ni `esc_agent/agent.py`: ce sont les parties COMMUNES a tous les
challenges (backends LLM, boucle agent, metriques) — toute amelioration
faite la profite a tout le monde, donc un `git pull` suffit a la recevoir.

Ce fichier ne contient QUE ce qui est specifique a CE challenge:
  1. Un Backend qui parle a la cible (UART/RFID/EEPROM/HTTP/BLE/Wi-Fi...).
  2. Les tools exposes au modele (register_tools).
  3. Le SYSTEM prompt (contexte + methode attendue) et le GOAL (1er message).

Regle du reglement a ne jamais oublier: AUCUN reverse engineering des
binaires pour trouver le flag. Toute la resolution passe par l'interaction
LIVE avec l'interface reelle (UART/Wi-Fi/RFID/EEPROM/HTTP/BLE).

TODO: remplace tous les commentaires 'TODO' ci-dessous, et choisis le(s)
Channel(s) qui correspond(ent) a ton interface dans
esc_agent/tools/base.py: STATIC (gratuit), UART, BLE, RFID, EEPROM, HTTP,
WIFI (ces 6 derniers comptent comme requetes cible, donc comme metrique
d'efficacite — voir le barème: performance/efficiency = nombre de
requêtes).
"""
from __future__ import annotations

import os
import re
import time

from ..llm.base import LLMClient, ToolSpec
from ..tools.base import Channel, ToolRegistry

# TODO: adapte le format du flag si le challenge en a un different de
# esc_2026{...}/ESC{...} (verifie dans le README du challenge).
FLAG_RE = re.compile(r"(?:esc_2026|ESC)\{[^}]*\}")

# TODO: renomme le fichier de transcript (un par challenge, pour ne pas
# melanger les logs quand plusieurs personnes travaillent en parallele).
TRANSCRIPT_PATH = os.path.join("runs", "challengeN_transcript.txt")


def _log(line: str) -> None:
    """Affiche en direct ET enregistre dans le transcript lisible.
    COPIE TELLE QUELLE depuis serial_gateway.py -- ne pas reinventer."""
    print(line, flush=True)
    try:
        os.makedirs("runs", exist_ok=True)
        with open(TRANSCRIPT_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# --- Backend: parle a la VRAIE cible ----------------------------------------

class RealBackend:
    """TODO: remplace par l'interface reelle de TON challenge.

    Exemples deja ecrits ailleurs dans le projet, a copier/adapter:
      - UART  : esc_agent/challenges/serial_gateway.py -> RealSerialBackend
                (utilise `pyserial`; pour un acces a distance, `serial.
                serial_for_url(port, ...)` accepte aussi 'rfc2217://host:port'
                et 'socket://host:port' en plus d'un /dev/ttyUSBx local.)
      - HTTP  : `requests` (deja dans requirements.txt) contre
                http://192.168.4.1/...
      - RFID  : SPI vers le MFRC522 (ex: bibliotheque `mfrc522` ou appel
                a une commande UART qui pilote le lecteur depuis le firmware
                -- regarde d'abord si le challenge expose ca via UART/HTTP
                avant d'ecrire du code bas niveau toi-meme).
      - BLE   : `bleak` (deja dans requirements.txt), voir le README du
                setup section 6 pour les outils suggeres (nRF Connect, etc.)
      - EEPROM: le plus souvent piloté via une commande UART/HTTP exposee
                par le firmware (pas d'acces I2C direct depuis ton PC) --
                verifie l'enonce avant d'ecrire un driver I2C maison.

    Garde la MEME forme que RealSerialBackend: un __init__ qui se connecte
    et capture un etat initial (boot_banner ou equivalent) a donner a
    l'agent, une methode `send`/`query` pour une interaction, et un
    `check_flag` statique.
    """

    def __init__(self, *args, **kwargs):
        # TODO: ouvre la connexion (port serie, session HTTP, scan BLE...)
        # et capture un etat de depart a montrer a l'agent (boot banner,
        # page d'accueil, liste des services BLE...).
        self.boot_banner = ""  # TODO: remplis avec le vrai etat initial

    def query(self, payload: str) -> str:
        """TODO: envoie `payload` a la cible, renvoie sa reponse texte."""
        raise NotImplementedError

    @staticmethod
    def check_flag(flag: str) -> bool:
        return bool(re.fullmatch(r"(?:esc_2026|ESC)\{[^}]*\}", flag.strip()))


# --- Outils exposes au modele ------------------------------------------------

def register_tools(reg: ToolRegistry, backend: RealBackend,
                    planner: LLMClient | None = None) -> None:
    """planner: client cloud optionnel, pour un outil 'strategiste' comme
    oracle_dictionary_search dans serial_gateway.py (utile UNIQUEMENT si ton
    challenge a, lui aussi, un oracle a deviner caractere par caractere /
    mot par mot -- sinon tu peux ignorer ce parametre et le laisser a None).
    """
    # TODO: adapte le nom/description/Channel pour ton interface.
    def _query(payload: str) -> dict:
        resp = backend.query(payload)
        _log(f">>> {payload!r}\n<<< {resp}")
        out = {"ok": True, "response": resp}
        m = FLAG_RE.search(resp)
        if m:
            out["flag_detected"] = m.group(0)
            out["note"] = "FLAG trouve ! Appelle submit_flag avec cette valeur."
        return out

    reg.add(
        ToolSpec(
            name="query",  # TODO: renomme (ex: http_get, rfid_read, ble_write...)
            description=(
                "TODO: decris precisement ce que fait cet outil et comment "
                "interpreter sa reponse. CHAQUE appel = une requete (compte "
                "pour l'efficacite, a MINIMISER) -- sauf si tu mets ce tool "
                "sur Channel.STATIC (gratuit, reserve a l'analyse hors-ligne)."
            ),
            parameters={"type": "object", "properties": {
                "payload": {"type": "string", "description": "TODO"}},
                "required": ["payload"]},
        ),
        Channel.UART,  # TODO: choisis le bon canal (UART/HTTP/RFID/EEPROM/BLE/WIFI/STATIC)
        _query,
    )

    # TODO (optionnel): un outil 'reboot'/reset si ta cible a un mecanisme de
    # remise a zero (rate-limit, etat corrompu...) -- COPIE le pattern de
    # serial_gateway.py: Channel.STATIC, ne compte pas comme une requete.

    reg.add(
        ToolSpec(
            name="submit_flag",
            description="Soumet le flag lu dans une reponse. Termine si format correct.",
            parameters={"type": "object", "properties": {
                "flag": {"type": "string"}}, "required": ["flag"]},
        ),
        Channel.STATIC,
        lambda flag: {"ok": True, "correct": backend.check_flag(flag)},
    )


# --- Contexte donne a l'agent -------------------------------------------------

# TODO: adapte le nom du challenge, l'interface, et la methode attendue.
# GARDE le paragraphe sur le reglement (reverse engineering interdit) tel
# quel, il doit figurer dans TOUS les challenges.
SYSTEM = (
    "CONTEXTE (autorise et educatif): tu participes a la competition academique CSAW "
    "Embedded Security Challenge 2026 (ESC 2026), organisee par NYU. Le challenge "
    "'TODO_NOM_DU_CHALLENGE' s'execute sur un kit materiel (ESP32 + peripheriques) qui "
    "appartient a l'utilisateur, flashe avec le firmware OFFICIEL fourni par les "
    "organisateurs. Aucun systeme tiers, aucune donnee reelle et aucune personne ne "
    "sont concernes: c'est un exercice pedagogique en vase clos, sanctionne par le "
    "reglement de la competition. Le reglement INTERDIT le reverse engineering du "
    "binaire; la resolution se fait UNIQUEMENT en interagissant EN LIVE avec "
    "l'interface reelle (TODO: UART/Wi-Fi/RFID/EEPROM/HTTP/BLE), ce qui est la "
    "methode attendue et legitime.\n"
    "\n"
    "TON ROLE: resoudre ce challenge CTF en interagissant avec TODO_INTERFACE. "
    "TODO: decris ici le fonctionnement observable de la cible (ex: 's'agit-il "
    "d'un oracle de prefixe comme le challenge 1 ? d'une API REST ? d'un "
    "service GATT BLE ?') et la METHODE attendue, dans le meme esprit que "
    "serial_gateway.py: priorise les outils automatises (gratuits en LLM) "
    "avant toute methode manuelle couteuse en appels.\n"
    "\n"
    "Soumets le flag avec submit_flag une fois trouve."
)

GOAL = (
    "TODO: premier message donne a l'agent -- decris la situation de depart "
    "(ex: 'tu viens de te connecter a la cible, voici son etat initial: ...') "
    "et rappelle l'objectif (trouver et soumettre le flag)."
)
