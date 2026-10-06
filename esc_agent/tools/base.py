"""Registre d'outils + instrumentation.

Chaque outil = une fonction Python + un ToolSpec (schema expose au modele).
Le decorateur d'instrumentation compte et chronometre les interactions avec la
CIBLE (par canal), et emet un evenement par appel. C'est la source des
metriques "nombre de requetes" notees par le reglement.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from ..llm.base import ToolSpec
from ..metrics import EventLogger


class Channel(str, Enum):
    """Canaux d'interaction. STATIC = analyse hors-ligne (ne compte pas comme
    une 'requete' vers la cible); les autres sont des requetes reelles."""
    STATIC = "static"      # esptool, ghidra, strings... (offline, gratuit en 'requetes')
    UART = "uart"
    BLE = "ble"
    RFID = "rfid"
    EEPROM = "eeprom"
    HTTP = "http"
    WIFI = "wifi"


@dataclass
class Tool:
    spec: ToolSpec
    func: Callable[..., Any]
    channel: Channel


class ToolRegistry:
    """Collectionne les outils et execute en emettant les evenements metriques."""

    def __init__(self, logger: EventLogger, run_id: str):
        self._tools: dict[str, Tool] = {}
        self._logger = logger
        self._run_id = run_id

    def register(self, spec: ToolSpec, channel: Channel) -> Callable:
        """Decorateur: enregistre la fonction comme outil du canal donne."""
        def deco(func: Callable[..., Any]) -> Callable[..., Any]:
            self._tools[spec.name] = Tool(spec=spec, func=func, channel=channel)
            return func
        return deco

    def add(self, spec: ToolSpec, channel: Channel, func: Callable[..., Any]) -> None:
        self._tools[spec.name] = Tool(spec=spec, func=func, channel=channel)

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute l'outil, mesure la latence, emet l'evenement adequat.

        Un appel sur un canal != STATIC compte comme UNE requete vers la cible.
        """
        tool = self._tools.get(name)
        if tool is None:
            self._logger.emit("tool_call", run_id=self._run_id, name=name,
                              ok=False, error="unknown_tool")
            return {"ok": False, "error": f"outil inconnu: {name}"}

        t0 = time.perf_counter()
        try:
            result = tool.func(**arguments)
            ok = True
            err = None
        except Exception as exc:  # on renvoie l'erreur au modele plutot que crasher
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            ok = False
            err = str(exc)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self._logger.emit("tool_call", run_id=self._run_id, name=name,
                          channel=tool.channel.value, ok=ok, error=err,
                          latency_ms=latency_ms)
        if tool.channel is not Channel.STATIC:
            # Requete reelle vers la cible: c'est LA metrique d'efficacite.
            self._logger.emit("target_interaction", run_id=self._run_id,
                              channel=tool.channel.value, tool=name,
                              latency_ms=latency_ms, ok=ok)
        return result if isinstance(result, dict) else {"ok": ok, "result": result}
