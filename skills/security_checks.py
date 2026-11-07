"""Security checks: Windows Defender status/scan, BitLocker status, and Windows
Update checks/installs.

Read-only checks (Defender status, BitLocker status, checking for updates) run
immediately. Starting a Defender scan or installing updates always confirms first
— both take real time and system resources, and installing updates can trigger a
restart, so they're the same risk class as a service restart or a firewall change.
"""
from __future__ import annotations

import re
import subprocess
from typing import List

from core.logging_setup import get_logger
from skills.system_admin import run_elevated

log = get_logger("jarvis.security")

_TIMEOUT = 30


def _run_ps(command: str, timeout: int = _TIMEOUT) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", check=False)


def _parse_fields(text: str) -> dict:
    return dict(re.findall(r"^(\w+)\s*:\s*(.*)$", text, re.M))


class SecurityChecks:
    """Windows Defender, BitLocker and Windows Update — the parts of Windows
    security JARVIS's other skills don't reach."""

    # ── Windows Defender ─────────────────────────────────────────────────────

    def defender_status(self) -> str:
        try:
            proc = _run_ps("Get-MpComputerStatus | Select-Object AntivirusEnabled,"
                           "RealTimeProtectionEnabled,AntivirusSignatureLastUpdated | Format-List")
        except FileNotFoundError:
            return "PowerShell isn't available on this platform."
        except subprocess.TimeoutExpired as exc:
            return f"Couldn't check Defender status: {exc}"
        if proc.returncode != 0 or not proc.stdout.strip():
            return "Couldn't read Windows Defender status (it may not be the active antivirus)."
        fields = _parse_fields(proc.stdout)
        av = fields.get("AntivirusEnabled", "?").strip()
        rtp = fields.get("RealTimeProtectionEnabled", "?").strip()
        sig = fields.get("AntivirusSignatureLastUpdated", "unknown").strip()
        return f"Antivirus enabled: {av}. Real-time protection: {rtp}. Signatures last updated: {sig}."

    def start_defender_scan(self, scan_type: str = "quick") -> str:
        scan_type = (scan_type or "quick").strip().lower()
        ps_type = "FullScan" if scan_type.startswith("full") else "QuickScan"
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             f"Start-MpScan -ScanType {ps_type}"])
        except FileNotFoundError:
            return "PowerShell isn't available on this platform."
        except Exception as exc:
            return f"Couldn't start the scan: {exc}"
        label = "full" if ps_type == "FullScan" else "quick"
        return f"Started a Windows Defender {label} scan in the background."

    # ── BitLocker ─────────────────────────────────────────────────────────────

    def bitlocker_status(self, drive: str = "C:") -> str:
        drive = (drive or "C:").strip().rstrip("\\/")
        if not drive.endswith(":"):
            drive += ":"
        # The drive goes inside a PowerShell string: only a bare letter, so "C'; Start-Process x; '"
        # can't end the string and run a second command (this check runs without confirmation).
        if not re.fullmatch(r"[A-Za-z]:", drive):
            return f"'{drive}' isn't a drive letter (e.g. C:)."
        try:
            proc = _run_ps(f"Get-BitLockerVolume -MountPoint '{drive}' | "
                           "Select-Object VolumeStatus,ProtectionStatus,EncryptionPercentage | Format-List")
        except FileNotFoundError:
            return "PowerShell isn't available on this platform."
        except subprocess.TimeoutExpired as exc:
            return f"Couldn't check BitLocker status: {exc}"
        if proc.returncode != 0 or not proc.stdout.strip():
            return f"Couldn't read BitLocker status for {drive} (it may not exist, or BitLocker isn't available)."
        fields = _parse_fields(proc.stdout)
        status = fields.get("ProtectionStatus", "?").strip()
        vol_status = fields.get("VolumeStatus", "?").strip()
        pct = fields.get("EncryptionPercentage", "?").strip()
        protected = {"1": "on", "0": "off"}.get(status, status)
        return f"{drive} — BitLocker protection is {protected}. Volume status: {vol_status}. Encrypted: {pct}%."

    # ── Windows Update ───────────────────────────────────────────────────────

    def check_windows_update(self) -> str:
        try:
            import win32com.client
        except Exception:
            return "Checking for updates needs the 'pywin32' package. Install it with: pip install pywin32"
        try:
            session = win32com.client.Dispatch("Microsoft.Update.Session")
            searcher = session.CreateUpdateSearcher()
            result = searcher.Search("IsInstalled=0 and IsHidden=0")
            updates = result.Updates
            count = updates.Count
        except Exception as exc:
            return f"Couldn't check for updates: {exc}"
        if count == 0:
            return "Windows is up to date."
        titles: List[str] = [updates.Item(i).Title for i in range(min(count, 10))]
        more = f" (+{count - 10} more)" if count > 10 else ""
        return f"{count} update(s) available:\n" + "\n".join(f"• {t}" for t in titles) + more

    def install_windows_updates(self) -> str:
        hint = run_elevated("UsoClient.exe StartInstall")
        return f"Requested Windows Update installation. {hint}"
