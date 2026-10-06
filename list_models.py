#!/usr/bin/env python3
"""Liste les modeles Gemini disponibles avec ta cle API.

Usage (apres avoir pose GEMINI_API_KEY):
    python list_models.py

Repere une ligne marquee '<-- utilisable' et recopie son nom (sans le prefixe
'models/') apres --model dans run.py.
"""
import os
from google import genai

key = os.environ.get("GEMINI_API_KEY")
if not key:
    raise SystemExit("Pose d'abord ta cle: $env:GEMINI_API_KEY=\"ta_cle\"")

client = genai.Client(api_key=key)

print("Modeles disponibles (ceux marques peuvent faire tourner l'agent):\n")
for m in client.models.list():
    name = getattr(m, "name", "?")
    actions = getattr(m, "supported_actions", None)
    if actions is None:
        actions = getattr(m, "supported_generation_methods", None)
    actions = list(actions or [])
    mark = "   <-- utilisable" if "generateContent" in actions else ""
    print(f"{name}{mark}")
