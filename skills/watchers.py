"""Watch-and-react automation: background condition watchers that notify when
something happens — "tell me when this download finishes", "notify me if CPU
stays above 90% for a minute". Built on the same polling pattern as
service_manager's top_processes and system_monitor.

Starting, listing, stopping or clearing watchers only affects JARVIS's own
in-memory watch list, not the system or any user data, so none of it is
confirm-gated — the same reasoning as canceling a reminder/alarm elsewhere in
the codebase.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from core.logging_setup import get_logger

log = get_logger("jarvis.watchers")

_POLL_SECONDS = 5.0
_DOWNLOAD_SUFFIXES = (".crdownload", ".part", ".tmp", ".download")


@dataclass
class _Watcher:
    id: str
    description: str
    kind: str                          # file_exists | download_stable | process_ends | cpu_above | mem_above
    target: str = ""
    threshold: float = 0.0
    duration: float = 0.0
    above_since: Optional[float] = field(default=None, repr=False)
    existing: frozenset = field(default=frozenset(), repr=False)   # download: files already there


class WatcherManager:
    """Background condition watchers that call ``app.notify(...)`` when triggered."""

    def __init__(self, app=None, poll_seconds: float = _POLL_SECONDS):
        self.app = app
        self.poll_seconds = poll_seconds
        self._watchers: Dict[str, _Watcher] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            if not self._stop.is_set():
                return
            # stop() was called and that worker is on its way out: a watcher added now must not
            # be left to a thread that's about to exit, so wait for it and start a fresh one.
            if thread is not threading.current_thread():
                thread.join(timeout=self.poll_seconds + 5)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="watchers", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ── public API ───────────────────────────────────────────────────────────

    def watch_file_created(self, path: str) -> str:
        path = os.path.expandvars(os.path.expanduser((path or "").strip().strip('"\'')))
        if not path:
            return "Which file should I watch for?"
        if not os.path.isabs(path):
            path = os.path.join(os.path.expanduser("~"), path)   # not JARVIS's own working folder
        if os.path.exists(path):
            return f"'{path}' already exists."
        wid = self._add(_Watcher(id=self._new_id(), description=f"the file '{path}' appears",
                                 kind="file_exists", target=path))
        return f"Watching for '{path}' to appear. (id: {wid})"

    def watch_download_finished(self, filename_contains: str, folder: Optional[str] = None) -> str:
        filename_contains = (filename_contains or "").strip()
        if not filename_contains or os.sep in filename_contains or "/" in filename_contains:
            return "Give me part of the download's file name to watch for."
        folder = folder or os.path.join(os.path.expanduser("~"), "Downloads")
        try:
            # Files already there (last month's 'report.pdf') must not count as the download finishing.
            existing = frozenset(f.lower() for f in os.listdir(folder))
        except OSError:
            existing = frozenset()
        wid = self._add(_Watcher(id=self._new_id(),
                                 description=f"a download containing '{filename_contains}' finishes",
                                 kind="download_stable", target=os.path.join(folder, filename_contains),
                                 existing=existing))
        return f"Watching for a download containing '{filename_contains}' to finish in {folder}. (id: {wid})"

    def watch_process_ends(self, process_name: str) -> str:
        process_name = (process_name or "").strip()
        if not process_name:
            return "Which program should I watch?"
        if not self._process_running(process_name):
            # Otherwise a typo ('chorme') "closes" at the first check and fires a false alert.
            return f"'{process_name}' isn't running right now, so there's nothing to wait for."
        wid = self._add(_Watcher(id=self._new_id(), description=f"'{process_name}' closes",
                                 kind="process_ends", target=process_name))
        return f"Watching for '{process_name}' to close. (id: {wid})"

    @staticmethod
    def _bad_limits(threshold, minutes) -> Optional[str]:
        try:
            threshold, minutes = float(threshold), float(minutes)
        except (TypeError, ValueError):
            return "Give the threshold and minutes as numbers."
        if not 0 < threshold < 100:      # also rejects nan: it would never (or always) trigger
            return "The threshold must be a percentage between 0 and 100."
        if not 0 <= minutes <= 24 * 60:
            return "The duration must be between 0 minutes and a day."
        return None

    def watch_cpu_above(self, threshold: float, minutes: float = 1.0) -> str:
        problem = self._bad_limits(threshold, minutes)
        if problem:
            return problem
        threshold, minutes = float(threshold), float(minutes)
        wid = self._add(_Watcher(id=self._new_id(),
                                 description=f"CPU stays above {threshold}% for {minutes} minute(s)",
                                 kind="cpu_above", threshold=float(threshold), duration=float(minutes) * 60))
        return f"Watching for CPU to stay above {threshold}% for {minutes} minute(s). (id: {wid})"

    def watch_memory_above(self, threshold: float, minutes: float = 1.0) -> str:
        problem = self._bad_limits(threshold, minutes)
        if problem:
            return problem
        threshold, minutes = float(threshold), float(minutes)
        wid = self._add(_Watcher(id=self._new_id(),
                                 description=f"memory usage stays above {threshold}% for {minutes} minute(s)",
                                 kind="mem_above", threshold=float(threshold), duration=float(minutes) * 60))
        return f"Watching for memory usage to stay above {threshold}% for {minutes} minute(s). (id: {wid})"

    def list_watchers(self) -> str:
        with self._lock:
            items = list(self._watchers.values())
        if not items:
            return "No active watchers."
        return "\n".join(f"• [{w.id}] {w.description}" for w in items)

    def stop_watcher(self, watcher_id: str) -> str:
        with self._lock:
            existed = self._watchers.pop(watcher_id, None)
        return f"Stopped watching for {existed.description}." if existed else f"No watcher with id '{watcher_id}'."

    def clear_watchers(self) -> str:
        with self._lock:
            count = len(self._watchers)
            self._watchers.clear()
        return f"Cleared {count} watcher(s)."

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:8]

    def _add(self, watcher: _Watcher) -> str:
        with self._lock:
            self._watchers[watcher.id] = watcher
        self.start()
        return watcher.id

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._check_all()
            self._stop.wait(self.poll_seconds)

    def _check_all(self) -> None:
        with self._lock:
            items = list(self._watchers.values())
        for watcher in items:
            try:
                if self._check_one(watcher):
                    self._fire(watcher)
            except Exception:
                log.exception("watcher %s failed", watcher.id)

    def _check_one(self, watcher: _Watcher) -> bool:
        if watcher.kind == "file_exists":
            return os.path.exists(watcher.target)
        if watcher.kind == "download_stable":
            return self._check_download_stable(watcher)
        if watcher.kind == "process_ends":
            return not self._process_running(watcher.target)
        if watcher.kind == "cpu_above":
            return self._check_sustained(watcher, self._cpu_percent())
        if watcher.kind == "mem_above":
            return self._check_sustained(watcher, self._mem_percent())
        return False

    @staticmethod
    def _check_download_stable(watcher: "_Watcher") -> bool:
        folder = os.path.dirname(watcher.target)
        needle = os.path.basename(watcher.target).lower()
        if not os.path.isdir(folder):
            return False
        try:
            matches = [f for f in os.listdir(folder)
                      if needle in f.lower() and not f.lower().endswith(_DOWNLOAD_SUFFIXES)
                      and f.lower() not in watcher.existing]
        except OSError:
            return False
        if not matches:
            return False
        path = os.path.join(folder, matches[0])
        try:
            size1 = os.path.getsize(path)
        except OSError:
            return False
        time.sleep(1)
        try:
            size2 = os.path.getsize(path)
        except OSError:
            return False
        return size1 == size2 and size1 > 0

    @staticmethod
    def _process_running(name: str) -> bool:
        try:
            import psutil
        except Exception:
            return True   # can't tell => assume still running, don't fire falsely
        needle = name.lower()
        for proc in psutil.process_iter(["name"]):
            try:
                if needle in (proc.info.get("name") or "").lower():
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _cpu_percent() -> float:
        try:
            import psutil
            return psutil.cpu_percent(interval=None)
        except Exception:
            return 0.0

    @staticmethod
    def _mem_percent() -> float:
        try:
            import psutil
            return psutil.virtual_memory().percent
        except Exception:
            return 0.0

    @staticmethod
    def _check_sustained(watcher: "_Watcher", value: float) -> bool:
        now = time.monotonic()
        if value >= watcher.threshold:
            if watcher.above_since is None:
                watcher.above_since = now
            return (now - watcher.above_since) >= watcher.duration
        watcher.above_since = None
        return False

    def _fire(self, watcher: _Watcher) -> None:
        with self._lock:
            self._watchers.pop(watcher.id, None)
        message = f"Heads up — {watcher.description}."
        notify = getattr(self.app, "notify", None) if self.app is not None else None
        if notify is not None:
            try:
                notify(message, speak=True)
            except Exception:
                log.exception("watcher notify failed")
        else:
            log.info(message)
