"""Security checks: Defender status/scan, BitLocker status, Windows Update. Status
reads run immediately; starting a Defender scan or installing updates confirms
first — both take real time/resources and an update install can trigger a restart."""
import re

from core.tools import params
from handlers.base import Handler

_DEFENDER_STATUS = re.compile(r"\b(?:defender|antivirus)\s+status\b|"
                              r"\bis\s+(?:windows\s+)?defender\s+(?:on|enabled|running)\b", re.I)
_START_SCAN = re.compile(r"^(?:please\s+)?(?:start|run)\s+(?:a\s+)?(full\s+|quick\s+)?"
                         r"(?:defender|antivirus|virus)\s+scan[.!?]*$", re.I)
_BITLOCKER = re.compile(r"\bbitlocker\s+status\b|\bis\s+bitlocker\s+(?:on|enabled)\b", re.I)
_CHECK_UPDATE = re.compile(r"\bcheck\s+for\s+(?:windows\s+)?updates\b|\bany\s+(?:windows\s+)?updates\s+available\b|"
                           r"\bwindows\s+update\s+status\b", re.I)
_INSTALL_UPDATE = re.compile(r"^(?:please\s+)?install\s+(?:the\s+)?(?:windows\s+)?updates[.!?]*$", re.I)


class SecurityHandler(Handler):
    intents = {"SECURITY"}

    def handle(self, text, intent):
        app = self.app
        sec = getattr(app, "security_checks", None)
        if sec is None:
            return "Security checks aren't available."
        confirm = app._ask_to_confirm
        low = text.strip()

        if _DEFENDER_STATUS.search(low):
            return sec.defender_status()
        m = _START_SCAN.match(low)
        if m:
            scan_type = "full" if (m.group(1) or "").strip().lower() == "full" else "quick"
            return confirm(f"Start a {scan_type} Defender scan?", lambda: sec.start_defender_scan(scan_type),
                          "start_defender_scan")
        if _BITLOCKER.search(low):
            return sec.bitlocker_status()
        if _CHECK_UPDATE.search(low):
            return sec.check_windows_update()
        if _INSTALL_UPDATE.match(low):
            return confirm("Install available Windows updates? This may restart the PC.",
                          lambda: sec.install_windows_updates(), "install_windows_updates")
        return None

    def register_tools(self, t):
        sec = getattr(self.app, "security_checks", None)
        if sec is None:
            return
        t.add("defender_status", "Check Windows Defender's status (enabled, real-time protection, signatures).",
              sec.defender_status)
        t.add("start_defender_scan", "Start a Windows Defender scan in the background.", sec.start_defender_scan,
              params(scan_type=("string", "quick or full", ("quick", "full"))),
              confirm=True, confirm_text="Start a {scan_type} Defender scan?")
        t.add("bitlocker_status", "Check BitLocker encryption status for a drive.", sec.bitlocker_status,
              params(drive=("string", "Drive letter, e.g. 'C:' (default C:)")))
        t.add("check_windows_update", "Check for available Windows updates.", sec.check_windows_update)
        t.add("install_windows_updates", "Install available Windows updates (may restart the PC).",
              sec.install_windows_updates, confirm=True,
              confirm_text="Install available Windows updates? This may restart the PC.")
