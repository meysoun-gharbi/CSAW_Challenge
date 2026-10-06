#!/usr/bin/env python3
"""Runner de benchmark: N runs -> statistiques de repetabilite.

Produit le tableau que les juges veulent voir: moyenne, ecart-type, CV
(repetabilite), taux de succes, requetes par canal. Ecrit aussi un CSV par run.

Usage:
  python bench.py -n 10
  python bench.py -n 10 --backend gemini --model gemini-3-pro
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from esc_agent.agent import Agent, new_run_id
from esc_agent.challenges.mock_challenge import GOAL, MockBackend
from esc_agent.metrics import EventLogger, aggregate, format_table
from esc_agent.tools.base import ToolRegistry
from esc_agent.tools.device import register_device_tools
from run import SYSTEM, build_llm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=10)
    ap.add_argument("--backend", default="mock", choices=["mock", "gemini", "claude"])
    ap.add_argument("--model", default="gemini-3-pro")
    ap.add_argument("--log", default="runs/bench.jsonl")
    ap.add_argument("--csv", default="runs/bench_summary.csv")
    ap.add_argument("--max-steps", type=int, default=12)
    args = ap.parse_args()

    summaries = []
    with EventLogger(args.log) as logger:
        for i in range(args.runs):
            llm = build_llm(args.backend, args.model)  # instance fraiche par run
            rid = new_run_id()
            backend = MockBackend()
            reg = ToolRegistry(logger, rid)
            register_device_tools(reg, backend)
            agent = Agent(llm, reg, logger, rid, max_steps=args.max_steps)
            s = agent.run(SYSTEM, GOAL, challenge="mock_uart_unlock")
            summaries.append(s)
            print(f"  run {i+1:>3}/{args.runs}  {rid}  "
                  f"solved={s.solved}  req={s.target_interactions}  "
                  f"llm={s.llm_calls}  tok={s.total_tokens}  {s.wall_ms:.0f}ms")

    # CSV par run (pour tracer des courbes / mettre dans le rapport)
    Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["run_id", "solved", "reason", "target_interactions",
                    "llm_calls", "total_tokens", "wall_ms"])
        for s in summaries:
            w.writerow([s.run_id, s.solved, s.reason, s.target_interactions,
                        s.llm_calls, s.total_tokens, f"{s.wall_ms:.1f}"])

    print(f"\n== Agregat ({args.backend}/{args.model}) ==")
    print(format_table(aggregate(summaries)))
    print(f"\nCSV: {args.csv}   journal: {args.log}")


if __name__ == "__main__":
    main()
