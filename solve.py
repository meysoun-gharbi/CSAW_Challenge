#!/usr/bin/env python3
"""Solve a CSAW ESC 2026 challenge using LLM + ESP32 serial.

Two-phase approach:
  Phase 1: Automated prefix oracle search (pure code, no LLM)
  Phase 2: LLM agent interprets results and follows instructions to get the flag

Usage:
  python3 solve.py --challenge 1 --port /dev/ttyUSB0
  python3 solve.py --challenge 1 --port /dev/ttyUSB0 --backend gemini
  python3 solve.py --challenge 2 --port /dev/ttyUSB0
"""
from __future__ import annotations

import argparse

from esc_agent.llm import build_client
from esc_agent.serial import SerialBackend
from esc_agent.agent import Agent
from esc_agent.oracle import OracleExplorer


def main():
    ap = argparse.ArgumentParser(description="CSAW ESC 2026 solver")
    ap.add_argument("--challenge", type=int, default=1, choices=[1, 2, 5])
    ap.add_argument("--port", required=True, help="serial port")
    ap.add_argument("--backend", default="gemini", choices=["ollama", "gemini"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--max-steps", type=int, default=200)
    ap.add_argument("--skip-oracle", action="store_true",
                    help="skip automated oracle search, go straight to LLM")
    args = ap.parse_args()

    if args.challenge == 1:
        from esc_agent.challenge1 import SYSTEM, GOAL, build_tools
    elif args.challenge == 2:
        from esc_agent.challenge2 import SYSTEM, GOAL, build_tools
    else:
        from esc_agent.challenge5 import SYSTEM, GOAL, build_tools

    llm = build_client(args.backend, args.model)
    print(f"=== CSAW ESC 2026 — Challenge {args.challenge} ===")
    print(f"Port: {args.port} | Backend: {args.backend} | Model: {llm.model}\n")

    backend = SerialBackend(args.port)
    boot = backend.boot_banner or ""
    print(f"[boot] {boot[:300]}\n")

    # --- Phase 1: automated oracle search ---
    oracle_summary = ""
    oracle_calls = 0
    if not args.skip_oracle:
        explorer = OracleExplorer(backend, max_calls=200)
        commands = explorer.run()
        oracle_calls = explorer.calls

        if commands:
            lines = []
            for cmd in commands:
                lines.append(f"Command: {cmd.command!r}\nOutput: {cmd.output}\n")
            oracle_summary = (
                f"AUTOMATED ORACLE SEARCH found {len(commands)} command(s) "
                f"in {oracle_calls} UART calls:\n\n" + "\n".join(lines)
            )
            print(f"\n[phase1] Found {len(commands)} commands in {oracle_calls} calls")
        else:
            oracle_summary = (
                f"Automated oracle search used {oracle_calls} UART calls but found no commands. "
                "Valid prefixes found: 'help', 'mode'. You need to extend them further."
            )
            print(f"\n[phase1] No commands found in {oracle_calls} calls")

        # Reboot to reset rate limits before LLM phase
        backend.reboot()

    # --- Phase 1.5: automatic auth solver ---
    auth_result = ""
    if args.challenge == 1 and not args.skip_oracle:
        import re

        # Extract MAC suffix from oracle results (the 'mac' command)
        mac_suffix = None
        for cmd in explorer.commands:
            if cmd.command.strip() == "mac":
                m = re.search(r"[0-9A-Fa-f]{6}", cmd.output)
                if m:
                    mac_suffix = m.group(0)
                    print(f"[auth] MAC suffix from oracle: {mac_suffix}")

        if mac_suffix:
            # Step 1: find the auth command from oracle results
            auth_triggered = False
            resp1 = ""
            for cmd in explorer.commands:
                if cmd.command.strip() != "mac" and (
                    "auth" in cmd.output.lower() or "enter" in cmd.output.lower()
                    or "suffix" in cmd.output.lower() or "verification" in cmd.output.lower()
                ):
                    print(f"[auth] Re-sending auth command: {cmd.command!r}", flush=True)
                    resp1 = backend.send(cmd.command)
                    oracle_calls += 1
                    print(f"[auth] -> {resp1[:300]}")
                    auth_triggered = True
                    break

            if not auth_triggered:
                print("[auth] No auth command found by oracle — LLM will handle it")

            if auth_triggered:
                # Step 2: send the MAC suffix as a separate line
                print(f"[auth] Sending MAC suffix: {mac_suffix}", flush=True)
                resp2 = backend.send(mac_suffix)
                oracle_calls += 1
                print(f"[auth] -> {resp2[:500]}")

                # Check if flag is already in the auth response
                fm = re.search(r"(?:esc_2026|ESC)\{[^}]*\}", resp2)
                if fm:
                    print(f"\n{'='*50}")
                    print(f"FLAG FOUND: {fm.group(0)}")
                    print(f"UART calls: {oracle_calls}")
                    return

                # Step 3: device is now in interactive mode (log commands).
                # DON'T reboot — that would lose the auth session.
                # Try listed commands while still in interactive mode.
                log_outputs = []
                if "log" in resp2.lower():
                    # Try bare 'log' first (listed last, could be special)
                    print("[auth] Trying 'log' (bare)...", flush=True)
                    resp_log = backend.send("log")
                    oracle_calls += 1
                    print(f"[auth] log -> {resp_log[:500]}")
                    log_outputs.append(("log", resp_log))

                    fm = re.search(r"(?:esc_2026|ESC)\{[^}]*\}", resp_log)
                    if fm:
                        print(f"\n{'='*50}")
                        print(f"FLAG FOUND: {fm.group(0)}")
                        print(f"UART calls: {oracle_calls}")
                        return

                auth_result = (
                    f"Auth: {resp1.strip()}\n"
                    f"MAC suffix: {mac_suffix}\n"
                    f"Auth result: {resp2}\n"
                )
                for log_cmd, log_out in log_outputs:
                    auth_result += f"\n'{log_cmd}' output: {log_out}\n"

            else:
                print("[auth] No auth prompt found — LLM will handle it")
                backend.reboot()

    # --- Phase 2: LLM agent ---
    print(f"\n[phase2] LLM agent starting ({llm.model})...\n")
    tools = build_tools(backend)

    goal = GOAL
    if boot:
        goal += f"\n\n--- Boot output ---\n{boot}"
    if auth_result:
        goal += f"\n\n--- Auth result ---\n{auth_result}"
    if oracle_summary:
        goal += f"\n\n--- Oracle search results ---\n{oracle_summary}"

    agent = Agent(llm, tools, SYSTEM, goal, max_steps=args.max_steps)
    result = agent.run()

    total_uart = oracle_calls + result["uart_calls"]
    print(f"\n{'='*50}")
    print(f"Solved:         {result['solved']}")
    if result['flag']:
        print(f"Flag:           {result['flag']}")
    print(f"UART calls:     {total_uart} (oracle: {oracle_calls}, agent: {result['uart_calls']})")
    print(f"LLM calls:      {result['llm_calls']}")
    print(f"Wall time:      {result['wall_s']:.1f}s")


if __name__ == "__main__":
    main()
