"""ProductivityHandler: clipboard-history reads, OCR and document reads run
immediately; clearing clipboard history confirms first."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.productivity import ProductivityHandler


class FakeApp:
    def __init__(self):
        self.productivity = Mock()
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class ProductivityHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = ProductivityHandler(self.app)

    def test_list_history_runs_immediately(self):
        self.app.productivity.list_clipboard_history.return_value = "0: hi"
        reply = self.h.handle("clipboard history", "PRODUCTIVITY")
        self.assertFalse(self.app.pending)
        self.assertEqual(reply, "0: hi")

    def test_clear_history_confirms(self):
        self.h.handle("clear clipboard history", "PRODUCTIVITY")
        self.assertEqual(self.app.pending[-1][0], "clear_clipboard_history")
        self.app.productivity.clear_clipboard_history.assert_not_called()
        self.app.pending[-1][1]()
        self.app.productivity.clear_clipboard_history.assert_called_once()

    def test_copy_from_history_runs_immediately(self):
        self.app.productivity.copy_from_history.return_value = "Copied to the clipboard."
        reply = self.h.handle("copy 2 from clipboard history", "PRODUCTIVITY")
        self.assertFalse(self.app.pending)
        self.app.productivity.copy_from_history.assert_called_once_with(2)
        self.assertEqual(reply, "Copied to the clipboard.")

    def test_paste_history_item_runs_immediately(self):
        self.h.handle("paste history item 3", "PRODUCTIVITY")
        self.app.productivity.copy_from_history.assert_called_once_with(3)

    def test_screen_text_runs_immediately(self):
        self.app.productivity.screen_text.return_value = "some text on screen"
        reply = self.h.handle("what does my screen say", "PRODUCTIVITY")
        self.assertFalse(self.app.pending)
        self.assertEqual(reply, "some text on screen")

    def test_ocr_image_runs_immediately(self):
        self.app.productivity.ocr_image.return_value = "text in image"
        reply = self.h.handle("ocr image screenshot.png", "PRODUCTIVITY")
        self.assertFalse(self.app.pending)
        self.app.productivity.ocr_image.assert_called_once_with("screenshot.png")
        self.assertEqual(reply, "text in image")

    def test_read_pdf_runs_immediately(self):
        self.app.productivity.read_pdf_text.return_value = "pdf contents"
        reply = self.h.handle("read the pdf report.pdf", "PRODUCTIVITY")
        self.assertFalse(self.app.pending)
        self.app.productivity.read_pdf_text.assert_called_once_with("report.pdf")
        self.assertEqual(reply, "pdf contents")

    def test_read_docx_runs_immediately(self):
        self.app.productivity.read_docx_text.return_value = "docx contents"
        reply = self.h.handle("read the word document notes.docx", "PRODUCTIVITY")
        self.assertFalse(self.app.pending)
        self.app.productivity.read_docx_text.assert_called_once_with("notes.docx")
        self.assertEqual(reply, "docx contents")

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "PRODUCTIVITY"))

    def test_no_productivity_skill(self):
        app = FakeApp()
        app.productivity = None
        h = ProductivityHandler(app)
        self.assertEqual(h.handle("clipboard history", "PRODUCTIVITY"), "Productivity extras aren't available.")

    def test_register_tools_confirm_gating(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        writes = ("clear_clipboard_history",)
        reads = ("list_clipboard_history", "copy_from_clipboard_history", "ocr_image", "screen_text",
                 "read_pdf_text", "read_docx_text")
        for name in writes:
            self.assertTrue(t.get(name).confirm, name)
        for name in reads:
            self.assertFalse(t.get(name).confirm, name)

    def test_register_tools_no_productivity_skill(self):
        app = FakeApp()
        app.productivity = None
        h = ProductivityHandler(app)
        t = ToolRegistry()
        h.register_tools(t)
        self.assertIsNone(t.get("list_clipboard_history"))


if __name__ == "__main__":
    unittest.main()
