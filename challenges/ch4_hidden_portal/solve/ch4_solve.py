#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Challenge 4 — solveur complet (boite noire, 100% HTTP + UART).

Chaine :
  1. GET /api/admin (Accept:*/*)            -> PNG stego
  2. LSB canal Rouge (row-major, MSB-first) -> "PIN:9573"
  3. POST /api/verify-pin {"sequence":[...]}-> deverrouille le vault
  4. GET /vault                             -> payload hex "encoded at rest"
  5. decodage GRAY CODE du payload          -> "...diag_dump <token>"
  6. UART `diag_dump <token>`               -> FLAG

Pre-requis : pip install pyserial  (urllib = stdlib).
A lancer associe au SoftAP + cable USB branche.

Usage :
  python ch4_solve.py --port COM12
"""
from __future__ import annotations
import argparse, json, re, struct, sys, time, urllib.request, zlib

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://192.168.4.1")
ap.add_argument("--port", default="COM12", help="port serie (COM12, /dev/ttyUSB0...)")
args = ap.parse_args()
FLAGRE = re.compile(r"(esc_2026|ESC)\{[^}]*\}", re.I)


def http(path, method="GET", body=None, accept="*/*"):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"User-Agent": "ch4", "Accept": accept}
    if data: hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(args.base.rstrip("/") + path, data=data, headers=hdr, method=method)
    with urllib.request.urlopen(req, timeout=6) as r:
        return r.read()


# ---- 1 & 2 : PNG stego -> PIN (LSB canal R, row-major, MSB-first) ----
def png_pixels(png):
    i = 8; idat = b""
    while i < len(png):
        ln = struct.unpack(">I", png[i:i+4])[0]; typ = png[i+4:i+8]; d = png[i+8:i+8+ln]
        if typ == b"IHDR": W, H, _, ct = struct.unpack(">IIBB", d[:10])
        elif typ == b"IDAT": idat += d
        i += 12 + ln
        if typ == b"IEND": break
    raw = zlib.decompress(idat); ch = {0:1,2:3,3:1,4:2,6:4}[ct]; stride = W*ch
    def paeth(a,b,c):
        p=a+b-c; pa=abs(p-a); pb=abs(p-b); pc=abs(p-c)
        return a if pa<=pb and pa<=pc else (b if pb<=pc else c)
    out = bytearray(); prev = bytearray(stride); pos = 0
    for _ in range(H):
        f = raw[pos]; pos += 1; line = bytearray(raw[pos:pos+stride]); pos += stride
        for x in range(stride):
            a = line[x-ch] if x>=ch else 0; b = prev[x]; c = prev[x-ch] if x>=ch else 0; v = line[x]
            if f==1: v=(v+a)&255
            elif f==2: v=(v+b)&255
            elif f==3: v=(v+((a+b)>>1))&255
            elif f==4: v=(v+paeth(a,b,c))&255
            line[x]=v
        out += line; prev = line
    return [tuple(out[j:j+ch]) for j in range(0, len(out), ch)]


def stego_pin(png):
    px = png_pixels(png)
    bits = [p[0] & 1 for p in px]                    # LSB canal Rouge
    data = bytes(int("".join(map(str, bits[i:i+8])), 2) for i in range(0, len(bits)-7, 8))
    txt = data.split(b"\x00")[0].decode("ascii", "replace")  # "PIN:9573"
    return re.search(r"\d{4}", txt).group(0)


# ---- 5 : decodage Gray code ----
def gray_to_bin(g):
    g ^= g >> 4; g ^= g >> 2; g ^= g >> 1; return g & 0xff


def main():
    print("[1] GET /api/admin -> PNG stego")
    png = http("/api/admin", accept="*/*")
    if png[:4] != b"\x89PNG": sys.exit("pas une PNG (negociation Accept ?)")

    print("[2] stego LSB canal R -> PIN")
    pin = stego_pin(png); print("    PIN =", pin)

    print("[3] POST /api/verify-pin")
    seq = [int(c) for c in pin]
    r = http("/api/verify-pin", method="POST", body={"sequence": seq})
    print("   ", r.decode("utf-8", "replace"))

    print("[4] GET /vault -> payload")
    vault = http("/vault").decode("utf-8", "replace")
    m = re.search(r"([0-9a-fA-F]{40,})", vault)
    payload = bytes.fromhex(m.group(1)); print("    payload", len(payload), "octets")

    print("[5] decodage Gray code")
    msg = bytes(gray_to_bin(c) for c in payload).decode("utf-8", "replace")
    print("   ", msg)
    tok = re.search(r"diag_dump\s+(\S+)", msg)
    token = tok.group(1) if tok else msg.split()[-1]
    print("    token =", token)

    print("[6] UART diag_dump", token)
    import serial
    s = serial.Serial(); s.port = args.port; s.baudrate = 115200; s.timeout = 0.3
    s.dtr = False; s.rts = False; s.open(); time.sleep(0.3); s.reset_input_buffer()
    s.write(f"diag_dump {token}\n".encode()); time.sleep(1.0)
    buf = b""; t = time.time()
    while time.time()-t < 3:
        n = s.in_waiting
        if n: buf += s.read(n); t = time.time()
        else: time.sleep(0.05)
    s.close()
    out = buf.decode("utf-8", "replace"); print("   ", out.strip()[-300:])
    fm = FLAGRE.search(out)
    print("\n*** FLAG ***", fm.group(0)) if fm else print("pas de flag — verifier le token/port")


if __name__ == "__main__":
    main()
