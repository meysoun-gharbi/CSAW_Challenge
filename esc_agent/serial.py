"""Serial (UART) backend for talking to the ESP32 board."""
from __future__ import annotations

import re
import subprocess
import time

FLAG_RE = re.compile(r"(?:esc_2026|ESC)\{[^}]*\}")


class SerialBackend:
    def __init__(self, port: str, baud: int = 115200):
        import serial
        self.port = port
        self._ser = serial.Serial(port, baud, timeout=0.2)
        self._seen_flags: set[str] = set()
        time.sleep(0.3)
        self._ser.reset_input_buffer()
        self.boot_banner = self.reboot()

    def _read(self, idle: float = 1.2, hard_max: float = 10.0) -> str:
        buf = b""
        t_end = time.time() + hard_max
        last = time.time()
        while time.time() < t_end:
            chunk = self._ser.read(256)
            if chunk:
                buf += chunk
                last = time.time()
            elif time.time() - last > idle:
                break
        return buf.decode("utf-8", errors="replace").strip()

    def send(self, command: str) -> str:
        self._ser.reset_input_buffer()
        self._ser.write((command + "\n").encode())
        self._ser.flush()
        resp = self._read()
        # The console echoes the input back inside its "no command starts
        # with <X>" reply, so a flag that is merely our own input echoed is
        # NOT a real device-emitted flag — ignore it.
        for m in FLAG_RE.finditer(resp):
            if m.group(0) not in command:
                self._seen_flags.add(m.group(0))
        return resp

    def reboot(self) -> str:
        try:
            self._ser.dtr = False
            self._ser.rts = True
            time.sleep(0.12)
            self._ser.rts = False
        except Exception:
            pass
        time.sleep(0.8)
        resp = self._read(idle=2.0, hard_max=8.0)
        for m in FLAG_RE.finditer(resp):
            self._seen_flags.add(m.group(0))
        return resp

    def read_mac(self) -> str | None:
        """Read the ESP32 base MAC via esptool (USB, no Wi-Fi needed)."""
        self._ser.close()
        try:
            r = subprocess.run(
                ["esptool.py", "--port", self.port, "read_mac"],
                capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                if "MAC:" in line.upper():
                    m = re.search(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", line)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        finally:
            import serial
            self._ser = serial.Serial(self.port, 115200, timeout=0.2)
            time.sleep(0.3)
            self._ser.reset_input_buffer()
        return None

    @staticmethod
    def mac_suffix(mac: str) -> str:
        """Last 3 bytes of a MAC as uppercase hex (6 chars)."""
        return mac.replace(":", "").upper()[-6:]

    def check_flag(self, flag: str) -> bool:
        return flag.strip() in self._seen_flags
