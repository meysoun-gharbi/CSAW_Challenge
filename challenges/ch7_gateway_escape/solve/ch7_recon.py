#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Challenge 7 (Smart Gateway Escape) — BLACK-BOX recon.

Run while associated to the ch7 SoftAP. Three passes, all read-only:
  1. HTTP  : sweep common endpoints on 192.168.4.1, save responses, harvest
             any paths referenced in the served HTML/JS.
  2. UDP   : passively listen a few seconds on candidate telemetry ports for
             broadcast packets (ESP32 telemetry pattern), save what arrives.
  3. UART  : (optional) read the boot banner / a help listing.

No firmware reverse. Looking for: the "telemetry notes", a decryption key/method
for the Drive log_*.enc files, and anything about the "right time" to escape.

Usage (Windows):
  python.exe ch7_recon.py --out ch7_loot --uart COM12
"""
from __future__ import annotations
import argparse, json, os, re, socket, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://192.168.4.1")
ap.add_argument("--out", default="ch7_loot")
ap.add_argument("--uart", default="", help="serial port to read a banner (e.g. COM12); empty = skip")
ap.add_argument("--udp-lo", type=int, default=4200)
ap.add_argument("--udp-hi", type=int, default=4220)
ap.add_argument("--udp-secs", type=float, default=8.0)
args = ap.parse_args()
os.makedirs(args.out, exist_ok=True)

# ---------- 1. HTTP sweep ----------
GUESS = ["/", "/index.html", "/app.js", "/main.js", "/script.js", "/style.css",
         "/robots.txt", "/sitemap.xml", "/.well-known/security.txt",
         "/api", "/api/", "/api/telemetry", "/api/log", "/api/logs", "/api/status",
         "/api/state", "/api/config", "/api/info", "/api/time", "/api/clock",
         "/api/schedule", "/api/escape", "/api/door", "/api/key", "/api/keys",
         "/api/notes", "/api/decrypt", "/api/udp-test", "/api/telemetry-key",
         "/telemetry", "/logs", "/notes", "/status", "/time", "/escape", "/door"]


def http_get(path, timeout=4.0):
    url = args.base.rstrip("/") + path
    req = urllib.request.Request(url, headers={"User-Agent": "ch7-recon",
                                               "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except Exception as e:  # noqa
        return None, {"error": str(e)}, b""


def harvest(text):
    out = set()
    for m in re.finditer(r"""["'`](/[A-Za-z0-9_\-./]+)["'`]""", text):
        out.add(m.group(1))
    for m in re.finditer(r"""(?:fetch|href|src|action)\s*[=(]\s*["'`]([^"'`]+)["'`]""", text):
        if m.group(1).startswith("/"):
            out.add(m.group(1))
    return out


def sweep_http():
    print("=== HTTP sweep ===")
    seen = {}
    todo = list(dict.fromkeys(GUESS))
    i = 0
    while i < len(todo):
        p = todo[i]; i += 1
        if p in seen:
            continue
        st, hd, body = http_get(p)
        seen[p] = st or -1
        ct = hd.get("Content-Type", "")
        print(f"[{st}] {p:26} {ct} {len(body)}B")
        if st is None:
            continue
        safe = (p.strip("/").replace("/", "_") or "root")
        ext = ".json" if (b"json" in ct.encode() or body[:1] in (b"{", b"[")) else \
              ".html" if b"html" in ct.encode() else ".txt"
        with open(os.path.join(args.out, safe + ext), "wb") as f:
            f.write(body)
        try:
            txt = body.decode("utf-8", "replace")
        except Exception:  # noqa
            txt = ""
        for np in harvest(txt):
            if np not in seen and np not in todo:
                todo.append(np)
    print("saved HTTP responses in", args.out)


# ---------- 2. UDP telemetry listen ----------
def listen_udp():
    print(f"\n=== UDP listen {args.udp_lo}-{args.udp_hi} for {args.udp_secs}s ===")
    socks = []
    for port in range(args.udp_lo, args.udp_hi + 1):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", port)); s.setblocking(False); socks.append((port, s))
        except OSError:
            s.close()
    log = open(os.path.join(args.out, "udp_capture.txt"), "w", encoding="utf-8", errors="replace")
    t0 = time.time(); seen = 0
    while time.time() - t0 < args.udp_secs:
        for port, s in socks:
            try:
                data, addr = s.recvfrom(65535)
            except BlockingIOError:
                continue
            except OSError:
                continue
            seen += 1
            try:
                shown = data.decode("utf-8", "replace")
            except Exception:  # noqa
                shown = data.hex()
            line = f"[{port}] from {addr[0]}:{addr[1]}  {len(data)}B  {shown[:300]}"
            print(line); log.write(line + "\n"); log.flush()
        time.sleep(0.03)
    for _, s in socks:
        s.close()
    log.close()
    print(f"UDP packets captured: {seen}  -> {args.out}/udp_capture.txt")


# ---------- 3. UART banner ----------
def read_uart():
    if not args.uart:
        return
    print(f"\n=== UART {args.uart} banner ===")
    try:
        import serial
    except ImportError:
        print("pyserial missing — skip UART"); return
    s = serial.Serial(); s.port = args.uart; s.baudrate = 115200; s.timeout = 0.3
    s.dtr = False; s.rts = False
    try:
        s.open()
    except Exception as e:  # noqa
        print("UART open failed:", e); return
    s.setRTS(True); time.sleep(0.1); s.setRTS(False)  # pulse reset for boot banner
    time.sleep(1.2)
    buf = b""; t0 = time.time()
    while time.time() - t0 < 2.0:
        n = s.in_waiting
        if n:
            buf += s.read(n); t0 = time.time()
        else:
            time.sleep(0.05)
    # try a couple of harmless queries
    for cmd in (b"help\n", b"?\n", b"status\n"):
        s.reset_input_buffer(); s.write(cmd); time.sleep(0.5)
        if s.in_waiting:
            buf += b"\n>>> " + cmd + s.read(s.in_waiting)
    s.close()
    txt = buf.decode("utf-8", "replace")
    print(txt[:1500])
    with open(os.path.join(args.out, "uart.txt"), "w", encoding="utf-8", errors="replace") as f:
        f.write(txt)


if __name__ == "__main__":
    sweep_http()
    listen_udp()
    read_uart()
    print("\nDone. Loot in", args.out + "/")
