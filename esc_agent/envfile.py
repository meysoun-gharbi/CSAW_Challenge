"""Chargeur .env minimal (stdlib, aucune dependance).

Lit un fichier `.env` (KEY=VALUE par ligne) et pose les variables dans
os.environ SANS ecraser celles deja definies. Appele au demarrage des runners
pour que les cles API (ANTHROPIC_API_KEY, GEMINI_API_KEY...) soient lues depuis
un fichier git-ignore plutot que tapees en clair a chaque lancement.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | os.PathLike | None = None) -> None:
    """Charge `.env` (celui donne, sinon dans le cwd, sinon a la racine du projet)."""
    candidates = []
    if path:
        candidates.append(Path(path))
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path(__file__).resolve().parent.parent / ".env")

    for p in candidates:
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key.lower().startswith("export "):
                key = key[len("export "):].strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
        return  # premier .env trouve = on s'arrete
