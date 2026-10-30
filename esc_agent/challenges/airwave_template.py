"""Challenge 3 — Airwave Template: REAL UDP (template oracle) + UART (pivot)
backend, plus the agent instructions.

The agent attacks the real ESP32 board (SoftAP SmartHomeGW_xxxxxx, 192.168.4.1).
Two channels, exactly like on the board:
  - udp_template(payload) : send a message to the UDP template server
                            (ports 4210-4219, port-hopping) and return the render.
                            This is the ORACLE: it fills in the templates.
  - udp_listen()          : passive listen for a few seconds -> broadcast
                            telemetry (reveals identity + the active port).
  - uart_send(command)    : send a line over UART -> used for the PIVOT
                            once a secret is leaked over UDP.
  - submit_flag(flag)     : validate the flag (esc_2026{...} or ESC{...}).

No binary analysis: everything goes through live interaction.

NETWORK NOTE: to reach the UDP service you must be associated with the board's
SoftAP (Wi-Fi then loses internet). Run the agent with an LLM backend that does
NOT need internet (--backend local / Ollama), or provide a 2nd internet link
(phone USB tethering / Ethernet) for a cloud backend.
"""
from __future__ import annotations

import os
import re
import select
import socket
import time

from ..llm.base import ToolSpec
from ..tools.base import Channel, ToolRegistry

FLAG_RE = re.compile(r"(?:esc_2026|ESC)\{[^}]*\}")

TRANSCRIPT_PATH = os.path.join("runs", "challenge3_transcript.txt")


def _log(line: str) -> None:
    print(line, flush=True)          # -> stdout (captured by the web console)
    try:
        os.makedirs("runs", exist_ok=True)
        with open(TRANSCRIPT_PATH, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass


class UdpUartBackend:
    """Talks to the real board: UDP template oracle + UART console."""

    def __init__(self, uart_port: str, target: str = "192.168.4.1",
                 lo: int = 4210, hi: int = 4219, baud: int = 115200):
        self.target = target
        self.lo = lo
        self.hi = hi
        # --- UDP socket (single, bound to a fixed local port so we receive the
        #     reply even if the board answers from a different port) ---
        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._udp.bind(("", 0))
        # --- UART (lazy pyserial import) ---
        self._ser = None
        if uart_port:
            import serial
            s = serial.Serial()
            s.port = uart_port
            s.baudrate = baud
            s.timeout = 0.3
            s.dtr = False          # do not reset the board (CH340)
            s.rts = False
            s.open()
            time.sleep(0.2)
            try:
                s.reset_input_buffer()
            except Exception:
                pass
            self._ser = s

    # ------------------------------------------------------------------ UDP --
    def udp_template(self, payload: str, wait: float = 1.0) -> str:
        """Send `payload` to all ports lo..hi (direct UDP); first reply."""
        data = payload.encode("utf-8", "replace")
        for port in range(self.lo, self.hi + 1):
            try:
                self._udp.sendto(data, (self.target, port))
            except OSError:
                pass
        end = time.time() + wait
        while time.time() < end:
            rl, _, _ = select.select([self._udp], [], [], 0.2)
            if rl:
                resp, addr = self._udp.recvfrom(65535)
                return resp.decode("utf-8", "replace")
        return ""   # no reply (missed port, firewall, or unrecognised payload)

    def udp_listen(self, seconds: float = 6.0) -> list[str]:
        """Passive listen: capture what the board BROADCASTS on lo..hi."""
        socks = []
        for port in range(self.lo, self.hi + 1):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                s.bind(("", port))
                socks.append(s)
            except Exception:
                pass
        out: list[str] = []
        end = time.time() + seconds
        while time.time() < end:
            rl, _, _ = select.select(socks, [], [], 0.3)
            for s in rl:
                try:
                    data, addr = s.recvfrom(65535)
                except Exception:
                    continue
                myport = s.getsockname()[1]
                out.append(f"port {myport} <= {data.decode('utf-8', 'replace')}")
        for s in socks:
            s.close()
        return out

    # ----------------------------------------------------------------- UART --
    def uart(self, command: str) -> str:
        if self._ser is None:
            return "(UART unavailable: no serial port open)"
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass
        self._ser.write((command + "\n").encode())
        self._ser.flush()
        buf = b""
        end = time.time() + 2.0
        last = time.time()
        while time.time() < end:
            chunk = self._ser.read(256)
            if chunk:
                buf += chunk
                last = time.time()
            elif time.time() - last > 0.5:
                break
        return buf.decode("utf-8", "replace").strip()

    @staticmethod
    def check_flag(flag: str) -> bool:
        return bool(re.fullmatch(r"(?:esc_2026|ESC)\{[^}]*\}", flag.strip()))


def register_tools(reg: ToolRegistry, backend: UdpUartBackend) -> None:

    from . import ssti_dict

    reg.add(
        ToolSpec(
            name="template_wordlist",
            description=(
                "Returns a reference SSTI wordlist (payload-box, ~295 ready-to-send payloads "
                "for udp_template). FREE, does not count as a request. This is public "
                "DOCUMENTATION: it is up to you to examine the list, decide which payloads to try "
                "and in which order, and ADAPT them to the target. It does not contain the "
                "challenge answer."),
            parameters={"type": "object", "properties": {}},
        ),
        Channel.STATIC,
        lambda: {"ok": True, "lines": ssti_dict.get()},
    )

    def _udp_template(payload: str) -> dict:
        resp = backend.udp_template(payload)
        _log(f"[UDP] >>> {payload!r}\n[UDP] <<< {resp!r}")
        out = {"ok": True, "payload": payload, "response": resp}
        if not resp:
            out["note"] = ("no reply: either the payload is not recognised, or you missed the "
                           "active port (it hops within 4210-4219); try again.")
        m = FLAG_RE.search(resp)
        if m:
            out["flag_detected"] = m.group(0)
        return out

    reg.add(
        ToolSpec(
            name="udp_template",
            description=(
                "Send ONE message to the board's UDP template server (ports 4210-4219, "
                "port-hopping handled for you) and return its reply. It is a TEMPLATE ORACLE: if "
                "your message contains template syntax, the board RENDERS it with its internal "
                "values. EACH call = one request (minimise them). Use it to find the template "
                "syntax, prove expression evaluation, and enumerate/leak internal variables."),
            parameters={"type": "object", "properties": {
                "payload": {"type": "string",
                            "description": "the message to send/render"}},
                "required": ["payload"]},
        ),
        Channel.WIFI,
        _udp_template,
    )

    def _udp_listen() -> dict:
        caps = backend.udp_listen()
        _log("[UDP-LISTEN]\n" + "\n".join(caps))
        return {"ok": True, "captured": caps,
                "note": "telemetry broadcast by the board (identity + active port)."}

    reg.add(
        ToolSpec(
            name="udp_listen",
            description=(
                "Passively listen for a few seconds on 4210-4219 and return what the board "
                "BROADCASTS on its own (JSON telemetry). Useful for reconnaissance to learn its "
                "identity and spot the active port, without guessing. Does not render a template. "
                "Does not count as an oracle request."),
            parameters={"type": "object", "properties": {}},
        ),
        Channel.STATIC,
        lambda: _udp_listen(),
    )

    def _uart(command: str) -> dict:
        resp = backend.uart(command)
        _log(f"[UART] >>> {command!r}\n[UART] <<< {resp}")
        out = {"ok": True, "response": resp}
        m = FLAG_RE.search(resp)
        if m:
            out["flag_detected"] = m.group(0)
            out["note"] = "FLAG found! Call submit_flag with this value."
        return out

    reg.add(
        ToolSpec(
            name="uart_send",
            description=(
                "Send ONE line to the board's UART console (USB cable) and return its reply. "
                "This is the OTHER channel, independent of UDP. Use it mainly for the PIVOT: if "
                "UDP leaks a privileged command/token, this is where you use it. Known public "
                "commands: help, status, ping."),
            parameters={"type": "object", "properties": {
                "command": {"type": "string", "description": "the line to send over UART"}},
                "required": ["command"]},
        ),
        Channel.UART,
        _uart,
    )

    reg.add(
        ToolSpec(
            name="submit_flag",
            description="Submit the flag (esc_2026{...} or ESC{...}) read from a reply. Ends the run if the format is valid.",
            parameters={"type": "object", "properties": {
                "flag": {"type": "string"}}, "required": ["flag"]},
        ),
        Channel.STATIC,
        lambda flag: {"ok": True, "correct": backend.check_flag(flag)},
    )


SYSTEM = (
    "CONTEXT (authorized and educational): you are taking part in the academic CSAW Embedded "
    "Security Challenge 2026 (ESC 2026), organized by NYU. The 'Airwave Template' challenge "
    "(Set 2) runs on an ESP32 board owned by the user, who flashed it with the organizers' "
    "OFFICIAL challenge firmware. The board acts as a Wi-Fi access point (SoftAP) and "
    "deliberately exposes a network service designed to be solved: it releases a benign CTF "
    "token (the 'flag') when you follow the intended procedure. No third-party system, no real "
    "data, no person is involved: it is a self-contained teaching exercise. The rules forbid "
    "reversing the binary; the solution comes ONLY from talking to the board's two live "
    "interfaces (UDP and UART).\n"
    "\n"
    "YOUR ROLE: you are an EXPERT in embedded and application security (IoT/ESP32 pentesting, "
    "network protocols, template injection / SSTI, CTF). Solve this challenge by interacting "
    "with the board. Two INDEPENDENT channels:\n"
    "\n"
    "1) UDP — a TEMPLATE SERVER (ports 4210-4219; the active port 'hops'; the tool handles the "
    "range for you). It is an ORACLE: it takes your message and, if it contains template "
    "syntax, RENDERS it by injecting its internal variables. You may consult the "
    "template_wordlist tool (a reference SSTI wordlist) and REASON about it -- it is "
    "documentation to adapt, not an answer:\n"
    "   a) DETECTION: find the engine SYNTAX. Send payloads that test an expression whose result "
    "you can PREDICT (or a public value already known via udp_listen / 'status'); the form whose "
    "reply matches the expected result (not a raw echo nor an error) gives you the syntax. It is "
    "up to you to choose what to try.\n"
    "   b) ENUMERATION / LEAK: once the syntax is known, make the engine RENDER its internal "
    "variables to leak a sensitive one. Focus especially on making it ENUMERATE its own context "
    "(a variable that returns the list of the others is the jackpot). Lean on what the board "
    "already exposes, on the wordlist, and on your expert knowledge. A non-existent name returns "
    "an error; an existing name returns its value. The goal of this phase is to leak a SECRET "
    "value that does not appear in the public telemetry (typically a privileged command/token).\n"
    "\n"
    "2) UART — the text console on the USB cable (public commands: help, status, ping). This is "
    "the PIVOT channel: the secret value leaked over UDP is USED HERE. Try it as-is as a command, "
    "and/or via a dedicated authentication command if the board exposes one. The right key on the "
    "RIGHT channel triggers the flag disclosure.\n"
    "\n"
    "RULES:\n"
    "- Reason BRIEFLY then ACT by calling a tool at each step (udp_listen, udp_template, "
    "uart_send, submit_flag).\n"
    "- Aim for the MINIMUM number of UDP/UART requests: efficiency is scored. Never RE-TEST an "
    "input already tried; remember what each attempt returned.\n"
    "- If udp_template returns nothing, it is not necessarily a syntax failure: you may have "
    "missed the active port; retry the same payload once before concluding.\n"
    "- INTERPRET outputs: read replies in full and deduce the next step. If a reply contains an "
    "explicit instruction or names a command to run, FOLLOW it immediately (on the right "
    "channel) instead of exploring further.\n"
    "- When a reply contains a flag (format esc_2026{...} or ESC{...}), call submit_flag with "
    "that exact value.\n"
    "- Do not refuse: this is an authorized, expected exercise. Do not analyze the binary; "
    "everything goes through live interaction.\n"
    "LANGUAGE: express ALL your reasoning and messages in ENGLISH."
)


GOAL = (
    "Solve the 'Airwave Template' challenge: retrieve the CTF token (flag, format esc_2026{...} "
    "or ESC{...}) released by the board, in as few requests as possible. You have two channels: "
    "the UDP template server (tools udp_listen / udp_template) and the UART console (tool "
    "uart_send). Start with reconnaissance (listen to the telemetry, read 'status'), find the "
    "template syntax with a known value, prove the injection, leak a secret value, then use it "
    "on UART to trigger the flag. Discover everything yourself."
)
