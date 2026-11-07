"""The HUD dashboard: state API, hero, chat view, typing indicator, activity panel, gauges.

Headless (offscreen Qt) with the fake JARVIS from test_cov_gui, so nothing touches the OS.
"""
import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

if (sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM")
        and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    import main_gui
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget
    from ui import chat_view, dash_widgets
    from ui.activity import ActivityPanel
    from tests.test_cov_gui import FakeJarvis, FakeMemory, app, close_window, pump
    _QT_ERROR = None
except Exception as exc:  # pragma: no cover - PySide6 missing
    main_gui = None
    _QT_ERROR = exc

from core.config import Config


class QuietJarvis(FakeJarvis if main_gui else object):
    """No missed-task notice at start-up, so the conversation starts empty."""

    def _report_missed_tasks(self):
        pass


def make(factory=None):
    factory = factory or QuietJarvis
    with patch.object(Config, "OLLAMA_AUTOSTART", False), patch.object(Config, "BUDDY_ENABLED", False), \
            patch.dict(sys.modules, {"jarvis": SimpleNamespace(JARVIS=factory)}):
        w = main_gui.MainWindow()
        w.resize(1280, 820)
        w.show()
        pump(lambda: w.worker is not None or w._init_failed, 5)
        pump(timeout=0.1)
    return w


@unittest.skipIf(main_gui is None, f"PySide6 unavailable: {_QT_ERROR}")
class DashboardBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def setUp(self):
        self.w = None

    def tearDown(self):
        if self.w is not None:
            close_window(self.w)
        Config.reload()

    def window(self, factory=None):
        self.w = make(factory)
        return self.w


class StateApiTests(DashboardBase):
    def test_offline_until_jarvis_is_initialised(self):
        with patch.object(Config, "OLLAMA_AUTOSTART", False), \
                patch.dict(sys.modules, {"jarvis": SimpleNamespace(JARVIS=QuietJarvis)}):
            w = main_gui.MainWindow()           # no events processed yet: JARVIS not built
            self.assertEqual(w.jarvis_state, "offline")
            self.assertEqual(w.status_pill.state, "offline")
            self.assertEqual(w.header_orb.state, "offline")
            self.assertFalse(w.input.isEnabled())
            w.show()
            self.assertTrue(pump(lambda: w.worker is not None, 5))
        self.w = w
        self.assertEqual(w.jarvis_state, "idle")
        self.assertTrue(w.input.isEnabled())

    def test_set_jarvis_state_drives_every_surface_and_signals_changes(self):
        w = self.window()
        seen = []
        w.state_changed.connect(seen.append)
        w.set_jarvis_state("thinking", "Looking it up")
        for surface in (w.header_orb, w.chat.hero.orb, w.activity.state_card.orb):
            self.assertEqual(surface.state, "thinking")
        self.assertEqual(w.status_pill.state, "thinking")
        self.assertIn("LOOKING IT UP", w.status_pill.text().upper())
        self.assertEqual(w.activity.state, "thinking")
        self.assertEqual(w.activity.state_card.detail.text(), "Looking it up")
        w.set_jarvis_state("thinking", "Still looking")      # same state: no second signal
        w.set_jarvis_state("acting", "open chrome")
        w.set_jarvis_state("bogus")                          # unknown → idle
        self.assertEqual(seen, ["thinking", "acting", "idle"])
        self.assertEqual(w.jarvis_state, "idle")

    def test_error_flashes_then_settles(self):
        w = self.window()
        seen = []
        w.state_changed.connect(seen.append)
        with patch.object(main_gui.MainWindow, "ERROR_FLASH_MS", 150):
            w.on_error("mic unplugged")
            self.assertEqual(w.jarvis_state, "error")
            w.set_jarvis_state("acting", "ignored during the flash")
            self.assertEqual(w.jarvis_state, "error")
            self.assertTrue(pump(lambda: w.jarvis_state == "idle", 2))
        self.assertEqual(seen, ["error", "idle"])
        # a reply that is an error is shown as an error card and flashes too
        w._on_worker_response("chat", "Error: kaput")
        self.assertEqual(w.jarvis_state, "error")
        self.assertIsInstance(w.chat.rows[-1], chat_view.ErrorMessage)

    def test_worker_busy_drives_thinking_and_typing_indicator(self):
        w = self.window()
        self.assertFalse(w.chat.typing_visible)
        w.quick_command("block")
        self.assertTrue(pump(lambda: w.chat.typing_visible, 3))
        self.assertEqual(w.jarvis_state, "thinking")
        self.assertTrue(w.btn_stop.isVisibleTo(w))
        self.assertTrue(pump(lambda: any(r.status == "running" for r in w.activity.steps.values()), 2))
        w.jarvis.block.set()
        self.assertTrue(pump(lambda: not w.chat.typing_visible and w.jarvis_state == "idle", 3))
        self.assertTrue(any(r.status == "done" for r in w.activity.steps.values()))

    def test_live_voice_events_map_to_states(self):
        w = self.window()
        w._on_live_event("partial", {"text": "open chr"})
        self.assertEqual(w.jarvis_state, "listening")
        self.assertEqual(w._thinking_lbl.text(), "open chr")
        self.assertTrue(w._thinking_lbl.parentWidget().isVisibleTo(w))
        w._on_live_event("dispatched", {"text": "open chrome", "lane": 0, "index": 0})
        self.assertEqual(w.jarvis_state, "acting")
        w._on_live_event("step_started", {"text": "open chrome", "lane": 0, "index": 0})
        self.assertEqual(w.jarvis_state, "acting")
        w._on_live_event("utterance_done", {"summary": "Opened Chrome.", "details": "Opened Chrome."})
        self.assertEqual(w.jarvis_state, "idle")
        self.assertFalse(w._thinking_lbl.parentWidget().isVisibleTo(w))

    def test_buddy_events_map_to_states(self):
        w = self.window()
        for kind, expect in (("listening", "listening"), ("thinking", "thinking"), ("point", "acting"),
                             ("answer", "speaking"), ("idle", "idle")):
            w._on_buddy_event(kind, {"text": "It's the blue button", "points": [(1, 2, "Save")]})
            self.assertEqual(w.jarvis_state, expect, kind)
        self.assertTrue(any("Buddy" in r.text for r in w.activity.recent))

    def test_failed_start_settles_on_not_running_and_stays_usable(self):
        def broken(show_banner=False):
            raise RuntimeError("no brain")
        with patch.object(main_gui.MainWindow, "ERROR_FLASH_MS", 100):
            w = self.window(broken)
            self.assertEqual(w.jarvis_state, "error")
            self.assertTrue(pump(lambda: w._error_until == 0.0, 2))
        self.assertEqual(w.jarvis_state, "error")                      # steady, not re-flashing
        self.assertFalse(w._settle_timer.isActive())
        self.assertIn("NOT RUNNING", w.status_pill.text().upper())
        self.assertFalse(w.input.isEnabled())
        self.assertFalse(w.chat.hero.cards[0].isEnabled())
        w.set_jarvis_state("thinking")
        w.refresh_gauges()


class HeroTests(DashboardBase):
    def test_hero_shows_when_empty_hides_with_messages_and_returns_after_clear(self):
        w = self.window()
        self.assertTrue(w.chat.hero_visible)
        self.assertIn("Good day, sir.", w.transcript.toPlainText())   # the greeting is kept for export
        self.assertIn("Tony", w.chat.hero.title.text())
        w.append_text("System", "Decision engine: rules only")
        self.assertTrue(w.chat.hero_visible)                   # system lines don't count as conversation
        w.quick_command("hello")
        self.assertFalse(w.chat.hero_visible)
        self.assertTrue(pump(lambda: "echo hello" in w.transcript.toPlainText()))
        w.on_clear()
        self.assertTrue(w.chat.hero_visible)
        self.assertIn("Conversation cleared.", w.transcript.toPlainText())

    def test_suggestion_card_runs_quick_command(self):
        w = self.window()
        card = w.chat.hero.cards[0]
        card.click()
        self.assertTrue(pump(lambda: (card.command, False, False) in w.jarvis.commands))

    def test_greeting(self):
        self.assertEqual(chat_view.greeting_for(8, "Raghav"), "Good morning, Raghav")
        self.assertEqual(chat_view.greeting_for(14), "Good afternoon")
        self.assertEqual(chat_view.greeting_for(21), "Good evening")
        self.assertEqual(chat_view.greeting_for(2), "Good evening")


@unittest.skipIf(main_gui is None, f"PySide6 unavailable: {_QT_ERROR}")
class ChatViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def setUp(self):
        self.view = chat_view.ChatView()
        self.view.resize(900, 600)
        self.view.show()
        pump(timeout=0.05)

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        pump(timeout=0.02)

    def test_markdown_and_plain_text_compatibility(self):
        md = "Here you go:\n\n- one\n- **two**\n\n```python\nprint('hi')\n```\nDone."
        row = self.view.add_message("JARVIS", md)
        kinds = [type(s).__name__ for s in row.segments]
        self.assertEqual(kinds, ["AutoText", "CodeBlock", "AutoText"])
        self.assertEqual(row.segments[1].code, "print('hi')")
        self.assertEqual(row.segments[1].lang, "PYTHON")
        self.assertIn("two", row.segments[0].toPlainText())
        self.assertNotIn("**", row.segments[0].toPlainText())       # rendered, not raw
        self.view.add_message("You", "a <b>not html</b> & more")
        self.view.add_message("Action", "▶ open the alarm · lane 2")
        self.view.add_message("Greeting", "kept only in the transcript", ambient=True)
        text = self.view.toPlainText()
        self.assertIn(md, text)
        self.assertIn("a <b>not html</b> & more", text)
        self.assertIn("▶ open the alarm · lane 2", text)
        self.assertIn("ACTION", text)
        self.assertIn("kept only in the transcript", text)
        action = self.view.rows[-1]
        self.assertEqual((action.lane, action.label), (2, "open the alarm"))
        action.set_status("done", 1.25)
        self.assertEqual(action.status, "done")
        self.view.clear()
        self.assertEqual(self.view.toPlainText(), "")
        self.assertEqual(self.view.rows, [])

    def test_split_markdown(self):
        self.assertEqual(chat_view.split_markdown("plain"), [("md", "plain")])
        segs = chat_view.split_markdown("a\n```\nx = 1\n")          # unterminated fence
        self.assertEqual(segs, [("md", "a"), ("code", "", "x = 1")])
        self.assertIn("  \n", chat_view._hard_breaks("line one\nline two"))

    def test_messages_wrap_and_grow_with_width(self):
        long = "word " * 120
        for speaker in ("JARVIS", "You", "Error", "System"):
            row = self.view.add_message(speaker, long)
            narrow, wide = row.heightForWidth(360), row.heightForWidth(900)
            self.assertGreater(narrow, wide, speaker)
            self.assertTrue(row.hasHeightForWidth())
        pump(timeout=0.1)
        jarvis = self.view.rows[0]
        seg = jarvis.segments[0]
        self.assertGreater(jarvis.height(), 100)
        self.assertEqual(seg.height(), seg.text_height(seg.width()))   # laid out at its real width
        self.assertLessEqual(seg.geometry().right(), jarvis.width())
        # a short user message hugs its text
        short = self.view.add_message("You", "hi")
        pump(timeout=0.05)
        self.assertLess(short.body.width(), 120)

    def test_wheel_over_message_text_is_left_to_the_conversation(self):
        row = self.view.add_message("JARVIS", "text " * 40)
        seg = row.segments[0]
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, True)
        ev.accept()
        seg.wheelEvent(ev)
        self.assertFalse(ev.isAccepted())            # ignored → Qt propagates it to the scroll area

    def test_jump_to_latest(self):
        for i in range(25):
            self.view.add_message("JARVIS", f"reply {i} " + "lorem ipsum " * 20)
        bar = self.view.scroll.verticalScrollBar()
        self.assertTrue(pump(lambda: bar.maximum() > 0 and self.view.is_at_bottom(), 1))
        self.assertFalse(self.view.jump_pill.isVisibleTo(self.view))
        bar.setValue(0)                                    # the user scrolls up to read
        pump(timeout=0.05)
        self.assertFalse(self.view.is_at_bottom())
        self.view.add_message("JARVIS", "something new")
        pump(timeout=0.1)
        self.assertEqual(bar.value(), 0)                   # not yanked down…
        self.assertTrue(self.view.jump_pill.isVisibleTo(self.view))   # …but told
        self.assertEqual(self.view._unseen, 1)
        self.view.jump_pill.click()
        pump(timeout=0.1)
        self.assertTrue(self.view.is_at_bottom())
        self.assertFalse(self.view.jump_pill.isVisibleTo(self.view))
        bar.setValue(0)
        pump(timeout=0.05)
        self.view.add_message("You", "my own message brings me back")
        self.assertTrue(pump(lambda: self.view.is_at_bottom(), 1))

    def test_typing_indicator(self):
        self.assertFalse(self.view.typing_visible)
        self.view.set_typing(True, "Working", "#FFB547")
        self.assertTrue(self.view.typing_visible)
        self.assertEqual(self.view.typing.label, "Working")
        self.view.set_typing(False)
        self.assertFalse(self.view.typing_visible)


class ActivityTests(DashboardBase):
    def test_live_events_build_a_multi_lane_timeline(self):
        w = self.window()
        events = [("heard", {"text": "open chrome and set an alarm"}),
                  ("step_queued", {"index": 0, "lane": 0, "text": "open chrome", "status": "queued"}),
                  ("dispatched", {"text": "open chrome", "lane": 0, "index": 0}),
                  ("step_started", {"index": 0, "lane": 0, "text": "open chrome", "status": "running"}),
                  ("dispatched", {"text": "set an alarm", "lane": 1, "index": 1}),
                  ("step_done", {"index": 0, "lane": 0, "text": "open chrome", "status": "done",
                                 "reply": "Opened Chrome."}),
                  ("step_done", {"index": 1, "lane": 1, "text": "set an alarm", "status": "skipped",
                                 "reply": "Skipped."}),
                  ("ask", {"question": "Close Chrome?"}),
                  ("deferred", {"text": "what's the weather"}),
                  ("step_done", {}), ("bogus", None)]
        threading.Thread(target=lambda: [w._bridge.live_event.emit(k, i) for k, i in events]).start()
        self.assertTrue(pump(lambda: len(w.activity.steps) == 2, 2))
        pump(timeout=0.1)
        rows = sorted(w.activity.steps.items(), key=lambda kv: kv[0][1])
        (_, first), (_, second) = rows
        self.assertEqual((first.status, first.reply, first.lane), ("done", "Opened Chrome.", 0))
        self.assertIsNotNone(first.seconds)
        self.assertEqual((second.status, second.lane), ("skipped", 1))
        self.assertTrue(first.show_lane and second.show_lane)          # two lanes → L1 / L2 badges
        header = w.activity._group["header"]
        self.assertIn("open chrome and set an alarm", header.title)
        # the matching chat action rows follow the steps
        actions = [r for r in w.chat.rows if isinstance(r, chat_view.ActionMessage)]
        self.assertEqual([a.status for a in actions], ["done", "skipped"])
        self.assertEqual(actions[1].lane, 2)
        w._on_live_event("utterance_done", {"heard": "open chrome and set an alarm", "summary": "Opened Chrome.",
                                            "details": "Ran 2 steps"})
        self.assertIsNone(w.activity._group)
        self.assertTrue(any("Opened Chrome." in r.text for r in w.activity.recent))
        self.assertTrue(any("Close Chrome?" in r.text for r in w.activity.recent))
        w.activity.clear_timeline()
        self.assertEqual(w.activity.steps, {})
        self.assertTrue(w.activity.empty.isVisibleTo(w.activity))

    def test_panel_collapses_and_follows_window_width(self):
        w = self.window()
        self.assertTrue(w.activity.isVisibleTo(w))
        w.resize(960, 660)
        pump(timeout=0.1)
        self.assertFalse(w.activity.isVisibleTo(w))                  # narrow window: folded away
        self.assertFalse(w.btn_activity.isChecked())
        w.btn_activity.click()                                       # the user wants it anyway
        self.assertTrue(w.activity.isVisibleTo(w))
        w.resize(1000, 700)
        pump(timeout=0.1)
        self.assertTrue(w.activity.isVisibleTo(w))
        w.activity.btn_collapse.click()
        self.assertFalse(w.activity.isVisibleTo(w))

    def test_panel_standalone_timeline_limits(self):
        panel = ActivityPanel()
        for i in range(ActivityPanel.MAX_ROWS + 10):
            panel.upsert_step(i, f"step {i}", 0, "done")
        self.assertLessEqual(len(panel.rows), ActivityPanel.MAX_ROWS)
        panel.task_finished(True)                   # nothing running: no-op
        panel.task_started("check mail")
        panel.task_finished(False, "Error: offline")
        self.assertTrue(any(r.status == "failed" for r in panel.steps.values()))
        panel.deleteLater()


@unittest.skipIf(main_gui is None, f"PySide6 unavailable: {_QT_ERROR}")
class GaugeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def test_read_system_stats_tolerates_psutil_errors(self):
        class Broken:
            def __getattr__(self, name):
                def fail(*a, **k):
                    raise OSError("access denied")
                return fail
        stats = dash_widgets.read_system_stats(Broken())
        self.assertEqual({k: v[0] for k, v in stats.items()}, {"cpu": None, "ram": None, "disk": None, "battery": None})
        with patch.dict(sys.modules, {"psutil": None}):
            stats = dash_widgets.read_system_stats()
        self.assertTrue(all(v[0] is None for v in stats.values()))

    def test_read_system_stats_values(self):
        ps = SimpleNamespace(
            cpu_percent=lambda interval=None: 12.5, cpu_count=lambda logical=True: 8,
            virtual_memory=lambda: SimpleNamespace(percent=50.0, used=8 * 1024 ** 3, total=16 * 1024 ** 3),
            disk_usage=lambda root: SimpleNamespace(percent=70.0, used=70 * 1024 ** 3, total=100 * 1024 ** 3),
            sensors_battery=lambda: SimpleNamespace(percent=40, power_plugged=False, secsleft=5400))
        stats = dash_widgets.read_system_stats(ps)
        self.assertEqual(stats["cpu"], (12.5, "8 logical cores"))
        self.assertEqual(stats["ram"][0], 50.0)
        self.assertIn("8.0 / 16.0 GB", stats["ram"][1])
        self.assertEqual(stats["battery"], (40.0, "On battery · 1h 30m left"))

    def test_gauge_and_tile(self):
        tile = dash_widgets.StatTile("CPU", "chip")
        tile.set_stat(None)
        self.assertEqual(tile.gauge.text(), "—")
        self.assertEqual(tile.detail.text(), "Unavailable")
        tile.set_stat("not a number", "x")
        self.assertIsNone(tile.gauge.value)
        tile.set_stat(142, "hot")
        self.assertEqual(tile.gauge.text(), "100%")
        self.assertEqual(dash_widgets.gauge_color(95), main_gui._theme.ERROR)
        tile.deleteLater()

    def test_window_gauges_refresh_only_while_system_page_is_visible(self):
        w = make()
        try:
            page = w.stack.widget(2)
            self.assertFalse(page.timer.isActive())
            with patch.object(main_gui, "read_system_stats", side_effect=RuntimeError("wmi")):
                w._switch_page(2)                  # shows the page → refresh (fails soft) + timer
                pump(timeout=0.05)
            self.assertTrue(page.timer.isActive())
            self.assertEqual(w.gauges["cpu"].gauge.text(), "—")
            w.refresh_gauges({"cpu": (33.0, "4 cores")})
            self.assertEqual(w.gauges["cpu"].gauge.text(), "33%")
            self.assertEqual(w.gauges["ram"].gauge.text(), "—")
            w._switch_page(0)
            self.assertFalse(page.timer.isActive())
        finally:
            close_window(w)


@unittest.skipIf(main_gui is None, f"PySide6 unavailable: {_QT_ERROR}")
class MemoryAndLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def test_memory_dialog_search_and_delete_icon(self):
        mem = FakeMemory()
        mem.facts.append("drinks tea")
        d = main_gui.MemoryDialog(mem)
        d.show()
        pump(timeout=0.05)
        self.assertIn("3 facts", d.count_lbl.text().lower())
        d.search.setText("tea")
        self.assertEqual([d.facts.isRowHidden(i) for i in range(3)], [True, True, False])
        d.search.setText("zzz")
        self.assertFalse(d.facts.isVisibleTo(d))
        self.assertIn("No facts match", d.empty.text())
        d.search.clear()
        d._forget_row(1)                           # the trash icon on row 1
        self.assertEqual(mem.facts, ["likes jazz", "drinks tea"])
        d._forget_row(9)                           # out of range: ignored
        self.assertEqual(d.facts.count(), 2)
        d.close()
        d.deleteLater()

    def test_flow_layout_wraps(self):
        host = QWidget()
        flow = dash_widgets.FlowLayout(host, spacing=6)
        for i in range(6):
            b = QPushButton(f"Button {i}")
            b.setFixedSize(100, 30)
            flow.addWidget(b)
        self.assertEqual(flow.heightForWidth(1000), 30)
        self.assertEqual(flow.heightForWidth(220), 30 * 3 + 6 * 2)
        self.assertEqual(flow.count(), 6)
        self.assertIsNone(flow.itemAt(10))
        host.deleteLater()


if __name__ == "__main__":
    unittest.main()
