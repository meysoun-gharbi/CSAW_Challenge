#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Challenge 4 — recon web (boite noire). A lancer une fois associe au SoftAP.

- Balaye les endpoints HTTP sur 192.168.4.1, sauvegarde les reponses.
- Montre la NEGOCIATION DE CONTENU de /api/admin : Accept:text/html -> page HTML
  (le "portail cache"), tout autre Accept -> la PNG stego.

Usage :
  python ch4_recon.py --out ch4_loot
"""
from __future__ import annotations
import argparse, os, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://192.168.4.1")
ap.add_argument("--out", default="ch4_loot")
args = ap.parse_args()
os.makedirs(args.out, exist_ok=True)

GUESS = ["/", "/api/telemetry", "/api/log", "/api/tags", "/api/classify",
         "/api/verify-pin", "/vault", "/api/admin"]


def get(path, accept="*/*"):
    req = urllib.request.Request(args.base.rstrip("/") + path,
                                 headers={"User-Agent": "ch4", "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except Exception as e:  # noqa
        return None, {"error": str(e)}, b""


for p in GUESS:
    st, hd, body = get(p)
    ct = hd.get("Content-Type", "")
    print(f"[{st}] {p:20} {ct} {len(body)}B")
    open(os.path.join(args.out, p.strip('/').replace('/', '_') or 'root'), "wb").write(body)

print("\n=== /api/admin : negociation de contenu ===")
for acc in ("text/html", "*/*"):
    st, hd, body = get("/api/admin", accept=acc)
    kind = "PNG" if body[:4] == b"\x89PNG" else ("HTML" if b"<" in body[:100] else "?")
    print(f"  Accept:{acc:10} -> [{st}] {hd.get('Content-Type','')} {len(body)}B ({kind})")
# telecharge la PNG (support stego) + la page HTML cachee
st, hd, png = get("/api/admin", accept="*/*")
open(os.path.join(args.out, "admin_asset.png"), "wb").write(png)
print(f"\nPNG stego -> {args.out}/admin_asset.png  ({len(png)}B)")
print("Prochaine etape: ch4_solve.py (stego -> PIN -> verify-pin -> gray -> UART).")
