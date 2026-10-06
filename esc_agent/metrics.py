"""Couche metriques: journal d'evenements JSONL + agregation.

Tout ce que le reglement ESC note cote efficacite/performance passe par ici:
- requetes reelles vers la cible (par canal: UART, BLE, RFID, EEPROM, HTTP)
- appels LLM, tokens (input/output/cache/thinking), latences
- succes + raison, par run
- agregation N-runs: moyenne, ecart-type, CV (repetabilite), taux de succes
"""
from __future__ import annotations

import json
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


# --- Journal d'evenements -----------------------------------------------------

class EventLogger:
    """Ecrit une ligne JSON par evenement. Un fichier = une campagne de runs."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")

    def emit(self, event_type: str, **fields: Any) -> None:
        rec = {"ts": time.time(), "type": event_type, **fields}
        self._fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "EventLogger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# --- Chronometre d'intervalle -------------------------------------------------

class Timer:
    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.ms = (time.perf_counter() - self._t0) * 1000.0


# --- Resume d'un run ----------------------------------------------------------

@dataclass
class RunSummary:
    run_id: str
    challenge: str
    model: str
    solved: bool
    reason: str = ""
    llm_calls: int = 0
    tool_calls: int = 0
    target_interactions: int = 0           # total requetes reelles vers la cible
    interactions_by_channel: dict[str, int] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    thinking_tokens: int = 0
    total_tokens: int = 0
    wall_ms: float = 0.0
    llm_ms: float = 0.0                     # temps passe dans les appels LLM
    tool_ms: float = 0.0                    # temps passe dans les outils

    def cache_hit_rate(self) -> float:
        denom = self.input_tokens + self.cached_tokens
        return (self.cached_tokens / denom) if denom else 0.0


# --- Agregation N-runs --------------------------------------------------------

def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "cv": 0.0}
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    cv = (std / mean) if mean else 0.0   # coefficient de variation = score de repetabilite
    return {"n": len(values), "mean": mean, "std": std,
            "min": min(values), "max": max(values), "cv": cv}


def aggregate(summaries: Iterable[RunSummary]) -> dict[str, Any]:
    """Statistiques transverses: moyenne/ecart-type/CV + taux de succes."""
    s = list(summaries)
    if not s:
        return {}
    n = len(s)
    solved = [x for x in s if x.solved]
    # Convention utile: on mesure requetes/tokens/temps sur les runs REUSSIS,
    # sinon un echec rapide gonflerait artificiellement l'"efficacite".
    base = solved or s
    chan_tot: Counter[str] = Counter()
    for x in s:
        chan_tot.update(x.interactions_by_channel)
    return {
        "runs": n,
        "success_rate": len(solved) / n,
        "target_interactions": _stats([x.target_interactions for x in base]),
        "llm_calls": _stats([x.llm_calls for x in base]),
        "total_tokens": _stats([x.total_tokens for x in base]),
        "wall_ms": _stats([x.wall_ms for x in base]),
        "cache_hit_rate": _stats([x.cache_hit_rate() for x in base]),
        "interactions_by_channel_total": dict(chan_tot),
        "measured_on": "solved_runs" if solved else "all_runs",
    }


# --- Rejouer un JSONL vers des RunSummary (analyse a posteriori) ---------------

def summaries_from_log(path: str | Path) -> list[RunSummary]:
    """Reconstruit les resumes depuis un journal d'evenements."""
    runs: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "llm_calls": 0, "tool_calls": 0, "target_interactions": 0,
        "interactions_by_channel": Counter(),
        "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0,
        "thinking_tokens": 0, "total_tokens": 0,
        "llm_ms": 0.0, "tool_ms": 0.0,
        "challenge": "", "model": "", "solved": False, "reason": "",
        "wall_ms": 0.0,
    })
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        rid = e.get("run_id")
        if rid is None:
            continue
        r = runs[rid]
        t = e["type"]
        if t == "run_start":
            r["challenge"] = e.get("challenge", "")
            r["model"] = e.get("model", "")
        elif t == "llm_call":
            r["llm_calls"] += 1
            r["input_tokens"] += e.get("input_tokens", 0)
            r["output_tokens"] += e.get("output_tokens", 0)
            r["cached_tokens"] += e.get("cached_tokens", 0)
            r["thinking_tokens"] += e.get("thinking_tokens", 0)
            r["total_tokens"] += e.get("total_tokens", 0)
            r["llm_ms"] += e.get("latency_ms", 0.0)
        elif t == "target_interaction":
            r["target_interactions"] += 1
            r["interactions_by_channel"][e.get("channel", "unknown")] += 1
            r["tool_ms"] += e.get("latency_ms", 0.0)
        elif t == "tool_call":
            r["tool_calls"] += 1
        elif t == "run_end":
            r["solved"] = e.get("solved", False)
            r["reason"] = e.get("reason", "")
            r["wall_ms"] = e.get("wall_ms", 0.0)
    out = []
    for rid, r in runs.items():
        out.append(RunSummary(
            run_id=rid,
            challenge=r["challenge"], model=r["model"],
            solved=r["solved"], reason=r["reason"],
            llm_calls=r["llm_calls"], tool_calls=r["tool_calls"],
            target_interactions=r["target_interactions"],
            interactions_by_channel=dict(r["interactions_by_channel"]),
            input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
            cached_tokens=r["cached_tokens"], thinking_tokens=r["thinking_tokens"],
            total_tokens=r["total_tokens"],
            wall_ms=r["wall_ms"], llm_ms=r["llm_ms"], tool_ms=r["tool_ms"],
        ))
    return out


def format_table(agg: dict[str, Any]) -> str:
    """Rend l'agregat en tableau texte lisible (pour le terminal / le rapport)."""
    if not agg:
        return "(aucun run)"
    lines = []
    lines.append(f"runs={agg['runs']}  succes={agg['success_rate']*100:.0f}%  "
                 f"(mesure sur: {agg['measured_on']})")
    def row(label: str, key: str, unit: str = "") -> str:
        d = agg[key]
        return (f"  {label:<22} moy={d['mean']:.1f}{unit}  "
                f"ec-type={d['std']:.1f}  CV={d['cv']*100:.0f}%  "
                f"[{d['min']:.0f}-{d['max']:.0f}]")
    lines.append(row("requetes cible", "target_interactions"))
    lines.append(row("appels LLM", "llm_calls"))
    lines.append(row("tokens totaux", "total_tokens"))
    lines.append(row("temps mur (ms)", "wall_ms", " ms"))
    ch = agg.get("interactions_by_channel_total", {})
    if ch:
        lines.append("  requetes par canal:    " +
                     ", ".join(f"{k}={v}" for k, v in sorted(ch.items())))
    return "\n".join(lines)
