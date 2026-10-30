#!/usr/bin/env python3
"""Lance l'agent sur le VRAI challenge 3 (Airwave Template) via la carte.

Prerequis:
  - carte flashee avec le firmware du challenge, allumee (SoftAP SmartHomeGW_xxxxxx)
  - la machine ASSOCIEE au SoftAP (pour l'UDP) + cable USB branche (pour l'UART)
  - pyserial installe
  - un backend LLM HORS-LIGNE conseille, car etre sur le SoftAP coupe internet :
      * --backend local : Ollama sur localhost (modele tool-calling, ex qwen2.5:7b-instruct)
      * sinon --backend gemini mais il faut un 2e lien internet (partage USB telephone)

Usage (Windows, pour l'acces COM + Wi-Fi) :
  python.exe run_challenge3.py --uart COM11 --backend local --model qwen2.5:7b-instruct
  python.exe run_challenge3.py --uart COM11 --backend gemini --model gemini-flash-latest
"""
from __future__ import annotations

import argparse

from esc_agent.agent import Agent, new_run_id
from esc_agent.challenges.airwave_template import (
    GOAL, SYSTEM, UdpUartBackend, register_tools)
from esc_agent.metrics import EventLogger, aggregate, format_table
from esc_agent.tools.base import ToolRegistry
from run import build_llm


def main() -> None:
    from esc_agent.envfile import load_env
    load_env()

    ap = argparse.ArgumentParser()
    ap.add_argument("--uart", default="COM11", help="port serie (COM11, /dev/ttyUSB0...)")
    ap.add_argument("--target", default="192.168.4.1", help="IP de la carte sur le SoftAP")
    ap.add_argument("--lo", type=int, default=4210)
    ap.add_argument("--hi", type=int, default=4219)
    ap.add_argument("--backend", default="local", choices=["local", "gemini", "claude", "mock"])
    ap.add_argument("--model", default="qwen2.5:7b-instruct")
    ap.add_argument("--log", default="runs/challenge3.jsonl")
    ap.add_argument("--max-steps", type=int, default=200)
    ap.add_argument("--vertex", action="store_true",
                    help="backend gemini via Vertex AI (aiplatform) au lieu de l'API Developer")
    args = ap.parse_args()

    if args.vertex:
        import os
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    llm = build_llm(args.backend, args.model)
    rid = new_run_id()

    print(f"Challenge 3 — Airwave Template | UART={args.uart} | target={args.target}:"
          f"{args.lo}-{args.hi} | backend={llm.name}/{llm.model}")
    print("The agent discovers everything on its own: UDP telemetry, template oracle (SSTI), "
          "then UART pivot -> flag.\n")

    with EventLogger(args.log) as logger:
        backend = UdpUartBackend(args.uart, target=args.target, lo=args.lo, hi=args.hi)
        reg = ToolRegistry(logger, rid)
        register_tools(reg, backend)
        agent = Agent(llm, reg, logger, rid, max_steps=args.max_steps, verbose=True)
        summary = agent.run(SYSTEM, GOAL, challenge="airwave_template")

    print(f"\n==== Result ====")
    print(f"  solved        : {summary.solved}  ({summary.reason})")
    print(f"  target reqs   : {summary.target_interactions}  {summary.interactions_by_channel}")
    print(f"  LLM calls     : {summary.llm_calls}")
    print(f"  total tokens  : {summary.total_tokens}")
    print(f"  wall time     : {summary.wall_ms/1000:.1f} s")
    print("\n" + format_table(aggregate([summary])))
    print(f"\nDetailed log  : {args.log}")
    print(f"Transcript    : runs/challenge3_transcript.txt")


if __name__ == "__main__":
    main()
