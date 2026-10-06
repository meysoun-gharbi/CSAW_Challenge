"""Challenge factice pour valider le harnais de bout en bout (sans kit).

Scenario inspire des challenges ESC: une 'passerelle' demande une commande
UNLOCK avec un code. Le code n'est PAS donne en clair en live: il faut le
DEDUIRE de l'analyse statique (comme reverse de recon -> exploitation live),
ce qui est la bonne approche vis-a-vis du reglement.

Chemin attendu (efficace):
  1) static_analysis("unlock")  -> revele l'algo du code (offline, 0 requete cible)
  2) uart_send("UNLOCK 1337")   -> 1 seule requete live -> renvoie le flag
  3) submit_flag("ESC{...}")    -> succes

Un agent naif qui bruteforce UNLOCK consommera beaucoup de requetes: c'est
exactement ce que les metriques doivent faire ressortir.
"""
from __future__ import annotations

FLAG = "ESC{m0ck_uart_unlock_ok}"
_UNLOCK_CODE = 1337  # "derive" de l'analyse statique ci-dessous


class MockBackend:
    """Implemente DeviceBackend pour le scenario ci-dessus."""

    def __init__(self) -> None:
        self.unlocked = False

    def static_hint(self, query: str) -> str:
        q = query.lower()
        if "unlock" in q or "command" in q or "code" in q or "protocol" in q:
            return (
                "Firmware strings: handler 'UNLOCK <code>' sur UART. "
                "Pseudocode decompile: expected = (0x539) en decimal = 1337. "
                "Repondre 'UNLOCK 1337' deverrouille et imprime le flag."
            )
        if "eeprom" in q:
            return "EEPROM 0x50: octets 0x00-0x0F = copie badge; pas le flag ici."
        return "Rien de pertinent trouve pour cette requete d'analyse statique."

    def uart(self, command: str) -> str:
        cmd = command.strip()
        if cmd.upper().startswith("UNLOCK"):
            parts = cmd.split()
            if len(parts) == 2 and parts[1] == str(_UNLOCK_CODE):
                self.unlocked = True
                return f"OK UNLOCKED. FLAG={FLAG}"
            return "ERR bad code"
        if cmd.upper() in ("HELP", "?"):
            return "commands: HELP, STATUS, UNLOCK <code>"
        if cmd.upper() == "STATUS":
            return f"locked={not self.unlocked}"
        return "ERR unknown command"

    def eeprom_read(self, address: int, length: int) -> list[int]:
        data = bytes(range(16)) + b"\x00" * 240
        return list(data[address:address + min(length, 256)])

    def http_get(self, path: str) -> str:
        if path.rstrip("/") in ("", "/status"):
            return '{"ap":"SmartHomeGW","locked":true}'
        return "404"

    def check_flag(self, flag: str) -> bool:
        return flag.strip() == FLAG


GOAL = (
    "Objectif: deverrouiller la passerelle via UART et recuperer le flag "
    "(format ESC{...}), puis le soumettre avec submit_flag. "
    "Commence par l'analyse statique pour DEDUIRE la commande exacte au lieu de "
    "tatonner — chaque requete UART compte."
)
