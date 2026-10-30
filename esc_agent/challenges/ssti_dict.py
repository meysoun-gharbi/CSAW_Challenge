"""Charge la wordlist SSTI de reference embarquee (payload-box, non modifiee).

wordlists/ssti-all-payloads.txt : payloads SSTI PRETS A ENVOYER, dans l'ordre
  - detection  : {{7*7}}, ${7*7}, <%= 7*7 %>, #{7*7} ...  (eval -> 49)
  - dump        : {{config}}, {{self}}, {{request}} ...    (liste/contexte)
  - RCE         : {{''.__class__...}} ...                  (moteurs web)

Source : https://github.com/payload-box/ssti-advanced-payload-list
(voir wordlists/SOURCES.md). Rien n'est ecrit a la main ici.
"""
from __future__ import annotations

import os

_DIR = os.path.join(os.path.dirname(__file__), "wordlists")


def all_payloads() -> list[str]:
    path = os.path.join(_DIR, "ssti-all-payloads.txt")
    with open(path, encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f if ln.strip()]


def get(name: str = "payloads") -> list[str]:
    return all_payloads()
