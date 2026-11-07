"""Native Windows controls: power, media, volume, windows, clipboard, settings.

These back the "control my laptop" requests from audit §13.4/§14 — lock the
PC, pause the music, turn the volume down, close all windows — using Win32
APIs directly (ctypes / pywin32), never a shell command built from user text.
Destructive actions (shutdown, restart, sign out, sleep, close all windows)
are only reachable through JARVIS's confirmation step.
"""
import ctypes
import os
import re
import subprocess
import time

from core import clipboard
from core.logging_setup import get_logger

log = get_logger("jarvis.windows")

# Virtual-key codes
VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2,
      "volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF}
KEYEVENTF_KEYUP = 0x0002

SETTINGS_PAGES = {
    "bluetooth": "ms-settings:bluetooth", "wifi": "ms-settings:network-wifi", "wi-fi": "ms-settings:network-wifi",
    "network": "ms-settings:network", "display": "ms-settings:display", "sound": "ms-settings:sound",
    "battery": "ms-settings:batterysaver", "power": "ms-settings:powersleep", "update": "ms-settings:windowsupdate",
    "windows update": "ms-settings:windowsupdate", "apps": "ms-settings:appsfeatures",
    "privacy": "ms-settings:privacy", "notifications": "ms-settings:notifications",
    "personalization": "ms-settings:personalization", "wallpaper": "ms-settings:personalization-background",
    "background": "ms-settings:personalization-background", "storage": "ms-settings:storagesense",
    "mouse": "ms-settings:mousetouchpad", "keyboard": "ms-settings:typing", "date": "ms-settings:dateandtime",
    "time": "ms-settings:dateandtime", "language": "ms-settings:regionlanguage", "accounts": "ms-settings:yourinfo",
    "default apps": "ms-settings:defaultapps", "night light": "ms-settings:nightlight", "vpn": "ms-settings:network-vpn",
    "lock screen": "ms-settings:lockscreen", "sleep": "ms-settings:powersleep", "resolution": "ms-settings:display",
    "brightness": "ms-settings:display", "volume": "ms-settings:sound", "focus assist": "ms-settings:quiethours",
}

MEDIA_REPLIES = {"play_pause": "Toggled play/pause.", "next": "Skipped to the next track.",
                 "previous": "Went back a track.", "stop": "Stopped playback."}
VK_MENU = 0x12
DWMWA_CLOAKED = 14


def _com_init() -> None:
    """COM is per thread: commands run on worker threads, where pycaw/WMI/Shell need it initialised."""
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass


def _is_windows() -> bool:
    return os.name == "nt"


class WindowsControl:
    def __init__(self):
        self.available = _is_windows()

    # ── Keys / media ─────────────────────────────────────────────────────────

    def _tap(self, vk: int, times: int = 1) -> None:
        user32 = ctypes.windll.user32
        for _ in range(max(1, times)):
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.02)

    def media(self, action: str) -> str:
        """play_pause | next | previous | stop"""
        if not self.available:
            return "Media keys are only available on Windows."
        action = {"play": "play_pause", "pause": "play_pause", "resume": "play_pause", "toggle": "play_pause",
                  "skip": "next", "next": "next", "previous": "previous", "back": "previous",
                  "stop": "stop"}.get(action, action)
        if action not in MEDIA_REPLIES:
            return f"Unknown media action '{action}'."
        self._tap(VK[action])
        return MEDIA_REPLIES[action]

    def now_playing(self) -> str:
        """What's playing, via the Windows media session (needs the optional 'winsdk' package)."""
        try:
            import asyncio
            from winsdk.windows.media.control import \
                GlobalSystemMediaTransportControlsSessionManager as Manager
        except Exception:
            return "I can't read the media session (install the optional 'winsdk' package)."

        async def query():
            manager = await Manager.request_async()
            session = manager.get_current_session()
            if session is None:
                return None
            props = await session.try_get_media_properties_async()
            status = session.get_playback_info().playback_status
            return props.title, props.artist, int(status)

        try:
            info = asyncio.run(query())
        except Exception as exc:
            return f"Couldn't read the media session: {exc}"
        if not info:
            return "Nothing is playing right now."
        title, artist, status = info
        state = {4: "Playing", 5: "Paused", 3: "Stopped"}.get(status, "Loaded")
        return f"{state}: {title}" + (f" by {artist}" if artist else "")

    def is_playing(self) -> bool:
        return self.now_playing().startswith("Playing")

    # ── Volume ───────────────────────────────────────────────────────────────

    def _endpoint(self):
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        _com_init()
        speakers = AudioUtilities.GetSpeakers()
        endpoint = getattr(speakers, "EndpointVolume", None)
        if endpoint is None:
            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            endpoint = cast(interface, POINTER(IAudioEndpointVolume))
        return endpoint

    def get_volume(self) -> str:
        try:
            ep = self._endpoint()
            level = round(ep.GetMasterVolumeLevelScalar() * 100)
            return f"Volume is {level}%" + (" (muted)" if ep.GetMute() else "") + "."
        except Exception as exc:
            return f"Couldn't read the volume: {exc}"

    def set_volume(self, level: int) -> str:
        level = max(0, min(100, int(level)))
        try:
            ep = self._endpoint()
            ep.SetMute(0, None)
            ep.SetMasterVolumeLevelScalar(level / 100.0, None)
            return f"Volume set to {level}%."
        except Exception as exc:
            log.info("pycaw volume failed (%s); using volume keys", exc)
            if not self.available:
                return f"Couldn't set the volume: {exc}"
            self._tap(VK["volume_down"], 50)
            self._tap(VK["volume_up"], level // 2)
            return f"Volume set to about {level}%."

    def change_volume(self, delta: int) -> str:
        try:
            ep = self._endpoint()
            current = round(ep.GetMasterVolumeLevelScalar() * 100)
            return self.set_volume(current + int(delta))
        except Exception:
            if not self.available:
                return "Volume control is only available on Windows."
            self._tap(VK["volume_up" if delta > 0 else "volume_down"], max(1, abs(int(delta)) // 2))
            return f"Volume turned {'up' if delta > 0 else 'down'}."

    def mute(self, on: bool = True) -> str:
        try:
            self._endpoint().SetMute(1 if on else 0, None)
            return "Muted." if on else "Unmuted."
        except Exception:
            if not self.available:
                return "Volume control is only available on Windows."
            self._tap(VK["volume_mute"])
            return "Toggled mute."

    # ── Power ────────────────────────────────────────────────────────────────

    def lock(self) -> str:
        if not self.available:
            return "Locking is only available on Windows."
        if not ctypes.windll.user32.LockWorkStation():
            return "Windows refused to lock the PC (locking may be disabled by policy)."
        return "Locked the PC."

    def sleep(self) -> str:
        if not self.available:
            return "Sleep is only available on Windows."
        # SetSuspendState(hibernate=False, force=False, wakeup_events_disabled=False)
        if not ctypes.windll.powrprof.SetSuspendState(0, 0, 0):
            return "Windows refused to go to sleep."
        return "Putting the PC to sleep."

    def shutdown(self, restart: bool = False, delay: int = 30) -> str:
        if not self.available:
            return "Power control is only available on Windows."
        flag = "/r" if restart else "/s"
        try:
            result = subprocess.run(["shutdown", flag, "/t", str(int(delay))], capture_output=True, text=True)
        except Exception as exc:
            return f"Couldn't {'restart' if restart else 'shut down'}: {exc}"
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return (f"Windows refused to {'restart' if restart else 'shut down'} (code {result.returncode})"
                    + (f": {detail}" if detail else "."))
        return (f"{'Restarting' if restart else 'Shutting down'} in {delay} seconds. "
                f"Say 'cancel shutdown' to stop it.")

    def cancel_shutdown(self) -> str:
        if not self.available:
            return "Power control is only available on Windows."
        try:
            result = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
        except Exception as exc:
            return f"Couldn't cancel the shutdown: {exc}"
        return "Cancelled the pending shutdown." if result.returncode == 0 else "There was no shutdown to cancel."

    def sign_out(self) -> str:
        if not self.available:
            return "Sign out is only available on Windows."
        try:
            result = subprocess.run(["shutdown", "/l"], capture_output=True, text=True)
        except Exception as exc:
            return f"Couldn't sign out: {exc}"
        if result.returncode != 0:
            return f"Windows refused to sign out (code {result.returncode})."
        return "Signing out."

    # ── Brightness ───────────────────────────────────────────────────────────

    def set_brightness(self, level: int) -> str:
        level = max(0, min(100, int(level)))
        try:
            import wmi
            _com_init()
            methods = wmi.WMI(namespace="wmi").WmiMonitorBrightnessMethods()
            if not methods:
                return "This display doesn't support software brightness control."
            # Named arguments: WmiSetBrightness(Timeout, Brightness) — never rely on positional order.
            methods[0].WmiSetBrightness(Brightness=level, Timeout=0)
            return f"Brightness set to {level}%."
        except Exception as exc:
            return f"Couldn't change brightness: {exc}"

    def get_brightness(self):
        """Current brightness 0-100, or None when it can't be read (external monitor, no WMI)."""
        try:
            import wmi
            _com_init()
            info = wmi.WMI(namespace="wmi").WmiMonitorBrightness()
            return int(info[0].CurrentBrightness) if info else None
        except Exception:
            return None

    def change_brightness(self, delta: int) -> str:
        current = self.get_brightness()
        if current is None:
            return "Couldn't read the current brightness; tell me a level, e.g. 'brightness 60'."
        return self.set_brightness(current + int(delta))

    # ── Windows ──────────────────────────────────────────────────────────────

    def _is_cloaked(self, hwnd) -> bool:
        """Suspended UWP / virtual-desktop windows are 'visible' but cloaked (invisible to the user)."""
        if not self.available:
            return False
        try:
            from ctypes import wintypes
            cloaked = ctypes.c_int(0)
            hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED,
                                                            ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            return hr == 0 and cloaked.value != 0
        except Exception:
            return False

    def _is_own_window(self, hwnd) -> bool:
        """JARVIS's own windows (GUI or the console it runs in): closing them would kill JARVIS."""
        if not self.available:
            return False
        try:
            from ctypes import wintypes
            if hwnd and hwnd == ctypes.windll.kernel32.GetConsoleWindow():
                return True
            pid = wintypes.DWORD(0)
            ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
            return pid.value == os.getpid()
        except Exception:
            return False

    def _top_windows(self):
        import win32gui
        found = []

        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd).strip() \
                    and not self._is_cloaked(hwnd):
                if win32gui.GetParent(hwnd) == 0 and win32gui.GetClassName(hwnd) not in (
                        "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                    found.append((hwnd, win32gui.GetWindowText(hwnd)))
            return True

        win32gui.EnumWindows(cb, None)
        return found

    def list_windows(self) -> str:
        try:
            wins = self._top_windows()
        except Exception as exc:
            return f"Couldn't list windows: {exc}"
        if not wins:
            return "No open windows."
        return "Open windows:\n" + "\n".join(f"{i}. {t}" for i, (_, t) in enumerate(wins[:25], 1))

    def _find(self, title: str):
        needle = (title or "").strip().lower()
        wins = self._top_windows()
        exact = [w for w in wins if w[1].lower() == needle]
        return exact or [w for w in wins if needle and needle in w[1].lower()]

    def window_action(self, title: str, action: str) -> str:
        """action: focus | minimize | maximize | restore | close"""
        try:
            import win32con
            import win32gui
            matches = self._find(title)
        except Exception as exc:
            return f"Window control unavailable: {exc}"
        if not matches:
            return f"No window matching '{title}'."
        hwnd, name = matches[0]
        try:
            if action == "focus":
                # SW_RESTORE would un-maximize a maximized window; only restore minimized ones.
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE if win32gui.IsIconic(hwnd) else win32con.SW_SHOW)
                self._force_foreground(hwnd)
            elif action == "minimize":
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            elif action == "maximize":
                win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
            elif action == "restore":
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            elif action == "close":
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            else:
                return f"Unknown window action '{action}'."
        except Exception as exc:
            return f"Couldn't {action} '{name}': {exc}"
        past = {"focus": "Switched to", "minimize": "Minimized", "maximize": "Maximized",
                "restore": "Restored", "close": "Asked to close"}[action]
        return f"{past} '{name}'."

    def _force_foreground(self, hwnd) -> None:
        """SetForegroundWindow fails from a background process (voice/tray) unless the foreground
        lock is released; a synthetic ALT tap is the documented-safe way to get the right to do it."""
        import win32gui
        try:
            win32gui.SetForegroundWindow(hwnd)
            return
        except Exception:
            if not self.available:
                raise
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        win32gui.SetForegroundWindow(hwnd)

    def show_desktop(self) -> str:
        """Minimize everything (Win+M equivalent). Idempotent, unlike ToggleDesktop / Win+D,
        which would bring every window back when the desktop is already showing."""
        try:
            import win32com.client
            _com_init()
            win32com.client.Dispatch("Shell.Application").MinimizeAll()
            return "Minimized all windows."
        except Exception:
            if not self.available:
                return "Only available on Windows."
            user32 = ctypes.windll.user32
            user32.keybd_event(0x5B, 0, 0, 0)            # LWIN down
            user32.keybd_event(0x4D, 0, 0, 0)            # M
            user32.keybd_event(0x4D, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x5B, 0, KEYEVENTF_KEYUP, 0)
            return "Minimized all windows."

    def close_all_windows(self, keep=("jarvis",)) -> str:
        """Politely ask every app window to close (apps can still prompt to save)."""
        try:
            import win32con
            import win32gui
            wins = self._top_windows()
        except Exception as exc:
            return f"Window control unavailable: {exc}"
        closed = 0
        for hwnd, title in wins:
            if any(k in title.lower() for k in keep) or self._is_own_window(hwnd):
                continue
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                closed += 1
            except Exception:
                continue
        return f"Asked {closed} window(s) to close. Apps with unsaved work may ask you first."

    # ── Settings / clipboard / typing ────────────────────────────────────────

    def open_settings(self, page: str = "") -> str:
        page = (page or "").lower().strip()
        target, matched = "ms-settings:", ""
        for key in sorted(SETTINGS_PAGES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(key)}\b", page):
                target, matched = SETTINGS_PAGES[key], key
                break
        page = matched          # an unknown page opens the Settings home — don't claim otherwise
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return f"Opened {page + ' ' if page else ''}settings."
        except Exception as exc:
            return f"Couldn't open settings: {exc}"

    @staticmethod
    def _open_clipboard(win32clipboard, attempts: int = 10):
        """Another app may hold the clipboard for a moment; retry briefly. Caller holds clipboard.LOCK."""
        clipboard.open_clipboard(win32clipboard, attempts)

    def _read_clipboard_text(self):
        """Raw clipboard text, '' when empty/non-text, None when it can't be read."""
        try:
            import win32clipboard
            with clipboard.LOCK:
                self._open_clipboard(win32clipboard)
                try:
                    try:
                        return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or ""
                    except Exception:
                        return ""
                finally:
                    win32clipboard.CloseClipboard()
        except Exception:
            return None

    def get_clipboard(self) -> str:
        try:
            import win32clipboard
            with clipboard.LOCK:
                self._open_clipboard(win32clipboard)
                try:
                    text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                except Exception:
                    text = ""
                finally:
                    win32clipboard.CloseClipboard()
            return text or "(The clipboard is empty.)"
        except Exception as exc:
            return f"Clipboard read error: {exc}"

    def set_clipboard(self, text: str, private: bool = False) -> str:
        """``private`` marks the copy so clipboard history (ours and Win+V) skips it."""
        try:
            import win32clipboard
            with clipboard.LOCK:
                self._open_clipboard(win32clipboard)
                try:
                    win32clipboard.EmptyClipboard()
                    if text:
                        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
                        if private:
                            clipboard.mark_private(win32clipboard)
                finally:
                    win32clipboard.CloseClipboard()
            return "Copied to the clipboard." if text else "Cleared the clipboard."
        except Exception as exc:
            return f"Clipboard write error: {exc}"

    def type_text(self, text: str) -> str:
        """Type any Unicode text at the cursor by pasting (UC 6.3), restoring the clipboard after.

        The user's clipboard text comes back afterwards (or the clipboard is
        emptied if it was empty), so typed text — possibly a password — isn't
        left behind. Non-text clipboard content (images, files) can't be kept.
        """
        if not self.available:
            return "Typing is only available on Windows."
        previous = self._read_clipboard_text()
        result = self.set_clipboard(text, private=True)
        if not result.startswith("Copied"):
            return result
        time.sleep(0.15)
        user32 = ctypes.windll.user32
        user32.keybd_event(0x11, 0, 0, 0)                # CTRL
        user32.keybd_event(0x56, 0, 0, 0)                # V
        user32.keybd_event(0x56, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.6)                                  # let slow apps finish reading the paste
        if previous is not None:
            self.set_clipboard(previous)
        return f"Typed {len(text)} character(s)."

    # ── Display resolution ───────────────────────────────────────────────────

    RESOLUTION_NAMES = {"480p": (854, 480), "720p": (1280, 720), "hd": (1280, 720), "768p": (1366, 768),
                        "900p": (1600, 900), "1080p": (1920, 1080), "full hd": (1920, 1080), "fhd": (1920, 1080),
                        "1440p": (2560, 1440), "2k": (2560, 1440), "qhd": (2560, 1440), "4k": (3840, 2160),
                        "2160p": (3840, 2160), "uhd": (3840, 2160)}

    @classmethod
    def parse_resolution(cls, text: str):
        """'720p', '1280x720', '1280 by 720', 'full hd' → (1280, 720) or None."""
        low = (text or "").lower()
        m = re.search(r"(\d{3,4})\s*(?:x|×|by|\*)\s*(\d{3,4})", low)
        if m:
            return int(m.group(1)), int(m.group(2))
        for name in sorted(cls.RESOLUTION_NAMES, key=len, reverse=True):
            if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", low):
                return cls.RESOLUTION_NAMES[name]
        m = re.search(r"(?<![\w.])(480|720|768|900|1080|1440|2160)(?![\w.])", low)   # "resolution to 1080"
        if m:
            return cls.RESOLUTION_NAMES[m.group(1) + "p"]
        return None

    def _modes(self):
        import win32api
        modes, i = set(), 0
        while True:
            try:
                dm = win32api.EnumDisplaySettings(None, i)
            except Exception:
                break
            modes.add((dm.PelsWidth, dm.PelsHeight))
            i += 1
        return modes

    def get_resolution(self):
        import win32api
        import win32con
        dm = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
        return dm.PelsWidth, dm.PelsHeight

    def set_resolution(self, width: int, height: int) -> str:
        """Change the primary display mode for this session (not saved; a reboot restores it)."""
        if not self.available:
            return "Changing resolution is only available on Windows."
        try:
            import win32api
            import win32con
            current = self.get_resolution()
            if current == (width, height):
                return f"The display is already at {width}×{height}."
            modes = self._modes()
            if (width, height) not in modes:
                common = sorted(m for m in modes if m[0] >= 800)[-6:]
                return (f"Your display doesn't support {width}×{height}. Supported modes include: "
                        + ", ".join(f"{w}×{h}" for w, h in common) + ".")
            dm = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
            dm.PelsWidth, dm.PelsHeight = width, height
            dm.Fields = win32con.DM_PELSWIDTH | win32con.DM_PELSHEIGHT
            result = win32api.ChangeDisplaySettings(dm, 0)
            if result != win32con.DISP_CHANGE_SUCCESSFUL:
                return f"Windows refused the resolution change (code {result})."
            self._previous_resolution = current
            return f"Resolution changed from {current[0]}×{current[1]} to {width}×{height}."
        except Exception as exc:
            return f"Couldn't change the resolution: {exc}"

    def restore_resolution(self) -> str:
        """Return to the mode saved in the registry (what Windows had before JARVIS changed it)."""
        if not self.available:
            return "Only available on Windows."
        try:
            import win32api
            import win32con
            result = win32api.ChangeDisplaySettings(None, 0)
            if result != win32con.DISP_CHANGE_SUCCESSFUL:
                return f"Windows refused to restore the resolution (code {result})."
            self._previous_resolution = None
            w, h = self.get_resolution()
            return f"Resolution restored to {w}×{h}."
        except Exception as exc:
            return f"Couldn't restore the resolution: {exc}"

    # ── Playback readiness ──────────────────────────────────────────────────

    def wait_for_playback(self, timeout: float = 12.0) -> bool:
        """Wait until some media session reports Playing (needs winsdk); False on timeout/unknown."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.now_playing()
            if state.startswith("Playing"):
                return True
            if state.startswith("I can't read"):
                return False      # no winsdk: caller falls back to a fixed delay
            time.sleep(0.7)
        return False
