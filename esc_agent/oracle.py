"""Automated prefix oracle explorer.

Discovers commands by DFS through the prefix oracle with two optimizations:
  1. Word completion: when a partial word is found (e.g. 'dev'), try common
     English CLI words that start with it ('developer', 'device') before
     going character-by-character. This is generic English, not challenge answers.
  2. After a space, try '-' first for --options (standard CLI convention).

All attempts are printed for visibility.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .serial import SerialBackend

ORACLE_PREFIX = "one or more commands start with"
ORACLE_DEAD = "no command starts with"

LETTERS_FREQ = "hlsmcrditevabuwngoqkfpjxyz"
AFTER_SPACE = "-" + LETTERS_FREQ + " !@_"
NORMAL = LETTERS_FREQ + " -!@_"

# Common English words found in CLI/system contexts. NOT command names —
# just words. Used to complete partial words (e.g. 'dev' -> 'developer').
WORD_LIST = [
    "access", "account", "action", "activate", "add", "address", "admin",
    "advanced", "alarm", "alert", "all", "allow", "analyze", "apply", "auth",
    "authenticate", "auto", "backup", "ban", "block", "boot", "bridge",
    "broadcast", "buffer", "bypass", "cache", "capture", "cert", "change",
    "channel", "check", "clean", "clear", "client", "clock", "close", "cmd",
    "code", "command", "config", "configure", "connect", "console", "control",
    "copy", "count", "create", "critical", "daemon", "data", "database",
    "debug", "default", "delete", "deny", "deploy", "describe", "detail",
    "detect", "developer", "device", "dhcp", "diag", "diagnostics", "direct",
    "disable", "disconnect", "discover", "display", "dns", "domain", "down",
    "download", "driver", "dump", "edit", "eeprom", "enable", "encrypt",
    "endpoint", "engine", "enter", "error", "event", "exec", "execute",
    "exit", "expert", "export", "extend", "external", "factory", "file",
    "filter", "find", "firewall", "firmware", "flag", "flash", "flush",
    "force", "format", "forward", "full", "function", "gateway", "generate",
    "get", "global", "grant", "group", "guest", "halt", "handler", "hardware",
    "hash", "health", "help", "hidden", "hint", "history", "home", "host",
    "http", "id", "identify", "import", "info", "init", "initialize",
    "inject", "input", "inspect", "install", "interface", "internal", "ip",
    "join", "keep", "kernel", "key", "kill", "label", "launch", "level",
    "license", "link", "list", "listen", "load", "local", "lock", "log",
    "login", "logout", "lookup", "mac", "main", "maintenance", "manage",
    "manual", "map", "mask", "master", "match", "memory", "menu", "message",
    "mode", "model", "modify", "module", "monitor", "mount", "move", "name",
    "network", "node", "normal", "note", "notify", "off", "on", "open",
    "operate", "option", "order", "output", "override", "owner", "package",
    "pair", "panic", "parameter", "parse", "partition", "pass", "password",
    "path", "pause", "peer", "permit", "pin", "ping", "pipe", "policy",
    "port", "power", "print", "priority", "private", "probe", "process",
    "profile", "program", "project", "prompt", "protect", "protocol",
    "provision", "proxy", "public", "pull", "push", "query", "queue",
    "raw", "read", "reboot", "receive", "recover", "redirect", "refresh",
    "register", "reject", "release", "reload", "remote", "remove", "rename",
    "repair", "replace", "report", "request", "reset", "resolve", "restart",
    "restore", "restrict", "result", "resume", "retry", "return", "reveal",
    "reverse", "revoke", "rfid", "role", "root", "route", "rule", "run",
    "safe", "save", "scan", "schedule", "script", "search", "secret",
    "secure", "security", "select", "self", "send", "serial", "server",
    "service", "session", "set", "setup", "shell", "show", "shutdown",
    "signal", "slave", "sleep", "smart", "snapshot", "snmp", "socket",
    "software", "source", "special", "ssh", "ssl", "start", "state",
    "static", "status", "step", "stop", "store", "stream", "subnet",
    "subscribe", "summary", "super", "support", "suspend", "switch",
    "sync", "system", "table", "tag", "target", "task", "tcp", "telnet",
    "temp", "terminal", "test", "time", "timeout", "tls", "token", "tool",
    "top", "trace", "track", "traffic", "transfer", "trigger", "trunk",
    "trust", "tunnel", "type", "udp", "undo", "unlock", "unset", "up",
    "update", "upgrade", "upload", "uptime", "user", "validate", "value",
    "verbose", "verify", "version", "view", "virtual", "vlan", "volume",
    "wait", "watch", "web", "whitelist", "wifi", "wipe", "wireless",
    "worker", "write", "zone",
]


@dataclass
class Command:
    command: str
    output: str


class OracleExplorer:
    def __init__(self, backend: SerialBackend, max_calls: int = 500, verbose: bool = True):
        self.backend = backend
        self.max_calls = max_calls
        self.verbose = verbose
        self.calls = 0
        self.dead_streak = 0
        self.commands: list[Command] = []

    def _send(self, cmd: str) -> str:
        if self.calls >= self.max_calls:
            raise StopIteration("max calls")
        resp = self.backend.send(cmd)
        self.calls += 1
        return resp

    def _classify(self, cmd: str, resp: str) -> str:
        lower = resp.lower()
        if ORACLE_DEAD in lower:
            return "dead"
        if ORACLE_PREFIX in lower:
            # Check if there's EXTRA content beyond the oracle message.
            # e.g. "one or more commands start with help\nThis help menu..."
            # That means the command executed AND is a prefix.
            lines = resp.strip().split("\n")
            oracle_line = None
            extra_lines = []
            for line in lines:
                if ORACLE_PREFIX in line.lower():
                    oracle_line = line
                else:
                    stripped = line.strip()
                    if stripped and "[rate-limit]" not in stripped.lower():
                        extra_lines.append(stripped)
            if extra_lines:
                return "command_and_prefix"
            return "prefix"
        return "command"

    def _maybe_reboot(self):
        if self.dead_streak >= 8:
            if self.verbose:
                print(f"  [oracle] reboot (clearing rate limit)", flush=True)
            self.backend.reboot()
            self.dead_streak = 0

    def _log(self, msg: str):
        if self.verbose:
            print(f"  [oracle] {msg}", flush=True)

    def _try(self, cmd: str) -> str | None:
        """Send cmd. Returns 'prefix', 'command', 'command_and_prefix', or None (dead)."""
        try:
            resp = self._send(cmd)
        except StopIteration:
            return None

        kind = self._classify(cmd, resp)

        if kind == "dead":
            self._log(f"  dead: {cmd!r}")
            self.dead_streak += 1
            self._maybe_reboot()
            return None

        self.dead_streak = 0

        if kind in ("command", "command_and_prefix"):
            self._log(f"FOUND: {cmd!r} -> {resp[:200]}")
            self.commands.append(Command(cmd, resp))
            # If the device entered an interactive state (prompt waiting for
            # input), reboot to avoid the next probe being eaten as input.
            lower = resp.lower()
            if "enter" in lower or "required" in lower or lower.rstrip().endswith(":"):
                self._log("  (interactive prompt detected — rebooting)")
                self.backend.reboot()
            return kind

        self._log(f"prefix: {cmd!r}")
        return "prefix"

    def _last_partial_word(self, prefix: str) -> str:
        """Extract the last partial word from a prefix. e.g. 'mode dev' -> 'dev'."""
        parts = prefix.split(" ")
        return parts[-1] if parts else ""

    def _word_completions(self, prefix: str) -> list[str]:
        """Find words from WORD_LIST that could complete the last partial word."""
        partial = self._last_partial_word(prefix)
        if len(partial) < 1:
            return []
        base = prefix[: len(prefix) - len(partial)]
        return [base + w for w in WORD_LIST if w.startswith(partial) and w != partial]

    def _explore(self, prefix: str, depth: int = 0) -> bool:
        """DFS from prefix. Returns True if any command was found."""
        if depth > 40 or self.calls >= self.max_calls:
            return False

        found_any = False
        word_hit = False

        # Try word completions first — try ALL of them, don't stop at first hit.
        # This finds multiple commands under the same prefix (e.g. 'mac' + 'mode' under 'm').
        completions = self._word_completions(prefix)
        for candidate in completions:
            if self.calls >= self.max_calls:
                break
            result = self._try(candidate)
            if result in ("command", "command_and_prefix"):
                found_any = True
                word_hit = True
            elif result == "prefix":
                word_hit = True
                if self._explore(candidate, depth + 1):
                    found_any = True

        # Char-by-char only if word completions didn't match anything.
        # If words hit, deeper exploration already happened via recursion.
        if not word_hit:
            chars = AFTER_SPACE if prefix.endswith(" ") else NORMAL
            for ch in chars:
                if self.calls >= self.max_calls:
                    break
                candidate = prefix + ch
                result = self._try(candidate)
                if result in ("command", "command_and_prefix"):
                    return True
                if result == "prefix":
                    if self._explore(candidate, depth + 1):
                        return True

        return found_any

    def _was_tested(self, candidate: str) -> bool:
        """Check if this exact candidate was already sent."""
        # Simple heuristic: if we tried a completion that starts with this, skip
        return False  # don't skip — let DFS handle dedup naturally

    def run(self) -> list[Command]:
        print("[oracle] Starting automated prefix search...", flush=True)
        t0 = time.time()

        # Explore ALL valid prefix letters (don't stop early)
        for ch in LETTERS_FREQ:
            if self.calls >= self.max_calls:
                break
            result = self._try(ch)
            if result in ("command", "command_and_prefix"):
                continue
            if result == "prefix":
                self._explore(ch)

        elapsed = time.time() - t0
        print(f"\n[oracle] Done: {len(self.commands)} command(s) found, "
              f"{self.calls} UART calls, {elapsed:.1f}s\n", flush=True)
        for cmd in self.commands:
            print(f"  {cmd.command!r}:", flush=True)
            print(f"    {cmd.output[:500]}\n", flush=True)
        return self.commands
