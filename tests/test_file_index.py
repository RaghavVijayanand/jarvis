"""FileIndex: folder indexing (text/pdf/docx extraction), TF-IDF-style search,
and atomic JSON persistence — all against a temp directory, no real Windows deps."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from skills.file_index import FileIndex


class FileIndexTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.index_file = self.tmp / "index.json"
        self.productivity = Mock()
        self.fi = FileIndex(productivity=self.productivity, index_file=self.index_file)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, content):
        path = self.tmp / name
        path.write_text(content, encoding="utf-8")
        return path


class EdgeCaseTests(FileIndexTestBase):
    def test_empty_folder_names_are_refused(self):
        self.assertIn("Which folder", self.fi.add_folder(""))
        self.write("a.txt", "budget")
        self.fi.add_folder(str(self.tmp))
        self.assertIn("Which folder", self.fi.remove_folder("  "))
        self.assertEqual(len(self.fi._data["files"]), 1)          # '' didn't wipe the index

    def test_remove_folder_respects_path_boundaries(self):
        (self.tmp / "Docs").mkdir()
        (self.tmp / "Docs2").mkdir()
        self.write("Docs/a.txt", "alpha")
        self.write("Docs2/b.txt", "beta")
        self.fi.add_folder(str(self.tmp))
        self.assertIn("Removed 1", self.fi.remove_folder(str(self.tmp / "Docs")))
        self.assertIn("beta", self.fi.search("beta"))

    def test_deleted_files_drop_out_of_results(self):
        path = self.write("gone.txt", "quarterly budget")
        self.fi.add_folder(str(self.tmp))
        path.unlink()
        self.assertIn("deleted", self.fi.search("budget"))

    def test_links_are_not_followed(self):
        import os
        (self.tmp / "real").mkdir()
        self.write("real/a.txt", "unique")
        loop = self.tmp / "real" / "loop"
        try:
            loop.symlink_to(self.tmp, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            import _winapi
            _winapi.CreateJunction(str(self.tmp), str(loop))
        self.assertIn("Indexed 1 file", self.fi.add_folder(str(self.tmp / "real")))


class AddFolderTests(FileIndexTestBase):
    def test_not_a_folder(self):
        msg = self.fi.add_folder(str(self.tmp / "nope"))
        self.assertIn("not a folder", msg)

    def test_indexes_text_files(self):
        self.write("a.txt", "the quarterly budget report for Q3")
        self.write("b.md", "notes about the picnic")
        msg = self.fi.add_folder(str(self.tmp))
        self.assertIn("Indexed 2 file(s)", msg)
        self.assertEqual(len(self.fi._data["files"]), 2)

    def test_skips_unlisted_extensions(self):
        self.write("a.exe", "binary junk")
        msg = self.fi.add_folder(str(self.tmp))
        self.assertIn("Indexed 0 file(s)", msg)

    def test_custom_extensions(self):
        self.write("a.rst", "hello world")
        self.write("b.txt", "hello world")
        msg = self.fi.add_folder(str(self.tmp), extensions=["rst"])
        self.assertIn("Indexed 1 file(s)", msg)

    def test_pdf_extraction_via_productivity(self):
        pdf = self.tmp / "report.pdf"
        pdf.write_bytes(b"%PDF-fake")
        self.productivity.read_pdf_text.return_value = "quarterly budget details"
        msg = self.fi.add_folder(str(self.tmp))
        self.assertIn("Indexed 1 file(s)", msg)
        self.productivity.read_pdf_text.assert_called_once_with(str(pdf))

    def test_pdf_extraction_failure_skipped(self):
        (self.tmp / "report.pdf").write_bytes(b"%PDF-fake")
        self.productivity.read_pdf_text.return_value = "Couldn't open that PDF."
        msg = self.fi.add_folder(str(self.tmp))
        self.assertIn("Indexed 0 file(s)", msg)
        self.assertIn("1 skipped", msg)

    def test_pdf_no_productivity_skipped(self):
        (self.tmp / "report.pdf").write_bytes(b"%PDF-fake")
        fi = FileIndex(productivity=None, index_file=self.index_file)
        msg = fi.add_folder(str(self.tmp))
        self.assertIn("Indexed 0 file(s)", msg)

    def test_docx_extraction_via_productivity(self):
        docx = self.tmp / "notes.docx"
        docx.write_bytes(b"PK-fake")
        self.productivity.read_docx_text.return_value = "meeting notes about budget"
        msg = self.fi.add_folder(str(self.tmp))
        self.assertIn("Indexed 1 file(s)", msg)
        self.productivity.read_docx_text.assert_called_once_with(str(docx))

    def test_docx_extraction_failure_skipped(self):
        (self.tmp / "notes.docx").write_bytes(b"PK-fake")
        self.productivity.read_docx_text.return_value = "No text found in that document."
        msg = self.fi.add_folder(str(self.tmp))
        self.assertIn("0 file(s)", msg)

    def test_oversized_file_skipped(self):
        from skills import file_index as fi_mod
        original = fi_mod._MAX_FILE_BYTES
        fi_mod._MAX_FILE_BYTES = 5
        try:
            self.write("a.txt", "this is way more than five bytes")
            msg = self.fi.add_folder(str(self.tmp))
            self.assertIn("0 file(s)", msg)
            self.assertIn("skipped", msg)
        finally:
            fi_mod._MAX_FILE_BYTES = original

    def test_recurses_into_subfolders(self):
        sub = self.tmp / "sub"
        sub.mkdir()
        (sub / "c.txt").write_text("nested content", encoding="utf-8")
        msg = self.fi.add_folder(str(self.tmp))
        self.assertIn("Indexed 1 file(s)", msg)

    def test_extract_text_generic_exception_returns_none(self):
        path = self.tmp / "weird.txt"
        path.write_text("hi", encoding="utf-8")
        with unittest.mock.patch.object(Path, "read_bytes", side_effect=OSError("boom")):
            self.assertIsNone(self.fi._extract_text(path))


class RemoveClearStatusTests(FileIndexTestBase):
    def test_remove_folder(self):
        self.write("a.txt", "hello")
        self.fi.add_folder(str(self.tmp))
        msg = self.fi.remove_folder(str(self.tmp))
        self.assertIn("Removed", msg)
        self.assertEqual(len(self.fi._data["files"]), 0)

    def test_remove_folder_none_matching(self):
        msg = self.fi.remove_folder(str(self.tmp / "other"))
        self.assertIn("Removed 0", msg)

    def test_clear_index(self):
        self.write("a.txt", "hello")
        self.fi.add_folder(str(self.tmp))
        msg = self.fi.clear_index()
        self.assertIn("Cleared", msg)
        self.assertEqual(len(self.fi._data["files"]), 0)

    def test_index_status_empty(self):
        msg = self.fi.index_status()
        self.assertIn("empty", msg)

    def test_index_status_nonempty(self):
        self.write("a.txt", "hello world")
        self.fi.add_folder(str(self.tmp))
        msg = self.fi.index_status()
        self.assertIn("1 file(s) indexed", msg)


class SearchTests(FileIndexTestBase):
    def setUp(self):
        super().setUp()
        self.write("budget.txt", "the quarterly budget report discusses Q3 spending in detail")
        self.write("picnic.txt", "notes about the summer picnic and sandwiches")
        self.fi.add_folder(str(self.tmp))

    def test_empty_query(self):
        self.assertEqual(self.fi.search("   "), "Tell me what to search for.")

    def test_empty_index(self):
        fi = FileIndex(productivity=self.productivity, index_file=self.tmp / "other.json")
        self.assertIn("empty", fi.search("budget"))

    def test_search_ranks_relevant_file_first(self):
        result = self.fi.search("budget")
        self.assertIn("budget.txt", result.splitlines()[0])

    def test_search_no_match(self):
        result = self.fi.search("xylophone")
        self.assertIn("No indexed files match", result)

    def test_search_limit(self):
        result = self.fi.search("the", limit=1)
        self.assertEqual(len(result.splitlines()) // 2, 1)

    def test_search_includes_snippet(self):
        result = self.fi.search("picnic")
        self.assertIn("picnic", result.lower())


class PersistenceTests(FileIndexTestBase):
    def test_round_trips_through_disk(self):
        self.write("a.txt", "hello world")
        self.fi.add_folder(str(self.tmp))
        fi2 = FileIndex(productivity=self.productivity, index_file=self.index_file)
        self.assertEqual(len(fi2._data["files"]), 1)

    def test_load_missing_file(self):
        fi = FileIndex(index_file=self.tmp / "missing.json")
        self.assertEqual(fi._data, {"files": {}})

    def test_load_corrupt_json(self):
        self.index_file.write_text("not json", encoding="utf-8")
        fi = FileIndex(index_file=self.index_file)
        self.assertEqual(fi._data, {"files": {}})

    def test_load_wrong_shape(self):
        self.index_file.write_text(json.dumps({"files": "nope"}), encoding="utf-8")
        fi = FileIndex(index_file=self.index_file)
        self.assertEqual(fi._data, {"files": {}})

    def test_load_not_a_dict(self):
        self.index_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        fi = FileIndex(index_file=self.index_file)
        self.assertEqual(fi._data, {"files": {}})


if __name__ == "__main__":
    unittest.main()
