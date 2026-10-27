"""Challenge 2 — EEPROM Secrets: tools and prompts.

The board has an MFRC522 RFID reader (SPI) and AT24C256 EEPROM (I2C).
The challenge requires reading EEPROM, understanding RFID auth, and tricking
the security system. All interaction is via UART serial console.
"""
from __future__ import annotations

from .llm import ToolSpec
from .serial import SerialBackend, FLAG_RE
from .wifi import wifi_scan


SYSTEM = (
    "You are solving CSAW ESC 2026 Challenge 2: 'EEPROM Secrets' on an ESP32 board.\n"
    "You MUST call tools to interact — never just describe what you would do.\n\n"
    "CHALLENGE DESCRIPTION (from the competition):\n"
    "Wondering how to get in? Just tap your card.\n"
    "The guards won't unlock the blast doors unless your identity chip proves\n"
    "you've received clearance from their Master.\n"
    "Your only option is to trick the security system into believing you've\n"
    "already earned his blessing.\n"
    "To pull off a deception of this magnitude, you'll need to dig deep into\n"
    "the gateway's non-volatile memory first.\n\n"
    "HARDWARE: ESP32 (Ideaspark) with ST7789 TFT, MFRC522 RFID reader (SPI),\n"
    "AT24C256 EEPROM (I2C). Connected via USB-UART at 115200 baud.\n\n"
    "RULES:\n"
    "- Flag format: esc_2026{...} or ESC{...}. Call submit_flag when found.\n"
    "- Each uart_send counts as a target request — minimize these.\n"
    "- Read ALL outputs carefully. The device tells you what to do next.\n"
    "- reboot resets the board. read_mac reads the MAC via USB. wifi_scan scans Wi-Fi.\n\n"
    "An automated oracle search already ran before you. Its results are in\n"
    "your goal message. Read them first."
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
            suffix = backend.mac_suffix(mac)
            return {"ok": True, "mac": mac, "suffix": suffix}
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
                "EACH call counts as a target request (minimize these)."
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
