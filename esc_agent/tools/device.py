"""Outils 'device' + backends.

Un DeviceBackend expose les primitives physiques (UART, EEPROM, BLE, HTTP) et
l'analyse statique. On fournit:
  - MockBackend     : simule un challenge, pour tourner SANS materiel ni kit
  - SerialBackend   : stub pyserial (a completer quand le kit arrive)
  - (BLE/HTTP real) : memes stubs a brancher plus tard

Les fonctions d'outil sont enregistrees sur le ToolRegistry avec leur canal, ce
qui rend chaque appel mesurable comme 'requete vers la cible'.
"""
from __future__ import annotations

from typing import Any, Protocol

from ..llm.base import ToolSpec
from .base import Channel, ToolRegistry


class DeviceBackend(Protocol):
    def static_hint(self, query: str) -> str: ...
    def uart(self, command: str) -> str: ...
    def eeprom_read(self, address: int, length: int) -> list[int]: ...
    def http_get(self, path: str) -> str: ...
    def check_flag(self, flag: str) -> bool: ...


# --- Enregistrement des outils sur le registre --------------------------------

def register_device_tools(reg: ToolRegistry, backend: DeviceBackend) -> None:
    """Branche un backend (mock ou reel) comme outils appelables par le modele."""

    reg.add(
        ToolSpec(
            name="static_analysis",
            description=(
                "Analyse STATIQUE hors-ligne du firmware (equiv. strings/ghidra/esptool). "
                "Ne consomme PAS de requete vers la cible. Utiliser pour comprendre "
                "le protocole et DEDUIRE la bonne commande avant d'interagir en live."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "ce que tu cherches (ex: 'format commande unlock')"},
                },
                "required": ["query"],
            },
        ),
        Channel.STATIC,
        lambda query: {"ok": True, "info": backend.static_hint(query)},
    )

    reg.add(
        ToolSpec(
            name="uart_send",
            description=(
                "Envoie UNE ligne de commande a la cible via UART (115200 8N1) et "
                "renvoie la reponse. CHAQUE appel compte comme une requete: minimise-les."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "ligne a envoyer (sans \\n)"},
                },
                "required": ["command"],
            },
        ),
        Channel.UART,
        lambda command: {"ok": True, "response": backend.uart(command)},
    )

    reg.add(
        ToolSpec(
            name="eeprom_read",
            description="Lit l'EEPROM I2C (0x50). Renvoie des octets. Compte comme une requete.",
            parameters={
                "type": "object",
                "properties": {
                    "address": {"type": "integer", "description": "offset de depart"},
                    "length": {"type": "integer", "description": "nb d'octets (<=256)"},
                },
                "required": ["address", "length"],
            },
        ),
        Channel.EEPROM,
        lambda address, length: {"ok": True, "bytes": backend.eeprom_read(address, length)},
    )

    reg.add(
        ToolSpec(
            name="http_get",
            description="GET sur l'UI web de la passerelle (http://192.168.4.1). Compte comme une requete.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "chemin, ex: '/status'"},
                },
                "required": ["path"],
            },
        ),
        Channel.HTTP,
        lambda path: {"ok": True, "body": backend.http_get(path)},
    )

    reg.add(
        ToolSpec(
            name="submit_flag",
            description="Soumet le flag trouve. Termine le challenge si correct.",
            parameters={
                "type": "object",
                "properties": {
                    "flag": {"type": "string"},
                },
                "required": ["flag"],
            },
        ),
        Channel.STATIC,  # la verification n'est pas une requete vers la cible
        lambda flag: {"ok": True, "correct": backend.check_flag(flag)},
    )


# --- Backend materiel reel (stubs a completer quand le kit arrive) ------------

class SerialBackend:
    """Backend UART reel via pyserial. A completer/valider avec le kit.

    Laisse volontairement incomplet: on remplit quand le hardware est la.
    """

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 115200, timeout: float = 2.0):
        try:
            import serial  # noqa: F401  (import tardif: pas requis en mode mock)
        except ImportError as exc:
            raise RuntimeError(
                "pyserial manquant: `pip install pyserial` quand tu brancheras le kit"
            ) from exc
        import serial
        self._ser = serial.Serial(port, baud, timeout=timeout)

    def uart(self, command: str) -> str:
        self._ser.write((command + "\r\n").encode())
        return self._ser.read_until(b"\n").decode(errors="replace").strip()

    def static_hint(self, query: str) -> str:
        raise NotImplementedError("brancher ici ta sortie d'analyse statique (ghidra/esptool)")

    def eeprom_read(self, address: int, length: int) -> list[int]:
        raise NotImplementedError("exposer via une commande firmware ou un pont I2C")

    def http_get(self, path: str) -> str:
        raise NotImplementedError("utiliser requests vers http://192.168.4.1" )

    def check_flag(self, flag: str) -> bool:
        raise NotImplementedError("comparer au flag attendu / soumettre a l'organisateur")
