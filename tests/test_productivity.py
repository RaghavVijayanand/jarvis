"""ProductivitySkill: clipboard history (in-memory, thread not exercised directly),
OCR (winsdk mocked), and PDF/docx text extraction (pypdf/python-docx mocked)."""
import sys
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

import skills.productivity as prod_mod
from skills.productivity import ClipboardHistory, ProductivitySkill


class ClipboardHistoryTests(unittest.TestCase):
    def setUp(self):
        self.ch = ClipboardHistory(poll_seconds=0.01, max_history=5)

    def test_empty_history(self):
        self.assertIn("empty", self.ch.list_history())

    def test_list_history_after_manual_append(self):
        self.ch._history.appendleft("hello world")
        self.ch._history.appendleft("second copy")
        result = self.ch.list_history()
        self.assertIn("0: second copy", result)
        self.assertIn("1: hello world", result)

    def test_list_history_truncates_long_entries(self):
        self.ch._history.appendleft("x" * 200)
        result = self.ch.list_history()
        self.assertIn("...", result)
        self.assertLessEqual(len(result.splitlines()[0]), 90)

    def test_get_entry(self):
        self.ch._history.appendleft("b")
        self.ch._history.appendleft("a")
        self.assertEqual(self.ch.get_entry(0), "a")
        self.assertEqual(self.ch.get_entry(1), "b")
        self.assertIsNone(self.ch.get_entry(5))
        self.assertIsNone(self.ch.get_entry(-1))

    def test_clear(self):
        self.ch._history.appendleft("a")
        result = self.ch.clear()
        self.assertIn("Cleared", result)
        self.assertEqual(len(self.ch._history), 0)

    def test_max_history_evicts_oldest(self):
        for i in range(10):
            self.ch._history.appendleft(f"item{i}")
        self.assertEqual(len(self.ch._history), 5)

    def test_read_clipboard_no_pywin32(self):
        with patch.dict(sys.modules, {"win32clipboard": None}):
            self.assertIsNone(self.ch._read_clipboard())

    def test_start_and_stop_thread(self):
        self.ch.start()
        self.assertTrue(self.ch._thread.is_alive())
        self.ch.stop()
        self.ch._thread.join(timeout=2)
        self.assertFalse(self.ch._thread.is_alive())

    def test_start_twice_does_not_spawn_second_thread(self):
        self.ch.start()
        first = self.ch._thread
        self.ch.start()
        self.assertIs(self.ch._thread, first)
        self.ch.stop()
        self.ch._thread.join(timeout=2)

    def test_loop_appends_changed_clipboard_text(self):
        values = iter(["first", "first", "second", "second"])

        def fake_read():
            return next(values, "second")
        with patch.object(self.ch, "_read_clipboard", side_effect=fake_read):
            self.ch.start()
            self.ch._thread.join(timeout=1)
        self.ch.stop()
        history = list(self.ch._history)
        self.assertIn("first", history)
        self.assertIn("second", history)


class ProductivitySkillClipboardTests(unittest.TestCase):
    def setUp(self):
        self.pr = ProductivitySkill()
        self.addCleanup(self.pr.clipboard_history.stop)

    def test_list_clipboard_history_delegates(self):
        self.pr.clipboard_history._history.appendleft("hi")
        self.assertIn("hi", self.pr.list_clipboard_history())

    def test_copy_from_history_bad_index_type(self):
        self.assertIn("Give me a clipboard history index", self.pr.copy_from_history("nope"))

    def test_copy_from_history_out_of_range(self):
        self.assertIn("No clipboard history entry", self.pr.copy_from_history(3))

    def test_copy_from_history_success(self):
        self.pr.clipboard_history._history.appendleft("copy me")
        fake_win32clipboard = types.ModuleType("win32clipboard")
        fake_win32clipboard.OpenClipboard = Mock()
        fake_win32clipboard.EmptyClipboard = Mock()
        fake_win32clipboard.SetClipboardText = Mock()
        fake_win32clipboard.CloseClipboard = Mock()
        fake_win32clipboard.CF_UNICODETEXT = 13
        with patch.dict(sys.modules, {"win32clipboard": fake_win32clipboard}):
            result = self.pr.copy_from_history(0)
        self.assertIn("Copied", result)
        fake_win32clipboard.SetClipboardText.assert_called_once_with("copy me", 13)

    def test_copy_from_history_no_pywin32(self):
        self.pr.clipboard_history._history.appendleft("copy me")
        with patch.dict(sys.modules, {"win32clipboard": None}):
            result = self.pr.copy_from_history(0)
        self.assertIn("isn't available", result)

    def test_clear_clipboard_history(self):
        self.pr.clipboard_history._history.appendleft("a")
        result = self.pr.clear_clipboard_history()
        self.assertIn("Cleared", result)


class OcrTests(unittest.TestCase):
    def setUp(self):
        self.pr = ProductivitySkill()
        self.addCleanup(self.pr.clipboard_history.stop)

    def test_ocr_image_missing_file(self):
        self.assertIn("Can't find", self.pr.ocr_image("/no/such/file.png"))

    def test_ocr_image_no_winsdk(self):
        with patch("os.path.isfile", return_value=True):
            with patch.dict(sys.modules, {"winsdk": None, "winsdk.windows": None,
                                          "winsdk.windows.globalization": None,
                                          "winsdk.windows.graphics.imaging": None,
                                          "winsdk.windows.media.ocr": None,
                                          "winsdk.windows.storage": None}):
                result = self.pr.ocr_image("/tmp/fake.png")
        self.assertIn("winsdk", result)

    def test_screen_text_no_screen_automation(self):
        self.pr.app = None
        self.assertIn("isn't available", self.pr.screen_text())

    def test_screen_text_capture_failure(self):
        screen = Mock()
        screen.take_screenshot.side_effect = RuntimeError("no display")
        self.pr.app = Mock(screen_automation=screen)
        result = self.pr.screen_text()
        self.assertIn("Couldn't capture", result)

    def test_screen_text_delegates_to_ocr(self):
        screen = Mock()
        screen.take_screenshot.return_value = "/tmp/shot.png"
        self.pr.app = Mock(screen_automation=screen)
        with patch.object(self.pr, "ocr_image", return_value="some text") as ocr:
            result = self.pr.screen_text()
        ocr.assert_called_once_with("/tmp/shot.png")
        self.assertEqual(result, "some text")


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.pr = ProductivitySkill()
        self.addCleanup(self.pr.clipboard_history.stop)

    def test_read_pdf_missing_file(self):
        self.assertIn("Can't find", self.pr.read_pdf_text("/no/such.pdf"))

    def test_read_pdf_no_pypdf(self):
        with patch("os.path.isfile", return_value=True):
            with patch.dict(sys.modules, {"pypdf": None}):
                result = self.pr.read_pdf_text("/tmp/fake.pdf")
        self.assertIn("pypdf", result)

    def test_read_pdf_success(self):
        page1, page2 = Mock(), Mock()
        page1.extract_text.return_value = "Hello "
        page2.extract_text.return_value = "world"
        reader = Mock(pages=[page1, page2])
        fake_pypdf = types.ModuleType("pypdf")
        fake_pypdf.PdfReader = Mock(return_value=reader)
        with patch("os.path.isfile", return_value=True), patch.dict(sys.modules, {"pypdf": fake_pypdf}):
            result = self.pr.read_pdf_text("/tmp/fake.pdf")
        self.assertIn("Hello", result)
        self.assertIn("world", result)

    def test_read_pdf_open_error(self):
        fake_pypdf = types.ModuleType("pypdf")
        fake_pypdf.PdfReader = Mock(side_effect=Exception("corrupt"))
        with patch("os.path.isfile", return_value=True), patch.dict(sys.modules, {"pypdf": fake_pypdf}):
            result = self.pr.read_pdf_text("/tmp/fake.pdf")
        self.assertIn("Couldn't open", result)

    def test_read_pdf_no_text(self):
        page = Mock()
        page.extract_text.return_value = ""
        reader = Mock(pages=[page])
        fake_pypdf = types.ModuleType("pypdf")
        fake_pypdf.PdfReader = Mock(return_value=reader)
        with patch("os.path.isfile", return_value=True), patch.dict(sys.modules, {"pypdf": fake_pypdf}):
            result = self.pr.read_pdf_text("/tmp/fake.pdf")
        self.assertIn("No extractable text", result)

    def test_read_docx_missing_file(self):
        self.assertIn("Can't find", self.pr.read_docx_text("/no/such.docx"))

    def test_read_docx_no_python_docx(self):
        with patch("os.path.isfile", return_value=True):
            with patch.dict(sys.modules, {"docx": None}):
                result = self.pr.read_docx_text("/tmp/fake.docx")
        self.assertIn("python-docx", result)

    def test_read_docx_success(self):
        p1, p2 = Mock(text="Hello"), Mock(text="world")
        document = Mock(paragraphs=[p1, p2])
        fake_docx = types.ModuleType("docx")
        fake_docx.Document = Mock(return_value=document)
        with patch("os.path.isfile", return_value=True), patch.dict(sys.modules, {"docx": fake_docx}):
            result = self.pr.read_docx_text("/tmp/fake.docx")
        self.assertIn("Hello", result)
        self.assertIn("world", result)

    def test_read_docx_open_error(self):
        fake_docx = types.ModuleType("docx")
        fake_docx.Document = Mock(side_effect=Exception("bad zip"))
        with patch("os.path.isfile", return_value=True), patch.dict(sys.modules, {"docx": fake_docx}):
            result = self.pr.read_docx_text("/tmp/fake.docx")
        self.assertIn("Couldn't open", result)


if __name__ == "__main__":
    unittest.main()
