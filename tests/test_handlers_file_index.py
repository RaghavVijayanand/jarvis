"""FileIndexHandler: indexing/searching all run immediately (nothing here is
destructive — the index is rebuildable)."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.file_index import FileIndexHandler


class FakeApp:
    def __init__(self):
        self.file_index = Mock()
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class FileIndexHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = FileIndexHandler(self.app)

    def test_index_folder_runs_immediately(self):
        self.app.file_index.add_folder.return_value = "Indexed 3 file(s) under 'C:\\Docs'."
        reply = self.h.handle(r"index folder C:\Docs", "FILEINDEX")
        self.assertFalse(self.app.pending)
        self.app.file_index.add_folder.assert_called_once_with("C:\\Docs")
        self.assertIn("Indexed", reply)

    def test_remove_folder_runs_immediately(self):
        self.app.file_index.remove_folder.return_value = "Removed 3 file(s) under 'C:\\Docs' from the index."
        reply = self.h.handle(r"remove folder C:\Docs from the index", "FILEINDEX")
        self.assertFalse(self.app.pending)
        self.app.file_index.remove_folder.assert_called_once_with("C:\\Docs")
        self.assertIn("Removed", reply)

    def test_unindex_folder_alias(self):
        self.h.handle(r"unindex folder C:\Docs from the index", "FILEINDEX")
        self.app.file_index.remove_folder.assert_called_once_with("C:\\Docs")

    def test_clear_index_runs_immediately(self):
        self.app.file_index.clear_index.return_value = "Cleared the file index (3 file(s))."
        reply = self.h.handle("clear the file index", "FILEINDEX")
        self.assertFalse(self.app.pending)
        self.app.file_index.clear_index.assert_called_once()
        self.assertIn("Cleared", reply)

    def test_clear_file_index_no_the(self):
        self.h.handle("clear my file index", "FILEINDEX")
        self.app.file_index.clear_index.assert_called_once()

    def test_index_status_runs_immediately(self):
        self.app.file_index.index_status.return_value = "3 file(s) indexed, 900 word(s) total."
        reply = self.h.handle("file index status", "FILEINDEX")
        self.assertFalse(self.app.pending)
        self.app.file_index.index_status.assert_called_once()
        self.assertIn("indexed", reply)

    def test_how_many_files_are_indexed(self):
        self.h.handle("how many files are indexed", "FILEINDEX")
        self.app.file_index.index_status.assert_called_once()

    def test_search_files_runs_immediately(self):
        self.app.file_index.search.return_value = "• C:\\Docs\\budget.docx\n    ..."
        reply = self.h.handle("search my files for Q3 budget", "FILEINDEX")
        self.assertFalse(self.app.pending)
        self.app.file_index.search.assert_called_once_with("Q3 budget")
        self.assertIn("budget.docx", reply)

    def test_search_indexed_files_alias(self):
        self.h.handle("search indexed files for Q3 budget", "FILEINDEX")
        self.app.file_index.search.assert_called_once_with("Q3 budget")

    def test_find_file_about(self):
        self.h.handle("find the document about the Q3 budget", "FILEINDEX")
        self.app.file_index.search.assert_called_once_with("the Q3 budget")

    def test_find_file_where(self):
        self.h.handle("find the file where I discussed layoffs", "FILEINDEX")
        self.app.file_index.search.assert_called_once_with("I discussed layoffs")

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "FILEINDEX"))

    def test_no_file_index(self):
        app = FakeApp()
        app.file_index = None
        h = FileIndexHandler(app)
        self.assertEqual(h.handle("file index status", "FILEINDEX"), "The file index isn't available.")

    def test_register_tools_none_confirm_gated(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        for name in ("index_folder", "remove_indexed_folder", "clear_file_index", "file_index_status",
                     "search_indexed_files"):
            self.assertFalse(t.get(name).confirm, name)

    def test_register_tools_no_file_index(self):
        app = FakeApp()
        app.file_index = None
        h = FileIndexHandler(app)
        t = ToolRegistry()
        h.register_tools(t)
        self.assertIsNone(t.get("index_folder"))


if __name__ == "__main__":
    unittest.main()
