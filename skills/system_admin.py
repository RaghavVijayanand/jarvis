"""OS-level administration: registry, firewall rules, scheduled tasks and elevation.

These reach further than JARVIS's other skills — a registry write, a firewall rule
or a scheduled task affects the whole machine, and some of them need admin rights
JARVIS doesn't have by default. Every write path here is meant to be called only
after the caller (handlers/admin.py's tool registrations) has already gotten an
explicit "yes" — this module does not confirm anything itself, it just acts.

Nothing here elevates JARVIS itself for its whole lifetime. When a specific action
needs admin rights and the process isn't already elevated, ``run_elevated`` launches
*just that one command* in a new elevated process (a single UAC prompt), so JARVIS
keeps running as a normal user the rest of the time. There is no way to read that
elevated process's output back — that's the tradeoff for not staying elevated.
"""
from __future__ import annotations

import re
import subprocess
from typing import List, Optional

from core.logging_setup import get_logger

log = get_logger("jarvis.admin")

try:
    import winreg
except Exception:  # pragma: no cover - non-Windows
    winreg = None

try:
    import ctypes
except Exception:  # pragma: no cover
    ctypes = None

_HIVES = {
    "hkcu": "HKEY_CURRENT_USER", "hkey_current_user": "HKEY_CURRENT_USER",
    "hklm": "HKEY_LOCAL_MACHINE", "hkey_local_machine": "HKEY_LOCAL_MACHINE",
    "hkcr": "HKEY_CLASSES_ROOT", "hkey_classes_root": "HKEY_CLASSES_ROOT",
    "hku": "HKEY_USERS", "hkey_users": "HKEY_USERS",
    "hkcc": "HKEY_CURRENT_CONFIG", "hkey_current_config": "HKEY_CURRENT_CONFIG",
}
_REG_TYPES = {"string": "REG_SZ", "expand_string": "REG_EXPAND_SZ", "dword": "REG_DWORD",
              "qword": "REG_QWORD", "multi_string": "REG_MULTI_SZ", "binary": "REG_BINARY"}
_TIMEOUT = 20


def _hive_label(name: str) -> Optional[str]:
    return _HIVES.get((name or "").strip().lower().replace(" ", "_"))


def _hive_const(name: str):
    label = _hive_label(name)
    if label is None or winreg is None:
        return None
    return getattr(winreg, label, None)


def is_admin() -> bool:
    """True if this process already has administrator rights."""
    if ctypes is None:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_elevated(command: str) -> str:
    """Launch ONE command in a new elevated process (a single UAC prompt) instead of
    elevating JARVIS itself. ``command`` runs through ``cmd.exe /c``, so build it the
    same way you would for a shell — and never pass it unvalidated user text without a
    confirm step upstream, since this is a real code-execution path by design."""
    if ctypes is None:
        return "Elevation isn't available on this platform."
    try:
        # ShellExecuteW's return value is > 32 on success (per the Win32 docs);
        # 32 or less means it failed to launch, or the user declined the UAC prompt.
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f"/c {command}", None, 1)
        if int(result) > 32:
            return "Started with administrator rights — approve the Windows security prompt if one appeared."
        return "That needs administrator approval, and either it wasn't granted or it couldn't start."
    except Exception as exc:
        return f"Couldn't request elevation: {exc}"


def run_elevated_args(args: List[str]) -> str:
    """Launch ONE program elevated with an argument list — no ``cmd.exe`` in between, so
    values the user approved (a registry value, a rule name) can never be read as
    ``&``/``|`` command separators."""
    if ctypes is None:
        return "Elevation isn't available on this platform."
    try:
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", args[0], subprocess.list2cmdline(args[1:]),
                                                     None, 1)
        if int(result) > 32:
            return "Started with administrator rights — approve the Windows security prompt if one appeared."
        return "That needs administrator approval, and either it wasn't granted or it couldn't start."
    except Exception as exc:
        return f"Couldn't request elevation: {exc}"


def _registry_data(type_name: str, value):
    """Tool/user text → the Python type winreg needs for ``type_name``. Raises ValueError."""
    if type_name in ("REG_DWORD", "REG_QWORD"):
        number = int(str(value).strip(), 0)          # '10', '0x1F'
        if not 0 <= number < 1 << (32 if type_name == "REG_DWORD" else 64):
            raise ValueError(f"it doesn't fit in a {type_name}")
        return number
    if type_name == "REG_MULTI_SZ":
        return [str(v) for v in value] if isinstance(value, (list, tuple)) else str(value).splitlines()
    if type_name == "REG_BINARY":
        return bytes.fromhex(re.sub(r"0x|[\s,]", "", str(value)))
    return str(value)


def _run(args: List[str], timeout: int = _TIMEOUT) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", check=False)


class SystemAdmin:
    """Registry, firewall and OS-level scheduled tasks — the parts of Windows that
    JARVIS's app/window/file skills don't reach."""

    # ── elevation ────────────────────────────────────────────────────────────
    @staticmethod
    def is_admin() -> bool:
        return is_admin()

    @staticmethod
    def request_elevated(command: str) -> str:
        return run_elevated(command)

    # ── registry ─────────────────────────────────────────────────────────────
    def read_registry_value(self, hive: str, path: str, name: str):
        if winreg is None:
            return "Registry access isn't available on this platform."
        const = _hive_const(hive)
        if const is None:
            return f"Unknown registry hive '{hive}'. Use HKCU, HKLM, HKCR, HKU or HKCC."
        try:
            with winreg.OpenKey(const, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
            return value
        except FileNotFoundError:
            return f"{hive}\\{path}\\{name} doesn't exist."
        except OSError as exc:
            return f"Couldn't read {hive}\\{path}\\{name}: {exc}"

    def write_registry_value(self, hive: str, path: str, name: str, value, value_type: str = "string") -> str:
        if winreg is None:
            return "Registry access isn't available on this platform."
        const = _hive_const(hive)
        if const is None:
            return f"Unknown registry hive '{hive}'. Use HKCU, HKLM, HKCR, HKU or HKCC."
        type_name = _REG_TYPES.get((value_type or "string").lower(), "REG_SZ")
        type_const = getattr(winreg, type_name, None)
        try:
            data = _registry_data(type_name, value)
        except ValueError as exc:
            return f"'{value}' isn't a valid {type_name} value: {exc}."
        try:
            with winreg.CreateKeyEx(const, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, name, 0, type_const, data)
            return f"Set {hive}\\{path}\\{name} = {value}."
        except PermissionError:
            reg_data = ("\\0".join(data) if type_name == "REG_MULTI_SZ"
                        else data.hex() if type_name == "REG_BINARY" else str(data))
            hint = run_elevated_args(["reg", "add", f"{_hive_label(hive)}\\{path}", "/v", name,
                                      "/t", type_name, "/d", reg_data, "/f"])
            return f"That needs administrator rights. {hint}"
        except OSError as exc:
            return f"Couldn't set {hive}\\{path}\\{name}: {exc}"

    def delete_registry_value(self, hive: str, path: str, name: str) -> str:
        if winreg is None:
            return "Registry access isn't available on this platform."
        const = _hive_const(hive)
        if const is None:
            return f"Unknown registry hive '{hive}'. Use HKCU, HKLM, HKCR, HKU or HKCC."
        try:
            with winreg.OpenKey(const, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
            return f"Deleted {hive}\\{path}\\{name}."
        except FileNotFoundError:
            return f"{hive}\\{path}\\{name} doesn't exist."
        except PermissionError:
            hint = run_elevated_args(["reg", "delete", f"{_hive_label(hive)}\\{path}", "/v", name, "/f"])
            return f"That needs administrator rights. {hint}"
        except OSError as exc:
            return f"Couldn't delete {hive}\\{path}\\{name}: {exc}"

    # ── firewall (netsh) ─────────────────────────────────────────────────────
    def list_firewall_rules(self, name_filter: str = "") -> str:
        args = ["netsh", "advfirewall", "firewall", "show", "rule",
                f"name={name_filter}" if name_filter else "name=all"]
        try:
            proc = _run(args)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't list firewall rules: {exc}"
        names = re.findall(r"^Rule Name:\s*(.+)$", proc.stdout, re.M)
        return "\n".join(f"• {n.strip()}" for n in names[:40]) if names else "No matching firewall rules."

    def add_firewall_rule(self, name: str, direction: str = "in", action: str = "allow",
                          protocol: str = "TCP", port: Optional[str] = None,
                          program: Optional[str] = None) -> str:
        args = ["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}",
                f"dir={'in' if str(direction).lower().startswith('in') else 'out'}",
                f"action={'allow' if str(action).lower().startswith('allow') else 'block'}"]
        args += [f"program={program}"] if program else [f"protocol={(protocol or 'TCP').upper()}",
                                                         f"localport={port or 'any'}"]
        return self._elevated_run(args, f"Added firewall rule '{name}'.")

    def remove_firewall_rule(self, name: str) -> str:
        return self._elevated_run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
                                  f"Removed firewall rule '{name}'.")

    # ── OS-level scheduled tasks (distinct from JARVIS's own reminders) ────────
    def list_scheduled_tasks(self, query: str = "") -> str:
        try:
            proc = _run(["schtasks", "/query", "/fo", "csv", "/nh"])
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"Couldn't list scheduled tasks: {exc}"
        names = [ln.split('","')[0].strip('"') for ln in proc.stdout.splitlines() if ln.strip()]
        if query:
            names = [n for n in names if query.lower() in n.lower()]
        return "\n".join(f"• {n}" for n in names[:40]) if names else "No matching scheduled tasks."

    def create_scheduled_task(self, name: str, command: str, schedule: str = "ONCE",
                              start_time: Optional[str] = None) -> str:
        args = ["schtasks", "/create", "/tn", name, "/tr", command, "/sc", (schedule or "ONCE").upper(), "/f"]
        if start_time:
            args += ["/st", start_time]
        return self._elevated_run(args, f"Created scheduled task '{name}'.")

    def delete_scheduled_task(self, name: str) -> str:
        return self._elevated_run(["schtasks", "/delete", "/tn", name, "/f"], f"Deleted scheduled task '{name}'.")

    def _elevated_run(self, args: List[str], ok_message: str) -> str:
        try:
            proc = _run(args)
        except FileNotFoundError:
            return f"{args[0]} isn't available on this platform."
        except subprocess.TimeoutExpired:
            return "That command timed out."
        if proc.returncode == 0:
            return ok_message
        combined = proc.stdout + proc.stderr
        if "access is denied" in combined.lower() or "requires elevation" in combined.lower():
            hint = run_elevated_args(args)
            return f"That needs administrator rights. {hint}"
        return f"That command failed: {combined.strip()[-300:]}"
