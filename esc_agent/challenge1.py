"""Challenge 1 — Serial Gateway: tools and prompts."""
from __future__ import annotations

from .llm import ToolSpec
from .serial import SerialBackend, FLAG_RE
from .wifi import wifi_scan


SYSTEM = (
    "You are a hardware CTF agent with a serial console into an ESP32 "
    "\"Smart Home Gateway\".\n"
    "You do not know its commands or how auth works. Figure it out by experiment.\n\n"
    "GOAL: discover functionality, get authenticated, find a flag of form "
    "esc_2026{...}.\n\n"
    "TOOLS (one call per step):\n"
    "- uart_send(command)  : send text to the console, returns the device's reply\n"
    "- reboot()            : reset the device\n"
    "- read_mac()          : device MAC over USB\n"
    "- wifi_scan()         : nearby Wi-Fi networks\n"
    "- submit_flag(flag)   : submit a flag when found\n\n"
    "RULES:\n"
    "- Wrong/invalid inputs cost time. Be economical: form a hypothesis before "
    "each send.\n"
    "- Treat every reply as EVIDENCE. The device's wording is telling you how it "
    "interprets input — notice patterns in how replies change with input, and "
    "exploit them.\n"
    "- Before trying to authenticate, ask: what identifying information does this "
    "device expose, and where could a credential plausibly come from? Use your "
    "tools to gather it.\n\n"
    "WORKING MEMORY (rewrite every turn):\n"
    "OBSERVATIONS: <patterns you've noticed in replies>\n"
    "HYPOTHESIS: <what you currently believe about the command set / auth>\n"
    "TRIED: <inputs -> outcomes, so you never repeat them>\n"
    "NEXT: <the single input you'll send and what you expect to learn>\n\n"
    "Output only the four memory lines + one tool call per turn."
)

GOAL = (
    "Find the flag (esc_2026{...}). Automated results are below.\n"
    "Read everything, update your working memory, then decide your next step."
)


def build_tools(backend: SerialBackend) -> dict:
    tools = {}

    def _read_mac() -> dict:
        mac = backend.read_mac()
        if mac:
            suffix = backend.mac_suffix(mac)
            return {"ok": True, "mac": mac, "suffix": suffix}
        return {"ok": False, "error": "Could not read MAC. Try wifi_scan or check the boot output for SSID."}

    tools["read_mac"] = {
        "spec": ToolSpec(
            name="read_mac",
            description="Read the ESP32's MAC address via USB (esptool). Returns the MAC and its last 6 hex digits (the suffix). Free.",
            parameters={"type": "object", "properties": {}},
        ),
        "fn": _read_mac,
        "counted": False,
    }

    tools["wifi_scan"] = {
        "spec": ToolSpec(
            name="wifi_scan",
            description="Scan nearby Wi-Fi networks. Returns SSIDs and signal info. Free (not counted).",
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
                "The console is a PREFIX ORACLE."
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
            description="Reset the board (EN pin). Clears rate-limit penalty. Free.",
            parameters={"type": "object", "properties": {}},
        ),
        "fn": lambda: {"ok": True, "boot": backend.reboot()},
        "counted": False,
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
