"""Backend LLM 'mock' deterministe — pour tester le harnais hors-ligne.

Il n'appelle aucun reseau. Il implemente une petite politique qui resout le
challenge factice de facon EFFICACE (analyse statique -> 1 requete UART ->
submit), afin de prouver que la plomberie (boucle + metriques) fonctionne.
Il fabrique aussi un 'usage' tokens plausible pour exercer l'agregation.

En conditions reelles, on remplace ce backend par GeminiClient — l'interface
est identique, donc rien d'autre ne change.
"""
from __future__ import annotations

import time
import uuid

from .base import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class MockClient(LLMClient):
    name = "mock"
    model = "mock-deterministic"

    def __init__(self) -> None:
        self._phase = 0  # 0: analyse, 1: unlock, 2: submit, 3: fini

    def step(self, system: str, history: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        t0 = time.perf_counter()

        # Politique scriptee: on lit les resultats d'outils dans l'historique
        # pour avancer d'une phase a l'autre (comme le ferait un vrai modele).
        last_tool = next((m for m in reversed(history) if m.role == "tool"), None)
        text: str | None = None
        calls: list[ToolCall] = []

        if self._phase == 0:
            calls = [ToolCall(id=_cid(), name="static_analysis",
                              arguments={"query": "unlock command code"})]
            self._phase = 1
        elif self._phase == 1:
            # On a 'lu' l'analyse statique -> on deduit le code et on envoie 1 requete.
            calls = [ToolCall(id=_cid(), name="uart_send",
                              arguments={"command": "UNLOCK 1337"})]
            self._phase = 2
        elif self._phase == 2:
            # On a 'lu' la reponse UART contenant un flag ESC{...} -> on soumet.
            import re
            flag = "ESC{m0ck_uart_unlock_ok}"
            if last_tool and last_tool.text:
                m = re.search(r"ESC\{[^}]*\}", last_tool.text)
                if m:
                    flag = m.group(0)
            calls = [ToolCall(id=_cid(), name="submit_flag", arguments={"flag": flag})]
            self._phase = 3
        else:
            text = "Flag soumis. Challenge resolu."

        latency = (time.perf_counter() - t0) * 1000.0
        prompt_text = system + "".join((m.text or "") for m in history)
        out_text = text or "".join(f"{c.name}({c.arguments})" for c in calls)
        usage = Usage(
            input_tokens=_approx_tokens(prompt_text),
            output_tokens=_approx_tokens(out_text),
            total_tokens=_approx_tokens(prompt_text) + _approx_tokens(out_text),
        )
        return LLMResponse(text=text, tool_calls=calls, usage=usage,
                           latency_ms=latency, model=self.model)


def _cid() -> str:
    return "call_" + uuid.uuid4().hex[:8]
