"""Challenge 5 — Minions Lockout: tools and prompts.

Brief (official): "Margo is going to the prom and her father secured the
alarm. Try to get in without sounding the alarm. Every time an intruder is
detected lockout mode starts. A reset will be necessary and the password
changes. This challenge might sound brutal but if you clock out your
feelings the solution prompts itself."

Reading: a password gate drawn from the 157-name official wordlist
(esc_agent/data/minions_wordlist.txt, provided by the organizers for this
exact purpose). Wrong guesses eventually trip "lockout" (the alarm); reset
(free, EN pin) clears it and the secret is re-picked. There is nothing to
reverse-engineer here: the wordlist IS the sanctioned brute-force input, we
just need to find the right console command to reach the prompt and then
walk the list with free reboots on every lockout (esc_agent/lockout.py).
"""
from __future__ import annotations

from .llm import ToolSpec
from .lockout import MinionsBruteForcer, load_wordlist
from .serial import SerialBackend, FLAG_RE
from .wifi import wifi_scan

SYSTEM = (
    "You are solving CSAW ESC 2026 Challenge 5: 'Minions Lockout' on an ESP32 board.\n"
    "You MUST call tools to interact — never just describe what you would do.\n\n"
    "CHALLENGE DESCRIPTION (from the competition):\n"
    "Margo is going to the prom and her father secured the alarm. Try to get in\n"
    "without sounding the alarm. Every time an intruder is detected lockout mode\n"
    "starts. A reset will be necessary and the password changes. This challenge\n"
    "might sound brutal but if you clock out your feelings the solution prompts\n"
    "itself.\n\n"
    "WHAT THIS MEANS: a password gate picks a secret from a known list of 157\n"
    "minion first names (the organizers' own wordlist — this is the sanctioned\n"
    "brute-force target, not reverse engineering). Wrong guesses eventually trip\n"
    "a 'lockout'/alarm state; a reboot (free, EN pin, doesn't count as a request)\n"
    "clears it and the secret is re-picked. Your job:\n"
    "  1. Find the exact console command/sequence that opens the password prompt\n"
    "     (use uart_send to explore — it is likely similar to challenges 1/2's\n"
    "     prefix-oracle console: try short words, read what the console says).\n"
    "  2. Once you've identified that command, call brute_minions with it. This\n"
    "     tool walks the whole 157-name list IN CODE (zero extra LLM calls),\n"
    "     rebooting for free every time lockout trips, and stops the instant a\n"
    "     name is accepted or the flag appears. Do NOT try to guess names\n"
    "     yourself one uart_send at a time — that wastes requests AND LLM calls\n"
    "     for something the tool already does deterministically and for free.\n"
    "  3. If brute_minions returns a granted name without a flag, the device is\n"
    "     probably now in an authenticated/interactive state — use uart_send to\n"
    "     look around (e.g. 'help', 'status') before rebooting (rebooting would\n"
    "     lose that authenticated session).\n\n"
    "RULES:\n"
    "- Flag format: esc_2026{...} or ESC{...}. Call submit_flag when found.\n"
    "- Each uart_send counts as a target request — minimize these.\n"
    "- brute_minions' internal UART sends also count (reported in its result),\n"
    "  but its reboots are free, and it is far cheaper than any manual approach.\n"
    "- Read ALL outputs carefully. The device tells you what to do next."
)

GOAL = (
    "Find the flag (esc_2026{...}). Automated results are below.\n"
    "Read everything, then decide your next step."
)


def build_tools(backend: SerialBackend) -> dict:
    tools = {}

    def _read_mac() -> dict:
        mac = backend.read_mac()
        if mac:
            return {"ok": True, "mac": mac, "suffix": backend.mac_suffix(mac)}
        return {"ok": False, "error": "Could not read MAC via esptool."}

    tools["read_mac"] = {
        "spec": ToolSpec(
            name="read_mac",
            description="Read the ESP32's MAC address via USB (esptool). Free.",
            parameters={"type": "object", "properties": {}},
        ),
        "fn": _read_mac,
        "counted": False,
    }

    tools["wifi_scan"] = {
        "spec": ToolSpec(
            name="wifi_scan",
            description="Scan nearby Wi-Fi networks. Free (not counted).",
            parameters={"type": "object", "properties": {}},
        ),
        "fn": lambda: {"ok": True, "scan": wifi_scan()},
        "counted": False,
    }

    def _uart(command: str) -> dict:
        resp = backend.send(command)
        print(f"  >>> {command!r}", flush=True)
        print(f"  <<< {resp[:500]}", flush=True)
        out = {"ok": True, "response": resp}
        m = FLAG_RE.search(resp)
        if m and m.group(0) not in command:
            out["flag_detected"] = m.group(0)
            out["hint"] = "FLAG found! Call submit_flag with this value."
        return out

    tools["uart_send"] = {
        "spec": ToolSpec(
            name="uart_send",
            description=(
                "Send one line to the UART console and get the response. "
                "EACH call counts as a target request (minimize these). "
                "Use this to find the command that opens the password prompt, "
                "NOT to guess minion names one by one — use brute_minions for that."
            ),
            parameters={"type": "object", "properties": {
                "command": {"type": "string", "description": "the command to send"}
            }, "required": ["command"]},
        ),
        "fn": _uart,
        "counted": True,
    }

    tools["reboot"] = {
        "spec": ToolSpec(
            name="reboot",
            description="Reset the board (EN pin). Clears lockout. Free.",
            parameters={"type": "object", "properties": {}},
        ),
        "fn": lambda: {"ok": True, "boot": backend.reboot()},
        "counted": False,
    }

    def _brute_minions(enter_cmd: str = "") -> dict:
        forcer = MinionsBruteForcer(backend, enter_cmd=enter_cmd or None)
        result = forcer.run()
        out = {
            "calls": forcer.calls,
            "attempts_tried": len(forcer.attempts),
        }
        if result is None:
            out["ok"] = False
            out["note"] = (
                "Exhausted the whole wordlist with no match. Either enter_cmd "
                "is wrong (re-check with uart_send), or lockout detection "
                "missed the real keyword (see last few attempts below)."
            )
            out["last_attempts"] = [
                {"name": a.name, "outcome": a.outcome, "response": a.response[:200]}
                for a in forcer.attempts[-5:]
            ]
        else:
            out["ok"] = True
            out["granted_name"] = forcer.granted_name
            out["response"] = result.response
            if forcer.flag:
                out["flag_detected"] = forcer.flag
                out["hint"] = "FLAG found! Call submit_flag with this value."
        return out

    tools["brute_minions"] = {
        "spec": ToolSpec(
            name="brute_minions",
            description=(
                "Automated brute force of the password gate using the official "
                "157-name minion wordlist (zero extra LLM calls, free reboots on "
                "lockout). Call this ONCE you know the exact command that opens "
                "the password prompt (pass it as enter_cmd), or with enter_cmd="
                "'' if names can be sent directly without an entry command. "
                "Stops at the first accepted name or the flag."
            ),
            parameters={"type": "object", "properties": {
                "enter_cmd": {"type": "string",
                              "description": "command that opens the password prompt, or '' if none needed"}
            }, "required": []},
        ),
        "fn": _brute_minions,
        "counted": True,
    }

    tools["submit_flag"] = {
        "spec": ToolSpec(
            name="submit_flag",
            description="Submit the flag (esc_2026{...} or ESC{...}). Ends the run if correct.",
            parameters={"type": "object", "properties": {
                "flag": {"type": "string"}
            }, "required": ["flag"]},
        ),
        "fn": lambda flag: {"correct": backend.check_flag(flag), "flag": flag},
        "counted": False,
    }

    return tools
