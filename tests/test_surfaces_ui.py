"""HUD redesign of the always-available surfaces: command bar, cursor buddy overlay, tray."""
import os
import sys
import time
import unittest
from unittest.mock import patch

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


class MarkdownTests(unittest.TestCase):
    def test_subset_is_rendered_and_escaped(self):
        from ui.bar_markdown import looks_like_markdown, to_html
        html = to_html("You have **3 emails**:\n\n- *Priya*\n- run `ls -la`\n\n1. first\n```\nx = 1 < 2\n```")
        self.assertIn("<b", html)
        self.assertIn("3 emails", html)
        self.assertIn("<i>Priya</i>", html)
        self.assertIn("▸", html)                              # bullet marker
        self.assertIn("01", html)                             # numbered marker
        self.assertIn("Cascadia", html)                       # code uses the mono stack
        self.assertIn("1&nbsp;&lt;&nbsp;2", html)             # code is escaped, spacing kept
        self.assertNotIn("<script", to_html("<script>alert(1)</script>"))
        self.assertTrue(looks_like_markdown("- item"))
        self.assertFalse(looks_like_markdown("Opened Spotify."))
        self.assertIn("href=\"https://example.com\"", to_html("[site](https://example.com)"))
        self.assertNotIn("href", to_html("[x](javascript:alert(1))"))


@needs_qt
class CommandBarHudTests(unittest.TestCase):
    def setUp(self):
        qapp()
        from ui.command_bar import CommandBar
        front = patch.object(CommandBar, "_bring_to_front")    # real ALT tap + SetForegroundWindow
        front.start()
        self.addCleanup(front.stop)
        self.bar = CommandBar("Ctrl + Shift + Space")
        self.addCleanup(self.bar.close)

    def cards(self):
        lay = self.bar.results_layout
        return [lay.itemAt(i).widget() for i in range(lay.count() - 1)]

    def test_set_state_drives_orb_status_and_scan_line(self):
        from ui import theme
        bar = self.bar
        self.assertEqual(bar.orb.state, "idle")
        self.assertIs(bar.logo, bar.orb)
        for state in theme.STATE_COLORS:
            bar.set_state(state)
            self.assertEqual(bar.state, state)
            self.assertEqual(bar.orb.state, state)
            self.assertEqual(bar.card.scanning, state in ("thinking", "acting"))
        bar.set_state("thinking")
        self.assertEqual(bar.status.text(), "Working…")
        bar.set_state("listening")
        self.assertEqual(bar.status.text(), "Listening…")
        bar.set_state("bogus")
        self.assertEqual(bar.state, "idle")
        self.assertEqual(bar.status.text(), "")
        bar.set_busy(True)
        self.assertEqual((bar.state, bar.orb.state, bar.logo.busy), ("thinking", "thinking", True))
        bar.set_busy(False)
        self.assertEqual((bar.state, bar.logo.busy), ("idle", False))
        bar.logo.set_busy(True)                                # older callers
        self.assertEqual(bar.orb.state, "thinking")

    def test_mic_turns_idle_orb_into_listening(self):
        self.bar.set_mic(True)
        self.assertTrue(self.bar.btn_mic.isChecked())
        self.assertEqual(self.bar.orb.state, "listening")
        self.bar.set_busy(True)
        self.assertEqual(self.bar.orb.state, "thinking")      # busy wins over the mic
        self.bar.set_busy(False)
        self.assertEqual(self.bar.orb.state, "listening")
        self.bar.set_mic(False)
        self.assertEqual(self.bar.orb.state, "idle")

    def test_markdown_reply_card(self):
        self.bar.run("summarise")
        text = "You have **3 unread**:\n- one\n- `two`"
        self.bar.show_result(text)
        you, reply = self.cards()
        self.assertEqual((reply.kind, reply.label.text()), ("reply", text))   # text() is the source
        self.assertIn("<b", reply.label.html())
        self.assertIn("▸", reply.label.html())
        self.bar.show_result("<b>nope</b>", error=True)
        err = self.cards()[-1]
        self.assertEqual((err.kind, err.label.text()), ("error", "<b>nope</b>"))
        self.assertIsNone(you.btn_copy)

    def test_copy_button_copies_the_source(self):
        from PySide6.QtWidgets import QApplication
        self.bar.run("x")
        self.bar.show_result("Use `dir`.")
        card = self.cards()[-1]
        self.assertTrue(card.btn_copy.isHidden())             # only on hover
        card.enterEvent(None)
        self.assertFalse(card.btn_copy.isHidden())
        card.btn_copy.click()
        self.assertEqual(QApplication.clipboard().text(), "Use `dir`.")
        self.assertEqual(card.btn_copy.icon_name, "check")
        card._copy_reset()
        self.assertEqual(card.btn_copy.icon_name, "copy")
        card.leaveEvent(None)
        self.assertTrue(card.btn_copy.isHidden())

    def test_painting_and_size(self):
        bar = self.bar
        bar.summon()
        pump()
        for i in range(4):
            bar.run(f"q{i}")
            bar.show_result("**bold** and a list:\n- a\n- b\n```\ncode\n```", error=i == 2)
        bar.set_state("acting")
        image = bar.grab()
        self.assertFalse(image.isNull())
        self.assertLessEqual(abs(bar.width() - 736), 40)       # ~700px card + glow margin
        self.assertLessEqual(bar.scroll.height(), 340)
        bar.hide()
        self.assertFalse(bar.card._timer.isActive())          # scan line stops when hidden


@needs_qt
class TraySetStateTests(unittest.TestCase):
    def setUp(self):
        qapp()
        from ui.tray import Tray
        self.tray = Tray("Ctrl+Shift+Space")

    def test_states(self):
        from ui import theme
        from ui.tray import state_icon
        tray = self.tray
        self.assertEqual(tray.menu.actions()[0], tray.act_header)
        self.assertFalse(tray.act_header.isEnabled())
        self.assertIn("Standing by", tray.act_header.text())
        for state, label in theme.STATE_LABELS.items():
            tray.set_state(state)
            self.assertEqual(tray.state, state)
            self.assertTrue(tray.icon.toolTip().startswith(f"JARVIS — {label}"))
            self.assertIn(label, tray.act_header.text())
            self.assertEqual(tray.header.state, state)
        self.assertIs(state_icon("idle"), state_icon("offline"))            # no dot for either
        self.assertIsNot(state_icon("idle"), state_icon("listening"))
        self.assertIsNot(state_icon("listening"), state_icon("error"))
        tray.set_busy(True)
        self.assertEqual(tray.state, "thinking")
        self.assertIn("working", tray.icon.toolTip())
        tray.set_busy(False)
        self.assertEqual(tray.state, "idle")
        self.assertEqual(tray.icon.toolTip(), "JARVIS — Standing by")
        tray.set_state("nonsense")
        self.assertEqual(tray.state, "idle")

    def test_icons_toggle_labels_and_render(self):
        tray = self.tray
        for act in (tray.act_ask, tray.act_dash, tray.act_buddy, tray.act_voice, tray.act_startup,
                    tray.act_settings, tray.act_quit):
            self.assertFalse(act.icon().isNull())
        self.assertTrue(tray.act_voice.text().endswith("OFF"))
        tray.set_checked(tray.act_voice, True)
        self.assertTrue(tray.act_voice.text().endswith("ON"))
        seen = []
        tray.startup_toggled.connect(seen.append)
        tray.act_startup.trigger()
        self.assertEqual(seen, [True])
        self.assertTrue(tray.act_startup.text().endswith("ON"))
        self.assertFalse(tray.menu.grab().isNull())


@needs_qt
class OverlayHudTests(unittest.TestCase):
    def setUp(self):
        qapp()
        from ui.buddy_overlay import BuddyOverlay
        self.o = BuddyOverlay()
        self.addCleanup(self.o.close)

    def test_many_and_offscreen_points_paint(self):
        from PySide6.QtCore import QPoint
        o = self.o
        o.show()
        pts = [(i * 97 % 3000 - 500, i * 53 % 2000 - 300, f"Target {i} " * (i % 3)) for i in range(40)]
        pts += [(-10000, -10000, "far away"), (10 ** 6, 10 ** 6, ""), (0, 0, "corner")]
        o.set_state("point", {"points": pts})
        for age in (0.1, 0.5, 0.9, 1.4, 3.0, 8.5):
            o._points_since = time.monotonic() - age
            o._points_until = o._points_since + o.POINT_SECONDS
            self.assertFalse(o.grab().isNull())
        o._cursor = QPoint(-50, -50)                           # buddy off-screen too
        o.set_state("answer", {"text": "word " * 400})         # very long reply: elided, still paints
        o._message_since -= 1
        self.assertFalse(o.grab().isNull())
        rect = o._bubble_layout(o._buddy_center(), o.message)[0]
        self.assertLessEqual(rect.width(), 360)
        self.assertTrue(o._bubble_cache[3].endswith("…"))
        for kind in ("listening", "thinking", "heard", "error", "idle"):
            o.set_state(kind, {"text": "x", "message": "y"})
            self.assertFalse(o.grab().isNull())

    def test_repaints_only_while_needed(self):
        from PySide6.QtCore import QRect
        o = self.o
        o.set_state("idle", {})
        o.message, o._points, o._message_until = "", [], 0
        o._was_animating = False
        self.assertFalse(o.animating())
        with patch("ui.buddy_overlay.QCursor.pos", return_value=o._cursor), patch.object(o, "update") as upd:
            o._tick()
            o._tick()
            upd.assert_not_called()                            # idle + still cursor: nothing to do
            o.set_state("thinking", {})
            upd.reset_mock()
            self.assertTrue(o.animating())
            o._tick()
            upd.assert_called()
            region = upd.call_args.args[0]
            self.assertIsInstance(region, QRect)               # only the buddy's neighbourhood
            self.assertLess(region.width() * region.height(), o.width() * o.height() / 4)
            o.set_state("idle", {})
            o._message_until = 0
            upd.reset_mock()
            o._tick()                                          # one last frame to erase the animation
            upd.assert_called_once()
            upd.reset_mock()
            o._tick()
            upd.assert_not_called()

    def test_timer_stops_when_hidden(self):
        o = self.o
        o.show()
        self.assertTrue(o._timer.isActive())
        o.hide()
        self.assertFalse(o._timer.isActive())
        o.show()
        self.assertTrue(o._timer.isActive())


if __name__ == "__main__":
    unittest.main()
