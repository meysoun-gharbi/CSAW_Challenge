#!/usr/bin/env python3
"""List available Gemini models for your API key."""
import os
from google import genai

key = os.environ.get("GEMINI_API_KEY")
if not key:
    raise SystemExit("Set GEMINI_API_KEY first")

client = genai.Client(api_key=key)
for m in client.models.list():
    name = getattr(m, "name", "?")
    actions = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None)
    actions = list(actions or [])
    if "generateContent" in actions:
        print(name)
