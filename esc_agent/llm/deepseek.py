"""Backend DeepSeek (API REST compatible OpenAI) — secours CLOUD bon marche.

ISOLE A DESSEIN, comme gemini.py/claude.py: tout le code specifique a DeepSeek
est ici. Si l'API bouge, seul ce fichier change; la boucle, les outils et les
metriques ne bougent pas.

Role prevu dans le harnais: filet de secours PAYANT mais tres bon marche
(~$0.14/M tokens input) derriere Gemini (gratuit mais quota journalier
limite), via CloudFallbackClient (voir cloud_fallback.py). Pas de SDK dedie:
l'API DeepSeek est un clone du format OpenAI /chat/completions, donc on parle
HTTP brut avec `requests` (deja dans requirements.txt) plutot que d'ajouter
une dependance ('openai') juste pour ca.

Mode 'stateless': on reconstruit tout l'historique a chaque pas (temperature=0
par defaut pour la repetabilite). tool_choice='required' force un appel
d'outil a chaque pas (equivalent du mode ANY de Gemini / any de Claude).

Pre-requis: variable d'env DEEPSEEK_API_KEY (voir .env.example).
Doc API: https://api-docs.deepseek.com/
"""
from __future__ import annotations

import json
import os
import time

import requests

from .base import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage


class DeepSeekClient(LLMClient):
    name = "deepseek"

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ):
        key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError(
                "Cle API absente: pose DEEPSEEK_API_KEY (voir .env.example) avant de lancer."
            )
        self._key = key
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        # Certains modeles/versions d'API refusent tool_choice='required' (400);
        # on retombe alors sur 'auto' pour le reste du run, comme claude.py.
        self._force_tool = True

    # --- traduction de nos types vers le format OpenAI-like -------------------

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
        """Convertit le transcript normalise en messages OpenAI-like.

        A la difference d'Ollama (API locale tolerante), l'API DeepSeek EXIGE
        le round-trip exact des 'id' de tool_call (assistant.tool_calls[].id
        <-> tool.tool_call_id), sous peine de 400. On s'appuie donc sur
        ToolCall.id / Message.tool_call_id, deja portes par le transcript
        normalise (meme mecanisme que claude.py).
        """
        msgs: list[dict] = [{"role": "system", "content": system}]
        for m in history:
            if m.role == "user":
                msgs.append({"role": "user", "content": m.text or ""})
            elif m.role == "assistant":
                entry: dict = {"role": "assistant", "content": m.text}
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in m.tool_calls
                    ]
                msgs.append(entry)
            elif m.role == "tool":
                msgs.append({
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "content": m.text or "",
                })
        return msgs

    def _post_with_retry(self, payload: dict, max_attempts: int = 5) -> dict:
        """Reessaie quand l'API est surchargee/rate-limitee — backoff exponentiel."""
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        delay = 4.0
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self._timeout)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == max_attempts:
                    raise
                print(f"      (DeepSeek injoignable, nouvel essai {attempt}/"
                      f"{max_attempts - 1} dans {delay:.0f}s...)", flush=True)
                time.sleep(delay)
                delay *= 2
                continue

            if resp.status_code == 400 and self._force_tool:
                body = resp.text.lower()
                if "tool_choice" in body or "required" in body:
                    self._force_tool = False
                    payload["tool_choice"] = "auto"
                    print("      (DeepSeek n'accepte pas tool_choice='required' -> "
                          "bascule sur 'auto')", flush=True)
                    continue
            if resp.status_code in (429, 500, 502, 503) and attempt < max_attempts:
                print(f"      (DeepSeek surcharge/limite [{resp.status_code}], nouvel "
                      f"essai {attempt}/{max_attempts - 1} dans {delay:.0f}s...)", flush=True)
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        if last_exc:
            raise last_exc
        raise RuntimeError("DeepSeek: echec apres plusieurs tentatives")

    @staticmethod
    def _extract_usage(data: dict) -> Usage:
        u = data.get("usage") or {}
        inp = int(u.get("prompt_tokens") or 0)
        out = int(u.get("completion_tokens") or 0)
        total = int(u.get("total_tokens") or (inp + out))
        # DeepSeek expose le cache de prompt via prompt_cache_hit_tokens.
        cached = int(u.get("prompt_cache_hit_tokens") or 0)
        return Usage(input_tokens=inp, output_tokens=out, cached_tokens=cached,
                     total_tokens=total, raw=u)

    # --- un pas de modele -------------------------------------------------------

    def step(self, system: str, history: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": self._build_messages(system, history),
            "tools": self._build_tools(tools),
            "tool_choice": "required" if self._force_tool else "auto",
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }
        t0 = time.perf_counter()
        data = self._post_with_retry(payload)
        latency = (time.perf_counter() - t0) * 1000.0

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {}) or {}
            args_raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
            except Exception:  # noqa: BLE001
                args = {"raw": args_raw}
            tool_calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))

        text = msg.get("content") or None
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=self._extract_usage(data),
            latency_ms=latency,
            model=self.model,
            raw=data,
        )
