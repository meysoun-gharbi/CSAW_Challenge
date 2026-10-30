"""Backend LOCAL via une API compatible OpenAI (Ollama, LM Studio, llama.cpp...).

ISOLE A DESSEIN, comme gemini.py / claude.py. Le modele tourne sur TA machine
(aucun cout, aucun quota). On parle au serveur local par HTTP, au format OpenAI
`/v1/chat/completions` (celui qu'exposent Ollama & co).

Config par defaut : Ollama sur http://localhost:11434/v1 (surchargeable par les
variables d'env LOCAL_LLM_BASE_URL / LOCAL_LLM_API_KEY). Aucune dependance pip :
on utilise urllib de la stdlib.

ATTENTION : le modele local DOIT savoir faire du 'tool calling'. Les bons choix
sont p.ex. qwen2.5:7b-instruct ou llama3.1:8b. Un parseur de secours recupere
aussi les appels renvoyes en texte par les modeles plus faibles.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid

from .base import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage


class LocalClient(LLMClient):
    name = "local"

    def __init__(self, model: str = "qwen2.5:7b-instruct",
                 base_url: str | None = None, api_key: str | None = None,
                 temperature: float = 0.0, timeout: float = 180.0):
        self.model = model
        self._base = (base_url or os.environ.get("LOCAL_LLM_BASE_URL")
                      or "http://localhost:11434/v1").rstrip("/")
        self._key = api_key or os.environ.get("LOCAL_LLM_API_KEY") or "local"
        self._temperature = temperature
        self._timeout = timeout

    # --- traduction de nos types vers le format OpenAI ------------------------

    @staticmethod
    def _build_tools(tools: list[ToolSpec]) -> list[dict]:
        return [{"type": "function",
                 "function": {"name": s.name, "description": s.description,
                              "parameters": s.parameters}} for s in tools]

    @staticmethod
    def _build_messages(system: str, history: list[Message]) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": system}]
        for m in history:
            if m.role == "user":
                msgs.append({"role": "user", "content": m.text or ""})
            elif m.role == "assistant":
                a: dict = {"role": "assistant", "content": m.text or ""}
                if m.tool_calls:
                    a["tool_calls"] = [{
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name,
                                     "arguments": json.dumps(tc.arguments,
                                                             ensure_ascii=False)},
                    } for tc in m.tool_calls]
                msgs.append(a)
            elif m.role == "tool":
                msgs.append({"role": "tool",
                             "tool_call_id": m.tool_call_id or "",
                             "content": m.text or ""})
        return msgs

    # --- normalisation des arguments (robustesse modeles faibles) -------------

    @staticmethod
    def _clean_args(args) -> dict:
        """Deballe les formes bizarres type {"command": {"type": "string",
        "value": "a"}} renvoyees par certains petits modeles -> {"command": "a"}."""
        if not isinstance(args, dict):
            return {}
        out = {}
        for k, v in args.items():
            if isinstance(v, dict) and "value" in v and set(v.keys()) <= {"type", "value"}:
                out[k] = v["value"]
            else:
                out[k] = v
        return out

    # --- appel HTTP (compatible OpenAI) ---------------------------------------

    def _post_chat(self, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._base + "/chat/completions", data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._key}"})
        with urllib.request.urlopen(req, timeout=self._timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # --- un pas de modele -----------------------------------------------------

    def step(self, system: str, history: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": self._build_messages(system, history),
            "tools": self._build_tools(tools),
            "tool_choice": "auto",
            "temperature": self._temperature,
            "stream": False,
        }
        t0 = time.perf_counter()
        resp = self._post_chat(payload)
        latency = (time.perf_counter() - t0) * 1000.0

        choice = (resp.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = msg.get("content") or None
        tool_calls: list[ToolCall] = []

        # 1) cas normal : tool_calls structures
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            tool_calls.append(ToolCall(id=tc.get("id") or _cid(),
                                       name=fn.get("name", ""),
                                       arguments=self._clean_args(args)))

        # 2) secours : certains modeles mettent l'appel en TEXTE dans content
        if not tool_calls and text:
            salvaged = _salvage_toolcall(text)
            if salvaged:
                name, args = salvaged
                tool_calls.append(ToolCall(id=_cid(), name=name,
                                           arguments=self._clean_args(args)))
                text = None  # le "texte" etait en fait l'appel

        u = resp.get("usage") or {}
        usage = Usage(input_tokens=int(u.get("prompt_tokens") or 0),
                      output_tokens=int(u.get("completion_tokens") or 0),
                      total_tokens=int(u.get("total_tokens") or 0))
        return LLMResponse(text=text, tool_calls=tool_calls, usage=usage,
                           latency_ms=latency, model=self.model, raw=resp)


def _cid() -> str:
    return "call_" + uuid.uuid4().hex[:8]


def _salvage_toolcall(text: str):
    """Essaie d'extraire {"name":..., "arguments":{...}} d'un texte JSON."""
    s = text.strip()
    # retire d'eventuels fences ```json ... ```
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("{"):] if "{" in s else s
    try:
        obj = json.loads(s)
    except Exception:
        return None
    if isinstance(obj, dict) and "name" in obj and isinstance(obj.get("arguments"), dict):
        return obj["name"], obj["arguments"]
    return None
