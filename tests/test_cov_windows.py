"""Windows control skill + control/media/apps handlers, with the Win32/COM boundary mocked.

Every Windows module (win32gui, win32api, win32con, win32clipboard, win32com, pycaw, comtypes,
wmi, winsdk) is replaced in ``sys.modules`` for the duration of a test, and ``ctypes.windll`` is a
Mock, so these tests assert the exact API calls and arguments without needing Windows.
"""
import ctypes
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from core.tools import ToolRegistry
from handlers.apps import AppsHandler
from handlers.control import ControlHandler, _power_request
from handlers.media import MediaHandler
from skills import windows_control as wc_mod
from skills.windows_control import KEYEVENTF_KEYUP, VK, WindowsControl

WIN32CON = SimpleNamespace(SW_RESTORE=9, SW_SHOW=5, SW_MINIMIZE=6, SW_MAXIMIZE=3, WM_CLOSE=0x0010,
                           ENUM_CURRENT_SETTINGS=-1, DM_PELSWIDTH=0x80000, DM_PELSHEIGHT=0x100000,
                           DISP_CHANGE_SUCCESSFUL=0)


def fake_modules(**extra):
    mods = {"win32con": WIN32CON, "win32gui": Mock(), "win32api": Mock(),
            "win32clipboard": Mock(CF_UNICODETEXT=13), "pythoncom": Mock(), "comtypes": Mock(CLSCTX_ALL=23)}
    mods.update(extra)
    return mods


class WinTestCase(unittest.TestCase):
    """A WindowsControl that believes it is on Windows, with windll and sleep mocked."""

    def setUp(self):
        self.mods = fake_modules()
        self.windll = MagicMock()
        for p in (patch.dict(sys.modules, self.mods),
                  patch.object(ctypes, "windll", self.windll, create=True),
                  patch("skills.windows_control.time.sleep")):
            p.start()
            self.addCleanup(p.stop)
        self.w = WindowsControl()
        self.w.available = True
        self.user32 = self.windll.user32

    def keys(self):
        return [c.args for c in self.user32.keybd_event.call_args_list]


# ── media keys ────────────────────────────────────────────────────────────────

class MediaKeyTests(WinTestCase):
    def test_play_pause_sends_down_then_up(self):
        self.assertEqual(self.w.media("pause"), "Toggled play/pause.")
        self.assertEqual(self.keys(), [(0xB3, 0, 0, 0), (0xB3, 0, KEYEVENTF_KEYUP, 0)])

    def test_aliases(self):
        for alias, vk in (("skip", 0xB0), ("back", 0xB1), ("stop", 0xB2), ("resume", 0xB3)):
            self.user32.reset_mock()
            self.w.media(alias)
            self.assertEqual(self.keys()[0][0], vk)

    def test_non_media_vk_name_does_not_crash(self):
        # Regression: "volume_mute" is in VK but had no reply text -> KeyError.
        self.assertIn("Unknown media action", self.w.media("volume_mute"))
        self.assertIn("Unknown media action", self.w.media("rewind"))
        self.user32.keybd_event.assert_not_called()

    def test_not_windows(self):
        self.w.available = False
        self.assertIn("only available on Windows", self.w.media("next"))

    def test_tap_times(self):
        self.w._tap(VK["volume_up"], 3)
        self.assertEqual(self.user32.keybd_event.call_count, 6)


class NowPlayingTests(WinTestCase):
    def _winsdk(self, session):
        manager = Mock()
        manager.get_current_session.return_value = session

        async def request_async():
            return manager

        control = types.ModuleType("winsdk.windows.media.control")
        control.GlobalSystemMediaTransportControlsSessionManager = SimpleNamespace(request_async=request_async)
        return {"winsdk": types.ModuleType("winsdk"), "winsdk.windows": types.ModuleType("winsdk.windows"),
                "winsdk.windows.media": types.ModuleType("winsdk.windows.media"),
                "winsdk.windows.media.control": control}

    def _session(self, title, artist, status):
        session = Mock()

        async def props():
            return SimpleNamespace(title=title, artist=artist)

        session.try_get_media_properties_async = props
        session.get_playback_info.return_value = SimpleNamespace(playback_status=status)
        return session

    def test_playing(self):
        with patch.dict(sys.modules, self._winsdk(self._session("Song", "Band", 4))):
            self.assertEqual(self.w.now_playing(), "Playing: Song by Band")
            self.assertTrue(self.w.is_playing())
            self.assertTrue(self.w.wait_for_playback(1))

    def test_paused_no_artist(self):
        with patch.dict(sys.modules, self._winsdk(self._session("Pod", "", 5))):
            self.assertEqual(self.w.now_playing(), "Paused: Pod")

    def test_no_session(self):
        with patch.dict(sys.modules, self._winsdk(None)):
            self.assertEqual(self.w.now_playing(), "Nothing is playing right now.")

    def test_query_error(self):
        session = self._session("x", "y", 4)
        session.get_playback_info.side_effect = OSError("rpc down")
        with patch.dict(sys.modules, self._winsdk(session)):
            self.assertIn("Couldn't read the media session: rpc down", self.w.now_playing())

    def test_no_winsdk(self):
        with patch.dict(sys.modules, {"winsdk": None}):
            self.assertIn("winsdk", self.w.now_playing())
            self.assertFalse(self.w.wait_for_playback(5))

    def test_wait_for_playback_times_out(self):
        with patch.object(self.w, "now_playing", return_value="Paused: x"), \
                patch("skills.windows_control.time.time", side_effect=[0, 0, 100]):
            self.assertFalse(self.w.wait_for_playback(1))


# ── volume (pycaw) ────────────────────────────────────────────────────────────

class VolumeTests(WinTestCase):
    def setUp(self):
        super().setUp()
        self.ep = Mock()
        self.ep.GetMasterVolumeLevelScalar.return_value = 0.5
        self.ep.GetMute.return_value = 0
        self.utils = Mock()
        self.utils.GetSpeakers.return_value = SimpleNamespace(EndpointVolume=self.ep)
        pycaw = types.ModuleType("pycaw.pycaw")
        pycaw.AudioUtilities = self.utils
        pycaw.IAudioEndpointVolume = SimpleNamespace(_iid_="IID")
        p = patch.dict(sys.modules, {"pycaw": types.ModuleType("pycaw"), "pycaw.pycaw": pycaw})
        p.start()
        self.addCleanup(p.stop)

    def test_set_volume_scalar_and_unmute(self):
        self.assertEqual(self.w.set_volume(40), "Volume set to 40%.")
        self.ep.SetMute.assert_called_once_with(0, None)
        self.ep.SetMasterVolumeLevelScalar.assert_called_once_with(0.4, None)
        self.mods["pythoncom"].CoInitialize.assert_called()      # COM initialised on this thread

    def test_set_volume_clamps(self):
        self.w.set_volume(250)
        self.ep.SetMasterVolumeLevelScalar.assert_called_with(1.0, None)
        self.w.set_volume(-5)
        self.ep.SetMasterVolumeLevelScalar.assert_called_with(0.0, None)

    def test_get_volume(self):
        self.assertEqual(self.w.get_volume(), "Volume is 50%.")
        self.ep.GetMute.return_value = 1
        self.assertEqual(self.w.get_volume(), "Volume is 50% (muted).")

    def test_change_volume_relative(self):
        self.assertEqual(self.w.change_volume(+20), "Volume set to 70%.")
        self.ep.SetMasterVolumeLevelScalar.assert_called_with(0.7, None)

    def test_mute_unmute(self):
        self.assertEqual(self.w.mute(True), "Muted.")
        self.ep.SetMute.assert_called_with(1, None)
        self.assertEqual(self.w.mute(False), "Unmuted.")
        self.ep.SetMute.assert_called_with(0, None)

    def test_old_pycaw_activate_path(self):
        speakers = Mock(spec=["Activate"])
        self.utils.GetSpeakers.return_value = speakers
        with patch("ctypes.cast", return_value=self.ep) as cast, patch("ctypes.POINTER", side_effect=lambda t: t):
            self.assertEqual(self.w.set_volume(10), "Volume set to 10%.")
        speakers.Activate.assert_called_once_with("IID", 23, None)
        cast.assert_called_once()

    def test_pycaw_failure_falls_back_to_keys(self):
        self.utils.GetSpeakers.side_effect = OSError("CO_E_NOTINITIALIZED")
        self.assertEqual(self.w.set_volume(40), "Volume set to about 40%.")
        vks = [a[0] for a in self.keys() if a[2] == 0]
        self.assertEqual(vks.count(VK["volume_down"]), 50)
        self.assertEqual(vks.count(VK["volume_up"]), 20)
        self.user32.reset_mock()
        self.assertEqual(self.w.change_volume(-10), "Volume turned down.")
        self.assertEqual([a[0] for a in self.keys() if a[2] == 0], [VK["volume_down"]] * 5)
        self.user32.reset_mock()
        self.assertEqual(self.w.mute(), "Toggled mute.")
        self.assertEqual(self.keys()[0][0], VK["volume_mute"])

    def test_pycaw_failure_off_windows(self):
        self.utils.GetSpeakers.side_effect = OSError("nope")
        self.w.available = False
        self.assertIn("Couldn't set the volume", self.w.set_volume(40))
        self.assertIn("only available on Windows", self.w.change_volume(10))
        self.assertIn("only available on Windows", self.w.mute())
        self.assertIn("Couldn't read the volume", self.w.get_volume())


# ── power ────────────────────────────────────────────────────────────────────

class PowerTests(WinTestCase):
    def test_lock(self):
        self.user32.LockWorkStation.return_value = 1
        self.assertEqual(self.w.lock(), "Locked the PC.")
        self.user32.LockWorkStation.return_value = 0
        self.assertIn("refused", self.w.lock())

    def test_sleep(self):
        self.windll.powrprof.SetSuspendState.return_value = 1
        self.assertEqual(self.w.sleep(), "Putting the PC to sleep.")
        self.windll.powrprof.SetSuspendState.assert_called_with(0, 0, 0)
        self.windll.powrprof.SetSuspendState.return_value = 0
        self.assertIn("refused", self.w.sleep())

    def test_shutdown_and_restart_commands(self):
        with patch("skills.windows_control.subprocess.run", return_value=Mock(returncode=0)) as run:
            self.assertIn("Shutting down in 30 seconds", self.w.shutdown())
            self.assertEqual(run.call_args.args[0], ["shutdown", "/s", "/t", "30"])
            self.assertIn("Restarting in 5 seconds", self.w.shutdown(restart=True, delay=5))
            self.assertEqual(run.call_args.args[0], ["shutdown", "/r", "/t", "5"])

    def test_shutdown_error_code_reported(self):
        result = Mock(returncode=1190, stderr="A system shutdown has already been scheduled.", stdout="")
        with patch("skills.windows_control.subprocess.run", return_value=result):
            reply = self.w.shutdown()
        self.assertIn("1190", reply)
        self.assertIn("already been scheduled", reply)
        with patch("skills.windows_control.subprocess.run", side_effect=FileNotFoundError("shutdown")):
            self.assertIn("Couldn't shut down", self.w.shutdown())

    def test_cancel_shutdown(self):
        with patch("skills.windows_control.subprocess.run", return_value=Mock(returncode=0)) as run:
            self.assertIn("Cancelled", self.w.cancel_shutdown())
            self.assertEqual(run.call_args.args[0], ["shutdown", "/a"])
        with patch("skills.windows_control.subprocess.run", return_value=Mock(returncode=1116)):
            self.assertIn("no shutdown", self.w.cancel_shutdown())
        with patch("skills.windows_control.subprocess.run", side_effect=OSError("x")):
            self.assertIn("Couldn't cancel", self.w.cancel_shutdown())

    def test_sign_out(self):
        with patch("skills.windows_control.subprocess.run", return_value=Mock(returncode=0)) as run:
            self.assertEqual(self.w.sign_out(), "Signing out.")
            self.assertEqual(run.call_args.args[0], ["shutdown", "/l"])
        with patch("skills.windows_control.subprocess.run", return_value=Mock(returncode=5)):
            self.assertIn("refused", self.w.sign_out())
        with patch("skills.windows_control.subprocess.run", side_effect=OSError("x")):
            self.assertIn("Couldn't sign out", self.w.sign_out())

    def test_all_power_off_windows(self):
        self.w.available = False
        with patch("skills.windows_control.subprocess.run") as run:
            for fn in (self.w.lock, self.w.sleep, self.w.shutdown, self.w.cancel_shutdown, self.w.sign_out,
                       lambda: self.w.type_text("x"),
                       lambda: self.w.set_resolution(1, 1), self.w.restore_resolution):
                self.assertIn("Windows", fn())
        run.assert_not_called()


# ── brightness (WMI) ─────────────────────────────────────────────────────────

class BrightnessTests(WinTestCase):
    def setUp(self):
        super().setUp()
        self.method = Mock()
        self.conn = Mock()
        self.conn.WmiMonitorBrightnessMethods.return_value = [self.method]
        self.conn.WmiMonitorBrightness.return_value = [SimpleNamespace(CurrentBrightness=40)]
        self.wmi = Mock()
        self.wmi.WMI.return_value = self.conn
        p = patch.dict(sys.modules, {"wmi": self.wmi})
        p.start()
        self.addCleanup(p.stop)

    def test_set_uses_named_arguments(self):
        self.assertEqual(self.w.set_brightness(55), "Brightness set to 55%.")
        self.wmi.WMI.assert_called_with(namespace="wmi")
        self.method.WmiSetBrightness.assert_called_once_with(Brightness=55, Timeout=0)

    def test_clamps(self):
        self.w.set_brightness(900)
        self.method.WmiSetBrightness.assert_called_with(Brightness=100, Timeout=0)

    def test_unsupported_display(self):
        self.conn.WmiMonitorBrightnessMethods.return_value = []
        self.assertIn("doesn't support", self.w.set_brightness(50))

    def test_wmi_error(self):
        self.wmi.WMI.side_effect = Exception("x_wmi: not supported")
        self.assertIn("Couldn't change brightness", self.w.set_brightness(50))
        self.assertIsNone(self.w.get_brightness())
        self.assertIn("Couldn't read the current brightness", self.w.change_brightness(10))

    def test_get_and_change(self):
        self.assertEqual(self.w.get_brightness(), 40)
        self.assertEqual(self.w.change_brightness(-15), "Brightness set to 25%.")
        self.conn.WmiMonitorBrightness.return_value = []
        self.assertIsNone(self.w.get_brightness())


# ── windows (win32gui) ───────────────────────────────────────────────────────

class WindowTests(WinTestCase):
    WINDOWS = {1: ("Inbox - Outlook", "rctrl"), 2: ("Chrome - Google Chrome", "Chrome_WidgetWin_1"),
               3: ("", "x"), 4: ("Program Manager", "Progman"), 5: ("JARVIS", "Tk"), 6: ("Settings", "AppFrame"),
               7: ("Child", "c")}

    def setUp(self):
        super().setUp()
        g = self.gui = self.mods["win32gui"]
        g.EnumWindows.side_effect = lambda cb, extra: [cb(h, extra) for h in self.WINDOWS]
        g.IsWindowVisible.return_value = True
        g.GetWindowText.side_effect = lambda h: self.WINDOWS[h][0]
        g.GetClassName.side_effect = lambda h: self.WINDOWS[h][1]
        g.GetParent.side_effect = lambda h: 99 if h == 7 else 0
        g.IsIconic.return_value = False
        self.windll.kernel32.GetConsoleWindow.return_value = 0
        self.windll.user32.GetWindowThreadProcessId.return_value = 1

        def cloak(hwnd, attr, ref, size):
            ref._obj.value = 1 if hwnd.value == 6 else 0     # the suspended UWP "Settings" window
            return 0

        self.windll.dwmapi.DwmGetWindowAttribute.side_effect = cloak

    def test_top_windows_filters_shell_children_cloaked_and_untitled(self):
        self.assertEqual([h for h, _ in self.w._top_windows()], [1, 2, 5])
        self.assertEqual(self.windll.dwmapi.DwmGetWindowAttribute.call_args.args[1], 14)   # DWMWA_CLOAKED

    def test_list_windows(self):
        self.assertEqual(self.w.list_windows(), "Open windows:\n1. Inbox - Outlook\n2. Chrome - Google Chrome\n3. JARVIS")
        self.gui.EnumWindows.side_effect = lambda cb, extra: None
        self.assertEqual(self.w.list_windows(), "No open windows.")
        self.gui.EnumWindows.side_effect = RuntimeError("no desktop")
        self.assertIn("Couldn't list windows", self.w.list_windows())

    def test_focus_does_not_unmaximize(self):
        self.assertEqual(self.w.window_action("chrome", "focus"), "Switched to 'Chrome - Google Chrome'.")
        self.gui.ShowWindow.assert_called_once_with(2, WIN32CON.SW_SHOW)
        self.gui.SetForegroundWindow.assert_called_once_with(2)

    def test_focus_restores_minimized(self):
        self.gui.IsIconic.return_value = True
        self.w.window_action("outlook", "focus")
        self.gui.ShowWindow.assert_called_once_with(1, WIN32CON.SW_RESTORE)

    def test_focus_retries_after_foreground_lock(self):
        self.gui.SetForegroundWindow.side_effect = [Exception("(0, 'SetForegroundWindow')"), None]
        self.assertIn("Switched to", self.w.window_action("chrome", "focus"))
        self.assertEqual(self.keys(), [(0x12, 0, 0, 0), (0x12, 0, KEYEVENTF_KEYUP, 0)])   # ALT tap
        self.assertEqual(self.gui.SetForegroundWindow.call_count, 2)

    def test_focus_fails_cleanly(self):
        self.gui.SetForegroundWindow.side_effect = Exception("denied")
        self.assertIn("Couldn't focus 'Chrome - Google Chrome': denied", self.w.window_action("chrome", "focus"))

    def test_other_actions(self):
        for action, sw, past in (("minimize", 6, "Minimized"), ("maximize", 3, "Maximized"),
                                 ("restore", 9, "Restored")):
            self.gui.ShowWindow.reset_mock()
            self.assertEqual(self.w.window_action("outlook", action), f"{past} 'Inbox - Outlook'.")
            self.gui.ShowWindow.assert_called_once_with(1, sw)
        self.assertIn("Asked to close", self.w.window_action("Inbox - Outlook", "close"))
        self.gui.PostMessage.assert_called_once_with(1, 0x0010, 0, 0)
        self.assertIn("Unknown window action", self.w.window_action("outlook", "explode"))
        self.assertIn("No window matching 'notepad'", self.w.window_action("notepad", "focus"))

    def test_window_action_unavailable(self):
        self.gui.EnumWindows.side_effect = RuntimeError("stub")
        self.assertIn("Window control unavailable", self.w.window_action("x", "focus"))
        self.assertIn("Window control unavailable", self.w.close_all_windows())

    def test_close_all_skips_jarvis_and_own_process(self):
        self.WINDOWS = {**self.WINDOWS, 8: ("C:\\python.exe", "ConsoleWindowClass")}
        self.windll.kernel32.GetConsoleWindow.return_value = 8
        self.gui.PostMessage.side_effect = lambda h, *a: (_ for _ in ()).throw(Exception("gone")) if h == 1 else None
        reply = self.w.close_all_windows()
        self.assertEqual([c.args[0] for c in self.gui.PostMessage.call_args_list], [1, 2])
        self.assertIn("Asked 1 window(s)", reply)

    def test_own_process_window_detected(self):
        def pid_of(hwnd, ref):
            ref._obj.value = os.getpid() if hwnd.value == 2 else 1

        self.windll.user32.GetWindowThreadProcessId.side_effect = pid_of
        self.assertTrue(self.w._is_own_window(2))
        self.assertFalse(self.w._is_own_window(1))
        self.w.available = False
        self.assertFalse(self.w._is_own_window(2))
        self.assertFalse(self.w._is_cloaked(6))

    def test_show_desktop_minimizes_all(self):
        client = Mock()
        with patch.dict(sys.modules, {"win32com": Mock(client=client), "win32com.client": client}):
            self.assertEqual(self.w.show_desktop(), "Minimized all windows.")
        client.Dispatch.assert_called_once_with("Shell.Application")
        client.Dispatch.return_value.MinimizeAll.assert_called_once_with()
        client.Dispatch.return_value.ToggleDesktop.assert_not_called()

    def test_show_desktop_key_fallback(self):
        client = Mock()
        client.Dispatch.side_effect = Exception("CoInitialize has not been called")
        with patch.dict(sys.modules, {"win32com": Mock(client=client), "win32com.client": client}):
            self.assertEqual(self.w.show_desktop(), "Minimized all windows.")
            self.assertEqual(self.keys(), [(0x5B, 0, 0, 0), (0x4D, 0, 0, 0), (0x4D, 0, 2, 0), (0x5B, 0, 2, 0)])
            self.w.available = False
            self.assertEqual(self.w.show_desktop(), "Only available on Windows.")


# ── settings / clipboard / typing ────────────────────────────────────────────

class SettingsClipboardTests(WinTestCase):
    def test_open_settings_pages(self):
        with patch.object(os, "startfile", create=True) as start:
            self.assertEqual(self.w.open_settings(" bluetooth "), "Opened bluetooth settings.")
            start.assert_called_with("ms-settings:bluetooth")
            self.assertEqual(self.w.open_settings("windows update"), "Opened windows update settings.")
            start.assert_called_with("ms-settings:windowsupdate")
            self.w.open_settings("update")
            start.assert_called_with("ms-settings:windowsupdate")      # not "date"
            self.w.open_settings("lock screen")
            start.assert_called_with("ms-settings:lockscreen")
            self.assertEqual(self.w.open_settings("frobnicator"), "Opened settings.")   # no false claim
            start.assert_called_with("ms-settings:")
            self.assertEqual(self.w.open_settings(), "Opened settings.")
        with patch.object(os, "startfile", side_effect=OSError("no handler"), create=True):
            self.assertIn("Couldn't open settings: no handler", self.w.open_settings("wifi"))

    def test_clipboard_read_write(self):
        cb = self.mods["win32clipboard"]
        cb.GetClipboardData.return_value = "hello"
        self.assertEqual(self.w.get_clipboard(), "hello")
        cb.GetClipboardData.assert_called_with(13)
        cb.CloseClipboard.assert_called()
        cb.GetClipboardData.side_effect = TypeError("no text")
        self.assertEqual(self.w.get_clipboard(), "(The clipboard is empty.)")
        self.assertEqual(self.w.set_clipboard("héllo"), "Copied to the clipboard.")
        cb.EmptyClipboard.assert_called_once_with()
        cb.SetClipboardText.assert_called_once_with("héllo", 13)

    def test_clipboard_errors(self):
        cb = self.mods["win32clipboard"]
        cb.OpenClipboard.side_effect = Exception("Access is denied")
        self.assertIn("Clipboard read error", self.w.get_clipboard())
        self.assertIn("Clipboard write error", self.w.set_clipboard("x"))
        self.assertIn("Clipboard write error", self.w.type_text("x"))
        self.user32.keybd_event.assert_not_called()

    def test_type_text_pastes_and_restores(self):
        cb = self.mods["win32clipboard"]
        cb.GetClipboardData.return_value = "old"
        self.assertEqual(self.w.type_text("नमस्ते"), "Typed 6 character(s).")
        self.assertEqual(self.keys(), [(0x11, 0, 0, 0), (0x56, 0, 0, 0), (0x56, 0, 2, 0), (0x11, 0, 2, 0)])
        self.assertEqual([c.args[0] for c in cb.SetClipboardText.call_args_list], ["नमस्ते", "old"])

    def test_type_text_leaves_an_empty_clipboard_empty(self):
        cb = self.mods["win32clipboard"]
        cb.GetClipboardData.side_effect = TypeError("no text")
        self.w.type_text("my password")
        self.assertEqual([c.args[0] for c in cb.SetClipboardText.call_args_list], ["my password"])
        self.assertEqual(cb.EmptyClipboard.call_count, 2)          # emptied again afterwards

    def test_clipboard_busy_is_retried(self):
        cb = self.mods["win32clipboard"]
        cb.OpenClipboard.side_effect = [Exception("busy"), None]
        cb.GetClipboardData.return_value = "hi"
        self.assertEqual(self.w.get_clipboard(), "hi")


# ── resolution (ChangeDisplaySettings / DEVMODE) ─────────────────────────────

class ResolutionSkillTests(WinTestCase):
    def setUp(self):
        super().setUp()
        self.api = self.mods["win32api"]
        self.current = SimpleNamespace(PelsWidth=1920, PelsHeight=1080, Fields=0)
        modes = [(1920, 1080), (1280, 720), (1280, 720), (800, 600), (640, 480)]

        def enum(device, i):
            if i == -1:
                return self.current
            if i >= len(modes):
                raise Exception("EnumDisplaySettings failed")
            return SimpleNamespace(PelsWidth=modes[i][0], PelsHeight=modes[i][1])

        self.api.EnumDisplaySettings.side_effect = enum
        self.api.ChangeDisplaySettings.return_value = 0

    def test_parse_phrases(self):
        p = WindowsControl.parse_resolution
        self.assertEqual(p("change resolution to 1080p"), (1920, 1080))
        self.assertEqual(p("set resolution to 1080"), (1920, 1080))
        self.assertEqual(p("1366x768"), (1366, 768))
        self.assertEqual(p("1280 × 720"), (1280, 720))
        self.assertEqual(p("4k please"), (3840, 2160))
        self.assertEqual(p("uhd"), (3840, 2160))
        self.assertEqual(p("switch to hd"), (1280, 720))
        self.assertIsNone(p("change the resolution"))
        self.assertIsNone(p("resolution 1.5"))
        self.assertIsNone(p(None))

    def test_change_sets_devmode_fields(self):
        self.assertEqual(self.w.set_resolution(1280, 720), "Resolution changed from 1920×1080 to 1280×720.")
        dm, flags = self.api.ChangeDisplaySettings.call_args.args
        self.assertIs(dm, self.current)
        self.assertEqual((dm.PelsWidth, dm.PelsHeight, dm.Fields, flags), (1280, 720, 0x80000 | 0x100000, 0))
        self.assertEqual(self.w._previous_resolution, (1920, 1080))

    def test_already_and_unsupported(self):
        self.assertIn("already at 1920×1080", self.w.set_resolution(1920, 1080))
        reply = self.w.set_resolution(3840, 2160)
        self.assertIn("doesn't support 3840×2160", reply)
        self.assertIn("1280×720", reply)
        self.assertNotIn("640×480", reply)
        self.api.ChangeDisplaySettings.assert_not_called()

    def test_refused_code(self):
        self.api.ChangeDisplaySettings.return_value = -2          # DISP_CHANGE_BADMODE
        self.assertEqual(self.w.set_resolution(1280, 720), "Windows refused the resolution change (code -2).")

    def test_exception(self):
        self.api.EnumDisplaySettings.side_effect = Exception("no display")
        self.assertIn("Couldn't change the resolution", self.w.set_resolution(1280, 720))

    def test_restore(self):
        self.assertEqual(self.w.restore_resolution(), "Resolution restored to 1920×1080.")
        self.api.ChangeDisplaySettings.assert_called_once_with(None, 0)
        self.api.ChangeDisplaySettings.return_value = 1
        self.assertIn("refused to restore", self.w.restore_resolution())
        self.api.ChangeDisplaySettings.side_effect = Exception("boom")
        self.assertIn("Couldn't restore", self.w.restore_resolution())


# ── handlers ─────────────────────────────────────────────────────────────────

class FakeApp:
    def __init__(self):
        self.windows = Mock()
        self.windows.parse_resolution = WindowsControl.parse_resolution
        self.app_control = Mock()
        self.system_control = Mock()
        self.pending = []
        self.notify = Mock()
        self.handlers = Mock()

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class ControlHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = ControlHandler(self.app)
        self.w = self.app.windows

    def say(self, text):
        return self.h.handle(text, "CONTROL")

    def test_power_requests_need_confirmation(self):
        for text, label in (("restart the pc", "restart"), ("reboot now", "restart"), ("please restart", "restart"),
                            ("shut down the computer", "shutdown"), ("shutdown", "shutdown"),
                            ("power off my laptop", "shutdown"), ("turn off the pc", "shutdown"),
                            ("sign out of windows", "sign_out"), ("log off", "sign_out"),
                            ("put the computer to sleep", "sleep"), ("hibernate", "sleep")):
            self.app.pending.clear()
            self.assertIn("Reply yes", self.say(text), text)
            self.assertEqual([p[0] for p in self.app.pending], [label], text)
        self.w.shutdown.assert_not_called()
        self.w.sleep.assert_not_called()
        self.w.sign_out.assert_not_called()

    def test_confirmed_actions_call_skill(self):
        self.say("restart the computer")
        self.app.pending[-1][1]()
        self.w.shutdown.assert_called_once_with(restart=True)
        self.say("shut down")
        self.app.pending[-1][1]()
        self.w.shutdown.assert_called_with(restart=False)

    def test_power_verbs_aimed_elsewhere_are_not_pc_power(self):
        for text in ("restart spotify", "sign out of gmail", "shut down chrome", "set a sleep timer for spotify"):
            self.app.pending.clear()
            self.assertIsNone(self.say(text), text)
            self.assertEqual(self.app.pending, [], text)
        self.assertFalse(_power_request("reboot the router", r"restart|reboot"))

    def test_cancel_shutdown(self):
        for text in ("cancel shutdown", "cancel the restart", "abort the shutdown", "stop the shutdown"):
            self.say(text)
        self.assertEqual(self.w.cancel_shutdown.call_count, 4)
        self.assertEqual(self.app.pending, [])

    def test_lock(self):
        self.w.lock.return_value = "Locked the PC."
        self.assertEqual(self.say("lock my pc"), "Locked the PC.")

    def test_settings_phrases_never_lock_or_power(self):
        self.w.open_settings.return_value = "Opened settings."
        for text, page in (("open lock screen settings", "lock screen"), ("open sleep settings", "sleep"),
                           ("open bluetooth settings", "bluetooth"), ("show me the restart settings", "restart"),
                           ("go to wifi settings", "wifi"), ("settings", "")):
            self.w.open_settings.reset_mock()
            self.assertEqual(self.say(text), "Opened settings.")
            self.assertIn(page, self.w.open_settings.call_args.args[0])
        self.w.lock.assert_not_called()
        self.assertEqual(self.app.pending, [])

    def test_resolution_flow(self):
        self.assertIn("1920×1080", self.say("change resolution to 1080p"))
        self.assertEqual(self.app.pending[-1][0], "resolution")
        self.assertIn("Which resolution", self.say("change the resolution"))
        self.w.get_resolution.return_value = (2560, 1440)
        self.assertEqual(self.say("what's my screen resolution"), "Your screen resolution is 2560×1440.")
        self.w.get_resolution.side_effect = Exception("stub")
        self.assertIn("Couldn't read the resolution", self.say("what is the current resolution"))
        self.w.set_resolution.assert_not_called()

    def test_restore_and_keep(self):
        self.w.restore_resolution.return_value = "Resolution restored to 1920×1080."
        self.assertEqual(self.say("revert the resolution"), "Resolution restored to 1920×1080.")
        self.assertEqual(self.say("keep resolution"), "There's no pending resolution change.")

    def test_brightness_phrases(self):
        self.say("brightness 50%")
        self.w.set_brightness.assert_called_with(50)
        self.say("set brightness to 70 percent")
        self.w.set_brightness.assert_called_with(70)
        self.say("30% brightness")
        self.w.set_brightness.assert_called_with(30)
        self.say("turn brightness up by 20")
        self.w.change_brightness.assert_called_with(20)
        self.say("decrease brightness")
        self.w.change_brightness.assert_called_with(-10)
        self.say("dim the screen")
        self.w.change_brightness.assert_called_with(-10)
        self.say("lower the brightness to 20")
        self.w.set_brightness.assert_called_with(20)
        self.w.get_brightness.return_value = 65
        self.assertEqual(self.say("what's the brightness"), "Brightness is 65%.")
        self.w.get_brightness.return_value = None
        self.assertIn("can't read", self.say("what is the current brightness"))
        self.assertIn("Tell me a level", self.say("brightness"))

    def test_window_phrases(self):
        self.say("close all open windows")
        self.assertEqual(self.app.pending[-1][0], "close_all")
        self.w.close_all_windows.assert_not_called()
        self.say("minimize all windows")
        self.say("show the desktop")
        self.assertEqual(self.w.show_desktop.call_count, 2)
        self.say("list open windows")
        self.w.list_windows.assert_called_once_with()
        for text, args in (("switch to chrome", ("chrome", "focus")), ("maximize the notepad window", ("notepad", "maximize")),
                           ("minimise spotify", ("spotify", "minimize")), ("restore outlook", ("outlook", "restore")),
                           ("focus word", ("word", "focus"))):
            self.say(text)
            self.assertEqual(self.w.window_action.call_args.args, args, text)

    def test_recycle_bin_and_unknown(self):
        self.say("empty the recycle bin")
        self.assertEqual(self.app.pending[-1][0], "empty_recycle_bin")
        self.app.system_control.empty_recycle_bin.assert_not_called()
        for text in ("delete everything in the recycle bin", "clear my recycle bin",
                     "clean out the recycle bin", "remove everything from the recycle bin"):
            self.say(text)
            self.assertEqual(self.app.pending[-1][0], "empty_recycle_bin", text)
        self.app.system_control.empty_recycle_bin.assert_not_called()
        self.assertIsNone(self.say("do a barrel roll"))

    def test_replies_are_strings(self):
        # Real skill forced into its "not Windows" mode on every OS: on a real Windows PC this list
        # would otherwise lock the session, cancel shutdowns and change the screen resolution.
        wc = WindowsControl()
        wc.available = False
        self.app.windows = wc
        no_win_modules = dict.fromkeys(("wmi", "win32api", "win32con", "win32gui", "win32process"))
        with patch.object(os, "startfile", side_effect=OSError("x"), create=True), \
                patch.object(ctypes, "windll", MagicMock(), create=True), \
                patch.dict(sys.modules, no_win_modules), \
                patch("skills.windows_control.subprocess.run", side_effect=OSError("x")):
            for text in ("lock my pc", "cancel shutdown", "brightness 40", "turn brightness up", "list windows",
                         "show desktop", "switch to chrome", "open bluetooth settings", "what's my resolution",
                         "revert resolution", "keep resolution", "close all windows"):
                self.assertIsInstance(self.say(text), str, text)


class ResolutionTimerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.app.windows.set_resolution.return_value = "Resolution changed from 1920×1080 to 1280×720."
        self.app.windows.restore_resolution.return_value = "Resolution restored to 1920×1080."
        self.h = ControlHandler(self.app)
        self.timers = []

        def make_timer(interval, fn):
            t = Mock(interval=interval, fn=fn)
            self.timers.append(t)
            return t

        p = patch("handlers.control.threading.Timer", side_effect=make_timer)
        p.start()
        self.addCleanup(p.stop)

    def test_apply_starts_daemon_timer(self):
        reply = self.h.apply_resolution(1280, 720)
        self.assertIn("keep resolution", reply)
        self.assertEqual(self.timers[0].interval, 15)
        self.assertTrue(self.timers[0].daemon)
        self.timers[0].start.assert_called_once_with()

    def test_timeout_reverts(self):
        self.h.apply_resolution(1280, 720)
        self.timers[0].fn()
        self.app.notify.assert_called_once()
        self.assertIn("restored", self.app.notify.call_args.args[0])
        self.assertIsNone(self.h._resolution_timer)

    def test_failed_change_starts_no_timer(self):
        self.app.windows.set_resolution.return_value = "Your display doesn't support 1×1."
        self.assertNotIn("keep resolution", self.h.apply_resolution(1, 1))
        self.assertEqual(self.timers, [])

    def test_keep_cancels(self):
        self.h.apply_resolution(1280, 720)
        self.assertEqual(self.h.handle("keep this resolution", "CONTROL"), "Keeping this resolution.")
        self.timers[0].cancel.assert_called_once_with()
        self.timers[0].fn()                             # fired anyway (cancel raced the timer thread)
        self.app.notify.assert_not_called()

    def test_stale_timer_does_not_clobber_newer_change(self):
        self.h.apply_resolution(1280, 720)
        self.h.apply_resolution(800, 600)               # second change supersedes the first
        self.timers[0].fn()                             # the first timer's callback was already running
        self.app.notify.assert_not_called()
        self.assertIs(self.h._resolution_timer, self.timers[1])
        self.assertEqual(self.h.handle("keep resolution", "CONTROL"), "Keeping this resolution.")

    def test_revert_errors_are_contained(self):
        self.h.apply_resolution(1280, 720)
        self.app.notify.side_effect = RuntimeError("ui gone")
        with self.assertLogs("jarvis.handlers.ControlHandler", "ERROR"):
            self.timers[0].fn()                         # must not raise in the timer thread


class MediaHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = MediaHandler(self.app)
        self.w = self.app.windows

    def say(self, text):
        return self.h.handle(text, "MEDIA")

    def test_absolute_volume(self):
        for text, level in (("set volume to 40", 40), ("volume 40%", 40), ("40% volume", 40),
                            ("set the sound to 15 percent", 15), ("turn the volume down to 20", 20),
                            ("turn volume up to 80.", 80)):
            self.say(text)
            self.w.set_volume.assert_called_with(level)
        self.w.change_volume.assert_not_called()

    def test_relative_volume(self):
        for text, delta in (("turn the volume up by 20", 20), ("volume down 10", -10),
                            ("increase volume by 5%", 5), ("lower the volume by 30", -30)):
            self.say(text)
            self.w.change_volume.assert_called_with(delta)
        self.w.set_volume.assert_not_called()

    def test_step_volume(self):
        for text, delta in (("turn volume up", 10), ("turn it up", 10), ("turn up the volume", 10), ("louder", 10),
                            ("raise the volume", 10), ("volume down", -10), ("quieter", -10),
                            ("turn down the volume", -10), ("lower the volume", -10), ("decrease volume", -10)):
            self.w.change_volume.reset_mock()
            self.say(text)
            self.w.change_volume.assert_called_once_with(delta)

    def test_mute_and_query(self):
        self.say("unmute")
        self.w.mute.assert_called_with(False)
        self.say("mute the sound")
        self.w.mute.assert_called_with(True)
        self.say("what's the volume")
        self.w.get_volume.assert_called_once_with()
        self.say("what's playing")
        self.w.now_playing.assert_called_once_with()

    def test_transport(self):
        for text, action in (("next song", "next"), ("skip this", "next"), ("previous track", "previous"),
                             ("go back", "previous"), ("stop", "stop"), ("please stop the music", "stop"),
                             ("pause", "play_pause"), ("resume the video", "play_pause")):
            self.say(text)
            self.w.media.assert_called_with(action)
        self.assertIsNone(self.say("hmm"))


class AppsHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = AppsHandler(self.app)
        self.c = self.app.app_control

    def test_close_app_needs_yes(self):
        self.assertIn("Close chrome?", self.h.handle("close the chrome app", "APP"))
        self.c.close_app_by_name.assert_not_called()
        self.app.pending[-1][1]()
        self.c.close_app_by_name.assert_called_once_with("chrome")

    def test_close_all_windows_routes_to_control(self):
        self.app.handlers.dispatch.return_value = "Ask every open window to close?"
        for text in ("close all windows", "quit everything", "close all the windows"):
            self.assertEqual(self.h.handle(text, "APP"), "Ask every open window to close?")
        self.app.app_control = None                       # closing windows doesn't need app control
        self.assertEqual(self.h.handle("close every open window", "APP"), "Ask every open window to close?")
        self.app.handlers.dispatch.assert_called_with("close all windows", "CONTROL")

    def test_list_and_discover(self):
        self.h.handle("list installed apps", "APP")
        self.c.list_installed_apps.assert_called_with("")
        self.h.handle("show all installed apps", "APP")
        self.c.list_installed_apps.assert_called_with("")
        self.h.handle("show apps matching spot", "APP")
        self.c.list_installed_apps.assert_called_with("spot")
        self.h.handle("scan for new apps", "APP")
        self.c.discover_applications.assert_called_once_with()
        self.c.launch_app_by_name.assert_not_called()

    def test_launch(self):
        self.h.handle("Open Spotify", "APP", browser="edge")
        self.c.launch_app_by_name.assert_called_once_with("Open Spotify", browser="edge")
        self.app.app_control = None
        self.assertIn("isn't available", self.h.handle("open spotify", "APP"))


class ToolRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.t = ToolRegistry(confirm=lambda q: True)
        for cls in (ControlHandler, MediaHandler, AppsHandler):
            cls(self.app).register_tools(self.t)

    def test_power_tool(self):
        self.app.windows.shutdown.return_value = "Restarting."
        self.assertEqual(self.t.execute("power_action", {"action": "restart"}), "Restarting.")
        self.app.windows.shutdown.assert_called_once_with(True)
        self.assertIn("Unknown power action", self.t.execute("power_action", {"action": "explode"}))

    def test_power_tool_declined(self):
        self.t.set_confirm(lambda q: False)
        self.assertIn("declined", self.t.execute("power_action", {"action": "shutdown"}))
        self.assertIn("declined", self.t.execute("set_resolution", {"width": 1280, "height": 720}))
        self.app.windows.shutdown.assert_not_called()
        self.app.windows.set_resolution.assert_not_called()

    def test_other_tools(self):
        self.app.windows.set_resolution.return_value = "Your display doesn't support that."
        self.t.execute("set_resolution", {"width": "1280", "height": "720"})
        self.app.windows.set_resolution.assert_called_once_with(1280, 720)
        self.t.execute("set_volume", {"level": 30})
        self.app.windows.set_volume.assert_called_once_with(level=30)
        self.t.execute("open_app_or_website", {"target": "github.com"})
        self.app.app_control.launch_app_by_name.assert_called_once_with("github.com", browser=None)
        self.assertIn("close_app", self.t.names())

    def test_no_app_control_skips_app_tools(self):
        self.app.app_control = None
        t = ToolRegistry()
        AppsHandler(self.app).register_tools(t)
        self.assertEqual(len(t), 0)


class ComInitTests(unittest.TestCase):
    def test_com_init_tolerates_missing_modules(self):
        with patch.dict(sys.modules, {"pythoncom": None, "comtypes": None}):
            wc_mod._com_init()                            # must not raise

    def test_is_windows(self):
        self.assertEqual(wc_mod._is_windows(), os.name == "nt")


if __name__ == "__main__":
    unittest.main()
