"""Archives, content search, duplicate finding and disk usage — the newer
FileManagerSkill methods. All I/O happens in a temp directory."""
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from skills.file_manager import FileManagerSkill


class FileExtrasBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        home_patch = patch("skills.file_manager.Path.home", return_value=self.home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        env = patch.dict(os.environ, {"APPDATA": str(self.home / "AppData" / "Roaming")})
        env.start()
        self.addCleanup(env.stop)
        self.fm = FileManagerSkill()
        self.fm.current_directory = str(self.work)

    def write(self, name, data=b"x"):
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            data = data.encode()
        path.write_bytes(data)
        return path


class ArchiveTests(FileExtrasBase):
    def test_create_and_extract_round_trip(self):
        self.write("a.txt", "hello")
        self.write("sub/b.txt", "world")
        result = self.fm.create_archive(["a.txt", "sub"], "bundle")
        self.assertIn("Created bundle.zip", result)
        archive = self.work / "bundle.zip"
        self.assertTrue(archive.is_file())
        with zipfile.ZipFile(archive) as zf:
            names = set(zf.namelist())
        self.assertIn("a.txt", names)
        self.assertTrue(any(n.endswith("b.txt") for n in names))

        extract_result = self.fm.extract_archive("bundle.zip")
        self.assertIn("Extracted bundle.zip", extract_result)
        extracted_dir = self.work / "bundle"
        self.assertTrue((extracted_dir / "a.txt").is_file())
        self.assertEqual((extracted_dir / "a.txt").read_text(), "hello")

    def test_archive_inside_its_own_source_folder_skips_itself(self):
        self.write("docs/a.txt", "hello")
        self.assertIn("Created", self.fm.create_archive(["docs"], "docs/backup"))
        with zipfile.ZipFile(self.work / "docs" / "backup.zip") as zf:
            self.assertEqual([n.replace("\\", "/") for n in zf.namelist()], ["docs/a.txt"])

    def test_extract_refuses_to_overwrite_existing_files(self):
        with zipfile.ZipFile(self.work / "pack.zip", "w") as zf:
            zf.writestr("notes.txt", "from zip")
        self.write("pack/notes.txt", "my edits")
        result = self.fm.extract_archive("pack.zip")
        self.assertIn("overwrite 1 existing file", result)
        self.assertEqual((self.work / "pack" / "notes.txt").read_text(), "my edits")

    def test_extract_refuses_archive_bigger_than_free_space(self):
        with zipfile.ZipFile(self.work / "big.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("zeros.bin", b"Z" * 4096)
        with patch("skills.file_manager.shutil.disk_usage", return_value=Mock(free=100)):
            result = self.fm.extract_archive("big.zip")
        self.assertIn("more than", result)
        self.assertFalse((self.work / "big").exists())

    def test_create_archive_missing_source(self):
        result = self.fm.create_archive(["nope.txt"], "out")
        self.assertIn("not found", result)

    def test_create_archive_refuses_existing_name(self):
        self.write("a.txt", "hi")
        self.write("out.zip", "already here")
        result = self.fm.create_archive(["a.txt"], "out.zip")
        self.assertIn("already exists", result)

    def test_extract_missing_archive(self):
        result = self.fm.extract_archive("nope.zip")
        self.assertIn("not found", result)

    def test_extract_non_zip_extension_refused(self):
        self.write("data.rar", "not really a zip")
        result = self.fm.extract_archive("data.rar")
        self.assertIn("only extract .zip", result)

    def test_extract_corrupt_zip(self):
        self.write("bad.zip", "not a real zip file")
        result = self.fm.extract_archive("bad.zip")
        self.assertIn("doesn't look like a valid zip", result)

    def test_extract_blocks_zip_slip(self):
        archive = self.work / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../../evil.txt", "pwned")
        result = self.fm.extract_archive("evil.zip", destination="evil_out")
        self.assertIn("Refusing to extract", result)
        self.assertFalse((self.work / "evil.txt").exists())

    def test_create_archive_no_sources(self):
        self.assertIn("Tell me what to zip", self.fm.create_archive([], "out"))


class SearchContentsTests(FileExtrasBase):
    def test_finds_matching_line(self):
        self.write("notes.txt", "line one\nthe budget is tight\nline three")
        self.write("other.md", "nothing relevant here")
        result = self.fm.search_file_contents("budget")
        self.assertIn("notes.txt:2:", result)
        self.assertNotIn("other.md", result)

    def test_no_matches(self):
        self.write("notes.txt", "hello world")
        result = self.fm.search_file_contents("zzz_not_present")
        self.assertIn("No files", result)

    def test_binary_files_are_skipped(self):
        self.write("image.bin", b"\x00\x01\x02budget\x00\x03")
        result = self.fm.search_file_contents("budget")
        self.assertIn("No files", result)

    def test_extension_filter(self):
        self.write("a.txt", "budget notes here")
        self.write("b.md", "budget notes here too")
        result = self.fm.search_file_contents("budget", extensions=["md"])
        self.assertIn("b.md", result)
        self.assertNotIn("a.txt", result)

    def test_empty_query(self):
        self.assertIn("Tell me what text", self.fm.search_file_contents(""))

    def test_not_a_folder(self):
        self.write("f.txt", "x")
        result = self.fm.search_file_contents("x", folder="f.txt")
        self.assertIn("is not a folder", result)


class DuplicateTests(FileExtrasBase):
    def test_finds_duplicate_group(self):
        self.write("a.txt", "same content")
        self.write("sub/b.txt", "same content")
        self.write("c.txt", "different content entirely")
        result = self.fm.find_duplicate_files()
        self.assertIn("1 duplicate group", result)
        self.assertIn("a.txt", result)
        self.assertIn("b.txt", result)
        self.assertNotIn("c.txt", result)

    def test_no_duplicates(self):
        self.write("a.txt", "one")
        self.write("b.txt", "two")
        result = self.fm.find_duplicate_files()
        self.assertIn("No duplicate files", result)

    def test_empty_files_are_not_flagged(self):
        self.write("a.txt", "")
        self.write("b.txt", "")
        result = self.fm.find_duplicate_files()
        self.assertIn("No duplicate files", result)


class DiskUsageTests(FileExtrasBase):
    def test_reports_sizes_sorted_descending(self):
        self.write("small.txt", b"x" * 10)
        self.write("big.txt", b"x" * 10_000)
        result = self.fm.disk_usage_by_folder()
        lines = result.splitlines()
        big_i = next(i for i, l in enumerate(lines) if "big.txt" in l)
        small_i = next(i for i, l in enumerate(lines) if "small.txt" in l)
        self.assertLess(big_i, small_i)

    def test_includes_subfolder_totals(self):
        self.write("sub/a.txt", b"x" * 5000)
        self.write("sub/b.txt", b"x" * 5000)
        result = self.fm.disk_usage_by_folder()
        self.assertIn("sub", result)

    def test_empty_folder(self):
        empty = self.work / "empty"
        empty.mkdir()
        result = self.fm.disk_usage_by_folder("empty")
        self.assertIn("is empty", result)

    def test_human_size_formatting(self):
        self.assertEqual(self.fm._human_size(500), "500B")
        self.assertEqual(self.fm._human_size(2048), "2.0KB")
        self.assertEqual(self.fm._human_size(5 * 1024 * 1024), "5.0MB")


if __name__ == "__main__":
    unittest.main()
