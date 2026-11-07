"""Power plans (powercfg) and startup-app management — for ANY app, not just JARVIS's
own toggle in core/autostart.py.

Switching a power plan or toggling another app's startup entry is reversible but
changes system-wide behavior, so both are confirm-gated by the caller
(handlers/power.py) — the same risk class as a firewall rule or a service restart.

Startup apps are tracked the same way Task Manager's Startup tab tracks them: the
Run key holds the launch command, and a matching value under ...\\StartupApproved\\Run
holds a 12-byte flag whose first byte is 0x02 (enabled) or 0x03 (disabled). An app
with no StartupApproved entry yet is enabled by default (that's the out-of-the-box
state), so it's reported as enabled until someone disables it once.
"""
from __future__ import annotations

import re
import subprocess
from typing import List, Optional, Tuple

from core.logging_setup import get_logger
from skills.network_manager import console_encoding

log = get_logger("jarvis.power")

try:
    import winreg
except Exception:  # pragma: no cover - non-Windows
    winreg = None

_TIMEOUT = 20
_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APPROVED_PATH = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
_RUN_HIVES = ("HKCU", "HKLM")
# "<label>: <GUID>  (<name>) *" — matched on the GUID, not the English "Power Scheme GUID"
# label, so a German/Hindi/... Windows lists its plans too.
_PLAN_ROW = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
                       r"\s*\((.+?)\)(\s*\*)?")


def _hive_const(hive_name: str):
    if winreg is None:
        return None
    return {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}.get(hive_name)


def _run(args: List[str], timeout: int = _TIMEOUT) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          encoding=console_encoding(), errors="replace", check=False)


class PowerManager:
    """Power plans and startup app entries — the parts of Windows power/startup
    behavior beyond JARVIS's own sleep/restart/shutdown controls."""

    # ── power plans ──────────────────────────────────────────────────────────

    def list_power_plans(self) -> str:
        try:
            proc = _run(["powercfg", "/list"])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't list power plans: {exc}"
        rows = _PLAN_ROW.findall(proc.stdout)
        if not rows:
            return "No power plans found."
        return "\n".join(f"• {name.strip()}{' (active)' if star.strip() else ''}" for _, name, star in rows)

    def active_power_plan(self) -> str:
        try:
            proc = _run(["powercfg", "/getactivescheme"])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't check the active power plan: {exc}"
        m = re.search(r"\((.+?)\)", proc.stdout)
        return f"Active power plan: {m.group(1).strip()}" if m else (proc.stdout.strip() or
                                                                      "Couldn't read the active power plan.")

    def set_power_plan(self, name: str) -> str:
        guid = self._find_plan_guid(name)
        if guid is None:
            return f"No power plan matching '{name}'. Try listing power plans first."
        try:
            proc = _run(["powercfg", "/setactive", guid])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't switch power plans: {exc}"
        if proc.returncode == 0:
            return f"Switched to the '{name}' power plan."
        return f"Couldn't switch power plans: {(proc.stdout + proc.stderr).strip()[-300:]}"

    def _find_plan_guid(self, name: str) -> Optional[str]:
        try:
            proc = _run(["powercfg", "/list"])
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        rows = [(guid, label) for guid, label, _ in _PLAN_ROW.findall(proc.stdout)]
        q = (name or "").strip().lower()
        if not q:
            return None         # '' is a substring of every name: never "match" the first plan
        for guid, label in rows:
            if q == label.strip().lower():
                return guid
        for guid, label in rows:
            if q in label.strip().lower():
                return guid
        return None

    # ── startup apps ─────────────────────────────────────────────────────────

    def list_startup_apps(self) -> str:
        if winreg is None:
            return "Startup app management isn't available on this platform."
        entries = self._all_run_entries()
        if not entries:
            return "No startup apps found."
        lines = []
        for hive_name, value_name, _command in entries:
            enabled = self._is_enabled(hive_name, value_name)
            lines.append(f"• {value_name} ({hive_name}) — {'enabled' if enabled else 'disabled'}")
        return "\n".join(lines)

    def _all_run_entries(self) -> List[Tuple[str, str, str]]:
        entries: List[Tuple[str, str, str]] = []
        for hive_name in _RUN_HIVES:
            const = _hive_const(hive_name)
            try:
                with winreg.OpenKey(const, _RUN_PATH) as key:
                    i = 0
                    while True:
                        try:
                            value_name, value_data, _ = winreg.EnumValue(key, i)
                        except OSError:
                            break
                        i += 1
                        entries.append((hive_name, value_name, value_data))
            except OSError:
                continue
        return entries

    def _is_enabled(self, hive_name: str, value_name: str) -> bool:
        const = _hive_const(hive_name)
        try:
            with winreg.OpenKey(const, _APPROVED_PATH) as key:
                data, _ = winreg.QueryValueEx(key, value_name)
            if isinstance(data, (bytes, bytearray)) and len(data) >= 1:
                return data[0] != 0x03
        except OSError:
            pass
        return True   # not tracked yet => enabled is the default, out-of-the-box state

    def _find_run_entry(self, name: str) -> Optional[Tuple[str, str]]:
        q = (name or "").strip().lower()
        if not q:
            return None         # '' would match (and toggle) the first startup entry
        entries = self._all_run_entries()
        for hive_name, value_name, _cmd in entries:
            if value_name.strip().lower() == q:
                return hive_name, value_name
        for hive_name, value_name, _cmd in entries:
            if q in value_name.strip().lower():
                return hive_name, value_name
        return None

    def enable_startup_app(self, name: str) -> str:
        return self._set_startup_enabled(name, True)

    def disable_startup_app(self, name: str) -> str:
        return self._set_startup_enabled(name, False)

    def _set_startup_enabled(self, name: str, enabled: bool) -> str:
        if winreg is None:
            return "Startup app management isn't available on this platform."
        found = self._find_run_entry(name)
        if found is None:
            return f"No startup app matching '{name}'. Try listing startup apps first."
        hive_name, value_name = found
        const = _hive_const(hive_name)
        flag = bytes([0x02 if enabled else 0x03]) + bytes(11)
        try:
            with winreg.CreateKeyEx(const, _APPROVED_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, value_name, 0, winreg.REG_BINARY, flag)
            return f"{'Enabled' if enabled else 'Disabled'} '{value_name}' at startup."
        except PermissionError:
            return f"Couldn't change '{value_name}': administrator rights are needed."
        except OSError as exc:
            return f"Couldn't change '{value_name}': {exc}"
