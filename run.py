#!/usr/bin/env python3
"""Lance UN run de l'agent sur le challenge factice.

Usage:
  python run.py                 # backend mock (hors-ligne, sans cle API)
  python run.py --backend gemini --model gemini-3-pro   # vrai Gemini (GEMINI_API_KEY requis)

Le mode mock prouve que boucle + outils + metriques fonctionnent sans materiel.
"""
from __future__ import annotations

import argparse

from esc_agent.agent import Agent, new_run_id
from esc_agent.challenges.mock_challenge import GOAL, MockBackend
from esc_agent.metrics import EventLogger, aggregate, format_table
from esc_agent.tools.base import ToolRegistry
from esc_agent.tools.device import register_device_tools

SYSTEM = (
    "Tu es un agent d'analyse de securite pour un challenge ESP32 (CSAW ESC). "
    "Tu disposes d'outils d'analyse statique (gratuits en requetes) et d'outils "
    "d'interaction live avec la cible (chaque appel = une requete, a minimiser). "
    "Methode: comprendre via l'analyse statique, DEDUIRE la bonne action, puis "
    "agir en live en un minimum de requetes. Soumets le flag avec submit_flag."
)


def build_llm(backend: str, model: str):
    if backend == "mock":
        from esc_agent.llm.mock import MockClient
        return MockClient()
    if backend == "gemini":
        from esc_agent.llm.gemini import GeminiClient
        return GeminiClient(model=model)
    if backend == "claude":
        from esc_agent.llm.claude import ClaudeClient
        return ClaudeClient(model=model)
    if backend == "ollama":
        from esc_agent.llm.ollama import OllamaClient
        return OllamaClient(model=model)
    raise SystemExit(f"backend inconnu: {backend}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="mock", choices=["mock", "gemini", "claude", "ollama"])
    ap.add_argument("--model", default="gemini-3-pro")
    ap.add_argument("--log", default="runs/run.jsonl")
    ap.add_argument("--max-steps", type=int, default=12)
    args = ap.parse_args()

    llm = build_llm(args.backend, args.model)
    rid = new_run_id()
    with EventLogger(args.log) as logger:
        backend = MockBackend()
        reg = ToolRegistry(logger, rid)
        register_device_tools(reg, backend)
        agent = Agent(llm, reg, logger, rid, max_steps=args.max_steps)
        summary = agent.run(SYSTEM, GOAL, challenge="mock_uart_unlock")

    print(f"\nrun {rid}  backend={llm.name}  model={llm.model}")
    print(f"  resolu   : {summary.solved}  ({summary.reason})")
    print(f"  requetes cible : {summary.target_interactions}  {summary.interactions_by_channel}")
    print(f"  appels LLM     : {summary.llm_calls}")
    print(f"  tokens totaux  : {summary.total_tokens}")
    print(f"  temps mur      : {summary.wall_ms:.0f} ms")
    print("\n-- agregat (1 run) --")
    print(format_table(aggregate([summary])))


if __name__ == "__main__":
    main()
