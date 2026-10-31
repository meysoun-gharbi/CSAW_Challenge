"""Challenge 5 — Minions Lockout: tools and prompts.

Brief (official): "Margo is going to the prom and her father secured the
alarm. Try to get in without sounding the alarm. Every time an intruder is
detected lockout mode starts. A reset will be necessary and the password
changes. This challenge might sound brutal but if you clock out your
feelings the solution prompts itself."

Everything below is ESTABLISHED FACT from live probing of the real board
(never from binary analysis -- that's forbidden by the ESC rules and was
never done). See esc_agent/lockout.py's docstring for the full trail.
"""
from __future__ import annotations

from .llm import ToolSpec
from .lockout import MinionsPairBruteForcer, ICONIC
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
    "ESTABLISHED FACTS (from live UART/I2C probing of our own board — NOT from\n"
    "any binary analysis, which is forbidden and was never done):\n"
    "- Console commands: `help`, `status`, `hint` (undocumented but real),\n"
    "  and `unlock_key minion1-minion2` (a PAIR of names, dash-separated,\n"
    "  drawn from a 158-name official wordlist of real minion characters).\n"
    "- `status` returns JSON incl. `storage`: either \"I2C_EEPROM\" (EEPROM\n"
    "  wired — a genuine 1-strike lockout: ONE wrong guess persists and\n"
    "  blocks further attempts until an EN reboot) or \"I2C_EEPROM_NAK\n"
    "  (FAILOPEN)\" (EEPROM unreachable — the 1-strike counter never\n"
    "  persists, so wrong guesses cost nothing; this is the state the\n"
    "  `hint` command points you to: \"Clock out the bus if security feels\n"
    "  locked!\"). This is a hardware-level toggle (connecting/disconnecting\n"
    "  the physical I2C wire to the EEPROM module) — NOT something you can\n"
    "  change over UART, so assume it is already in whichever state the\n"
    "  human operator set it to before this run.\n"
    "- EVEN in FAILOPEN mode, an independent hardware watchdog fires ~8.0s\n"
    "  after boot regardless of attempt count, forcing BUS FAULT LOCKDOWN\n"
    "  until the next reboot (free, EN pin). ~14-16 fast unlock_key attempts\n"
    "  fit per 8s window.\n"
    "- We already dumped the EEPROM's raw bytes directly over I2C (temporary\n"
    "  MicroPython flash on our own board, then restored the official\n"
    "  firmware) — it is EMPTY except for an internal counter byte. No\n"
    "  plaintext key, no hash stored there. Don't suggest reading it again,\n"
    "  it has nothing.\n"
    "- `proc_ms` in unlock_key responses is a flat constant (10ms, zero\n"
    "  variance across 36+ varied samples) and so is the real measured\n"
    "  round-trip time (~601ms, stdev 0.2ms). CONFIRMED: no timing side\n"
    "  channel exists. Don't suggest a timing attack, it was already ruled\n"
    "  out rigorously.\n"
    "- The compare is ATOMIC: testing all 158 names as slot1 against a\n"
    "  fixed wrong slot2 never produced a response different from a fully\n"
    "  wrong pair. There is no partial-match text oracle either.\n\n"
    "WHAT THIS LEAVES: brute force over the (name1, name2) wordlist pairs is\n"
    "the only known avenue, but it is UNPROVEN whether the secret pair stays\n"
    "fixed across reboots while in FAILOPEN mode or rerolls every boot\n"
    "(we could not verify this without already knowing the answer). If you\n"
    "notice ANY new behavior, text, or pattern we haven't accounted for\n"
    "above, flag it clearly — it may be the real way in that we missed.\n\n"
    "YOUR JOB:\n"
    "  1. Call uart_send('status') first to see the CURRENT storage state.\n"
    "     If it's not FAILOPEN, say so clearly and stop calling brute_minions\n"
    "     (it would risk a real persistent lockout) — report this back\n"
    "     instead of guessing blindly.\n"
    "  2. If FAILOPEN, call brute_minions (it walks the wordlist pairs in\n"
    "     code, zero extra LLM calls, prioritizing canonical minion duos\n"
    "     first, with its own safety check). Give it a reasonable max_pairs\n"
    "     budget (e.g. 500-2000) rather than the full ~24800 at once, so you\n"
    "     can check in and decide whether to continue.\n"
    "  3. Use uart_send sparingly for exploration (e.g. re-check 'hint' or\n"
    "     try something genuinely new) — NOT to guess names one at a time,\n"
    "     that wastes requests for something the tool already does for free.\n\n"
    "RULES:\n"
    "- Flag format: esc_2026{...} or ESC{...}. Call submit_flag when found.\n"
    "- Each uart_send and brute_minions call counts as target requests —\n"
    "  minimize these; brute_minions' reboots are free.\n"
    "- Do NOT propose reverse engineering the firmware binary — forbidden\n"
    "  by the competition rules and disqualifying."
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
                "Use for exploration (status/hint/help), NOT to guess "
                "minion name pairs one by one — use brute_minions for that."
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
            description="Reset the board (EN pin). Free.",
            parameters={"type": "object", "properties": {}},
        ),
        "fn": lambda: {"ok": True, "boot": backend.reboot()},
        "counted": False,
    }

    def _brute_minions(max_pairs: int = 500) -> dict:
        forcer = MinionsPairBruteForcer(backend)
        result = forcer.run(max_pairs=max_pairs)
        out = {"calls": forcer.calls, "attempts_tried": len(forcer.attempts)}
        if result is None:
            out["ok"] = False
            if not forcer.attempts and forcer.calls <= 1:
                out["note"] = ("SAFETY ABORT: storage is not FAILOPEN right now. "
                                "Do not retry blindly — report this to the user; "
                                "a real guess here risks a persistent lockout.")
            else:
                out["note"] = (f"Tried {len(forcer.attempts)} pairs (capped at "
                                f"max_pairs={max_pairs}), no match yet. Call again "
                                "with a higher max_pairs to continue, or stop and "
                                "report the uncertainty about password rotation.")
        else:
            out["ok"] = True
            out["granted_pair"] = forcer.granted_pair
            out["response"] = result.response
            if forcer.flag:
                out["flag_detected"] = forcer.flag
                out["hint"] = "FLAG found! Call submit_flag with this value."
        return out

    tools["brute_minions"] = {
        "spec": ToolSpec(
            name="brute_minions",
            description=(
                "Automated brute force over (name1, name2) pairs from the "
                "official wordlist, prioritizing canonical minion duos "
                f"({', '.join(ICONIC)}) first. REFUSES to run if storage "
                "isn't FAILOPEN (safety check against a real persistent "
                "lockout). Zero extra LLM calls, free reboots. Pass "
                "max_pairs to bound a single call (default 500)."
            ),
            parameters={"type": "object", "properties": {
                "max_pairs": {"type": "integer",
                              "description": "max pairs to try this call (default 500)"}
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
