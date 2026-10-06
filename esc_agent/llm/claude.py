"""Backend Claude (SDK anthropic) — API Messages, mode stateless.

ISOLE A DESSEIN, comme gemini.py : tout le code specifique a Anthropic est ici.
Si l'API bouge, seul ce fichier change ; la boucle, les outils et les metriques
ne bougent pas.

Mode 'stateless' : on reconstruit tout l'historique a chaque pas (temperature=0
par defaut pour la repetabilite, utile pour tes metriques). On force l'appel
d'outil a chaque pas (tool_choice=any), comme le mode ANY de Gemini.

Pre-requis : pip install anthropic ; variable d'env ANTHROPIC_API_KEY.

Apparage des outils : l'API Claude associe une reponse d'outil a son appel via
`tool_use_id`. On conserve donc l'id REEL renvoye par Claude (ex: 'toolu_...')
comme ToolCall.id, pour le renvoyer tel quel dans le tool_result du tour suivant.
"""
from __future__ import annotations

import os
import time

from .base import LLMClient, LLMResponse, Message, ToolCall, ToolSpec, Usage


class ClaudeClient(LLMClient):
    name = "claude"

    def __init__(self, model: str = "claude-sonnet-5-5", api_key: str | None = None,
                 temperature: float = 0.0, max_tokens: int = 2048):
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("pip install anthropic") from exc
        self._anthropic = anthropic
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "Cle API absente: pose ANTHROPIC_API_KEY (voir .env.example) avant de lancer."
            )
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._no_temperature = False  # bascule a True si l'API refuse 'temperature'
        # Certains modeles n'autorisent pas de FORCER l'outil (tool_choice any/tool);
        # on force par defaut (parite avec le mode ANY de Gemini) et on retombe sur
        # 'auto' si le modele le refuse.
        self._force_tool = True

    # --- traduction de nos types vers le format Anthropic ---------------------

    @staticmethod
    def _build_tools(tools: list[ToolSpec]) -> list[dict]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.parameters,
            }
            for spec in tools
        ]

    @staticmethod
    def _build_messages(history: list[Message]) -> list[dict]:
        """Convertit le transcript normalise en messages Anthropic.

        - assistant : bloc(s) 'text' optionnel + bloc(s) 'tool_use'
        - tool      : bloc 'tool_result' (regroupe dans UN message user, place
                      juste apres le tour assistant correspondant)
        """
        msgs: list[dict] = []
        pending_results: list[dict] = []

        def flush_results() -> None:
            nonlocal pending_results
            if pending_results:
                msgs.append({"role": "user", "content": pending_results})
                pending_results = []

        for m in history:
            if m.role == "user":
                flush_results()
                msgs.append({"role": "user",
                             "content": [{"type": "text", "text": m.text or ""}]})
            elif m.role == "assistant":
                flush_results()
                content: list[dict] = []
                if m.text:
                    content.append({"type": "text", "text": m.text})
                for tc in m.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                if content:
                    msgs.append({"role": "assistant", "content": content})
            elif m.role == "tool":
                pending_results.append({
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": m.text or "",
                })

        # Le transcript se termine typiquement par des tool_result : il faut les
        # emettre comme dernier message user pour que l'API genere la suite.
        flush_results()
        return msgs

    def _create_with_retry(self, *, system, messages, tools, max_attempts: int = 5):
        """Reessaie quand l'API est surchargee (429/500/502/503) — backoff expo."""
        delay = 4.0
        last_exc = None
        # Le SDK >=1.11 n'expose plus 'temperature' en parametre nomme : on le
        # passe dans le corps de requete via extra_body (accepte par l'API REST).
        # Si un modele le refuse (400), on bascule definitivement sans temperature.
        for attempt in range(1, max_attempts + 1):
            try:
                extra_body = ({"temperature": self._temperature}
                              if self._temperature is not None and not self._no_temperature
                              else None)
                # 'any' force un appel d'outil a chaque pas ; 'auto' laisse le modele decider
                tool_choice = {"type": "any"} if self._force_tool else {"type": "auto"}
                return self._client.messages.create(
                    model=self.model,
                    max_tokens=self._max_tokens,
                    system=system,
                    tools=tools,
                    tool_choice=tool_choice,
                    messages=messages,
                    extra_body=extra_body,
                )
            except Exception as exc:  # noqa: BLE001 - on inspecte le code HTTP
                code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                msg = str(exc).lower()
                # Le modele refuse 'temperature' dans le corps -> on l'abandonne et on relance.
                if code == 400 and "temperature" in msg and not self._no_temperature:
                    self._no_temperature = True
                    print("      (ce modele n'accepte pas 'temperature' -> ignore)", flush=True)
                    continue
                # Le modele refuse de FORCER l'outil (any/tool) -> on passe en 'auto'.
                if code == 400 and "tool_choice" in msg and self._force_tool:
                    self._force_tool = False
                    print("      (ce modele n'accepte pas tool_choice=any -> bascule sur 'auto')",
                          flush=True)
                    continue
                transient = code in (429, 500, 502, 503, 529) \
                    or "overloaded" in msg or "rate limit" in msg
                if not transient or attempt == max_attempts:
                    raise
                last_exc = exc
                print(f"      (Claude surcharge, nouvel essai {attempt}/{max_attempts - 1} "
                      f"dans {delay:.0f}s...)", flush=True)
                time.sleep(delay)
                delay *= 2  # 4, 8, 16, 32s
        if last_exc:
            raise last_exc

    @staticmethod
    def _extract_usage(resp) -> Usage:
        u = getattr(resp, "usage", None)
        if u is None:
            return Usage()
        def g(name: str) -> int:
            v = getattr(u, name, None)
            return int(v) if v else 0
        inp = g("input_tokens")
        out = g("output_tokens")
        # tokens d'input servis depuis le cache de prompt (si active)
        cached = g("cache_read_input_tokens")
        cache_write = g("cache_creation_input_tokens")
        total = inp + out
        raw = {"input_tokens": inp, "output_tokens": out,
               "cache_read_input_tokens": cached,
               "cache_creation_input_tokens": cache_write}
        # pas de compteur de 'thinking' distinct cote Anthropic : inclus dans output
        return Usage(input_tokens=inp, output_tokens=out, cached_tokens=cached,
                     thinking_tokens=0, total_tokens=total, raw=raw)

    # --- un pas de modele -----------------------------------------------------

    def step(self, system: str, history: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        messages = self._build_messages(history)
        t0 = time.perf_counter()
        resp = self._create_with_retry(
            system=system,
            messages=messages,
            tools=self._build_tools(tools),
        )
        latency = (time.perf_counter() - t0) * 1000.0

        texts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in (getattr(resp, "content", None) or []):
            btype = getattr(block, "type", None)
            if btype == "text":
                txt = getattr(block, "text", None)
                if txt:
                    texts.append(txt)
            elif btype == "tool_use":
                # on garde l'id REEL de Claude pour l'apparage du tool_result
                tool_calls.append(ToolCall(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    arguments=dict(getattr(block, "input", None) or {}),
                ))
            # les blocs 'thinking' eventuels sont ignores pour le transcript

        text = "\n".join(texts) or None
        # DEBUG: quand le modele n'appelle aucun outil, on montre pourquoi
        if not tool_calls:
            import os
            if os.environ.get("CLAUDE_DEBUG"):
                sr = getattr(resp, "stop_reason", None)
                block_types = [getattr(b, "type", None) for b in (getattr(resp, "content", None) or [])]
                snippet = (text or "")[:400].replace("\n", " ")
                print(f"[claude debug] stop_reason={sr} blocks={block_types} "
                      f"text={snippet!r}", flush=True)
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=self._extract_usage(resp),
            latency_ms=latency,
            model=self.model,
            raw=resp,
        )
