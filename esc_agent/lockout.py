"""Automated brute-forcer for Challenge 5 — Minions Lockout.

Setup (from the official brief): a password gate picks a secret from the
official `minions_wordlist.txt` (157 first names). Wrong guesses eventually
trip an "intruder detected" lockout; a reboot is required and the secret is
then re-picked. Since the secret is re-picked on every lockout, there is no
point remembering which names failed *within* a lockout cycle across cycles
-- we simply walk the wordlist in order, and every lockout just costs a free
reboot + resume from the next untried name. This guarantees the whole list
is tried exactly once across all cycles with zero wasted guesses.

We don't know in advance:
  - the exact command/line that puts the console into "enter password" mode
  - the exact wording of the lockout message
  - how many guesses are allowed per cycle before lockout trips
...so all three are discovered empirically at runtime (see LOCKOUT_HINTS,
and `enter_cmd` is supplied by the caller after an oracle search identifies
the right prefix, e.g. 'unlock' or 'door').
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from .serial import SerialBackend, FLAG_RE

WORDLIST_PATH = os.path.join(os.path.dirname(__file__), "data", "minions_wordlist.txt")

# Vocabulary observed in similar "alarm/intruder" CTF consoles. Checked
# case-insensitively against every response. Extend this list the moment a
# real run shows a lockout message that isn't caught by it.
LOCKOUT_HINTS = ("lockout", "intruder", "locked out", "alarm", "too many",
                 "blocked", "banned", "detected")
GRANTED_HINTS = ("granted", "welcome", "unlocked", "access granted",
                 "correct", "success")


def load_wordlist(path: str = WORDLIST_PATH) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


@dataclass
class Attempt:
    name: str
    response: str
    outcome: str  # "granted" | "lockout" | "no_match"


class MinionsBruteForcer:
    def __init__(self, backend: SerialBackend, enter_cmd: str | None = None,
                 verbose: bool = True):
        self.backend = backend
        self.enter_cmd = enter_cmd
        self.verbose = verbose
        self.attempts: list[Attempt] = []
        self.calls = 0
        self.flag: str | None = None
        self.granted_name: str | None = None

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"  [lockout] {msg}", flush=True)

    def _classify(self, resp: str) -> str:
        lower = resp.lower()
        m = FLAG_RE.search(resp)
        if m:
            return "granted"
        if any(h in lower for h in GRANTED_HINTS):
            return "granted"
        if any(h in lower for h in LOCKOUT_HINTS):
            return "lockout"
        return "no_match"

    def run(self, wordlist: list[str] | None = None, max_calls: int = 400) -> Attempt | None:
        """Try names in order. Reboots (free) on lockout and resumes with the
        next untried name. Returns the winning Attempt, or None if the whole
        list is exhausted without success."""
        names = list(wordlist or load_wordlist())
        self._log(f"starting brute force over {len(names)} names "
                   f"(enter_cmd={self.enter_cmd!r})")

        i = 0
        while i < len(names) and self.calls < max_calls:
            name = names[i]

            if self.enter_cmd:
                # Re-issue the command that opens the password prompt; if the
                # device is already mid-prompt this is harmless (worst case
                # it's treated as a wrong guess, which the loop handles).
                self.backend.send(self.enter_cmd)
                self.calls += 1

            resp = self.backend.send(name)
            self.calls += 1
            kind = self._classify(resp)
            self.attempts.append(Attempt(name, resp, kind))
            self._log(f"{name!r} -> {kind} | {resp[:200]!r}")

            if kind == "granted":
                self.granted_name = name
                m = FLAG_RE.search(resp)
                if m:
                    self.flag = m.group(0)
                return self.attempts[-1]

            if kind == "lockout":
                self._log("lockout tripped — rebooting (free) and resuming")
                self.backend.reboot()
                time.sleep(0.2)
                # don't advance i: this name's result is inconclusive if the
                # lockout fired on this exact guess before a verdict; try the
                # SAME name once more right after reboot, then move on.
                # Simpler and safer: just move to the next name — the secret
                # is re-picked on every lockout anyway, so re-trying this one
                # buys nothing.
                i += 1
                continue

            i += 1

        self._log(f"exhausted {i} names, {self.calls} UART calls, no match")
        return None
