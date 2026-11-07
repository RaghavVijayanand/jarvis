"""Behaviour of the HUD Settings dialog and the welcome stepper (search, dirty tracking, key fields, nav)."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLineEdit
    _QT_ERROR = None
except Exception as exc:                 # pragma: no cover - PySide6 missing
    QApplication = None
    _QT_ERROR = exc

import core.config as cfg
from core.config import Config


def qapp():
    return QApplication.instance() or QApplication([])


class _EnvCase(unittest.TestCase):
    ENV = 'GEMINI_API_KEY="secret-key"\nJARVIS_WAKE_WORD="jarvis"\n'

    def setUp(self):
        qapp()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "Jarvis"
        self.dir.mkdir()
        self.env_path = self.dir / ".env"
        self.env_path.write_text(self.ENV, encoding="utf-8")
        self.patches = [patch.object(cfg, "ENV_PATH", self.env_path), patch.object(cfg, "APPDATA_DIR", self.dir),
                        patch.dict(os.environ, {}), patch("core.autostart.is_enabled", return_value=False)]
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


@unittest.skipIf(QApplication is None, f"PySide6 unavailable: {_QT_ERROR}")
class SettingsUiTests(_EnvCase):
    def dialog(self, **kw):
        from ui.settings import SettingsDialog
        d = SettingsDialog(**kw)
        self.addCleanup(d.deleteLater)
        return d

    def test_nav_switches_pages(self):
        from ui.settings import PAGES
        d = self.dialog()
        self.assertEqual(len(d.nav), len(PAGES))
        self.assertEqual(d.stack.count(), len(PAGES))
        self.assertTrue(d.nav[0].isChecked())
        d.nav[3].click()
        self.assertEqual(d.current_page(), 3)
        self.assertTrue(d.nav[3].isChecked())
        self.assertFalse(d.nav[0].isChecked())
        d.set_page(99)                                   # clamped
        self.assertEqual(d.current_page(), len(PAGES) - 1)

    def test_search_filters_jumps_and_highlights(self):
        d = self.dialog()
        counts = d.apply_search("wake word")
        self.assertEqual(d.current_page(), 2)            # Voice
        self.assertEqual(counts[2], 1)
        hits = d.matching_rows()
        self.assertEqual([r.title for r in hits], ["Wake word"])
        self.assertTrue(hits[0].highlighted())
        others = [r for r in d.rows if r.page == 2 and r is not hits[0]]
        self.assertTrue(others and all(r.isHidden() for r in others))
        self.assertEqual(d.nav[2].badge(), 1)
        self.assertTrue(d.nav[0].dimmed())
        # hotkeys live on the Buddy page; typing in the box drives the same filter
        d.search.setText("hotkey")
        self.assertEqual(d.current_page(), 3)
        self.assertIn("Command bar hotkey", [r.title for r in d.matching_rows()])
        # Enter cycles through pages with hits (only one page here) and never saves
        d.search.returnPressed.emit()
        self.assertEqual(d.current_page(), 3)
        # no match anywhere: stay put, show the empty state
        d.search.setText("zzzz-nothing")
        self.assertFalse(d.matching_rows())
        self.assertFalse(d.pages[3]._empty.isHidden())
        d.search.clear()
        self.assertFalse(any(r.isHidden() for r in d.rows))
        self.assertFalse(any(r.highlighted() for r in d.rows))
        self.assertIsNone(d.nav[0].badge())

    def test_save_disabled_until_something_changes(self):
        d = self.dialog()
        self.assertFalse(d.save_button.isEnabled())
        self.assertFalse(d.is_dirty())
        d.wake_word.setText("friday")
        self.assertTrue(d.save_button.isEnabled())
        self.assertEqual(d.changed_keys(), ["JARVIS_WAKE_WORD"])
        wake_row = next(r for r in d.rows if r.title == "Wake word")
        self.assertTrue(wake_row.modified())
        self.assertIn("1 unsaved change", d.dirty_label.text())
        d.wake_word.setText("jarvis")                    # back to the original → clean again
        self.assertFalse(d.save_button.isEnabled())
        self.assertFalse(wake_row.modified())
        d.live_voice.toggle()                            # ToggleSwitch counts too
        self.assertTrue(d.save_button.isEnabled())
        d.live_voice.toggle()
        d.startup.setChecked(True)                       # registry setting, not .env
        self.assertIn("startup", d.changed_keys())

    def test_accept_without_changes_still_works_when_save_is_disabled(self):
        d = self.dialog()
        before = self.env_path.read_text(encoding="utf-8")
        self.assertFalse(d.save_button.isEnabled())
        d.accept()
        self.assertEqual(d.result(), 1)
        self.assertEqual(self.env_path.read_text(encoding="utf-8"), before)

    def test_threshold_slider_drives_spin_box(self):
        d = self.dialog()
        d.threshold_slider.slider.setValue(70)
        self.assertAlmostEqual(d.threshold.value(), 0.70)
        self.assertEqual(d._values()["JARVIS_DECISION_THRESHOLD"], "0.70")
        d.volume.setValue(0.5)
        self.assertEqual(d.volume_slider.slider.value(), 50)

    def test_key_fields_eye_toggle_and_status(self):
        d = self.dialog()
        edit = d.gemini_edit
        self.assertEqual(edit.echoMode(), QLineEdit.Password)
        edit.eye.trigger()
        self.assertEqual(edit.echoMode(), QLineEdit.Normal)
        self.assertTrue(edit.revealed())
        edit.eye.trigger()
        self.assertEqual(edit.echoMode(), QLineEdit.Password)
        self.assertEqual(d.key_status["gemini"].text(), "Set")
        self.assertEqual(d.key_status["openrouter"].text(), "Not set")
        self.assertFalse(d.test_buttons["openrouter"].isEnabled())
        d.openrouter_edit.setText("sk-or-1")
        self.assertEqual(d.key_status["openrouter"].text(), "Set")
        self.assertTrue(d.test_buttons["openrouter"].isEnabled())

    def test_key_test_runs_off_the_ui_thread(self):
        d = self.dialog()
        with patch("ui.settings.threading.Thread") as thread:
            d.test_key("gemini")
        thread.assert_called_once()
        self.assertTrue(thread.call_args.kwargs["daemon"])
        self.assertEqual(d.key_status["gemini"].text(), "Testing…")
        d._on_key_tested("gemini", False, "Key rejected")
        self.assertEqual(d.key_status["gemini"].text(), "Key rejected")
        self.assertTrue(d.test_buttons["gemini"].isEnabled())
        with patch("requests.get", return_value=SimpleNamespace(status_code=200)):
            from ui.settings import _check_key
            self.assertEqual(_check_key("openrouter", "k"), (True, "Key works"))
        with patch("requests.get", side_effect=OSError("down")):
            self.assertFalse(_check_key("gemini", "k")[0])

    def test_decision_status_chip_and_about_page(self):
        d = self.dialog(decision=SimpleNamespace(status="Laya ready (english, 1.0s)"))
        from ui import theme
        self.assertEqual(d.decision_chip.text(), "Laya ready (english, 1.0s)")
        self.assertEqual(d.decision_chip.color(), theme.SUCCESS)
        self.assertEqual(d.version, "3.1")
        self.assertEqual(d.data_dir, str(Config.USER_DIR))
        with patch.object(d, "open_url") as opened:
            d.open_data_folder()
        opened.assert_called_once()

    def test_hotkey_keycaps_follow_combo(self):
        d = self.dialog()
        d.bar_hotkey.setCurrentIndex(d.bar_hotkey.findData("ctrl+shift+j"))
        self.assertEqual(d.bar_caps.keys(), ["Ctrl", "Shift", "J"])
        d.buddy_hotkey.setCurrentIndex(d.buddy_hotkey.findData("f9"))
        self.assertEqual(d.buddy_caps.keys(), ["F9"])

    def test_escape_clears_search_first(self):
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        d = self.dialog()
        d.show()
        self.addCleanup(d.close)
        d.search.setFocus()
        d.search.setText("voice")
        qapp().processEvents()
        if d.search.hasFocus():                          # offscreen focus is best effort
            d.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
            self.assertEqual(d.search.text(), "")
            self.assertTrue(d.isVisible())


@unittest.skipIf(QApplication is None, f"PySide6 unavailable: {_QT_ERROR}")
class WelcomeStepperTests(_EnvCase):
    def wizard(self):
        from ui.onboarding import WelcomeWizard
        w = WelcomeWizard()
        self.addCleanup(w.deleteLater)
        return w

    def test_cards_drive_the_key_field(self):
        w = self.wizard()
        self.assertTrue(w.opt_gemini.isChecked())         # a Gemini key is already set
        self.assertEqual(w.key.text(), "secret-key")
        self.assertTrue(w.key.isEnabled())
        w.opt_ollama.click()
        self.assertTrue(w.opt_ollama.isChecked())
        self.assertFalse(w.opt_gemini.isChecked())        # exclusive
        self.assertFalse(w.key.isEnabled())
        self.assertEqual(w.get_key.text(), "Get Ollama")
        w.opt_openrouter.click()
        self.assertTrue(w.key.isEnabled())
        self.assertEqual(w.get_key.text(), "Get a free key")
        w.opt_skip.setChecked(True)
        self.assertFalse(w.key.isEnabled())
        self.assertFalse(w.get_key.isEnabled())
        self.assertEqual(w.selected_brain(), "skip")
        self.assertEqual(w.opt_gemini.badge, "Recommended")

    def test_key_eye_toggle(self):
        w = self.wizard()
        self.assertEqual(w.key.echoMode(), QLineEdit.Password)
        w.key.eye.trigger()
        self.assertEqual(w.key.echoMode(), QLineEdit.Normal)

    def test_stepper_navigation_and_finish(self):
        w = self.wizard()
        self.assertEqual((w.step_count(), w.current_step()), (4, 0))
        self.assertTrue(w.back_button.isHidden())
        w.next_step()
        self.assertEqual(w.current_step(), 1)
        self.assertEqual(w.steps.current, 1)
        w.back()
        self.assertEqual(w.current_step(), 0)
        w.go_to(3)
        self.assertEqual(w.next_button.text(), "Start JARVIS")
        value, _caps, chip = w.summary_rows["brain"]
        self.assertEqual(value.text(), "Google Gemini")
        self.assertEqual(chip.text(), "Key added")
        with patch.object(w, "accept") as accept:
            w.next_step()
        accept.assert_called_once()

    def test_hotkey_keycaps_and_buddy_toggle(self):
        w = self.wizard()
        w.bar_key.setCurrentIndex(w.bar_key.findData("alt+j"))
        self.assertEqual(w.bar_caps.keys(), ["Alt", "J"])
        w.buddy.setChecked(False)
        self.assertFalse(w.buddy_key.isEnabled())
        self.assertEqual(w.values()["JARVIS_BUDDY"], "0")
        w.go_to(3)
        self.assertEqual(w.summary_rows["buddy"][0].text(), "Off")


@unittest.skipIf(QApplication is None, f"PySide6 unavailable: {_QT_ERROR}")
class HotkeyKeysTests(unittest.TestCase):
    def test_parse(self):
        from ui.settings_widgets import hotkey_keys
        self.assertEqual(hotkey_keys("Hold Ctrl + Alt"), ["Ctrl", "Alt"])
        self.assertEqual(hotkey_keys("Ctrl + Shift + Space"), ["Ctrl", "Shift", "Space"])
        self.assertEqual(hotkey_keys("F8"), ["F8"])
        self.assertEqual(hotkey_keys(""), [])


if __name__ == "__main__":
    unittest.main()
