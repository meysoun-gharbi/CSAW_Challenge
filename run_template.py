#!/usr/bin/env python3
"""GABARIT d'entree CLI pour un nouveau challenge.

Copie ce fichier en `run_challengeN.py` (N = numero du challenge), et:
  1. Copie `esc_agent/challenges/_template.py` en
     `esc_agent/challenges/<nom_du_challenge>.py`, remplis ses TODO.
  2. Change l'import ci-dessous pour pointer vers ce nouveau module.
  3. Adapte l'argument --port si ton challenge n'utilise pas un port serie
     (ex: --host pour HTTP, --device-name pour BLE...) -- garde le MEME nom
     `backend = RealBackend(...)` cote challenge pour que le reste de ce
     fichier n'ait rien d'autre a changer.

NE TOUCHE PAS a `run.py` (build_llm): c'est la fabrique de backends LLM
COMMUNE a tous les challenges (gemini/claude/deepseek/ollama/hybrid/
cloud_fallback) -- toute amelioration faite la (ex: un nouveau fallback)
profite automatiquement a TOUS les run_challengeN.py existants.

Usage (une fois adapte):
  python run_challengeN.py --port /dev/ttyUSB0 --backend gemini --model gemini-flash-latest
  python run_challengeN.py --port /dev/ttyUSB0 --backend cloud_fallback \\
      --model gemini-flash-latest --fallback-backend deepseek --fallback-model deepseek-chat
"""
from __future__ import annotations

import argparse

from esc_agent.agent import Agent, new_run_id
# TODO: change cet import pour ton module de challenge (copie/adapte de _template.py)
from esc_agent.challenges._template import GOAL, SYSTEM, RealBackend, register_tools
from esc_agent.llm.base import LLMClient
from esc_agent.metrics import EventLogger, aggregate, format_table
from esc_agent.tools.base import ToolRegistry
from run import build_llm


class _LazyCloud(LLMClient):
    """Construit le vrai client cloud seulement au premier appel reel.

    Utile UNIQUEMENT si ton challenge a, comme le challenge 1, un outil
    'strategiste' (planner) separe du backend principal de l'agent (ex: un
    oracle a deviner caractere par caractere / mot par mot). Si ton
    challenge n'a pas ce besoin, tu peux ignorer cette classe et
    build_planner ci-dessous, et simplement appeler
    register_tools(reg, backend) sans le parametre planner."""
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
    """Le 'planner' (strategiste), toujours un backend cloud, independamment
    du backend principal choisi pour l'agent. A SUPPRIMER si ton challenge
    n'a pas d'outil de type oracle_dictionary_search."""
    if args.backend in ("gemini", "claude", "deepseek", "cloud_fallback"):
        return llm
    if args.fallback_backend and args.fallback_model:
        return _LazyCloud(lambda: build_llm(args.fallback_backend, args.fallback_model))
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    # TODO: adapte si ton interface n'est pas un port serie (ex: --host
    # 192.168.4.1 pour HTTP, --device-name pour BLE...).
    ap.add_argument("--port", default="COM4",
                     help="port serie (COM4, /dev/ttyUSB0, rfc2217://host:2217...)")
    ap.add_argument("--backend", default="gemini",
                     choices=["gemini", "mock", "claude", "deepseek", "ollama",
                              "hybrid", "cloud_fallback"])
    ap.add_argument("--model", default="gemini-flash-latest")
    ap.add_argument("--fallback-backend", default=None,
                     choices=["gemini", "claude", "deepseek"],
                     help="(mode hybrid: cloud de secours ; mode cloud_fallback: "
                          "secours quand le backend principal est a sec)")
    ap.add_argument("--fallback-model", default=None,
                     help="(hybrid/cloud_fallback) modele de secours "
                          "(ex: gemini-flash-latest, deepseek-chat)")
    ap.add_argument("--local-timeout", type=float, default=20.0,
                     help="(mode hybrid) secondes max avant d'abandonner le local et escalader")
    # TODO: renomme le fichier de log par defaut (un par challenge).
    ap.add_argument("--log", default="runs/challengeN.jsonl")
    ap.add_argument("--max-steps", type=int, default=400)
    args = ap.parse_args()

    llm = build_llm(args.backend, args.model, args.fallback_backend, args.fallback_model,
                     args.local_timeout)
    rid = new_run_id()
    # TODO: adapte le nom affiche.
    print(f"Challenge N — TODO_NOM | port={args.port} | modele={llm.model}")
    print("L'agent decouvre tout seul: reconnaissance, interaction, puis le flag.\n")

    planner = build_planner(llm, args)
    if planner is None:
        print("(outil 'planner' desactive: pas de backend cloud configure -- "
              "utilise --fallback-backend/--fallback-model, ou --backend gemini/claude. "
              "Ignore ce message si ton challenge n'a pas d'outil planner.)\n")

    with EventLogger(args.log) as logger:
        backend = RealBackend(args.port)  # TODO: adapte les arguments de connexion
        reg = ToolRegistry(logger, rid)
        register_tools(reg, backend, planner=planner)  # retire ', planner=planner' si inutile
        agent = Agent(llm, reg, logger, rid, max_steps=args.max_steps, verbose=True)
        goal = GOAL
        if getattr(backend, "boot_banner", ""):
            goal = (GOAL + "\n\n--- Etat initial de la cible (a interpreter) ---\n"
                    + backend.boot_banner.strip())
        # TODO: adapte le nom du challenge (utilise pour les metriques/rapports).
        summary = agent.run(SYSTEM, goal, challenge="todo_nom_du_challenge")

    print(f"\n==== Resultat ====")
    print(f"  resolu        : {summary.solved}  ({summary.reason})")
    print(f"  requetes cible: {summary.target_interactions}")
    print(f"  appels LLM    : {summary.llm_calls}")
    print(f"  tokens totaux : {summary.total_tokens}")
    print(f"  temps mur     : {summary.wall_ms/1000:.1f} s")
    print("\n" + format_table(aggregate([summary])))
    if hasattr(llm, "local_steps"):  # mode hybrid/cloud_fallback: repartition
        print(f"  repartition   : primaire={llm.local_steps}  secours={llm.cloud_steps}")
    print(f"\nJournal detaille: {args.log}")


if __name__ == "__main__":
    main()
