"""Backend Ollama (modele local, via l'API HTTP /api/chat).

ISOLE A DESSEIN: tout le code specifique a Ollama est ici. Si l'API bouge,
seul ce fichier change; la boucle, les outils et les metriques ne bougent pas.

Pourquoi un backend local:
  - zero cout API, zero rate-limit -> ideal pour le benchmark de repetabilite
    (bench.py -n 20/50/...) sans budget a surveiller ;
  - autonomie si pas de reseau fiable le jour de la finale.

Limite connue: les petits modeles locaux (7-9B) sont moins fiables en
tool-calling strict que Gemini/Claude. A documenter dans le rapport si vous
comparez les backends (requetes/tokens/succes/CV).

Pre-requis:
  - un serveur Ollama qui tourne (local ou distant) : `ollama serve` ou le
    service systemd deja configure sur cette machine.
  - le modele deja pull : `ollama pull <nom>` (ou `ollama list` pour verifier).
  - pip install requests (deja dans requirements.txt).
"""
from __future__ import annotations

import json
import time
import uuid

import requests

from .base import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage


class OllamaClient(LLMClient):
    name = "ollama"

    def __init__(
        self,
        model: str = "qwen2.5:7b-instruct",
        host: str = "http://localhost:11434",
        temperature: float = 0.0,
        timeout: float = 120.0,
    ):
        self.model = model
        self._host = host.rstrip("/")
        self._temperature = temperature
        self._timeout = timeout
        self._check_available()

    # --- sante / garde-fous ----------------------------------------------------

    def _check_available(self) -> None:
        """Echoue tot et clairement si le serveur ou le modele ne sont pas prets."""
        try:
            resp = requests.get(f"{self._host}/api/tags", timeout=5)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Serveur Ollama injoignable sur {self._host} "
                "(verifie `ollama serve` / `systemctl status ollama`)."
            ) from exc
        names = {m.get("name") for m in resp.json().get("models", []) if m.get("name")}

        def _matches(installed: str) -> bool:
            if installed == self.model or installed.startswith(self.model + ":"):
                return True
            # tolere un nom court sans le namespace "org/" (ex: "qwen3-...-abliterated"
            # pour "richardyoung/qwen3-...-abliterated:latest")
            short = installed.split("/")[-1].split(":")[0]
            return short == self.model

        if not any(_matches(n) for n in names):
            raise RuntimeError(
                f"Modele '{self.model}' absent d'Ollama. Modeles installes: "
                f"{sorted(names)}. Lance `ollama pull {self.model}` d'abord "
                "(ou utilise le nom complet avec son namespace)."
            )
        # resout vers le nom complet installe pour que /api/chat le trouve
        for n in names:
            if _matches(n):
                self.model = n
                break

    # --- traduction de nos types vers le format Ollama (OpenAI-like) ----------

    @staticmethod
    def _build_tools(tools: list[ToolSpec]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in tools
        ]

    @staticmethod
    def _build_messages(system: str, history: list[Message]) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": system}]
        for m in history:
            if m.role == "user":
                msgs.append({"role": "user", "content": m.text or ""})
            elif m.role == "assistant":
                entry: dict = {"role": "assistant", "content": m.text or ""}
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            }
                        }
                        for tc in m.tool_calls
                    ]
                msgs.append(entry)
            elif m.role == "tool":
                try:
                    payload = json.loads(m.text) if m.text else {}
                except Exception:  # noqa: BLE001
                    payload = {"result": m.text}
                msgs.append({
                    "role": "tool",
                    "content": json.dumps(payload),
                })
        return msgs

    @staticmethod
    def _extract_usage(data: dict) -> Usage:
        inp = int(data.get("prompt_eval_count") or 0)
        out = int(data.get("eval_count") or 0)
        return Usage(input_tokens=inp, output_tokens=out, total_tokens=inp + out, raw=data)

    # --- un pas de modele -------------------------------------------------------

    def step(self, system: str, history: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": self._build_messages(system, history),
            "tools": self._build_tools(tools),
            "stream": False,
            "options": {"temperature": self._temperature},
        }
        t0 = time.perf_counter()
        resp = requests.post(f"{self._host}/api/chat", json=payload, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        latency = (time.perf_counter() - t0) * 1000.0

        msg = data.get("message", {}) or {}
        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {}) or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:  # noqa: BLE001
                    args = {"raw": args}
            tool_calls.append(ToolCall(id=_cid(), name=fn.get("name", ""), arguments=args))

        text = msg.get("content") or None
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=self._extract_usage(data),
            latency_ms=latency,
            model=self.model,
            raw=data,
        )


def _cid() -> str:
    return "call_" + uuid.uuid4().hex[:8]
