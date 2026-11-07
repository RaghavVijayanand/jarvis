"""File-manager regressions: Documents default, overwrite flow, CWD safety."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skills.file_manager import FileManagerSkill


class FileManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fm = FileManagerSkill()
        self.fm.current_directory = self.temp.name  # isolate all writes

    def test_default_location_is_documents(self):
        self.assertEqual(FileManagerSkill().current_directory,
                         str(Path.home() / "Documents"))

    def test_default_location_falls_back_to_home_when_unwritable(self):
        bogus_home = Path(self.temp.name) / "home"
        with patch('skills.file_manager.Path.home', return_value=bogus_home), \
             patch.object(Path, 'mkdir', side_effect=PermissionError):
            fm = FileManagerSkill()
        self.assertEqual(fm.current_directory, str(bogus_home))

    def test_create_ask_then_overwrite_completes(self):
        first = self.fm.create_file("notes")
        self.assertIn("created successfully", first)
        path = Path(self.temp.name) / "notes.txt"
        self.assertTrue(path.exists())
        second = self.fm.create_file("notes")
        self.assertIn("overwrite", second.lower())
        third = self.fm.create_file("notes", content="v2", overwrite=True)
        self.assertIn("created successfully", third)
        self.assertEqual(path.read_text(encoding='utf-8'), "v2")

    def test_create_at_location_overwrite_flow(self):
        self.assertIn("created successfully", self.fm.create_file_at_location("report", content="r1"))
        self.assertIn("overwrite", self.fm.create_file_at_location("report", content="r2").lower())
        self.assertIn("created successfully",
                      self.fm.create_file_at_location("report", content="r2", overwrite=True))

    def test_change_directory_does_not_mutate_process_cwd(self):
        before = os.getcwd()
        other = Path(self.temp.name) / "sub"
        other.mkdir()
        response = self.fm.change_directory(str(other))
        self.assertIn("Changed directory", response)
        self.assertEqual(os.getcwd(), before)
        self.assertEqual(self.fm.current_directory, str(other))

    def test_create_read_delete_roundtrip(self):
        self.fm.create_file("demo", content="hello")
        self.assertTrue(self.fm.file_exists("demo"))
        self.assertIn("hello", self.fm.read_file("demo"))
        self.assertIn("deleted", self.fm.delete_file("demo").lower())
        self.assertFalse(self.fm.file_exists("demo"))

    def test_live_default_directory_is_writable(self):
        fm = FileManagerSkill()  # real default location on this machine
        probe = Path(fm.current_directory) / "_jarvis_write_probe.tmp"
        try:
            probe.write_text('probe', encoding='utf-8')
            self.assertTrue(probe.exists())
        finally:
            probe.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
