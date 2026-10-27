"""LLM backends: Ollama (local) and Gemini (cloud).

Each backend implements the same interface: step(system, history, tools) -> LLMResponse.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    usage: Usage
    latency_ms: float = 0.0
    model: str = ""


# ---------------------------------------------------------------------------
# Ollama backend (local, native /api/chat with num_gpu=0 for CPU-only)
# ---------------------------------------------------------------------------

class OllamaClient:
    """Talks to Ollama via its native /api/chat endpoint (CPU-only by default)."""

    def __init__(self, model: str = "qwen2.5:7b",
                 base_url: str = "http://localhost:11434",
                 num_gpu: int = 0):
        self.model = model
        self._url = f"{base_url}/api/chat"
        self._num_gpu = num_gpu

    def _to_tools(self, tools: list[ToolSpec]) -> list[dict]:
        return [
            {"type": "function", "function": {
                "name": s.name, "description": s.description, "parameters": s.parameters}}
            for s in tools
        ]

    def _to_messages(self, system: str, history: list[dict]) -> list[dict]:
        msgs = [{"role": "system", "content": system}]
        for m in history:
            if m["role"] == "user":
                msgs.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.get("text") or ""}
                tcs = m.get("tool_calls", [])
                if tcs:
                    msg["tool_calls"] = [
                        {"id": tc.id, "function": {
                            "name": tc.name, "arguments": tc.arguments}}
                        for tc in tcs
                    ]
                msgs.append(msg)
            elif m["role"] == "tool":
                msgs.append({
                    "role": "tool",
                    "content": m["text"] or "",
                })
        return msgs

    def step(self, system: str, history: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": self._to_messages(system, history),
            "tools": self._to_tools(tools),
            "stream": False,
            "options": {"num_gpu": self._num_gpu, "temperature": 0},
        }
        data = json.dumps(body).encode()
        req = Request(self._url, data=data,
                      headers={"Content-Type": "application/json"})

        t0 = time.perf_counter()
        try:
            with urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read())
        except URLError as exc:
            body_bytes = getattr(exc, "read", lambda: b"")()
            raise RuntimeError(f"Ollama error: {exc} — {body_bytes.decode(errors='replace')}") from exc
        latency = (time.perf_counter() - t0) * 1000.0

        msg = result["message"]
        text = msg.get("content") or None
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc["function"]
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(ToolCall(
                id=tc.get("id", "call_" + uuid.uuid4().hex[:8]),
                name=fn["name"],
                arguments=args,
            ))

        usage = Usage(
            input_tokens=result.get("prompt_eval_count", 0),
            output_tokens=result.get("eval_count", 0),
            total_tokens=result.get("prompt_eval_count", 0) + result.get("eval_count", 0),
        )
        return LLMResponse(text=text, tool_calls=tool_calls, usage=usage,
                           latency_ms=latency, model=self.model)


# ---------------------------------------------------------------------------
# Gemini backend (cloud, google-genai SDK)
# ---------------------------------------------------------------------------

class GeminiClient:
    """Gemini via google-genai SDK.

    Two billing paths, same models:
      - AI Studio key (default): genai.Client(api_key=...). Free tier, then
        billed to card. Does NOT consume the $300 Google Cloud credit.
      - Vertex AI (opt-in): ADC auth + project/location. Consumes the $300
        credit. Enable with GOOGLE_GENAI_USE_VERTEXAI=true and
        GOOGLE_CLOUD_PROJECT set, after `gcloud auth application-default login`.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 vertexai: bool | None = None, project: str | None = None,
                 location: str | None = None):
        from google import genai
        from google.genai import types
        self._genai = genai
        self._types = types

        if vertexai is None:
            vertexai = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")

        if vertexai:
            project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
            location = location or os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
            if not project:
                raise RuntimeError(
                    "Vertex mode needs GOOGLE_CLOUD_PROJECT (and "
                    "`gcloud auth application-default login` for ADC).")
            self._client = genai.Client(vertexai=True, project=project, location=location)
            # Vertex needs a real publisher model id, not the AI Studio alias.
            default_model = "gemini-2.5-pro"
        else:
            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                raise RuntimeError(
                    "Set GEMINI_API_KEY (AI Studio), or use Vertex mode: "
                    "GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT.")
            self._client = genai.Client(api_key=key)
            default_model = "gemini-flash-latest"

        self.model = model or default_model
        self._include_thoughts = True
        self._sig_by_id: dict[str, object] = {}

    def _build_tools(self, tools: list[ToolSpec]):
        t = self._types
        decls = [
            t.FunctionDeclaration(name=s.name, description=s.description, parameters=s.parameters)
            for s in tools
        ]
        return [t.Tool(function_declarations=decls)]

    def _build_contents(self, history: list[dict]):
        t = self._types
        contents = []
        for m in history:
            if m["role"] == "user":
                contents.append(t.Content(role="user", parts=[t.Part.from_text(text=m["text"])]))
            elif m["role"] == "assistant":
                parts = []
                if m.get("text"):
                    parts.append(t.Part.from_text(text=m["text"]))
                for tc in m.get("tool_calls", []):
                    fc_part = t.Part(function_call=t.FunctionCall(
                        name=tc.name, args=tc.arguments))
                    sig = self._sig_by_id.get(tc.id)
                    if sig is not None:
                        fc_part.thought_signature = sig
                    parts.append(fc_part)
                if parts:
                    contents.append(t.Content(role="model", parts=parts))
            elif m["role"] == "tool":
                try:
                    payload = json.loads(m["text"]) if m["text"] else {}
                except Exception:
                    payload = {"result": m["text"]}
                if not isinstance(payload, dict):
                    payload = {"result": payload}
                contents.append(t.Content(role="user", parts=[
                    t.Part.from_function_response(name=m.get("tool_name", ""), response=payload)
                ]))
        return contents

    def step(self, system: str, history: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        t = self._types
        tool_config = t.ToolConfig(
            function_calling_config=t.FunctionCallingConfig(mode="ANY"))
        kwargs = dict(
            system_instruction=system,
            tools=self._build_tools(tools),
            tool_config=tool_config,
            temperature=0.0,
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
        )
        if self._include_thoughts:
            try:
                kwargs["thinking_config"] = t.ThinkingConfig(include_thoughts=True)
            except Exception:
                pass
        config = t.GenerateContentConfig(**kwargs)
        contents = self._build_contents(history)

        t0 = time.perf_counter()
        try:
            resp = self._generate(contents, config)
        except Exception as exc:
            if self._include_thoughts and "think" in str(exc).lower():
                self._include_thoughts = False
                del kwargs["thinking_config"]
                config = t.GenerateContentConfig(**kwargs)
                resp = self._generate(contents, config)
            else:
                raise
        latency = (time.perf_counter() - t0) * 1000.0

        tool_calls = []
        texts = []
        cands = getattr(resp, "candidates", None) or []
        if cands:
            content = getattr(cands[0], "content", None)
            for part in (getattr(content, "parts", None) or []):
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    args = dict(getattr(fc, "args", None) or {})
                    cid = "call_" + uuid.uuid4().hex[:8]
                    self._sig_by_id[cid] = getattr(part, "thought_signature", None)
                    tool_calls.append(ToolCall(id=cid, name=fc.name, arguments=args))
                    continue
                txt = getattr(part, "text", None)
                if txt and not getattr(part, "thought", False):
                    texts.append(txt)

        um = getattr(resp, "usage_metadata", None)
        usage = Usage()
        if um:
            usage.input_tokens = getattr(um, "prompt_token_count", 0) or 0
            usage.output_tokens = getattr(um, "candidates_token_count", 0) or 0
            usage.total_tokens = getattr(um, "total_token_count", 0) or 0

        return LLMResponse(
            text="\n".join(texts) or None, tool_calls=tool_calls, usage=usage,
            latency_ms=latency, model=self.model)

    def _generate(self, contents, config, max_attempts: int = 5):
        delay = 4.0
        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self._client.models.generate_content(
                    model=self.model, contents=contents, config=config)
            except Exception as exc:
                code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                msg = str(exc).lower()
                transient = code in (429, 500, 502, 503) or "unavailable" in msg \
                    or "overloaded" in msg or "high demand" in msg
                if not transient or attempt == max_attempts:
                    raise
                last_exc = exc
                print(f"  (retry {attempt}/{max_attempts-1} in {delay:.0f}s...)", flush=True)
                time.sleep(delay)
                delay *= 2
        raise last_exc


def build_client(backend: str = "ollama", model: str | None = None):
    """Factory: create the right LLM client."""
    if backend == "ollama":
        return OllamaClient(model=model or "qwen2.5:7b")
    elif backend == "gemini":
        return GeminiClient(model=model)
    else:
        raise ValueError(f"Unknown backend: {backend}")
