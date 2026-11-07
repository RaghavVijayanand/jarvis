"""The tray app: command bar, tray, single instance, shell wiring, onboarding, autostart, packaging."""
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parent.parent

try:
    import PySide6  # noqa: F401
    _HAS_QT = True
except ImportError:
    _HAS_QT = False
if _HAS_QT and sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

needs_qt = unittest.skipUnless(_HAS_QT, "needs PySide6")


def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def pump(seconds=0.05):
    app = qapp()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


# ── no Qt needed ─────────────────────────────────────────────────────────────

class FakeReg:
    HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_SZ = 1, 2, 3, 4

    def __init__(self):
        self.values = {}

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(self, *a):
        return self._Key()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 1

    def SetValueEx(self, key, name, _r, _t, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class AutostartTests(unittest.TestCase):
    def test_enable_disable_roundtrip(self):
        from core import autostart
        reg = FakeReg()
        with patch.object(autostart, "_winreg", return_value=reg):
            self.assertFalse(autostart.is_enabled())
            self.assertIn("will start", autostart.set_enabled(True))
            self.assertTrue(autostart.is_enabled())
            self.assertTrue(reg.values["JARVIS"].endswith("--tray"))
            self.assertIn("won't start", autostart.set_enabled(False))
            self.assertFalse(autostart.is_enabled())
            self.assertIn("won't start", autostart.set_enabled(False))       # already off: fine

    def test_stale_entry_reads_as_off_and_reenabling_repairs_it(self):
        from core import autostart
        reg = FakeReg()
        reg.values["JARVIS"] = '"C:\\Old Place\\Nowhere\\JARVIS.exe" --tray'
        with patch.object(autostart, "_winreg", return_value=reg):
            self.assertFalse(autostart.is_enabled())
            autostart.set_enabled(True)
            self.assertTrue(autostart.is_enabled())
        self.assertEqual(autostart._program_of('"C:\\A B\\x.exe" --tray'), "C:\\A B\\x.exe")
        self.assertEqual(autostart._program_of("C:\\x.exe --tray"), "C:\\x.exe")
        self.assertEqual(autostart._program_of('"unterminated'), "")
        self.assertEqual(autostart._program_of(""), "")

    def test_frozen_and_source_commands(self):
        from core import autostart
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", r"C:\JARVIS\JARVIS.exe"):
            self.assertEqual(autostart.launch_command(), '"C:\\JARVIS\\JARVIS.exe" --tray')
        cmd = autostart.launch_command()
        self.assertIn("app.py", cmd)
        self.assertTrue(cmd.endswith("--tray"))

    def test_errors_and_other_platforms(self):
        from core import autostart
        reg = FakeReg()
        reg.OpenKey = Mock(side_effect=PermissionError("denied"))
        with patch.object(autostart, "_winreg", return_value=reg):
            self.assertIn("Couldn't", autostart.set_enabled(True))
            self.assertFalse(autostart.is_enabled())
        with patch.object(autostart, "_winreg", return_value=None):
            self.assertIn("only available on Windows", autostart.set_enabled(True))
            self.assertFalse(autostart.is_enabled())


class HotkeyTests(unittest.TestCase):
    def test_pynput_format(self):
        from core.hotkeys import to_pynput
        self.assertEqual(to_pynput("ctrl+shift+space"), "<ctrl>+<shift>+<space>")
        self.assertEqual(to_pynput("Alt + J"), "<alt>+j")
        self.assertEqual(to_pynput("f8"), "<f8>")

    def test_tap_hotkey_start_fire_stop(self):
        from core.hotkeys import TapHotkey
        fired = []
        listener = Mock()
        keyboard = Mock()
        keyboard.GlobalHotKeys.return_value = listener
        with patch.dict("sys.modules", {"pynput": Mock(keyboard=keyboard), "pynput.keyboard": keyboard}):
            hk = TapHotkey("ctrl+shift+space", lambda: fired.append(1))
            self.assertTrue(hk.start())
        mapping = keyboard.GlobalHotKeys.call_args.args[0]
        mapping["<ctrl>+<shift>+<space>"]()
        self.assertEqual(fired, [1])
        self.assertEqual(hk.label, "Ctrl + Shift + Space")
        hk.stop()
        listener.stop.assert_called_once()
        hk.stop()
        with patch.dict("sys.modules", {"pynput": Mock(keyboard=keyboard), "pynput.keyboard": keyboard}):
            first = Mock()
            keyboard.GlobalHotKeys.return_value = first
            hk.start()
            keyboard.GlobalHotKeys.return_value = Mock()
            hk.start()                                      # restart must stop the old listener
        first.stop.assert_called_once()

    def test_failures_are_contained(self):
        from core.hotkeys import TapHotkey
        hk = TapHotkey("f8", Mock(side_effect=RuntimeError("boom")))
        hk._fire()                                          # must not raise into pynput's thread
        with patch.dict("sys.modules", {"pynput": None}):
            self.assertFalse(hk.start())

    def test_config_validates_hotkeys(self):
        from core.config import Config
        with patch.dict(os.environ, {"JARVIS_COMMAND_BAR_HOTKEY": "ctrl+alt+del", "JARVIS_ONBOARDED": "1"}):
            Config.reload()
            self.assertEqual(Config.COMMAND_BAR_HOTKEY, "ctrl+shift+space")
            self.assertTrue(Config.ONBOARDED)
        Config.reload()


class AppEntryTests(unittest.TestCase):
    def test_args(self):
        import app
        a = app.parse_args(["--tray", "-platform", "offscreen"])
        self.assertTrue(a.tray)
        self.assertFalse(a.dashboard)
        self.assertTrue(app.parse_args(["--selftest"]).selftest)

    def test_selftest_passes_and_writes_log(self):
        import app
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "st.log")
            with patch.dict(os.environ, {"JARVIS_SELFTEST_LOG": log}), patch("builtins.print"):
                code = app.main(["--selftest"]) if _HAS_QT else 0
            if _HAS_QT:
                self.assertEqual(code, 0)
                self.assertIn("SELFTEST OK", Path(log).read_text())

    def test_selftest_reports_failures(self):
        import app
        with patch.object(app, "SELFTEST_MODULES", ["no_such_module_xyz"]), patch("builtins.print"):
            self.assertEqual(app.selftest(), 1)

    def test_mutex_only_on_windows(self):
        import app
        with patch.object(sys, "platform", "linux"):
            self.assertIsNone(app.hold_mutex())


class PackagingTests(unittest.TestCase):
    def test_spec_uses_the_tray_app_and_real_files(self):
        spec = (ROOT / "build" / "jarvis.spec").read_text()
        self.assertIn("'app.py'", spec)
        self.assertIn("COLLECT(", spec)                     # one-folder build for the installer
        self.assertIn("console=False", spec)
        self.assertIn("pynput.keyboard._win32", spec)
        self.assertTrue((ROOT / "build" / "version_info.txt").exists())
        compile(spec, "jarvis.spec", "exec")

    def test_installer_script_matches_the_app(self):
        iss = (ROOT / "installer" / "jarvis.iss").read_text()
        import app
        self.assertIn(f"AppMutex={app.MUTEX_NAME}", iss)
        self.assertIn(r'Source: "..\dist\JARVIS\*"', iss)
        self.assertIn("PrivilegesRequired=lowest", iss)
        from core.autostart import RUN_KEY, VALUE_NAME
        self.assertIn(RUN_KEY, iss)
        self.assertIn(f'ValueName: "{VALUE_NAME}"', iss)
        self.assertIn("--tray", iss)
        self.assertIn(r"SetupIconFile=..\assets\jarvis.ico", iss)

    def test_icon_builds(self):
        sys.path.insert(0, str(ROOT / "build"))
        try:
            import make_icon
            with tempfile.TemporaryDirectory() as tmp, patch.object(make_icon, "OUT", Path(tmp) / "j.ico"):
                out = make_icon.main()
                from PIL import Image
                with Image.open(out) as im:
                    self.assertIn((256, 256), im.info["sizes"])
                    self.assertIn((16, 16), im.info["sizes"])
        finally:
            sys.path.remove(str(ROOT / "build"))

    def test_build_script_helpers(self):
        sys.path.insert(0, str(ROOT / "build"))
        try:
            import build_installer as bi
            self.assertRegex(bi.app_version(), r"^\d+\.\d+\.\d+$")
            with patch.object(bi.shutil, "which", return_value=None), \
                    patch.object(bi, "ISCC_CANDIDATES", [Path("/nope/ISCC.exe")]):
                self.assertIsNone(bi.find_iscc())
            with patch.object(bi.shutil, "which", return_value="/x/ISCC"):
                self.assertEqual(bi.find_iscc(), Path("/x/ISCC"))
        finally:
            sys.path.remove(str(ROOT / "build"))

    def test_batch_files_use_crlf(self):
        for name in ("build_installer.bat", "start_jarvis_gui.bat", "launcher.bat"):
            data = (ROOT / name).read_bytes()
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), name)
            self.assertTrue(data.isascii(), name)


# ── Qt surfaces ──────────────────────────────────────────────────────────────

@needs_qt
class CommandBarTests(unittest.TestCase):
    def setUp(self):
        qapp()
        from ui.command_bar import CommandBar
        self.bar = CommandBar("Ctrl + Shift + Space")
        self.addCleanup(self.bar.close)
        self.sent = []
        self.bar.submitted.connect(self.sent.append)

    def cards(self):
        lay = self.bar.results_layout
        return [(lay.itemAt(i).widget().kind, lay.itemAt(i).widget().label.text()) for i in range(lay.count() - 1)]

    def test_submit_and_reply(self):
        self.bar.summon()
        pump()
        self.assertTrue(self.bar.isVisible())
        self.bar.input.setText("  open spotify ")
        self.bar._submit()
        self.assertEqual(self.sent, ["open spotify"])
        self.assertTrue(self.bar.owns_reply())
        self.assertEqual(self.bar.status.text(), "Working…")
        self.bar.show_result("Opened Spotify.")
        self.assertFalse(self.bar.owns_reply())
        self.assertEqual(self.bar.status.text(), "")
        self.assertEqual(self.cards(), [("you", "› open spotify"), ("reply", "Opened Spotify.")])
        self.assertFalse(self.bar.chips.isVisible())
        self.bar.show_result("", error=True)
        self.assertEqual(self.cards()[-1], ("error", "Done."))
        self.bar.input.setText("   ")
        self.bar._submit()
        self.assertEqual(len(self.sent), 1)                 # blank input sends nothing

    def test_history_and_keys(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        for text in ("one", "two", "two"):
            self.bar.run(text)
        self.assertEqual(self.bar.history, ["one", "two"])  # no duplicate in a row

        def key(k, mods=Qt.NoModifier, target=None):
            ev = QKeyEvent(QEvent.KeyPress, k, mods)
            if target is None:
                self.bar.eventFilter(self.bar.input, ev)
            else:
                self.bar.keyPressEvent(ev)
        key(Qt.Key_Up)
        self.assertEqual(self.bar.input.text(), "two")
        key(Qt.Key_Up)
        key(Qt.Key_Up)
        self.assertEqual(self.bar.input.text(), "one")
        key(Qt.Key_Down)
        self.assertEqual(self.bar.input.text(), "two")
        key(Qt.Key_Down)
        self.assertEqual(self.bar.input.text(), "")
        key(Qt.Key_L, Qt.ControlModifier, target="bar")
        self.assertEqual(self.cards(), [])
        self.bar.show()
        key(Qt.Key_Escape, target="bar")
        self.assertFalse(self.bar.isVisible())

    def test_chips_mic_dashboard_and_cap(self):
        from ui import command_bar
        chip = self.bar.chips.findChildren(command_bar.QPushButton)[0]
        chip.click()
        self.assertEqual(self.sent, [command_bar.SUGGESTIONS[0][1]])
        mic = []
        self.bar.mic_toggled.connect(mic.append)
        self.bar.btn_mic.click()
        self.assertEqual(mic, [True])
        self.bar.set_mic(False)
        self.assertFalse(self.bar.btn_mic.isChecked())
        opened = []
        self.bar.open_dashboard.connect(lambda: opened.append(1))
        self.bar.show()
        self.bar.btn_expand.click()
        self.assertEqual(opened, [1])
        self.assertFalse(self.bar.isVisible())
        for i in range(30):
            self.bar.show_result(f"r{i}")
        pump()
        self.assertLessEqual(len(self.cards()), command_bar.MAX_RESULTS * 2)
        self.assertLessEqual(self.bar.scroll.height(), 340)

    def test_toggle(self):
        self.bar.toggle()
        pump()
        self.assertTrue(self.bar.isVisible())
        with patch.object(self.bar, "isActiveWindow", return_value=True):
            self.bar.toggle()
        self.assertFalse(self.bar.isVisible())


@needs_qt
class TrayAndInstanceTests(unittest.TestCase):
    def setUp(self):
        qapp()

    def test_single_instance_roundtrip(self):
        from ui.tray import SingleInstance
        name = f"jarvis-test-{os.getpid()}-{time.time()}"
        first = SingleInstance(name)
        self.addCleanup(first.close)
        self.assertFalse(SingleInstance(name).notify_running(timeout_ms=100))
        self.assertTrue(first.listen())
        got = []
        first.message.connect(got.append)
        self.assertTrue(SingleInstance(name).notify_running("dashboard"))
        for _ in range(100):
            pump(0.01)
            if got:
                break
        self.assertEqual(got, ["dashboard"])

    def test_tray_actions_and_state(self):
        from PySide6.QtWidgets import QSystemTrayIcon
        from ui.tray import Tray
        tray = Tray("Ctrl+Shift+Space")
        seen = []
        for name in ("ask", "dashboard", "settings", "quit"):
            getattr(tray, name).connect(lambda n=name: seen.append(n))
        tray.buddy_toggled.connect(lambda on: seen.append(("buddy", on)))
        tray.act_ask.trigger()
        tray.act_dash.trigger()
        tray.act_settings.trigger()
        tray.act_buddy.trigger()
        tray.act_quit.trigger()
        tray._activated(QSystemTrayIcon.Trigger)
        tray._activated(QSystemTrayIcon.DoubleClick)
        self.assertEqual(seen, ["ask", "dashboard", "settings", ("buddy", True), "quit", "ask", "dashboard"])
        seen.clear()
        tray.set_checked(tray.act_buddy, False)             # reflect state without re-emitting
        self.assertEqual(seen, [])
        self.assertFalse(tray.act_buddy.isChecked())
        tray.set_busy(True)
        self.assertIn("working", tray.icon.toolTip())
        tray.set_busy(False)
        tray.notify("t", "x" * 400)                         # hidden icon: silently skipped
        self.assertIn("Ctrl+Shift+Space", tray.act_ask.text())

    def test_theme_icons(self):
        from ui import theme
        for icon in (theme.app_icon(), theme.app_icon(busy=True), theme.mic_icon(), theme.expand_icon()):
            self.assertFalse(icon.isNull())
        self.assertFalse(theme.logo_pixmap(40).isNull())


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in list(self.slots):
            fn(*a)


class FakeButton:
    def __init__(self):
        self.checked = False
        self.toggled = FakeSignal()

    def isChecked(self):
        return self.checked

    def setChecked(self, on):
        if on != self.checked:
            self.checked = on
            self.toggled.emit(on)


class FakeWindow:
    def __init__(self):
        for name in ("bar_reply", "ready", "hidden_to_tray", "settings_changed"):
            setattr(self, name, FakeSignal())
        self._bridge = SimpleNamespace(notify_requested=FakeSignal())
        self.btn_voice_chat, self.btn_buddy = FakeButton(), FakeButton()
        self.visible = False
        self.minimized = False
        self.submitted = []
        self.accept = True
        self.worker = SimpleNamespace(busy_changed=FakeSignal())
        self.hide_on_close = None
        self.calls = []

    def submit_from_bar(self, text):
        self.submitted.append(text)
        return self.accept

    def isVisible(self):
        return self.visible

    def isMinimized(self):
        return self.minimized

    def show(self):
        self.visible = True

    def showNormal(self):
        self.visible, self.minimized = True, False

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def open_settings(self):
        self.calls.append("settings")

    def toggle_buddy(self, on):
        self.calls.append(("buddy", on))

    def toggle_voice_chat(self):
        self.calls.append(("voice", self.btn_voice_chat.checked))

    def quit_app(self):
        self.calls.append("quit")


@needs_qt
class ShellTests(unittest.TestCase):
    def setUp(self):
        qapp()
        self.window = FakeWindow()
        self.bar = MagicMock()
        for name in ("submitted", "open_dashboard", "mic_toggled"):
            setattr(self.bar, name, FakeSignal())
        self.tray = MagicMock()
        for name in ("ask", "dashboard", "settings", "buddy_toggled", "voice_toggled", "startup_toggled", "quit"):
            setattr(self.tray, name, FakeSignal())
        self.instance = SimpleNamespace(message=FakeSignal(), close=Mock())
        patcher = patch("core.hotkeys.TapHotkey")
        self.hotkey_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.hotkey_cls.return_value.label = "Ctrl + Shift + Space"
        self.hotkey_cls.return_value.combo = "ctrl+shift+space"
        auto = patch("core.autostart.is_enabled", return_value=False)
        auto.start()
        self.addCleanup(auto.stop)

    def make(self, **kw):
        from ui.shell import TrayApp
        return TrayApp(self.window, self.bar, tray=self.tray, instance=self.instance, **kw)

    def test_hidden_start_then_ready_and_routing(self):
        shell = self.make(start_hidden=True, first_run=True)
        self.assertTrue(self.window.hide_on_close)
        self.assertFalse(self.window.visible)
        self.tray.show.assert_called_once()
        self.window.ready.emit()
        self.assertEqual(self.hotkey_cls.return_value.start.call_count, 2)   # command bar + conversation (F8)
        self.tray.notify.assert_called()
        self.assertIn("Ctrl + Shift + Space", self.tray.notify.call_args.args[1])
        self.bar.submitted.emit("open notepad")
        self.assertEqual(self.window.submitted, ["open notepad"])
        self.window.accept = False
        self.bar.submitted.emit("too early")
        self.bar.show_result.assert_called_with("JARVIS is still starting — try again in a moment.", error=True)
        self.window.bar_reply.emit("Opened Notepad.")
        self.bar.show_result.assert_called_with("Opened Notepad.")
        self.window.worker.busy_changed.emit(True)
        self.tray.set_busy.assert_called_with(True)
        # hotkey (from pynput's thread) → signal → GUI thread → bar
        shell._summon.emit()
        pump()
        self.bar.summon.assert_called()

    def test_tray_menu_intents(self):
        shell = self.make(start_hidden=True)
        self.tray.ask.emit()
        self.bar.summon.assert_called_once()
        self.tray.dashboard.emit()
        self.assertTrue(self.window.visible)
        self.tray.settings.emit()
        self.assertIn("settings", self.window.calls)
        self.tray.buddy_toggled.emit(True)
        self.assertIn(("buddy", True), self.window.calls)
        self.tray.voice_toggled.emit(True)
        self.assertIn(("voice", True), self.window.calls)
        self.bar.set_mic.assert_called_with(True)          # mic state mirrored everywhere
        self.tray.voice_toggled.emit(True)                  # already on: no second toggle
        self.assertEqual(self.window.calls.count(("voice", True)), 1)
        with patch("core.autostart.set_enabled", return_value="JARVIS will start…") as setter:
            self.tray.startup_toggled.emit(True)
        setter.assert_called_once_with(True)
        self.instance.message.emit("ask")
        self.assertEqual(self.bar.summon.call_count, 2)
        self.window.visible = False
        self.window.minimized = True
        self.instance.message.emit("dashboard")
        self.assertTrue(self.window.visible)

    def test_hide_notice_once_notifications_and_quit(self):
        shell = self.make(start_hidden=False)
        self.assertTrue(self.window.visible)                # a normal launch shows the dashboard
        self.window.ready.emit()
        self.tray.notify.reset_mock()
        self.window.visible = False
        self.window.hidden_to_tray.emit()
        self.window.hidden_to_tray.emit()
        self.assertEqual(self.tray.notify.call_count, 1)
        self.window._bridge.notify_requested.emit("Reminder: stretch")
        self.tray.notify.assert_called_with("JARVIS", "Reminder: stretch")
        # a changed hotkey restarts the listener
        from core.config import Config
        with patch.object(Config, "COMMAND_BAR_HOTKEY", "f8"):
            self.window.settings_changed.emit()
        # the bar moves to F8 and keeps it; conversation mode gives the key up instead of fighting for it
        self.assertEqual([c.args[0] for c in self.hotkey_cls.call_args_list], ["ctrl+shift+space", "f8", "f8"])
        self.assertIsNone(shell.talk_hotkey)
        with patch("PySide6.QtCore.QTimer.singleShot") as later:
            shell.quit()
            shell.quit()                                     # idempotent
        self.assertEqual(self.window.calls.count("quit"), 1)
        self.tray.hide.assert_called_once()
        self.instance.close.assert_called_once()
        later.assert_called_once()

    def test_without_a_tray_the_window_behaves_normally(self):
        from ui.shell import TrayApp
        TrayApp(self.window, self.bar, tray=None, start_hidden=True)
        self.assertFalse(self.window.hide_on_close)
        self.assertTrue(self.window.visible)


@needs_qt
class OnboardingTests(unittest.TestCase):
    def setUp(self):
        qapp()

    def test_values_for_each_brain(self):
        from ui.onboarding import WelcomeWizard
        with patch("core.autostart.is_enabled", return_value=False):
            wiz = WelcomeWizard()
        self.addCleanup(wiz.close)
        wiz.opt_gemini.setChecked(True)
        wiz.key.setText(" AIza-test ")
        v = wiz.values()
        self.assertEqual(v["GEMINI_API_KEY"], "AIza-test")
        self.assertEqual(v["JARVIS_ONBOARDED"], "1")
        self.assertIn(v["JARVIS_BUDDY_HOTKEY"], ("ctrl+alt", "right ctrl", "ctrl+shift", "ctrl+win", "f9"))
        wiz.opt_openrouter.setChecked(True)
        self.assertEqual(wiz.values()["OPENROUTER_API_KEY"], "AIza-test")
        wiz.opt_ollama.setChecked(True)
        self.assertEqual(wiz.values()["JARVIS_OLLAMA_AUTOSTART"], "1")
        self.assertFalse(wiz.key.isEnabled())
        self.assertEqual(wiz.get_key.text(), "Get Ollama")
        with patch("webbrowser.open") as web:
            wiz._open_key_page()
        web.assert_called_with("https://ollama.com/download")
        wiz.opt_skip.setChecked(True)
        self.assertNotIn("GEMINI_API_KEY", wiz.values())

    def test_save_and_run(self):
        from ui import onboarding
        with patch("core.autostart.is_enabled", return_value=False):
            wiz = onboarding.WelcomeWizard()
        self.addCleanup(wiz.close)
        wiz.startup.setChecked(True)
        with patch.object(onboarding, "save_setting") as save, \
                patch("core.autostart.is_enabled", return_value=False), \
                patch("core.autostart.set_enabled", return_value="Couldn't change it: denied") as setter:
            notes = wiz.save()
        setter.assert_called_once_with(True)
        self.assertEqual(notes, ["Couldn't change it: denied"])
        self.assertIn(("JARVIS_ONBOARDED", "1"), [c.args for c in save.call_args_list])
        # cancelled welcome: remembered so it doesn't nag, nothing else saved
        with patch.object(onboarding.WelcomeWizard, "exec", return_value=0), \
                patch.object(onboarding, "save_setting") as save, patch("core.autostart.is_enabled", return_value=False):
            self.assertFalse(onboarding.run_onboarding())
        save.assert_called_once_with("JARVIS_ONBOARDED", "1")
        with patch.object(onboarding.WelcomeWizard, "exec", return_value=1), \
                patch.object(onboarding.WelcomeWizard, "save", return_value=[]) as saved, \
                patch("core.autostart.is_enabled", return_value=False):
            self.assertTrue(onboarding.run_onboarding())
        saved.assert_called_once()


@needs_qt
class AppMainTests(unittest.TestCase):
    def test_second_launch_hands_off(self):
        qapp()
        import app
        with patch("ui.tray.SingleInstance.notify_running", return_value=True) as notify, \
                patch("core.logging_setup.setup_logging"):
            self.assertEqual(app.main(["--dashboard"]), 0)
        notify.assert_called_once_with("dashboard")

    def test_first_run_builds_everything(self):
        qapp()
        import app
        import main_gui
        fake_app = MagicMock()
        fake_app.exec.return_value = 0
        window = MagicMock()
        window.threads_still_running.return_value = False
        with patch("ui.tray.SingleInstance.notify_running", return_value=False), \
                patch("ui.tray.SingleInstance.listen", return_value=True), \
                patch("core.logging_setup.setup_logging"), \
                patch("PySide6.QtWidgets.QApplication.instance", return_value=fake_app), \
                patch("ui.onboarding.run_onboarding") as onboard, \
                patch.object(main_gui, "MainWindow", return_value=window), \
                patch("ui.command_bar.CommandBar") as bar, \
                patch("ui.tray.Tray.available", return_value=False), \
                patch("ui.shell.TrayApp") as shell:
            self.assertEqual(app.main(["--setup", "--tray"]), 0)
        onboard.assert_called_once()
        bar.assert_called_once()
        kwargs = shell.call_args.kwargs
        self.assertIsNone(kwargs["tray"])
        self.assertTrue(kwargs["first_run"])
        self.assertTrue(kwargs["start_hidden"])
        fake_app.setQuitOnLastWindowClosed.assert_called_with(False)


@needs_qt
class MainWindowTrayBehaviourTests(unittest.TestCase):
    """The dashboard's own tray-mode behaviour, with a fake JARVIS (no OS access)."""

    def test_close_hides_quit_closes_and_bar_replies_route_back(self):
        qapp()
        from tests.test_cov_gui import FakeJarvis
        import main_gui
        with patch("jarvis.JARVIS", FakeJarvis), patch.object(main_gui.MainWindow, "start_buddy", return_value=False):
            w = main_gui.MainWindow()
            ready = []
            w.ready.connect(lambda: ready.append(1))
            for _ in range(200):
                pump(0.01)
                if ready:
                    break
        self.assertEqual(ready, [1])
        replies = []
        w.bar_reply.connect(replies.append)
        self.assertTrue(w.submit_from_bar("hello"))
        w.input.setText("typed here")
        w.on_send()
        for _ in range(300):
            pump(0.01)
            if len(w._reply_sources) == 0 and replies:
                break
        self.assertEqual(replies, ["echo hello"])           # only the bar's own request comes back to it
        w.hide_on_close = True
        hidden = []
        w.hidden_to_tray.connect(lambda: hidden.append(1))
        w.show()
        w.close()
        self.assertEqual(hidden, [1])
        self.assertFalse(w._closed)
        w.quit_app()
        self.assertTrue(w._closed)


if __name__ == "__main__":
    unittest.main()


@needs_qt
class ShellStateWiringTests(unittest.TestCase):
    """The dashboard's state_changed drives the tray icon and the command bar's orb."""

    def test_state_changed_reaches_tray_and_bar(self):
        qapp()
        from ui.shell import TrayApp
        window = FakeWindow()
        window.state_changed = FakeSignal()
        window.jarvis_state = "offline"
        bar = MagicMock()
        for name in ("submitted", "open_dashboard", "mic_toggled"):
            setattr(bar, name, FakeSignal())
        tray = MagicMock()
        for name in ("ask", "dashboard", "settings", "buddy_toggled", "voice_toggled", "startup_toggled", "quit"):
            setattr(tray, name, FakeSignal())
        with patch("core.hotkeys.TapHotkey"), patch("core.autostart.is_enabled", return_value=False):
            TrayApp(window, bar, tray=tray, start_hidden=True)
            window.ready.emit()
            window.ready.emit()                              # wiring happens once
        tray.set_state.assert_called_with("offline")        # current state applied immediately
        window.state_changed.emit("listening")
        tray.set_state.assert_called_with("listening")
        bar.set_state.assert_called_with("listening")
        self.assertEqual([c.args for c in tray.set_state.call_args_list].count(("listening",)), 1)
        tray.set_busy.assert_not_called()                    # state replaces the old busy flag
