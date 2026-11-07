"""PC control: power, windows, display (resolution, brightness), Settings pages, clipboard/typing tools."""
import re
import threading

from core.tools import params
from handlers.base import Handler

_TARGET = r"\b(?:pc|computer|laptop|system|machine|device|windows|workstation)\b"
_FILLER = r"(?:the|my|this|now|please|jarvis|right|immediately|down|off|it|of|for me)"


def _power_request(low, verbs):
    """True when a power verb is aimed at the PC itself: "restart the pc", "shut down now",
    but not "restart spotify" or "sign out of gmail" (those must not queue a PC restart/sign-out)."""
    m = re.search(rf"\b(?:{verbs})\b(.*)$", low)
    if not m:
        return False
    return bool(re.search(_TARGET, low) or re.fullmatch(rf"(?:\s*\b{_FILLER}\b)*\s*", m.group(1)))


class ControlHandler(Handler):
    intents = {"CONTROL"}

    def __init__(self, app):
        super().__init__(app)
        self._resolution_timer = None
        self._timer_lock = threading.Lock()

    def handle(self, text, intent):
        app = self.app
        low = text.lower().strip().rstrip(".!?")
        w = app.windows
        confirm = app._ask_to_confirm
        if re.search(r"\b(?:cancel|abort|stop|don'?t) (?:the )?(?:pending )?(?:shutdown|shut down|restart|reboot)\b",
                     low):
            return w.cancel_shutdown()
        # "open lock screen / sleep / restart settings" must open Settings, not lock or power off the PC.
        if re.search(r"\bsettings?\b", low) and not re.search(r"\d", low):
            return w.open_settings(re.sub(r"\b(open|show|the|my|settings?|page|go to)\b", " ", low))
        if re.search(r"\block\b", low):
            return w.lock()
        if _power_request(low, r"restart|reboot"):
            return confirm("Restart the computer?", lambda: w.shutdown(restart=True), "restart")
        if _power_request(low, r"shut ?down|power off") or \
                re.search(r"\bturn off (?:the |my )?(?:pc|computer|laptop)\b", low):
            return confirm("Shut down the computer?", lambda: w.shutdown(restart=False), "shutdown")
        if _power_request(low, r"log ?off|sign out|log out"):
            return confirm("Sign out of Windows? Unsaved work may be lost.", w.sign_out, "sign_out")
        if _power_request(low, r"sleep|hibernate"):
            return confirm("Put the computer to sleep?", w.sleep, "sleep")
        if re.search(r"\b(restore|revert|reset|undo)\b.*\bresolution\b|\bresolution back\b", low):
            self.cancel_resolution_timer()
            return w.restore_resolution()
        if re.search(r"\bkeep (?:this |the )?resolution\b", low):
            return "Keeping this resolution." if self.cancel_resolution_timer() else \
                "There's no pending resolution change."
        if "resolution" in low:
            size = w.parse_resolution(low)
            if not size and re.search(r"\bwhat\b|\bwhat's\b|\bcurrent\b", low):
                try:
                    cur = w.get_resolution()
                    return f"Your screen resolution is {cur[0]}×{cur[1]}."
                except Exception as exc:
                    return f"Couldn't read the resolution: {exc}"
            if not size:
                return "Which resolution? For example 'change resolution to 1080p' or '1280x720'."
            return confirm(f"Change the screen resolution to {size[0]}×{size[1]}?",
                           lambda: self.apply_resolution(*size), "resolution")
        if "brightness" in low or re.search(r"\b(?:dim|brighten)\b.*\bscreen\b", low):
            m = re.search(r"brightness\D*?(\d{1,3})|(\d{1,3})\s*(?:%|percent)?\s*brightness", low)
            num = int(m.group(1) or m.group(2)) if m else None
            down = re.search(r"\b(?:down|decrease|lower|reduce|dim|darker)\b", low)
            up = re.search(r"\b(?:up|increase|raise|brighter|brighten|higher)\b", low)
            if (up or down) and not re.search(r"\bto\s+\d", low):
                step = num if num is not None else 10          # "brightness up by 20" is relative, not 20%
                return w.change_brightness(-step if down else step)
            if num is not None:
                return w.set_brightness(num)
        if "brightness" in low and re.search(r"\bwhat\b|\bwhat's\b|\bcurrent\b", low):
            level = w.get_brightness()
            return f"Brightness is {level}%." if level is not None else "I can't read the brightness of this display."
        if "brightness" in low:
            return "Tell me a level, e.g. 'brightness 60'."
        if re.search(r"close (?:all|every)(?: open)? windows?", low):
            return confirm("Ask every open window to close?", w.close_all_windows, "close_all")
        if re.search(r"show (?:the )?desktop|minimi[sz]e (?:all|everything)", low):
            return w.show_desktop()
        if re.search(r"list (?:open |all )?windows|what windows", low):
            return w.list_windows()
        m = re.search(r"\b(minimi[sz]e|maximi[sz]e|restore|focus|switch to)\s+(?:the\s+)?(.+?)(?:\s+window)?$", low)
        if m:
            verb = m.group(1)
            action = {"switch to": "focus", "focus": "focus", "restore": "restore"}.get(verb) or (
                "minimize" if verb.startswith("minimi") else "maximize")
            return w.window_action(m.group(2), action)
        if re.search(r"\b(?:empty|clear|clean(?: out)?|wipe|delete|remove)\b.{0,30}?\brecycle bin\b|"
                     r"\brecycle bin\b.{0,20}?\b(?:empty|clear|delet(?:e|ing)|remov(?:e|ing))\b", low):
            return confirm("Permanently empty the Recycle Bin?", app.system_control.empty_recycle_bin,
                           "empty_recycle_bin")
        if re.search(r"\bsettings?\b", low):
            return w.open_settings(re.sub(r"\b(open|show|the|my|settings?|page|go to)\b", " ", low))
        return None

    # ── resolution with an automatic safety revert (like Windows' own 15 s prompt) ──
    def apply_resolution(self, width, height):
        reply = self.app.windows.set_resolution(width, height)
        if reply.startswith("Resolution changed"):
            self.cancel_resolution_timer()
            timer = threading.Timer(15, lambda: self._auto_revert(timer))
            timer.daemon = True
            with self._timer_lock:
                self._resolution_timer = timer
            timer.start()
            reply += " Say 'keep resolution' within 15 seconds, otherwise I'll switch it back."
        return reply

    def _auto_revert(self, timer=None):
        with self._timer_lock:
            # A timer that was cancelled (or superseded by a newer change) after it started firing
            # must not revert, nor clobber the newer timer's reference.
            if timer is not None and self._resolution_timer is not timer:
                return
            self._resolution_timer = None
        try:
            self.app.notify(self.app.windows.restore_resolution() + " (no 'keep resolution' heard)", speak=True)
        except Exception:
            self.log.exception("resolution auto-revert failed")

    def cancel_resolution_timer(self):
        with self._timer_lock:
            timer, self._resolution_timer = self._resolution_timer, None
        if timer is not None:
            timer.cancel()
            return True
        return False

    def register_tools(self, t):
        w = self.app.windows
        t.add("lock_pc", "Lock the Windows session.", w.lock)
        t.add("power_action", "Shut down, restart, sleep or sign out the PC.",
              lambda action: {"shutdown": lambda: w.shutdown(False), "restart": lambda: w.shutdown(True),
                              "sleep": w.sleep, "sign_out": w.sign_out}.get(
                  action, lambda: f"Unknown power action '{action}'.")(),
              params(["action"], action=("string", "Power action", ["shutdown", "restart", "sleep", "sign_out"])),
              confirm=True, confirm_text="Allow JARVIS to {action} the computer?")
        t.add("set_resolution", "Change the display resolution (reverts after 15 s unless the user keeps it).",
              lambda width, height: self.apply_resolution(int(width), int(height)),
              params(["width", "height"], width=("integer", "e.g. 1280"), height=("integer", "e.g. 720")),
              confirm=True, confirm_text="Change the screen resolution to {width}×{height}?")
        t.add("set_brightness", "Set display brightness (0-100).", w.set_brightness,
              params(["level"], level=("integer", "0-100")))
        t.add("window_action", "Focus, minimize, maximize, restore or close a window by title.", w.window_action,
              params(["title", "action"], title=("string", "Part of the window title"),
                     action=("string", "Action", ["focus", "minimize", "maximize", "restore", "close"])))
        t.add("list_windows", "List open windows.", w.list_windows)
        t.add("show_desktop", "Minimize all windows.", w.show_desktop)
        t.add("open_settings", "Open a Windows Settings page (bluetooth, wifi, display, sound, update …).",
              w.open_settings, params(page=("string", "Settings page name")))
        t.add("get_clipboard", "Read the clipboard text.", w.get_clipboard)
        t.add("set_clipboard", "Copy text to the clipboard.", w.set_clipboard,
              params(["text"], text=("string", "Text to copy")))
        t.add("type_text", "Type text at the current cursor position (supports any language).", w.type_text,
              params(["text"], text=("string", "Text to type")))
