"""Cross-platform Wi-Fi scanner (Linux nmcli / Windows netsh)."""
from __future__ import annotations

import shutil
import subprocess


def wifi_scan() -> str:
    # Linux (nmcli)
    if shutil.which("nmcli"):
        try:
            r = subprocess.run(
                ["nmcli", "-f", "SSID,BSSID,SIGNAL", "dev", "wifi", "list", "--rescan", "yes"],
                capture_output=True, text=True, timeout=25)
            if r.stdout.strip():
                return "Wi-Fi scan (nmcli):\n" + r.stdout.strip()
        except Exception:
            pass

    # Windows (netsh)
    if shutil.which("netsh") or shutil.which("netsh.exe"):
        try:
            cmd = shutil.which("netsh") or shutil.which("netsh.exe")
            r = subprocess.run(
                [cmd, "wlan", "show", "networks", "mode=bssid"],
                capture_output=True, text=True, timeout=20)
            if r.stdout.strip():
                return "Wi-Fi scan (netsh):\n" + r.stdout.strip()
        except Exception:
            pass

    return "ERROR: Wi-Fi scan unavailable (no nmcli or netsh found)"
