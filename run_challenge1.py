#!/usr/bin/env python3
"""Lance l'agent sur le VRAI challenge 1 (Serial Gateway) via la carte.

Prerequis:
  - carte flashee avec le firmware du challenge, branchee (ex: COM4 ou /dev/ttyUSB0)
  - pip install google-genai pyserial   (et anthropic pour --backend claude)
  - GEMINI_API_KEY (ou ANTHROPIC_API_KEY) pose dans l'environnement

Usage:
  python run_challenge1.py --port COM4 --backend gemini --model gemini-flash-latest
  python run_challenge1.py --port /dev/ttyUSB0 --backend gemini --model gemini-flash-latest
  python run_challenge1.py --port COM4 --max-steps 400
"""
from __future__ import annotations

import argparse

from esc_agent.agent import Agent, new_run_id
from esc_agent.challenges.serial_gateway import GOAL, SYSTEM, RealSerialBackend, register_tools
from esc_agent.llm.base import LLMClient
from esc_agent.metrics import EventLogger, aggregate, format_table
from esc_agent.tools.base import ToolRegistry
from run import build_llm


class _LazyCloud(LLMClient):
    """Construit le vrai client cloud seulement au premier appel reel.

    Sert de 'planner' pour oracle_dictionary_search quand le backend principal
    est local/hybride: evite d'exiger le SDK cloud si le run n'a jamais besoin
    de generer de dictionnaire (par ex. s'il ne touche jamais l'oracle UART)."""
    name = "lazy-cloud"

    def __init__(self, factory):
        self._factory = factory
        self._client: LLMClient | None = None
        self.model = "lazy"

    def step(self, system, history, tools):
        if self._client is None:
            self._client = self._factory()
            self.model = self._client.model
        return self._client.step(system, history, tools)


def build_planner(llm, args) -> LLMClient | None:
    """Le 'planner' (strategiste) pour oracle_dictionary_search: toujours un
    backend cloud, independamment du backend principal choisi pour l'agent."""
    if args.backend in ("gemini", "claude"):
        return llm  # deja un client cloud: pas besoin d'en construire un autre
    if args.fallback_backend and args.fallback_model:
        return _LazyCloud(lambda: build_llm(args.fallback_backend, args.fallback_model))
    return None  # pas de cloud configure: l'outil oracle_dictionary_search sera desactive


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM4", help="port serie (COM4, /dev/ttyUSB0...)")
    ap.add_argument("--backend", default="gemini",
                     choices=["gemini", "mock", "claude", "ollama", "hybrid"])
    ap.add_argument("--model", default="gemini-flash-latest")
    ap.add_argument("--fallback-backend", default=None, choices=["gemini", "claude"],
                     help="(mode hybrid) backend cloud de secours")
    ap.add_argument("--fallback-model", default=None,
                     help="(mode hybrid) modele cloud de secours (ex: gemini-flash-latest)")
    ap.add_argument("--local-timeout", type=float, default=20.0,
                     help="(mode hybrid) secondes max avant d'abandonner le local et escalader")
    ap.add_argument("--log", default="runs/challenge1.jsonl")
    ap.add_argument("--max-steps", type=int, default=400)
    args = ap.parse_args()

    llm = build_llm(args.backend, args.model, args.fallback_backend, args.fallback_model,
                     args.local_timeout)
    rid = new_run_id()
    print(f"Challenge 1 — Serial Gateway | port={args.port} | modele={llm.model}")
    print("L'agent decouvre tout seul: recon Wi-Fi, oracle UART, puis le flag.\n")

    planner = build_planner(llm, args)
    if planner is None:
        print("(oracle_dictionary_search desactive: pas de backend cloud configure "
              "-- utilise --fallback-backend/--fallback-model, ou --backend gemini/claude)\n")

    with EventLogger(args.log) as logger:
        backend = RealSerialBackend(args.port)
        reg = ToolRegistry(logger, rid)
        register_tools(reg, backend, planner=planner)
        agent = Agent(llm, reg, logger, rid, max_steps=args.max_steps, verbose=True)
        # On donne a l'agent les logs UART de demarrage, a interpreter (comme le ferait
        # un humain qui ouvre un terminal serie et appuie sur reset).
        goal = GOAL
        if getattr(backend, "boot_banner", ""):
            goal = (GOAL + "\n\n--- Sortie de la console de la carte au demarrage "
                    "(logs UART a interpreter) ---\n" + backend.boot_banner.strip())
        summary = agent.run(SYSTEM, goal, challenge="serial_gateway")

    print(f"\n==== Resultat ====")
    print(f"  resolu        : {summary.solved}  ({summary.reason})")
    print(f"  requetes UART : {summary.target_interactions}")
    print(f"  appels LLM    : {summary.llm_calls}")
    print(f"  tokens totaux : {summary.total_tokens}")
    print(f"  temps mur     : {summary.wall_ms/1000:.1f} s")
    print("\n" + format_table(aggregate([summary])))
    if hasattr(llm, "local_steps"):  # mode hybrid: repartition local vs cloud
        print(f"  repartition   : local={llm.local_steps}  cloud={llm.cloud_steps}")
    print(f"\nJournal detaille: {args.log}")


if __name__ == "__main__":
    main()
