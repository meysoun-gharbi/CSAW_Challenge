"""Core agent loop: LLM decides which tool to call each step."""
from __future__ import annotations

import json
import re
import time
import uuid

from .llm import LLMResponse, ToolCall, ToolSpec


def _parse_tool_from_text(text: str, known_tools: set[str]) -> ToolCall | None:
    """Fallback: extract a tool call from model text output.

    Small models sometimes write tool calls as JSON in their text instead of
    using the structured tool calling API. This catches that pattern.
    """
    # Match {"name": "tool_name", "arguments": {...}}
    for m in re.finditer(r'\{[^{}]*"name"\s*:\s*"(\w+)"[^{}]*"arguments"\s*:\s*(\{[^{}]*\})', text):
        name = m.group(1)
        if name in known_tools:
            try:
                args = json.loads(m.group(2))
            except json.JSONDecodeError:
                args = {}
            return ToolCall(id="call_" + uuid.uuid4().hex[:8], name=name, arguments=args)

    # Match tool_name({"key": "value"}) or tool_name(key="value")
    for m in re.finditer(r'(\w+)\(\s*(\{[^)]*\})\s*\)', text):
        name = m.group(1)
        if name in known_tools:
            try:
                args = json.loads(m.group(2))
            except json.JSONDecodeError:
                args = {}
            return ToolCall(id="call_" + uuid.uuid4().hex[:8], name=name, arguments=args)

    # Match just a tool name with a simple string arg: uart_send("help")
    for m in re.finditer(r'(\w+)\(\s*["\']([^"\']+)["\']\s*\)', text):
        name = m.group(1)
        if name in known_tools:
            return ToolCall(id="call_" + uuid.uuid4().hex[:8], name=name,
                           arguments={"command": m.group(2)})

    # Match a zero-arg call: read_mac(), wifi_scan(), reboot()
    for m in re.finditer(r'(\w+)\(\s*\)', text):
        name = m.group(1)
        if name in known_tools:
            return ToolCall(id="call_" + uuid.uuid4().hex[:8], name=name, arguments={})

    return None


class Agent:
    def __init__(self, llm, tools: dict[str, dict],
                 system: str, goal: str, max_steps: int = 200):
        self.llm = llm
        self._tools = tools
        self.system = system
        self.max_steps = max_steps
        self.history: list[dict] = [{"role": "user", "text": goal}]
        self.solved = False
        self.flag = None
        self.uart_calls = 0
        self.llm_calls = 0
        self._tried_commands: dict[str, int] = {}

    def tool_specs(self) -> list[ToolSpec]:
        return [t["spec"] for t in self._tools.values()]

    def _execute(self, tc: ToolCall) -> dict:
        print(f"[tool] {tc.name}({tc.arguments})", flush=True)
        tool = self._tools.get(tc.name)
        if not tool:
            result = {"error": f"unknown tool: {tc.name}"}
        else:
            try:
                result = tool["fn"](**tc.arguments)
            except Exception as exc:
                result = {"error": str(exc)}
            if tool.get("counted"):
                self.uart_calls += 1
        print(f"  -> {json.dumps(result, ensure_ascii=False, default=str)[:500]}", flush=True)
        return result

    def run(self) -> dict:
        t0 = time.perf_counter()
        no_tool = 0
        dead_streak = 0
        known = set(self._tools.keys())

        for step in range(self.max_steps):
            # Inject tried-commands list so the model doesn't have to track it
            if self._tried_commands:
                tried = "; ".join(f"{c} (x{n})" for c, n in self._tried_commands.items())
                self.history.append({"role": "user",
                    "text": f"ALREADY TRIED (do not repeat): {tried}"})

            resp = self.llm.step(self.system, self.history, self.tool_specs())
            self.llm_calls += 1

            tool_calls = resp.tool_calls

            # Fallback: if model wrote a tool call in text, parse it
            if not tool_calls and resp.text:
                parsed = _parse_tool_from_text(resp.text, known)
                if parsed:
                    print(f"  (parsed tool call from text)", flush=True)
                    tool_calls = [parsed]

            self.history.append({
                "role": "assistant",
                "text": resp.text,
                "tool_calls": tool_calls,
            })

            if resp.text:
                print(f"\n[think] {resp.text[:300]}", flush=True)

            if not tool_calls:
                no_tool += 1
                if no_tool >= 5:
                    break
                self.history.append({"role": "user", "text":
                    "You MUST call a tool now. Do NOT write JSON — use the tool calling API. "
                    "Available tools: " + ", ".join(known)})
                continue
            no_tool = 0

            for tc in tool_calls:
                # Detect loops: same uart command sent 3+ times
                if tc.name == "uart_send":
                    cmd = tc.arguments.get("command", "")
                    self._tried_commands[cmd] = self._tried_commands.get(cmd, 0) + 1
                    if self._tried_commands[cmd] >= 3:
                        result = {"error": f"LOOP DETECTED: you already sent {cmd!r} {self._tried_commands[cmd]} times. Try something DIFFERENT."}
                        print(f"[loop] blocked repeat: {cmd!r}", flush=True)
                        self.history.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "tool_name": tc.name,
                            "text": json.dumps(result),
                        })
                        continue

                result = self._execute(tc)
                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "tool_name": tc.name,
                    "text": json.dumps(result, ensure_ascii=False, default=str),
                })
                if tc.name == "submit_flag" and result.get("correct"):
                    self.solved = True
                    self.flag = tc.arguments.get("flag")
                if tc.name == "uart_send":
                    if "no command starts with" in (result.get("response") or "").lower():
                        dead_streak += 1
                    else:
                        dead_streak = 0

            if self.solved:
                break
            if dead_streak >= 10:
                print(f"[abort] {dead_streak} consecutive dead-end commands — "
                      "the model is guessing in circles, stopping.", flush=True)
                break

        wall = (time.perf_counter() - t0) * 1000.0
        return {
            "solved": self.solved,
            "flag": self.flag,
            "uart_calls": self.uart_calls,
            "llm_calls": self.llm_calls,
            "wall_s": wall / 1000.0,
        }
