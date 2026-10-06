"""La boucle agent: Observer -> LLM -> Agir (outil) -> Verifier -> journaliser.

Entierement instrumentee. Renvoie un RunSummary (metriques du run). La logique
est backend-agnostique: elle ne connait que LLMClient + ToolRegistry.
"""
from __future__ import annotations

import time
import uuid

from .llm.base import LLMClient, Message
from .metrics import EventLogger, RunSummary
from .tools.base import ToolRegistry


class Agent:
    def __init__(self, llm: LLMClient, registry: ToolRegistry,
                 logger: EventLogger, run_id: str, max_steps: int = 12,
                 verbose: bool = False):
        self.llm = llm
        self.registry = registry
        self.logger = logger
        self.run_id = run_id
        self.max_steps = max_steps
        self.verbose = verbose  # affiche le raisonnement + les decisions d'outil en direct

    def run(self, system: str, goal: str, challenge: str = "mock") -> RunSummary:
        s = RunSummary(run_id=self.run_id, challenge=challenge, model=self.llm.model,
                       solved=False)
        self.logger.emit("run_start", run_id=self.run_id, challenge=challenge,
                         model=self.llm.model, max_steps=self.max_steps)
        history: list[Message] = [Message(role="user", text=goal)]
        tools = self.registry.specs()

        wall0 = time.perf_counter()
        reason = "max_steps_reached"
        # Quand le modele tourne en mode 'auto' (il n'est pas force d'appeler un
        # outil), il peut repondre du texte sans agir. On le relance alors avec un
        # nudge, et on n'abandonne qu'apres plusieurs tours sans outil d'affilee.
        no_tool_streak = 0
        max_no_tool = 3
        for _ in range(self.max_steps):
            resp = self.llm.step(system, history, tools)

            # --- metriques de l'appel LLM ---
            u = resp.usage
            s.llm_calls += 1
            s.input_tokens += u.input_tokens
            s.output_tokens += u.output_tokens
            s.cached_tokens += u.cached_tokens
            s.thinking_tokens += u.thinking_tokens
            s.total_tokens += u.total_tokens
            s.llm_ms += resp.latency_ms
            self.logger.emit("llm_call", run_id=self.run_id, model=resp.model,
                             input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                             cached_tokens=u.cached_tokens, thinking_tokens=u.thinking_tokens,
                             total_tokens=u.total_tokens, latency_ms=resp.latency_ms,
                             n_tool_calls=len(resp.tool_calls))

            # enregistre le tour assistant dans l'historique
            history.append(Message(role="assistant", text=resp.text,
                                   tool_calls=resp.tool_calls))

            # affichage en direct du raisonnement + des decisions d'outil
            if self.verbose:
                if resp.text and resp.text.strip():
                    print(f"\n[pensee du modele] {resp.text.strip()}", flush=True)
                for tc in resp.tool_calls:
                    print(f"[decision -> {tc.name}] {tc.arguments}", flush=True)

            if not resp.tool_calls:
                no_tool_streak += 1
                if no_tool_streak >= max_no_tool:
                    reason = "model_stopped"
                    break
                # nudge: on le pousse a agir plutot que d'abandonner tout de suite
                history.append(Message(role="user", text=(
                    "Tu n'as appele AUCUN outil. Pour progresser tu DOIS appeler un outil "
                    "(static_analysis, uart_send, reboot ou submit_flag). N'explique pas, "
                    "AGIS : appelle un outil maintenant.")))
                continue
            no_tool_streak = 0

            # --- execution des outils demandes ---
            solved_now = False
            for tc in resp.tool_calls:
                s.tool_calls += 1
                result = self.registry.execute(tc.name, tc.arguments)
                history.append(Message(role="tool", tool_call_id=tc.id,
                                       tool_name=tc.name, text=_as_text(result)))
                # condition de victoire: submit_flag correct
                if tc.name == "submit_flag" and result.get("correct") is True:
                    solved_now = True
            if solved_now:
                s.solved = True
                reason = "flag_correct"
                break

        # agrege les requetes-cible depuis les evenements du run (source de verite)
        wall_ms = (time.perf_counter() - wall0) * 1000.0
        s.wall_ms = wall_ms
        _fill_interactions(s, self.logger, self.run_id)
        s.reason = reason
        self.logger.emit("run_end", run_id=self.run_id, solved=s.solved,
                         reason=reason, wall_ms=wall_ms,
                         target_interactions=s.target_interactions)
        return s


def _as_text(result: dict) -> str:
    import json
    return json.dumps(result, ensure_ascii=False, default=str)


def _fill_interactions(s: RunSummary, logger: EventLogger, run_id: str) -> None:
    """Relit le JSONL de CE run pour compter les requetes cible par canal."""
    import json
    from collections import Counter
    chan: Counter[str] = Counter()
    total = 0
    tool_ms = 0.0
    for line in logger.path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("run_id") != run_id:
            continue
        if e.get("type") == "target_interaction":
            total += 1
            chan[e.get("channel", "unknown")] += 1
            tool_ms += e.get("latency_ms", 0.0)
    s.target_interactions = total
    s.interactions_by_channel = dict(chan)
    s.tool_ms = tool_ms


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]
