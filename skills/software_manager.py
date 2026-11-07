"""Install, remove and update Windows software via ``winget`` (the App Installer CLI
that ships with Windows 10 1809+ and Windows 11).

Every write action (install / uninstall / upgrade) is confirm-gated by the caller
(handlers/software.py and the matching tool registrations) — this module itself
never assumes it's safe to run something; it just does what it's told once asked.
Read-only actions (search, list, is_installed) run without confirmation.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from core.logging_setup import get_logger

log = get_logger("jarvis.software")

_TIMEOUT_SEARCH = 30
_TIMEOUT_WRITE = 300          # installs/uninstalls can take a while (downloads, MSI UI-less runs)
_COMMON_ARGS = ["--accept-source-agreements"]
_WRITE_ARGS = ["--accept-package-agreements", "--disable-interactivity"]


@dataclass
class Package:
    name: str
    id: str
    version: str = ""
    source: str = ""

    def __str__(self):
        return f"{self.name} ({self.id})" + (f" v{self.version}" if self.version else "")


def winget_available() -> bool:
    try:
        subprocess.run(["winget", "--version"], capture_output=True, timeout=10, check=False)
        return True
    except (FileNotFoundError, OSError):
        return False
    except subprocess.TimeoutExpired:
        return True           # it exists, just slow to answer once


def _run(args: List[str], timeout: int) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(["winget", *args], capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", check=False)


def _parse_table(output: str) -> List[Package]:
    """winget's human table has no stable machine format, so this locates the header's
    column starts ("Name", "Id", "Version", "Source") and slices every row the same way —
    the same technique winget's own docs suggest for scripting against it."""
    lines = [ln for ln in output.splitlines() if ln.strip()]
    header_i = next((i for i, ln in enumerate(lines)
                     if re.search(r"\bName\b", ln) and re.search(r"\bId\b", ln)), None)
    if header_i is None:
        return []
    header = lines[header_i]
    cols = {}
    for col in ("Name", "Id", "Version", "Available", "Source"):
        m = re.search(rf"\b{col}\b", header)
        if m:
            cols[col.lower()] = m.start()
    if "name" not in cols or "id" not in cols:
        return []
    order = sorted(cols.items(), key=lambda kv: kv[1])
    packages = []
    for line in lines[header_i + 1:]:
        if set(line.strip()) <= {"-"}:            # the "------" separator row
            continue
        fields = {}
        for i, (key, start) in enumerate(order):
            end = order[i + 1][1] if i + 1 < len(order) else len(line)
            fields[key] = line[start:end].strip()
        if fields.get("name") and fields.get("id"):
            packages.append(Package(name=fields["name"], id=fields["id"],
                                    version=fields.get("version", ""), source=fields.get("source", "")))
    return packages


class SoftwareManager:
    """Search, install, uninstall and upgrade Windows software through winget."""

    def __init__(self):
        self._available: Optional[bool] = None

    def available(self) -> bool:
        if self._available is None:
            self._available = winget_available()
        return self._available

    def _unavailable_message(self) -> str:
        return ("winget isn't available on this machine. It ships with Windows 10 (1809+) and "
                "Windows 11 as part of \"App Installer\" — install/update it from the Microsoft Store, "
                "then try again.")

    # ── read-only ────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> List[Package]:
        if not self.available():
            return []
        try:
            # --query: text like '--source=x' must stay a search term, never become a winget option.
            proc = _run(["search", "--query", query, *_COMMON_ARGS], _TIMEOUT_SEARCH)
        except subprocess.TimeoutExpired:
            return []
        return _parse_table(proc.stdout)[:limit]

    def list_installed(self, query: str = "", limit: int = 20) -> List[Package]:
        if not self.available():
            return []
        args = ["list", *(["--query", query] if query else []), *_COMMON_ARGS]
        try:
            proc = _run(args, _TIMEOUT_SEARCH)
        except subprocess.TimeoutExpired:
            return []
        return _parse_table(proc.stdout)[:limit]

    def is_installed(self, name: str) -> bool:
        return bool(self.list_installed(name, limit=1))

    def _best_match(self, name: str, candidates: List[Package], strict: bool = False) -> Optional[Package]:
        """``strict`` (uninstall/upgrade): the user confirmed "uninstall 'chrome'", so never fall
        back to whatever winget lists first — that may be 'Chrome Remote Desktop'."""
        if not candidates:
            return None
        low = name.strip().lower()
        for pkg in candidates:                       # exact name/id, or the id's last part ('VideoLAN.VLC')
            if low in (pkg.name.lower(), pkg.id.lower(), pkg.id.lower().rsplit(".", 1)[-1]):
                return pkg
        if strict and len(candidates) > 1:
            return None
        return candidates[0]                          # winget already ranks by relevance

    @staticmethod
    def _ambiguous(name: str, candidates: List[Package], verb: str) -> str:
        options = "\n".join(f"• {p}" for p in candidates[:5])
        return f"More than one installed program matches '{name}', so I didn't {verb} anything:\n{options}\n" \
               f"Say the exact name or ID."

    # ── write actions (caller must confirm first) ───────────────────────────

    def install(self, name: str) -> str:
        if not self.available():
            return self._unavailable_message()
        match = self._best_match(name, self.search(name, limit=5))
        if match is None:
            return f"I couldn't find '{name}' in winget's sources. Try 'search for {name}' first."
        try:
            proc = _run(["install", "--id", match.id, "-e", *_COMMON_ARGS, *_WRITE_ARGS], _TIMEOUT_WRITE)
        except subprocess.TimeoutExpired:
            return f"Installing {match} is taking a while — check its own window; winget may still be working."
        if proc.returncode == 0:
            return f"Installed {match}."
        tail = "\n".join(l for l in (proc.stdout + proc.stderr).splitlines() if l.strip())[-400:]
        return f"Installing {match} failed (exit {proc.returncode}).{(' ' + tail) if tail else ''}"

    def uninstall(self, name: str) -> str:
        if not self.available():
            return self._unavailable_message()
        candidates = self.list_installed(name, limit=5)
        match = self._best_match(name, candidates, strict=True)
        if match is None and candidates:
            return self._ambiguous(name, candidates, "uninstall")
        if match is None:
            return f"'{name}' doesn't look like it's installed (or winget doesn't manage it)."
        try:
            proc = _run(["uninstall", "--id", match.id, "-e", *_COMMON_ARGS, "--disable-interactivity"],
                       _TIMEOUT_WRITE)
        except subprocess.TimeoutExpired:
            return f"Uninstalling {match} is taking a while — check for a confirmation dialog it may need."
        if proc.returncode == 0:
            return f"Uninstalled {match}."
        tail = "\n".join(l for l in (proc.stdout + proc.stderr).splitlines() if l.strip())[-400:]
        return f"Uninstalling {match} failed (exit {proc.returncode}).{(' ' + tail) if tail else ''}"

    def upgrade(self, name: str = "") -> str:
        if not self.available():
            return self._unavailable_message()
        if not name or name.strip().lower() in ("all", "everything", "all apps", "all software"):
            try:
                proc = _run(["upgrade", "--all", *_COMMON_ARGS, *_WRITE_ARGS], _TIMEOUT_WRITE)
            except subprocess.TimeoutExpired:
                return "Upgrading everything is taking a while — it's still running in the background."
            ok = "\n".join(l for l in proc.stdout.splitlines() if l.strip())[-600:]
            return ok or "Nothing to upgrade — everything winget manages is already current."
        candidates = self.list_installed(name, limit=5)
        match = self._best_match(name, candidates, strict=True)
        if match is None and candidates:
            return self._ambiguous(name, candidates, "upgrade")
        if match is None:
            return f"'{name}' doesn't look like it's installed."
        try:
            proc = _run(["upgrade", "--id", match.id, "-e", *_COMMON_ARGS, *_WRITE_ARGS], _TIMEOUT_WRITE)
        except subprocess.TimeoutExpired:
            return f"Upgrading {match} is taking a while — it's still running in the background."
        if proc.returncode == 0:
            return f"Upgraded {match}." if "No available upgrade" not in proc.stdout else f"{match} is already up to date."
        tail = "\n".join(l for l in (proc.stdout + proc.stderr).splitlines() if l.strip())[-400:]
        return f"Upgrading {match} failed (exit {proc.returncode}).{(' ' + tail) if tail else ''}"

    # ── formatting ───────────────────────────────────────────────────────────

    @staticmethod
    def format_list(packages: List[Package], empty: str) -> str:
        if not packages:
            return empty
        return "\n".join(f"• {p}" for p in packages)
