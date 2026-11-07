"""Windows services (start/stop/restart via sc.exe) and a richer "what's using my
CPU/RAM" breakdown than the dashboard's live gauges give.

Starting, stopping or restarting a service is confirm-gated by the caller
(handlers/service.py) — a service often backs something else the user is running,
so it's the same risk class as closing an app.
"""
from __future__ import annotations

import re
import subprocess
from typing import List

from core.logging_setup import get_logger
from skills.network_manager import console_encoding

log = get_logger("jarvis.service")

try:
    import psutil
except Exception:  # pragma: no cover - always present in this project, but be defensive
    psutil = None

_TIMEOUT = 20


def _run(args: List[str], timeout: int = _TIMEOUT) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          encoding=console_encoding(), errors="replace", check=False)


def _bad_service_name(name: str) -> bool:
    """Empty, or something sc.exe would read as a switch/remote machine ('/?', '\\\\host')."""
    name = (name or "").strip()
    return not name or name.startswith(("-", "/", "\\")) or "=" in name


class ServiceManager:
    """Windows service control (sc.exe) and top-process breakdowns (psutil)."""

    # ── services ─────────────────────────────────────────────────────────────

    def list_services(self, query: str = "", running_only: bool = False) -> str:
        args = ["sc", "query", "state=" + ("running" if running_only else "all"), "type=service"]
        try:
            proc = _run(args, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't list services: {exc}"
        entries = re.findall(r"SERVICE_NAME:\s*(.+?)\s*\r?\nDISPLAY_NAME:\s*(.+?)\s*\r?\n", proc.stdout)
        if query:
            q = query.lower()
            entries = [(n, d) for n, d in entries if q in n.lower() or q in d.lower()]
        if not entries:
            return "No matching services."
        return "\n".join(f"• {display} ({name})" for name, display in entries[:40])

    def service_status(self, name: str) -> str:
        if _bad_service_name(name):
            return "Which service? Give its name, e.g. 'Spooler'."
        name = name.strip()
        try:
            proc = _run(["sc", "query", name])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't check '{name}': {exc}"
        if "1060" in proc.stdout or "does not exist" in proc.stdout.lower():
            return f"No service named '{name}'."
        m = re.search(r"STATE\s*:\s*\d+\s*(\w+)", proc.stdout)
        return f"'{name}' is {m.group(1).lower()}." if m else f"Couldn't read the status of '{name}'."

    def start_service(self, name: str) -> str:
        return self._control(name, "start", "Started")

    def stop_service(self, name: str) -> str:
        return self._control(name, "stop", "Stopped")

    def restart_service(self, name: str) -> str:
        stop = self._control(name, "stop", "Stopped")
        if "denied" in stop.lower() or "couldn't" in stop.lower():
            return stop
        start = self._control(name, "start", "Started")
        return f"{stop} {start}"

    def _control(self, name: str, verb: str, ok_word: str) -> str:
        if _bad_service_name(name):
            return "Which service? Give its name, e.g. 'Spooler'."
        name = name.strip()
        try:
            proc = _run(["sc", verb, name])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't {verb} '{name}': {exc}"
        combined = proc.stdout + proc.stderr
        if proc.returncode == 0:
            return f"{ok_word} '{name}'."
        if "1060" in combined:
            return f"No service named '{name}'."
        if "access is denied" in combined.lower() or re.search(r"\bFAILED\s+5\b", combined):
            return f"Couldn't {verb} '{name}': administrator rights are needed (run JARVIS as admin)."
        return f"Couldn't {verb} '{name}': {combined.strip()[-300:]}"

    # ── top processes ────────────────────────────────────────────────────────

    def top_processes(self, by: str = "cpu", limit: int = 10) -> str:
        """A richer 'what's using my CPU/RAM right now' than the dashboard gauges give."""
        if psutil is None:
            return "Process information isn't available on this platform."
        by = (by or "cpu").strip().lower()
        if by not in ("cpu", "memory", "ram"):
            by = "cpu"
        procs = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc.cpu_percent(None)          # prime the counter (first call is always 0)
                procs.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        import time
        time.sleep(0.3)
        cores = psutil.cpu_count() or 1
        rows = []
        for proc in procs:
            try:
                cpu = (proc.cpu_percent(None) or 0.0) / cores
                mem = proc.memory_info().rss
                name = proc.name() or f"PID {proc.pid}"
                rows.append((name, proc.pid, cpu, mem))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not rows:
            return "Couldn't read the process list."
        key = (lambda r: r[2]) if by == "cpu" else (lambda r: r[3])
        rows.sort(key=key, reverse=True)
        lines = []
        for name, pid, cpu, mem in rows[:max(1, min(30, int(limit)))]:
            mem_mb = mem / (1024 * 1024)
            lines.append(f"{cpu:5.1f}%  {mem_mb:7.0f} MB  {name} (pid {pid})")
        header = f"{'CPU':>6}  {'Memory':>10}  Process\n" + "\n".join(lines)
        return header
