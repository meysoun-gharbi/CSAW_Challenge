"""Backend Gemini (SDK google-genai) — voie STABLE: models.generate_content.

ISOLE A DESSEIN: tout le code specifique a Gemini est ici. Si l'API bouge,
seul ce fichier change; la boucle, les outils et les metriques ne bougent pas.

Mode 'stateless': on reconstruit tout l'historique a chaque pas (temperature=0
par defaut pour la repetabilite, utile pour tes metriques).

Pre-requis: pip install google-genai ; variable d'env GEMINI_API_KEY.
"""
from __future__ import annotations

import json
import os
import time
import uuid

from .base import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage


class GeminiClient(LLMClient):
    name = "gemini"

    def __init__(self, model: str = "gemini-2.5-flash", api_key: str | None = None,
                 temperature: float = 0.0):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("pip install google-genai") from exc
        self._genai = genai
        self._types = types
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError(
                "Cle API absente: pose GEMINI_API_KEY (voir .env.example) avant de lancer."
            )
        # Mode Vertex AI (aiplatform.googleapis.com) si GOOGLE_GENAI_USE_VERTEXAI=true.
        # Utile quand la cle est autorisee pour Vertex (express mode) mais PAS pour
        # l'API Developer generativelanguage. Sinon: API Developer (defaut).
        use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in (
            "1", "true", "yes", "on")
        if use_vertex:
            self._client = genai.Client(vertexai=True, api_key=key)
        else:
            self._client = genai.Client(api_key=key)
        self.model = model
        self._temperature = temperature
        # Gemini 3 attache une "thought_signature" a chaque appel d'outil; il faut
        # la renvoyer telle quelle au tour suivant. On la stocke par id d'appel.
        self._sig_by_id: dict[str, object] = {}
        self._include_thoughts = True  # resumes de pensee; desactive si non supporte

    # --- traduction de nos types vers le format google-genai ------------------

    def _build_tools(self, tools: list[ToolSpec]):
        t = self._types
        decls = [
            t.FunctionDeclaration(
                name=spec.name,
                description=spec.description,
                parameters=spec.parameters,
            )
            for spec in tools
        ]
        return [t.Tool(function_declarations=decls)]

    def _build_contents(self, history: list[Message]):
        t = self._types
        contents = []
        for m in history:
            if m.role == "user":
                contents.append(t.Content(role="user",
                                          parts=[t.Part.from_text(text=m.text or "")]))
            elif m.role == "assistant":
                parts = []
                if m.text:
                    parts.append(t.Part.from_text(text=m.text))
                for tc in m.tool_calls:
                    fc_part = t.Part(function_call=t.FunctionCall(
                        name=tc.name, args=tc.arguments))
                    sig = self._sig_by_id.get(tc.id)
                    if sig is not None:
                        # renvoyer la signature exactement comme recue
                        fc_part.thought_signature = sig
                    parts.append(fc_part)
                if parts:
                    contents.append(t.Content(role="model", parts=parts))
            elif m.role == "tool":
                # Gemini apparie les reponses d'outil par NOM (pas par id).
                try:
                    payload = json.loads(m.text) if m.text else {}
                except Exception:
                    payload = {"result": m.text}
                if not isinstance(payload, dict):
                    payload = {"result": payload}
                contents.append(t.Content(role="user", parts=[
                    t.Part.from_function_response(name=m.tool_name or "", response=payload)
                ]))
        return contents

    def _generate_with_retry(self, contents, config, max_attempts: int = 5):
        """Reessaie automatiquement quand Gemini est surcharge (503) ou limite (429)."""
        delay = 4.0
        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self._client.models.generate_content(
                    model=self.model, contents=contents, config=config,
                )
            except Exception as exc:  # noqa: BLE001 - on inspecte le code HTTP
                code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                transient = code in (429, 500, 502, 503) or "UNAVAILABLE" in str(exc) \
                    or "overloaded" in str(exc).lower() or "high demand" in str(exc).lower()
                if not transient or attempt == max_attempts:
                    raise
                last_exc = exc
                print(f"      (Gemini surcharge, nouvel essai {attempt}/{max_attempts - 1} "
                      f"dans {delay:.0f}s...)", flush=True)
                time.sleep(delay)
                delay *= 2  # backoff exponentiel: 4, 8, 16, 32s
        if last_exc:
            raise last_exc

    @staticmethod
    def _extract_usage(resp) -> Usage:
        um = getattr(resp, "usage_metadata", None)
        if um is None:
            return Usage()
        def g(name: str) -> int:
            v = getattr(um, name, None)
            return int(v) if v else 0
        inp = g("prompt_token_count")
        out = g("candidates_token_count")
        cached = g("cached_content_token_count")
        think = g("thoughts_token_count")
        total = g("total_token_count") or (inp + out)
        return Usage(input_tokens=inp, output_tokens=out, cached_tokens=cached,
                     thinking_tokens=think, total_tokens=total)

    # --- un pas de modele -----------------------------------------------------

    def _build_config(self, system: str, tools: list[ToolSpec]):
        t = self._types
        # Force le modele a APPELER un outil a chaque pas (au lieu de bavarder):
        tool_config = t.ToolConfig(
            function_calling_config=t.FunctionCallingConfig(mode="ANY")
        )
        kwargs = dict(
            system_instruction=system,
            tools=self._build_tools(tools),
            tool_config=tool_config,
            temperature=self._temperature,
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
        )
        # Resumes de pensee (thinking): expose le raisonnement du modele meme en
        # mode ANY. Desactive automatiquement si le modele ne le supporte pas.
        if getattr(self, "_include_thoughts", True):
            try:
                kwargs["thinking_config"] = t.ThinkingConfig(include_thoughts=True)
            except Exception:  # noqa: BLE001
                pass
        return t.GenerateContentConfig(**kwargs)

    def step(self, system: str, history: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        contents = self._build_contents(history)
        t0 = time.perf_counter()
        try:
            resp = self._generate_with_retry(contents, self._build_config(system, tools))
        except Exception as exc:  # noqa: BLE001
            # Si le modele refuse 'thinking_config', on le desactive et on relance.
            if getattr(self, "_include_thoughts", True) and "think" in str(exc).lower():
                self._include_thoughts = False
                print("      (ce modele ne supporte pas 'thinking' -> desactive)", flush=True)
                resp = self._generate_with_retry(contents, self._build_config(system, tools))
            else:
                raise
        latency = (time.perf_counter() - t0) * 1000.0

        tool_calls: list[ToolCall] = []
        texts: list[str] = []
        thoughts: list[str] = []
        cands = getattr(resp, "candidates", None) or []
        if cands:
            content = getattr(cands[0], "content", None)
            for part in (getattr(content, "parts", None) or []):
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    args = dict(getattr(fc, "args", None) or {})
                    cid = _cid()
                    # on memorise la signature attachee a cet appel (Gemini 3)
                    self._sig_by_id[cid] = getattr(part, "thought_signature", None)
                    tool_calls.append(ToolCall(id=cid, name=fc.name, arguments=args))
                    continue
                txt = getattr(part, "text", None)
                if txt:
                    # une part marquee thought=True est un resume de raisonnement
                    if getattr(part, "thought", False):
                        thoughts.append(txt)
                    else:
                        texts.append(txt)
        # on prefixe le raisonnement pour qu'il s'affiche dans [pensee du modele]
        combined = []
        if thoughts:
            combined.append("[raisonnement] " + "\n".join(thoughts))
        combined.extend(texts)
        text = "\n".join(combined) or None
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=self._extract_usage(resp),
            latency_ms=latency,
            model=self.model,
            raw=resp,
        )


def _cid() -> str:
    return "call_" + uuid.uuid4().hex[:8]
