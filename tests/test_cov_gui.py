"""GUI coverage / audit tests: main window, worker queue, live voice, confirmations, settings, launchers.

Runs headless: if there is no display the offscreen Qt platform is selected before the QApplication
is created. The embedded browser is exercised with a fake QWebEngineView (real Chromium can't start
as root in CI), and JARVIS itself is a fake object, so nothing touches the OS.
"""
import io
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if (sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM")
        and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    import main_gui  # imports QtWebEngineWidgets before any QApplication exists
    from PySide6.QtCore import QObject, Signal, QUrl
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
    _QT_ERROR = None
except Exception as exc:  # pragma: no cover - PySide6 missing
    main_gui = None
    _QT_ERROR = exc

import core.config as cfg
from core.config import Config

_APP = None


def app():
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def pump(until=None, timeout=3.0):
    """Process Qt events until ``until()`` is true (or for ``timeout`` seconds when no condition)."""
    end = time.time() + timeout
    while time.time() < end:
        app().processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    app().processEvents()
    return until() if until is not None else True


# ── Fakes ───────────────────────────────────────────────────────────────────

class FakeVoice:
    def __init__(self):
        self.sr_available = True
        self.selected_mic_index = 5
        self.spoken = []
        self.heard = ["hello there"]
        self.stopped = 0
        self.tts_setups = 0

    def speak(self, text, summarize=False):
        self.spoken.append(text)

    def stop_speaking(self):
        self.stopped += 1

    def listen_continuously(self, timeout=30):
        if self.heard:
            return self.heard.pop(0)
        time.sleep(0.02)
        return None

    def listen_for_command(self, timeout=5):
        return "testing"

    def get_available_microphones(self):
        return [{"index": 1, "name": "Mic A", "is_default": True},
                {"index": 5, "name": "Mic B", "is_default": False}]

    def get_current_microphone_info(self):
        return "Mic B"

    def set_microphone(self, index):
        self.selected_mic_index = index
        return True

    def setup_tts(self):
        self.tts_setups += 1


class FakeMemory:
    def __init__(self):
        self.memory = {"user_name": "Tony"}
        self.facts = ["likes jazz", "lives in Pune"]

    def list_facts(self):
        return list(self.facts)

    def remember_fact(self, text):
        self.facts.append(text)

    def forget(self, n):
        self.facts.pop(n - 1)

    def forget_all(self):
        self.facts.clear()


class FakeBrain:
    def __init__(self):
        self.available_models = {"gemini-flash": {"provider": "gemini", "supports_tools": True},
                                 "ollama:llama3.2": {"provider": "ollama", "supports_vision": True}}
        self.current_model = "gemini-flash"
        self.memory = FakeMemory()
        self.catalog_calls = 0
        self.switched = []
        self.cleared = 0

    def get_personality_response(self, kind):
        return "Good day, sir."

    def refresh_catalog_async(self, on_done=None):
        self.catalog_calls += 1
        if on_done:
            threading.Thread(target=on_done, args=("catalog ok",), daemon=True).start()

    def switch_model(self, name):
        self.switched.append(name)
        self.current_model = name
        return f"Switched to {name}"

    def clear_history(self):
        self.cleared += 1

    def _check_local_models(self):
        return ["llama3.2"]

    def _set_default_model(self):
        pass

    def prefer_default_model(self):
        return False

    def _initialize_providers(self):
        pass

    def benchmark_models(self):
        return "bench ok"

    def vision_models(self):
        return ["gemini-flash"]


class FakeDecision:
    def __init__(self):
        self.status = "rules only"
        self.engine, self.model, self.threshold = "rules", "english", 0.45
        self.cb = None
        self.unloaded = 0
        self.warmed = 0

    def set_status_callback(self, fn):
        self.cb = fn

    def unload(self):
        self.unloaded += 1

    def warm_up_async(self):
        self.warmed += 1


class FakeListener:
    def __init__(self):
        self.stopped = threading.Event()

    def stop(self):
        self.stopped.set()


class FakeJarvis:
    def __init__(self, show_banner=False):
        self.brain = FakeBrain()
        self.voice_engine = FakeVoice()
        self.decision = FakeDecision()
        self.skills = {"utility": SimpleNamespace(calculate=lambda e: "4"),
                       "weather": SimpleNamespace(get_weather=lambda c: "error: offline")}
        self.tools = [1, 2, 3]
        self.confirm_callback = self.notify_callback = self.exit_callback = None
        self.app_control = MagicMock()
        self.app_control.discover_applications.return_value = "12 apps"
        self.app_control.launch_app_by_name.side_effect = lambda n: f"Launched {n}"
        self.system_monitor = MagicMock()
        self.system_monitor.get_system_info.return_value = "CPU 5%"
        self.system_control = MagicMock()
        self.screen_automation = MagicMock()
        self.screen_automation.describe_screen.return_value = "A desktop."
        self.screen_automation.take_screenshot.return_value = "/tmp/s.png"
        self.screen_automation.find_and_click_element.return_value = {"message": "Clicked Save"}
        self.command_processor = MagicMock()
        self.command_processor.plan.return_value = SimpleNamespace(describe=lambda: "1. open notepad")
        self.commands = []
        self.confirm_answers = []
        self.block = threading.Event()
        self.stops = 0
        self.shutdowns = 0
        self.is_running = False
        self.voice_output_enabled = False
        self._voice_mode = False
        self.live = None          # what start_live_voice returns (or an Exception to raise)
        self.live_kwargs = None

    def _classify_command_intent(self, text):
        return "command"

    def confirm(self, question):
        return bool(self.confirm_callback(question))

    def process_command(self, text, use_voice=False):
        self.commands.append((text, use_voice, threading.current_thread() is threading.main_thread()))
        if text.startswith("confirm:"):
            answer = self.confirm(text[8:])
            self.confirm_answers.append(answer)
            return "confirmed" if answer else "cancelled"
        if text == "block":
            self.block.wait(10)
        if text == "boom":
            raise RuntimeError("kaput")
        if text == "empty":
            return ""
        return f"echo {text}"

    def stop_current_task(self):
        self.stops += 1

    def _report_missed_tasks(self):
        if self.notify_callback:
            self.notify_callback("You missed: dentist")

    def start_live_voice(self, on_event=None, on_status=None, require_wake_word=False):
        self.live_kwargs = (on_event, on_status)
        if isinstance(self.live, Exception):
            raise self.live
        if on_status:
            on_status("model ready")
        return self.live

    def shutdown(self):
        self.shutdowns += 1
        cb = self.exit_callback
        if cb:
            cb()


class FakeWebView(QWidget if main_gui else object):
    """Stands in for QWebEngineView (Chromium can't run in the test container)."""
    if main_gui:
        urlChanged = Signal(QUrl)
        loadFinished = Signal(bool)
        titleChanged = Signal(str)

    def __init__(self, *a):
        super().__init__(*a)
        self._url = QUrl()
        self.js = []
        self.nav = []

    def setUrl(self, url):
        self._url = url
        self.urlChanged.emit(url)

    def url(self):
        return self._url

    def title(self):
        return ""

    def back(self):
        self.nav.append("back")

    def forward(self):
        self.nav.append("forward")

    def reload(self):
        self.nav.append("reload")

    def page(self):
        view = self

        class Page:
            def runJavaScript(self, code, world=0, callback=None):
                view.js.append(code)
                if callback:
                    callback("result")
        return Page()


# ── Window helpers ──────────────────────────────────────────────────────────

def _jarvis_module(factory):
    return patch.dict(sys.modules, {"jarvis": SimpleNamespace(JARVIS=factory)})


def make_window(factory=FakeJarvis):
    with patch.object(Config, "OLLAMA_AUTOSTART", False), _jarvis_module(factory):
        w = main_gui.MainWindow()
        w.show()
        pump(lambda: w.worker is not None or "failed to start" in w.transcript.toPlainText(), 5)
        pump(timeout=0.1)
    return w


def close_window(w):
    if w.jarvis is not None:
        w.jarvis.block.set()
    with patch("core.ollama_manager.OllamaManager.get") as get:
        get.return_value.stop.return_value = None
        w.close()
    pump(timeout=0.05)
    w.deleteLater()
    pump(timeout=0.05)


@unittest.skipIf(main_gui is None, f"PySide6 unavailable: {_QT_ERROR}")
class GuiTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def setUp(self):
        self._env = patch.dict(os.environ, {})
        self._env.start()
        self.w = None

    def tearDown(self):
        if self.w is not None:
            close_window(self.w)
        self._env.stop()
        Config.reload()

    def window(self, factory=FakeJarvis):
        self.w = make_window(factory)
        return self.w

    def text(self):
        return self.w.transcript.toPlainText()


class MainWindowTests(GuiTestBase):
    def test_startup_chat_and_voice_output(self):
        w = self.window()
        j = w.jarvis
        self.assertTrue(w.worker.isRunning())
        self.assertIs(j.confirm_callback.__func__, main_gui.MainWindow._confirm_from_worker)
        self.assertTrue(w.input.isEnabled())
        self.assertIn("Good day, sir.", self.text())
        pump(lambda: "You missed: dentist" in self.text())
        self.assertEqual(w.model_combo.count(), 2)
        self.assertIn("gemini", w._model_status.text())
        # decision status arrives from a background thread through the bridge
        threading.Thread(target=j.decision.cb, args=("Laya ready (english)",)).start()
        self.assertTrue(pump(lambda: "Laya" in w._decision_dot.text()))
        w.input.setText("hello")
        w.on_send()
        self.assertTrue(pump(lambda: "echo hello" in self.text()))
        self.assertEqual(j.commands[-1], ("hello", False, False))   # ran on the worker, voice off
        w.btn_voice.setChecked(True)
        w.toggle_voice()
        self.assertTrue(j.voice_output_enabled)
        w.quick_command("help")
        self.assertTrue(pump(lambda: ("help", True, False) in j.commands))
        w.btn_voice.setChecked(False)
        w.toggle_voice()
        for cmd, expect in (("boom", "Error: kaput"), ("empty", "Done.")):
            w.quick_command(cmd)
            self.assertTrue(pump(lambda: expect in self.text()))
        w.input.setText("   ")
        w.on_send()
        # model switching / refresh
        w.model_combo.setCurrentIndex(1)
        self.assertEqual(j.brain.switched, ["ollama:llama3.2"])
        w._refresh_all_models()
        self.assertIn("Refreshing model lists", self.text())
        self.assertIn("llama3.2", w._local_ai_dot.toolTip())
        w.on_clear()
        self.assertEqual(j.brain.cleared, 1)
        w._switch_page(2)
        self.assertEqual(w.stack.currentIndex(), 2)
        self.assertTrue(w._nav_buttons[2].isChecked())
        w.on_error("bad")
        self.assertIn("bad", self.text())

    def test_init_failure_leaves_a_usable_window(self):
        def broken(show_banner=False):
            raise RuntimeError("no brain")
        w = self.window(broken)
        self.assertIsNone(w.jarvis)
        self.assertIn("JARVIS failed to start: no brain", self.text())
        self.assertFalse(w.input.isEnabled())
        # none of these may raise without JARVIS
        w.input.setText("hi")
        w.on_send()
        w.btn_voice_chat.setChecked(True)
        w.toggle_voice_chat()
        w.btn_voice.setChecked(True)
        w.toggle_voice()
        for fn in (w.stop_current, w.open_memory, w.open_mic_settings, w.test_voice, w.refresh_system_info,
                   w.take_screenshot_and_analyze, w.take_screenshot_only, w.analyze_current_screen,
                   w.execute_visual_task, w.discover_applications, w.execute_complex_task, w.plan_task_steps,
                   w.pause_task_queue, w.resume_task_queue, w.clear_task_queue, w.update_skills_tree,
                   w.test_all_skills, w.test_selected_skill, w._on_ollama_ready, w._refresh_all_models,
                   w.refresh_models, w.on_clear):
            fn()
        w._on_model_change = w.on_model_change("x")
        self.assertIsNone(w.worker)
        self.assertFalse(w.threads_still_running())

    def test_task_queue_pause_resume_clear(self):
        w = self.window()
        worker = w.worker
        ran = []
        gate = threading.Event()
        w.pause_task_queue()
        self.assertIn("PAUSED", w._queue_label.text())
        for i in range(3):
            w._run_task(f"task {i}", lambda i=i: ran.append(i) or f"done {i}", kind="task")
        self.assertEqual(w.task_queue_list.count(), 3)
        self.assertIn("3 waiting (PAUSED)", w._queue_label.text())
        # chat still has priority and runs while the queue is paused
        w.quick_command("still chatting")
        self.assertTrue(pump(lambda: "echo still chatting" in self.text()))
        pump(timeout=0.3)
        self.assertEqual(ran, [])
        w.resume_task_queue()
        self.assertTrue(pump(lambda: ran == [0, 1, 2]))
        self.assertTrue(pump(lambda: "done 2" in self.text()))
        self.assertTrue(pump(lambda: w.task_queue_list.count() == 0))
        # clear drops only pending tasks; the running one finishes
        w._run_task("long", lambda: gate.wait(5) and "long done")
        self.assertTrue(pump(lambda: w.btn_stop.isVisibleTo(w)))
        w._run_task("never", lambda: ran.append("never"))
        w.clear_task_queue()
        self.assertEqual(w.task_queue_list.count(), 0)
        w.stop_current()
        self.assertEqual(w.jarvis.stops, 1)
        gate.set()
        self.assertTrue(pump(lambda: "long done" in w.automation_log.toPlainText()))
        pump(timeout=0.3)
        self.assertNotIn("never", ran)
        self.assertFalse(w.btn_stop.isVisibleTo(w))
        self.assertTrue(worker.isRunning())

    def test_automation_and_system_pages(self):
        w = self.window()
        j = w.jarvis
        log = w.automation_log.toPlainText
        w.take_screenshot_only()
        w.analyze_current_screen()
        w.take_screenshot_and_analyze()
        w.visual_task_input.setText("the Save button")
        w.execute_visual_task()
        w.discover_applications()
        with patch.object(main_gui.QInputDialog, "getText", return_value=("notepad", True)):
            w.launch_application_dialog()
        w.complex_task_input.setPlainText("open notepad and type hi")
        w.plan_task_steps()
        self.assertIn("1. open notepad", log())
        w.execute_complex_task()
        for expect in ("Screenshot saved to /tmp/s.png", "A desktop.", "Clicked Save", "12 apps",
                       "Launched notepad", "echo open notepad and type hi"):
            self.assertTrue(pump(lambda: expect in log()), expect)
        self.assertIn("A desktop.", self.text())
        # skills
        w.update_skills_tree()
        self.assertEqual(w.skills_tree.topLevelItemCount(), 4)
        w.skills_tree.setCurrentItem(w.skills_tree.topLevelItem(0))
        w.test_selected_skill()
        w.test_all_skills()
        self.assertTrue(pump(lambda: "✅ utility: 4" in self.text() and "⚠️ weather" in self.text()))
        # system info comes back from a plain thread via a signal (QTimer from that thread never fires)
        w.system_info.clear()
        w.refresh_system_info()
        self.assertTrue(pump(lambda: w.system_info.toPlainText() == "CPU 5%"))
        j.system_monitor.get_system_info.side_effect = RuntimeError("wmi down")
        w.refresh_system_info()
        self.assertTrue(pump(lambda: "Error: wmi down" in w.system_info.toPlainText()))
        j.system_monitor = None
        j.system_control.get_system_status.return_value = "status ok"
        w.refresh_system_info()
        self.assertTrue(pump(lambda: w.system_info.toPlainText() == "status ok"))
        w.test_voice()
        self.assertTrue(pump(lambda: j.voice_engine.spoken))
        with patch.object(main_gui.QMessageBox, "about") as about:
            w.show_about()
        about.assert_called_once()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "chat.txt")
            with patch.object(main_gui.QFileDialog, "getSaveFileName", return_value=(out, "")):
                w.export_chat()
            self.assertIn("Good day", Path(out).read_text(encoding="utf-8"))
            bad = os.path.join(tmp, "missing", "chat.txt")
            with patch.object(main_gui.QFileDialog, "getSaveFileName", return_value=(bad, "")), \
                    patch.object(main_gui.QMessageBox, "warning") as warn:
                w.export_chat()
            warn.assert_called_once()

    def test_ollama_status_from_its_thread_reaches_gui_thread(self):
        w = self.window()
        calls = []
        real = w._on_ollama_ready

        def spy():
            calls.append(threading.current_thread() is threading.main_thread())
            real()
        w._on_ollama_ready = spy

        class Mgr:
            def start(self, on_status):
                threading.Thread(target=on_status, args=("Ollama ready",)).start()
        with patch("core.ollama_manager.OllamaManager.get", return_value=Mgr()):
            w._start_ollama()
        self.assertTrue(pump(lambda: len(calls) >= 1, 2))
        self.assertTrue(all(calls))
        self.assertTrue(pump(lambda: "Local AI: Ollama ready" in self.text()))
        with patch("core.ollama_manager.OllamaManager.get", side_effect=RuntimeError("no ollama")):
            w._start_ollama()


class LiveVoiceTests(GuiTestBase):
    def test_live_events_render(self):
        w = self.window()
        events = [("partial", {"text": "open chrome and go"}),
                  ("heard", {"text": "open chrome and go to github"}),
                  ("dispatched", {"text": "open chrome", "lane": 0}),
                  ("dispatched", {"text": "open the alarm", "lane": 1}),
                  ("step_done", {"lane": 1, "text": "open the alarm", "reply": "Opened Alarms."}),
                  ("ask", {"question": "Close Chrome?"}),
                  ("unknown", None)]

        def fire():
            for kind, info in events:
                w._bridge.live_event.emit(kind, info)
        threading.Thread(target=fire).start()
        self.assertTrue(pump(lambda: "Close Chrome? (say yes or no)" in self.text()))
        self.assertIn("open chrome and go", w._thinking_lbl.text())
        t = self.text()
        self.assertIn("▶ open chrome\n", t + "\n")
        self.assertIn("▶ open the alarm · lane 2", t)
        self.assertIn("ACTION", t)
        self.assertIn("[lane 2] open the alarm → Opened Alarms.", w.automation_log.toPlainText())
        w._on_live_event("utterance_done", {"summary": "Opened Chrome.", "details": "Ran 2 steps"})
        self.assertIn("Ran 2 steps", self.text())
        self.assertEqual(w._thinking_lbl.text(), "")
        self.assertTrue(pump(lambda: "Opened Chrome." in w.jarvis.voice_engine.spoken))
        w._on_live_event("step_done", {})          # malformed info must not raise in the slot

    def _mic(self, on):
        self.w.btn_voice_chat.setChecked(on)
        self.w.toggle_voice_chat()

    def test_live_voice_start_and_stop(self):
        w = self.window()
        listener = FakeListener()
        w.jarvis.live = listener
        with patch.object(Config, "LIVE_VOICE", True), patch("core.streaming.vosk_available", return_value=True):
            self._mic(True)
            self.assertTrue(pump(lambda: w._live_listener is listener))
            self.assertIn("Live voice starting", self.text())
            self.assertTrue(pump(lambda: "model ready" in self.text()))
            on_event = w.jarvis.live_kwargs[0]
            threading.Thread(target=on_event, args=("heard", {"text": "what time is it"})).start()
            self.assertTrue(pump(lambda: "what time is it" in self.text()))
            self._mic(False)
            self.assertTrue(listener.stopped.is_set())
            self.assertIsNone(w._live_listener)
            self.assertIn("Voice chat stopped.", self.text())

    def test_live_voice_switched_off_while_loading(self):
        w = self.window()
        listener = FakeListener()
        w.jarvis.live = listener
        w.voice_chat_active = False
        w._start_live_voice(session=w._voice_session)       # mic already off → listener stopped at once
        self.assertTrue(listener.stopped.is_set())
        self.assertIsNone(w._live_listener)
        w.voice_chat_active = True
        stale = FakeListener()
        w.jarvis.live = stale
        w._start_live_voice(session=w._voice_session - 1)   # superseded by a later toggle
        self.assertTrue(stale.stopped.is_set())
        self.assertIsNone(w._live_listener)

    def test_live_voice_unavailable_falls_back_to_classic(self):
        for live in (None, RuntimeError("no mic")):
            with self.subTest(live=live):
                if self.w is not None:
                    close_window(self.w)
                w = self.window()
                w.jarvis.live = live
                with patch.object(Config, "LIVE_VOICE", True), \
                        patch("core.streaming.vosk_available", return_value=True):
                    self._mic(True)
                    self.assertTrue(pump(lambda: w.voice_chat_worker is not None))
                    self.assertTrue(pump(lambda: "echo hello there" in self.text()))
                    self.assertIn("using normal voice chat", self.text())
                    self.assertTrue(pump(lambda: "echo hello there" in w.jarvis.voice_engine.spoken))
                    worker = w.voice_chat_worker
                    self._mic(False)
                    self.assertIsNone(w.voice_chat_worker)
                    self.assertTrue(worker.wait(2000))
                    self.assertFalse(w.jarvis._voice_mode)

    def test_classic_voice_chat_and_errors(self):
        w = self.window()
        v = w.jarvis.voice_engine
        v.sr_available = False
        self._mic(True)
        self.assertFalse(w.btn_voice_chat.isChecked())
        self.assertIn("Speech recognition isn't installed", self.text())
        v.sr_available = True
        calls = {"n": 0}

        def flaky(timeout=30):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("mic unplugged")
            time.sleep(0.02)
            return None
        v.listen_continuously = flaky
        with patch.object(Config, "LIVE_VOICE", False):
            self._mic(True)
            self.assertTrue(pump(lambda: "Voice chat error: mic unplugged" in self.text()))
            w._start_classic_voice_chat()            # already running: must not start a second worker
            self._mic(False)
        self.assertGreaterEqual(v.stopped, 1)

    def test_stuck_voice_worker_is_kept_alive_until_it_finishes(self):
        w = self.window()
        release = threading.Event()
        w.jarvis.voice_engine.listen_continuously = lambda timeout=30: release.wait(10) and None
        with patch.object(Config, "LIVE_VOICE", False):
            self._mic(True)
            pump(lambda: w.voice_chat_worker.isRunning())
            worker = w.voice_chat_worker
            with patch.object(worker, "wait", side_effect=lambda ms=0: main_gui.QThread.wait(worker, 10)):
                self._mic(False)
        self.assertIn(worker, w._retired_threads)          # not garbage-collected while running
        self.assertTrue(w.threads_still_running())
        release.set()
        self.assertTrue(pump(lambda: not w._retired_threads, 3))
        self.assertTrue(worker.isFinished())


class ConfirmTests(GuiTestBase):
    def test_confirm_from_worker_blocks_worker_not_gui(self):
        w = self.window()
        j = w.jarvis
        shown = []

        def answer(box, reply):
            shown.append(threading.current_thread() is threading.main_thread())
            return reply
        for reply, expect in ((QMessageBox.Yes, "confirmed"), (QMessageBox.No, "cancelled")):
            with patch.object(main_gui.QMessageBox, "exec", lambda box, r=reply: answer(box, r)):
                w.quick_command("confirm:Delete the file?")
                self.assertTrue(pump(lambda: len(j.confirm_answers) == len(shown) and shown, 5))
                self.assertTrue(pump(lambda: expect in self.text()))
        self.assertEqual(j.confirm_answers, [True, False])
        self.assertEqual(shown, [True, True])     # dialog on the GUI thread

    def test_timed_out_confirm_closes_its_dialog(self):
        w = self.window()
        real_wait = threading.Event.wait
        result, opened, closed = {}, [], []

        def fake_exec(box):
            opened.append(box)
            box.rejected.connect(lambda: closed.append(True))
            return real_exec(box)
        real_exec = main_gui.QMessageBox.exec

        def short_wait(event, timeout=None):
            return real_wait(event, 0.3 if timeout == 300 else timeout)
        with patch.object(threading.Event, "wait", short_wait), \
                patch.object(main_gui.QMessageBox, "exec", fake_exec):
            t = threading.Thread(target=lambda: result.setdefault("a", w._confirm_from_worker("Format?")))
            t.start()
            self.assertTrue(pump(lambda: not t.is_alive() and closed, 5))
        self.assertIs(result["a"], False)             # the worker gave up...
        self.assertEqual(len(opened), 1)              # ...and the dialog it asked for went away

    def test_confirm_on_main_thread_uses_direct_dialog(self):
        w = self.window()
        with patch.object(main_gui.QMessageBox, "question", return_value=QMessageBox.Yes):
            self.assertTrue(w._confirm_from_worker("Sure?"))

    def test_close_releases_a_waiting_confirmation(self):
        w = self.window()
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("a", w._confirm_from_worker("Shut down?")))
        t.start()
        end = time.time() + 2
        while not w._pending_confirms and time.time() < end:
            time.sleep(0.01)       # no event processing: the dialog signal stays queued
        self.assertTrue(w._pending_confirms)
        with patch.object(main_gui.QMessageBox, "exec", side_effect=AssertionError("dialog after close")) as ex:
            close_window(w)
            t.join(2)
            pump(timeout=0.2)
        self.w = None
        self.assertFalse(t.is_alive())
        self.assertIs(result["a"], False)
        ex.assert_not_called()
        self.assertFalse(w._confirm_from_worker("again?"))


class DashboardRoutingTests(GuiTestBase):
    def test_dashboard_runs_on_the_worker_even_when_paused(self):
        w = self.window()
        j = w.jarvis
        self.assertEqual(j.dashboard_runner.__func__, main_gui.MainWindow._run_for_dashboard)
        threads = []
        real = j.process_command

        def spy(text, use_voice=True):
            threads.append(main_gui.QThread.currentThread())
            return real(text, use_voice=use_voice)
        j.process_command = spy
        w.worker.pause()                               # a paused automation queue must not block it
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("r", w._run_for_dashboard("hello", timeout=5)))
        t.start()
        self.assertTrue(pump(lambda: not t.is_alive(), 6))
        self.assertEqual(threads, [w.worker])          # ran on the single command worker
        self.assertTrue(result["r"])

    def test_dashboard_after_close_is_refused(self):
        w = self.window()
        w._closing = True
        self.assertIn("shutting down", w._run_for_dashboard("hi"))


class LifecycleTests(GuiTestBase):
    def test_close_stops_everything(self):
        w = self.window()
        j, worker = w.jarvis, w.worker
        listener = FakeListener()
        w._live_listener = listener
        browser = MagicMock()
        w._browser_win = browser
        start = time.time()
        with patch("core.ollama_manager.OllamaManager.get") as get:
            w.close()
            get.return_value.stop.assert_called_once()
        self.assertLess(time.time() - start, 3)
        self.assertTrue(worker.wait(2000))
        self.assertTrue(listener.stopped.is_set())
        browser.close.assert_called_once()
        self.assertEqual(j.shutdowns, 1)
        self.assertGreaterEqual(j.stops, 1)
        self.assertIsNone(j.exit_callback)
        self.assertFalse(w.threads_still_running())
        w.close()                              # second close is a no-op
        self.assertEqual(j.shutdowns, 1)

    def test_exit_requested_from_worker_closes_window(self):
        w = self.window()
        j = w.jarvis
        threading.Thread(target=j.exit_callback).start()
        self.assertTrue(pump(lambda: not w.isVisible()))
        self.assertTrue(w.worker.wait(2000))

    def test_close_with_busy_worker_returns(self):
        w = self.window()
        w.quick_command("block")
        pump(lambda: w.btn_stop.isVisibleTo(w))
        with patch.object(w.worker, "wait", return_value=False), \
                patch("core.ollama_manager.OllamaManager.get"):
            w.close()
        self.assertTrue(w.threads_still_running())
        w.jarvis.block.set()
        self.assertTrue(main_gui.QThread.wait(w.worker, 3000))
        self.assertFalse(w.threads_still_running())

    def test_shutdown_errors_are_logged(self):
        w = self.window()
        w.jarvis.shutdown = MagicMock(side_effect=RuntimeError("x"))
        w._live_listener = MagicMock()
        w._live_listener.stop.side_effect = RuntimeError("y")
        with patch("core.ollama_manager.OllamaManager.get", side_effect=RuntimeError("z")):
            w.close()
        self.assertTrue(w._closed)

    def test_main_entry_point(self):
        fake_app = MagicMock()
        fake_app.exec.return_value = 0
        win = MagicMock()
        for busy in (False, True):
            win.threads_still_running.return_value = busy
            with patch.object(main_gui, "QApplication") as qa, patch.object(main_gui, "MainWindow", return_value=win), \
                    patch.object(main_gui, "setup_logging"), patch.object(main_gui.os, "_exit") as hard_exit:
                qa.return_value = fake_app
                with self.assertRaises(SystemExit):
                    main_gui.main()
            self.assertEqual(hard_exit.called, busy)


class DialogTests(GuiTestBase):
    def test_settings_and_memory_from_window(self):
        w = self.window()
        j = w.jarvis
        with patch.object(main_gui.SettingsDialog, "exec", return_value=0):
            w.open_settings()
        self.assertNotIn("Settings saved.", self.text())
        with patch.object(main_gui.SettingsDialog, "exec", return_value=1), \
                patch("core.config.load_env"), patch.dict(os.environ, {"JARVIS_DECISION_ENGINE": "laya"}):
            w.open_settings()
        self.assertIn("Settings saved.", self.text())
        self.assertEqual((j.decision.engine, j.decision.unloaded, j.decision.warmed), ("laya", 1, 1))
        self.assertEqual(j.voice_engine.tts_setups, 1)
        j.voice_engine.setup_tts = MagicMock(side_effect=RuntimeError("no sapi"))
        with patch.object(main_gui.SettingsDialog, "exec", return_value=1), patch("core.config.load_env"):
            w.open_settings()
        self.assertIn("could not all be applied", self.text())
        with patch.object(main_gui.MemoryDialog, "exec", return_value=0) as ex:
            w.open_memory()
        ex.assert_called_once()
        with patch.object(main_gui.MicrophoneSettingsDialog, "exec", return_value=0) as ex:
            w.open_mic_settings()
        ex.assert_called_once()

    def test_memory_dialog(self):
        mem = FakeMemory()
        with patch.dict(os.environ, {"JARVIS_LOCATION": "Pune"}):
            d = main_gui.MemoryDialog(mem)
        self.assertIn("Tony", d.header.text())
        self.assertEqual(d.facts.count(), 2)
        with patch.object(main_gui.QInputDialog, "getText", return_value=("drinks tea", True)):
            d._add()
        self.assertEqual(d.facts.count(), 3)
        d.facts.setCurrentRow(0)
        d._forget()
        self.assertEqual(mem.facts, ["lives in Pune", "drinks tea"])
        with patch.object(main_gui.QMessageBox, "question", return_value=QMessageBox.No):
            d._wipe()
        self.assertEqual(len(mem.facts), 2)
        with patch.object(main_gui.QMessageBox, "question", return_value=QMessageBox.Yes):
            d._wipe()
        self.assertEqual(d.facts.count(), 0)
        d.deleteLater()

    def test_microphone_dialog_selects_the_right_row(self):
        v = FakeVoice()
        with patch.multiple(main_gui.QMessageBox, information=MagicMock(), warning=MagicMock(),
                            critical=MagicMock()):
            d = main_gui.MicrophoneSettingsDialog(v)
            self.assertEqual(d.mic_list.currentItem().text(), "[5] Mic B")   # device 5 is row 1
            d.mic_list.setCurrentRow(0)
            d.test_microphone()
            main_gui.QMessageBox.information.assert_called()
            v.listen_for_command = lambda timeout=5: None
            d.test_microphone()
            main_gui.QMessageBox.warning.assert_called()
            v.set_microphone = lambda i: False
            d.test_microphone()
            main_gui.QMessageBox.critical.assert_called()
            d.accept()
            v.set_microphone = lambda i: True
            d.mic_list.setCurrentRow(1)
            d.accept()
            v.get_available_microphones = lambda: []
            d.populate_microphones()
            self.assertEqual(d.mic_list.item(0).text(), "No microphones found")
            d.mic_list.setCurrentRow(0)
            d.test_microphone()       # unparsable row → error box, no exception
            d.accept()
            d.mic_list.clearSelection()
            d.mic_list.setCurrentItem(None)
            d.test_microphone()
        d.deleteLater()


class BrowserTests(GuiTestBase):
    def test_browser_via_signals_with_fake_webengine(self):
        w = self.window()
        with patch.object(main_gui, "QWebEngineView", FakeWebView), patch.object(main_gui, "WEBENGINE_AVAILABLE", True):
            threading.Thread(target=w._on_browser_open, args=("example.com",)).start()
            self.assertTrue(pump(lambda: w._browser_win is not None))
            b = w._browser_win
            self.assertTrue(pump(lambda: b.webview.url().toString() == "https://example.com"))
            self.assertEqual(b._url_bar.text(), "https://example.com")
            threading.Thread(target=w._on_browser_open, args=("github.com", "1+1")).start()
            self.assertTrue(pump(lambda: b.webview.url().toString() == "https://github.com"))
            with patch.object(main_gui.QTimer, "singleShot", side_effect=lambda ms, fn: fn()):
                b.webview.loadFinished.emit(True)
            self.assertEqual(b.webview.js, ["1+1"])
            b._exec_pending_js(True)                  # nothing pending: no-op
            got = []
            w.run_js("document.title", got.append)
            self.assertEqual(got, ["result"])
            b.get_page_text(got.append)
            b._js_bar.setText("2+2")
            b._run_js_bar()
            self.assertIn("JS → result", b._status_lbl.text())
            b._run_js_bar()
            b._url_bar.setText("")
            b._go()
            b._url_bar.setText("python.org")
            b._go()
            self.assertEqual(b.webview.url().toString(), "https://python.org")
            b._load_finished(True)
            b.webview.titleChanged.emit("Python")
            self.assertIn("Python", b.windowTitle())
            b._back_btn.click(); b._forward_btn.click(); b._reload_btn.click()
            self.assertEqual(b.webview.nav, ["back", "forward", "reload"])
            w.navigate_browser_with_js("https://x.org", "go()")

    def test_browser_falls_back_to_system_browser(self):
        w = self.window()
        with patch("webbrowser.open") as wb, patch.object(main_gui, "WEBENGINE_AVAILABLE", False):
            w.navigate_browser("example.com")
            w.navigate_browser_with_js("example.com", "x()")
            w.run_js("x")
        self.assertEqual(wb.call_count, 2)
        with patch("webbrowser.open") as wb, patch.object(main_gui, "WEBENGINE_AVAILABLE", True), \
                patch.object(main_gui, "BrowserWindow", side_effect=RuntimeError("no GPU")):
            w.navigate_browser("https://example.com")
        wb.assert_called_once_with("https://example.com")


# ── Settings dialog round trip ──────────────────────────────────────────────

@unittest.skipIf(main_gui is None, f"PySide6 unavailable: {_QT_ERROR}")
class SettingsDialogTests(unittest.TestCase):
    ENV = ('GEMINI_API_KEY="secret-key"\n'
           'JARVIS_VOSK_MODEL_NAME="vosk-model-small-de-0.15"\n'
           'JARVIS_REQUEST_TIMEOUT="600"\n'
           'JARVIS_VOICE_VOLUME="0.9"\n'
           'JARVIS_DECISION_THRESHOLD="0.475"\n'
           'JARVIS_LOCATION="Chennai, India"\n'
           'SOMETHING_ELSE="kept"\n')

    @classmethod
    def setUpClass(cls):
        app()

    def setUp(self):
        from ui import settings as st
        self.st = st
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "Jarvis"
        self.dir.mkdir()
        self.env_path = self.dir / ".env"
        self.env_path.write_text(self.ENV, encoding="utf-8")
        self.patches = [patch.object(cfg, "ENV_PATH", self.env_path), patch.object(cfg, "APPDATA_DIR", self.dir),
                        patch.dict(os.environ, {})]
        for p in self.patches:
            p.start()
        for key in list(os.environ):
            if key.startswith("JARVIS_") or key in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_VISION_MODEL"):
                del os.environ[key]
        cfg.load_env()
        Config.reload()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        Config.reload()
        self.tmp.cleanup()

    def dialog(self, **kw):
        d = self.st.SettingsDialog(**kw)
        self.addCleanup(d.deleteLater)
        return d

    def test_ok_without_changes_keeps_env_byte_for_byte(self):
        d = self.dialog()
        self.assertEqual(d.gemini_edit.text(), "secret-key")
        self.assertEqual(d.gemini_edit.echoMode(), self.st.QLineEdit.Password)
        self.assertEqual(d.stt_model.currentData(), "vosk-model-small-de-0.15")   # unknown value kept
        self.assertEqual(d.location_edit.text(), "Chennai, India")
        self.assertEqual(d.get_values(), ("", "secret-key", "Chennai, India"))
        d.accept()
        self.assertEqual(d.result(), self.st.QDialog.Accepted)
        self.assertEqual(self.env_path.read_text(encoding="utf-8"), self.ENV)
        cfg.load_env()
        Config.reload()
        self.assertEqual((Config.REQUEST_TIMEOUT, Config.VOSK_MODEL_NAME), (600, "vosk-model-small-de-0.15"))

    def test_changes_are_saved_and_cleared_keys_removed(self):
        d = self.dialog(decision=SimpleNamespace(status="Laya ready"))
        d.gemini_edit.setText("")
        d.openrouter_edit.setText("or-key")
        d.engine.setCurrentIndex(d.engine.findData("rules"))
        d.stt_model.setCurrentIndex(d.stt_model.findData("vosk-model-small-en-us-0.15"))
        d.live_voice.setChecked(False)
        d.wake_word.setText("Friday")
        d.location_edit.setText("  ")
        d.accept()
        text = self.env_path.read_text(encoding="utf-8")
        self.assertNotIn("GEMINI_API_KEY", text)
        self.assertNotIn("JARVIS_LOCATION", text)
        for line in ('OPENROUTER_API_KEY=\'or-key\'', 'JARVIS_DECISION_ENGINE=\'rules\'', 'JARVIS_LIVE_VOICE=\'0\'',
                     'JARVIS_WAKE_WORD=\'friday\'', 'JARVIS_VOSK_MODEL_NAME=\'vosk-model-small-en-us-0.15\''):
            key, value = line.split("=", 1)
            self.assertRegex(text, rf'{key}=["\']{value.strip(chr(39))}["\']')
        for untouched in ('JARVIS_REQUEST_TIMEOUT="600"', 'JARVIS_DECISION_THRESHOLD="0.475"', 'SOMETHING_ELSE="kept"'):
            self.assertIn(untouched, text)
        Config.reload()
        self.assertEqual((Config.OPENROUTER_API_KEY, Config.GEMINI_API_KEY, Config.DECISION_ENGINE,
                          Config.LIVE_VOICE, Config.WAKE_WORD), ("or-key", "", "rules", False, "friday"))

    def test_failed_save_warns_and_keeps_dialog_open(self):
        d = self.dialog()
        d.default_model.setText("line1\nline2")      # save_setting rejects multi-line values
        d.show()
        with patch.object(self.st.QMessageBox, "warning") as warn:
            d.accept()
        warn.assert_called_once()
        self.assertTrue(d.isVisible())
        d.reject()

    def test_combo_helper(self):
        box = self.st._combo([("a", "A"), ("b", "B")], "b")
        self.assertEqual(box.currentData(), "b")
        box = self.st._combo([("a", "A")], "")
        self.assertEqual((box.currentData(), box.count()), ("a", 1))
        box = self.st._combo([("a", "A")], "zz")
        self.assertEqual((box.currentData(), box.count()), ("zz", 2))


# ── Launchers ───────────────────────────────────────────────────────────────

class DoctorTests(unittest.TestCase):
    def setUp(self):
        import doctor
        self.doctor = doctor
        self.cwd = os.getcwd()
        self.addCleanup(os.chdir, self.cwd)
        doctor.results.clear()
        self.addCleanup(doctor.results.clear)

    def _run(self, argv):
        brain = MagicMock()
        brain.refresh_catalog.return_value = "catalog"
        brain.available_models = {"m": {}}
        brain.benchmark_models.return_value = "bench"
        voice = MagicMock()
        voice.get_available_microphones.return_value = []
        voice.tts_engine = None
        engine = MagicMock()
        engine.laya_ready = True
        engine.decide.return_value = SimpleNamespace(intent="time", confidence=0.9, source="laya", multi_step=0.1)
        out = io.StringIO()
        with patch.object(sys, "argv", ["doctor.py"] + argv), redirect_stdout(out), \
                patch("requests.get", side_effect=OSError("down")), \
                patch("core.brain.MultiModelBrain", return_value=brain), \
                patch("core.voice.VoiceEngine", return_value=voice), \
                patch("core.decision.DecisionEngine", return_value=engine), \
                patch("core.streaming.vosk_available", return_value=True), \
                patch("core.streaming.model_ready", return_value=False), \
                patch("core.streaming.ensure_model", side_effect=lambda name, on_progress: on_progress("50%")):
            code = self.doctor.main()
        return code, out.getvalue()

    def test_main_quick_and_full(self):
        code, out = self._run([])
        self.assertIn("checks passed", out)
        self.assertIn(code, (0, 1))
        self.doctor.results.clear()
        code, out = self._run(["--live", "--laya", "--get-voice-model"])
        self.assertIn("what time is it", out)
        self.assertIn("bench", out)
        self.assertIn("download failed", out)
        self.assertEqual(code, 1)

    def test_check_helpers(self):
        out = io.StringIO()
        with redirect_stdout(out):
            with patch("requests.get") as get:
                get.return_value.json.return_value = {"models": [{"name": "llama3.2"}]}
                self.doctor.check_ollama()
            with patch("core.voice.VoiceEngine", side_effect=RuntimeError("no audio")), \
                    patch("core.streaming.vosk_available", side_effect=RuntimeError("bad vosk")):
                self.doctor.check_voice()
            with patch("core.streaming.vosk_available", return_value=False):
                self.doctor.check_voice()
            with patch("core.streaming.vosk_available", return_value=True), \
                    patch("core.streaming.model_ready", return_value=True):
                self.doctor.check_voice()
            engine = MagicMock(laya_ready=False, status="not installed")
            with patch("core.decision.DecisionEngine", return_value=engine):
                self.doctor.check_laya()
            with patch("core.streaming.ensure_model", side_effect=RuntimeError("offline")):
                self.doctor.get_voice_model()
        text = out.getvalue()
        for expect in ("llama3.2", "no audio", "bad vosk", "pip install vosk", "speech model ready", "not installed",
                       "offline"):
            self.assertIn(expect, text)


class RunJarvisTests(unittest.TestCase):
    def setUp(self):
        import run_jarvis
        self.rj = run_jarvis

    def _run(self, argv, factory=None, jarvis_dir=None):
        fake = MagicMock()
        factory = factory or MagicMock(return_value=fake)
        out = io.StringIO()
        mods = {"jarvis": SimpleNamespace(JARVIS=factory)}
        with patch.object(sys, "argv", ["run_jarvis.py"] + argv), redirect_stdout(out), \
                patch.dict(sys.modules, mods), \
                patch.object(self.rj, "jarvis_dir", Path(jarvis_dir) if jarvis_dir else self.rj.jarvis_dir):
            self.rj.main()
        return fake, out.getvalue()

    def test_modes(self):
        fake, out = self._run([])
        fake.start.assert_called_once_with("text")
        fake.shutdown.assert_called_once()
        fake, out = self._run(["voice"])
        fake.start.assert_called_once_with("voice")
        fake, out = self._run(["text"])
        self.assertIn("text mode", out)
        fake, out = self._run(["bogus"])
        self.assertIn("Unknown mode", out)
        fake, out = self._run(["help"])
        self.assertIn("Usage", out)
        fake.start.assert_not_called()
        if main_gui is None:
            return                          # the "gui" mode needs PySide6
        with patch("main_gui.main") as gui_main:
            self._run(["gui"])
        gui_main.assert_called_once()

    def test_errors(self):
        for exc, expect in ((KeyboardInterrupt(), "shutdown by user"), (ImportError("no rich"), "Import error"),
                            (RuntimeError("boom"), "Error starting JARVIS")):
            _, out = self._run([], factory=MagicMock(side_effect=exc))
            self.assertIn(expect, out)
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self._run([], jarvis_dir=tmp)
        self.assertIn("jarvis.py not found", out)


class SetupScriptTests(unittest.TestCase):
    def test_main(self):
        import setup as setup_script
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("requests\nlaya>=1\n", encoding="utf-8")
            (root / ".env.example").write_text("X=1\n", encoding="utf-8")
            appdir = root / "Jarvis"
            env = appdir / ".env"
            engine = MagicMock(laya_ready=True, status="Laya ready")
            seen = []

            def fake_run(args):
                if "-r" in args:
                    seen.append(Path(args[-1]).read_text(encoding="utf-8"))
                return SimpleNamespace(returncode=1 if "-r" in args else 0)
            out = io.StringIO()
            with patch.object(setup_script, "ROOT", root), patch.object(cfg, "ENV_PATH", env), \
                    patch.object(cfg, "APPDATA_DIR", appdir), patch("subprocess.run", side_effect=fake_run), \
                    patch("core.decision.DecisionEngine", return_value=engine), redirect_stdout(out):
                with patch.object(sys, "argv", ["setup.py", "--no-laya", "--laya"]):
                    self.assertEqual(setup_script.main(), 0)
                with patch.object(sys, "argv", ["setup.py"]):
                    self.assertEqual(setup_script.main(), 0)
                with patch.object(sys, "version_info", (3, 8)):
                    self.assertEqual(setup_script.main(), 1)
            self.assertEqual(env.read_text(encoding="utf-8"), "X=1\n")
            self.assertNotIn("laya", seen[0])
            self.assertIn("laya", seen[1])
            self.assertFalse((root / "requirements-nolaya.tmp.txt").exists())
            text = out.getvalue()
            self.assertIn("Created settings file", text)
            self.assertIn("Settings file exists", text)
            self.assertIn("failed", text)
            self.assertIn("Laya ready", text)


if __name__ == "__main__":
    unittest.main()
