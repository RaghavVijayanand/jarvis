"""Coverage and regression tests for skills/file_manager.py and skills/task_scheduler.py.

All file I/O happens in temporary directories (home, APPDATA and the task store
are patched); the scheduler uses a frozen clock and mocked timers unless a test
exercises the real worker thread.
"""
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime as real_datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from skills import file_manager as fm_module
from skills import task_scheduler as ts_module
from skills.file_manager import FileManagerSkill
from skills.task_scheduler import TaskScheduler


# --------------------------------------------------------------------------- helpers
FROZEN = real_datetime(2026, 9, 23, 10, 0, 0)  # a Wednesday


class _NtOs:
    """Module proxy reporting os.name == 'nt' without affecting pathlib."""
    name = "nt"

    def __init__(self, **extra):
        self.__dict__.update(extra)

    def __getattr__(self, attr):
        return getattr(os, attr)


def frozen_datetime(moment):
    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls.fromtimestamp(0).replace(year=moment.year, month=moment.month, day=moment.day,
                                                hour=moment.hour, minute=moment.minute,
                                                second=moment.second, microsecond=moment.microsecond)
            return value if tz is None else value.astimezone(tz)
    return FrozenDatetime


class FileTestBase(unittest.TestCase):
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
        path.write_bytes(data)
        return path


def _dir_link(link, target):
    """A directory symlink, or on Windows without the symlink privilege a junction — which any
    user can create, so it is exactly what a real redirect-into-Startup attempt would use."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import _winapi
        _winapi.CreateJunction(str(target), str(link))


def _file_symlink(case, link, target):
    try:
        link.symlink_to(target)
    except OSError:
        case.skipTest("file symlinks need Developer Mode or admin on Windows")


# --------------------------------------------------------------------------- file manager
class FileManagerDefaultsTests(FileTestBase):
    def test_default_documents_folder_created_under_home(self):
        self.assertEqual(FileManagerSkill().current_directory, str(self.home / "Documents"))
        self.assertTrue((self.home / "Documents").is_dir())

    def test_handle_file_command_passthrough(self):
        self.assertIsNone(self.fm.handle_file_command("what's the weather"))
        self.assertIn("Current directory", self.fm.handle_file_command("pwd"))


class FileManagerPathSafetyTests(FileTestBase):
    def test_relative_parent_traversal_is_stripped(self):
        self.fm.create_file("../../../escape.txt", "x")
        self.assertTrue((self.work / "escape.txt").exists())
        self.assertFalse((self.root / "escape.txt").exists())

    def test_bare_dotdot_does_not_create_file_named_after_the_folder(self):
        result = self.fm.create_file("..", "x")
        self.assertIn("Error", result)
        self.assertFalse((self.root / "work.txt").exists())
        self.assertIn("Error", self.fm.create_file("", "x"))
        self.assertIn("Error", self.fm.create_file_at_location("..", "x"))

    def test_absolute_dotdot_cannot_reach_protected_folder(self):
        ups = "/".join([".."] * (len(self.work.parts) + 2))       # past the drive root, any temp depth
        self.assertIn("system folders", self.fm.create_file(f"{self.work}/{ups}/windows/evil.txt", "x"))
        if os.name != "nt":     # on Windows '/Program Files' has no drive, so it's a plain relative name
            self.assertIn("system folders", self.fm.create_folder("/Program Files/x"))

    def test_symlink_into_protected_location_is_refused(self):
        startup = self.home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu"
        startup.mkdir(parents=True)
        link = self.work / "innocent"
        _dir_link(link, startup)
        self.assertIn("protected", self.fm.create_file("innocent/run.bat", "echo"))
        self.assertFalse((startup / "run.bat").exists())
        # Direct writes to JARVIS's own config folder are refused too.
        self.assertIn("protected", self.fm.create_file(str(self.home / "AppData/Roaming/Jarvis/.env"), "K=1"))

    def test_overwrite_through_symlink_refused(self):
        real = self.write("real.txt", b"orig")
        _file_symlink(self, self.work / "link.txt", real)
        self.assertIn("symbolic link", self.fm.create_file("link.txt", "new", overwrite=True))
        self.assertEqual(real.read_bytes(), b"orig")

    def test_reserved_device_names_rejected(self):
        for name in ("CON", "nul.txt", "com1.log", "Lpt9.tar.gz", "aux"):
            with self.subTest(name=name):
                self.assertIn("reserved", self.fm.create_file(name, "x"))
        self.assertIn("reserved", self.fm.create_file_at_location("prn", "x"))
        self.write("a.txt")
        self.assertIn("reserved", self.fm.rename_file("a.txt", "con"))
        self.assertIn("reserved", self.fm.create_folder("nul"))
        # Names that merely contain a device name are fine.
        self.assertIn("created successfully", self.fm.create_file("console notes", "x"))

    def test_illegal_characters_replaced(self):
        self.assertIn("created", self.fm.create_file('bad<>:"|?*name', "x"))
        self.assertTrue((self.work / "bad_______name.txt").exists())
        self.assertEqual(self.fm._clean_filename(' "a/ b. /../c\x01" '), "a/b/c_")

    def test_known_folder_prefixes(self):
        self.assertEqual(self.fm._resolve("desktop/x.txt"), self.home / "Desktop" / "x.txt")
        self.assertEqual(self.fm._resolve("the desktop"), self.home / "Desktop")
        self.assertEqual(self.fm._resolve("my downloads folder"), self.home / "Downloads")
        self.assertEqual(self.fm._resolve(str(self.root / "abs.txt")), self.root / "abs.txt")
        with self.assertRaises(ValueError):
            self.fm._resolve("  ")

    def test_has_extension(self):
        self.assertTrue(self.fm._has_extension("a.txt"))
        self.assertFalse(self.fm._has_extension("Mr. Smith notes"))
        self.assertIn("created", self.fm.create_file("Mr. Smith notes", "x"))
        self.assertTrue((self.work / "Mr. Smith notes.txt").exists())
        self.assertIn("x", self.fm.read_file("Mr. Smith notes"))


class FileManagerCrudTests(FileTestBase):
    def test_create_existing_asks_and_yes_overwrites(self):
        self.fm.create_file("n.txt", "one")
        prompt = self.fm.route_command("create file n.txt with content two")
        self.assertIn("Reply yes", prompt)
        self.assertIn("created successfully", self.fm.route_command("Yes."))
        self.assertEqual((self.work / "n.txt").read_text(encoding="utf-8"), "two")
        self.assertEqual(self.fm.route_command("overwrite n.txt"), "There is no pending file overwrite to confirm.")

    def test_confirm_after_file_deleted(self):
        self.fm.create_file("n.txt", "one")
        self.fm.create_file("n.txt", "two")
        (self.work / "n.txt").unlink()
        self.assertIn("file changed", self.fm.route_command("yes"))

    def test_confirm_os_error_reported(self):
        self.fm.create_file("n.txt", "one")
        self.fm.create_file("n.txt", "two")
        with patch.object(FileManagerSkill, "_fingerprint", side_effect=OSError("locked")):
            self.assertIn("Unable to confirm overwrite", self.fm.route_command("confirm"))

    def test_empty_content_writes_header(self):
        self.fm.create_file("blank")
        self.assertIn("Created by JARVIS", (self.work / "blank.txt").read_text(encoding="utf-8"))

    def test_create_at_location_desktop_and_absolute(self):
        self.assertIn("created", self.fm.create_file_at_location("todo", "x", "the desktop"))
        self.assertTrue((self.home / "Desktop" / "todo.txt").exists())
        other = self.root / "abs_dir"
        self.assertIn("created", self.fm.create_file_at_location("y.md", "x", str(other)))
        self.assertTrue((other / "y.md").exists())

    def test_file_exists_variants(self):
        self.assertFalse(self.fm.file_exists(""))
        self.write("a.txt")
        self.assertTrue(self.fm.file_exists("a.txt"))
        self.assertTrue(self.fm.file_exists("a"))
        self.assertFalse(self.fm.file_exists("b"))
        self.assertFalse(self.fm.file_exists("b.md"))
        with patch.object(FileManagerSkill, "_clean_filename", side_effect=RuntimeError):
            self.assertFalse(self.fm.file_exists("a"))

    def test_rename_collisions_and_case_only(self):
        self.write("a.txt")
        self.write("b.txt")
        self.assertIn("already exists", self.fm.rename_file("a.txt", "b.txt"))
        self.assertIn("not found", self.fm.rename_file("zzz.txt", "q.txt"))
        self.assertIn("new name", self.fm.rename_file("a.txt", ".."))
        with patch("skills.file_manager.os.path.normcase", side_effect=lambda s: s.lower()):
            # Simulate a case-insensitive filesystem: renaming to A.txt is not a collision.
            with patch.object(Path, "exists", return_value=True), patch.object(Path, "rename") as ren:
                self.assertIn("renamed", self.fm.rename_file("a.txt", "A.txt"))
                ren.assert_called_once()
        self.assertIn("renamed", self.fm.rename_file("a.txt", "c"))
        self.assertTrue((self.work / "c.txt").exists())

    def test_rename_error_path(self):
        self.write("a.txt")
        with patch.object(Path, "rename", side_effect=OSError("busy")):
            self.assertIn("Error renaming", self.fm.rename_file("a.txt", "z.txt"))

    def test_copy_and_move_collisions_and_folders(self):
        self.write("r.pdf", b"%PDF")
        self.assertIn("copied", self.fm.copy_file("r.pdf", "copy.pdf"))
        self.assertIn("already exists", self.fm.copy_file("r.pdf", "copy.pdf"))
        self.assertIn("not found", self.fm.copy_file("none.pdf", "x.pdf"))
        (self.work / "sub").mkdir()
        self.assertIn("copied", self.fm.copy_file("r.pdf", "sub"))
        self.assertTrue((self.work / "sub" / "r.pdf").exists())
        # A known folder that does not exist yet is still a folder, not a file name.
        self.assertIn("Moved", self.fm.route_command("move r.pdf to the downloads folder"))
        self.assertTrue((self.home / "Downloads" / "r.pdf").is_file())
        self.assertIn("not found", self.fm.move_file("r.pdf", "downloads"))
        self.write("r.pdf", b"again")
        self.assertIn("already exists", self.fm.move_file("r.pdf", "downloads"))
        self.assertIn("Moved", self.fm.move_file("r.pdf", "newdir/"))
        self.assertTrue((self.work / "newdir" / "r.pdf").is_file())

    def test_copy_move_errors(self):
        self.write("a.txt")
        with patch("skills.file_manager.shutil.copy2", side_effect=OSError("disk")):
            self.assertIn("Error copying", self.fm.copy_file("a.txt", "b.txt"))
        with patch("skills.file_manager.shutil.move", side_effect=OSError("disk")):
            self.assertIn("Error moving", self.fm.move_file("a.txt", "b.txt"))

    def test_create_folder(self):
        self.assertIn("created successfully", self.fm.create_folder("proj"))
        self.assertIn("already exists", self.fm.create_folder("proj"))

    def test_delete_uses_send2trash_when_available(self):
        path = self.write("d.txt")
        fake = types.ModuleType("send2trash")
        fake.send2trash = Mock()
        with patch.dict(sys.modules, {"send2trash": fake}):
            self.assertIn("Recycle Bin", self.fm.delete_file("d.txt"))
        fake.send2trash.assert_called_once_with(str(path))
        self.assertTrue(path.exists())  # the fake did not really delete

    def test_delete_never_permanent_on_windows_without_send2trash(self):
        path = self.write("d.txt")
        with patch.dict(sys.modules, {"send2trash": None}), patch.object(fm_module, "os", _NtOs()):
            self.assertIn("left it in place", self.fm.delete_file("d.txt"))
        self.assertTrue(path.exists())

    def test_delete_refuses_folders_missing_and_errors(self):
        (self.work / "f").mkdir()
        self.assertIn("folder", self.fm.delete_file("f"))
        self.assertIn("not found", self.fm.delete_file("nope"))
        self.write("e.txt")
        fake = types.ModuleType("send2trash")
        fake.send2trash = Mock(side_effect=OSError("recycle bin unavailable"))
        with patch.dict(sys.modules, {"send2trash": fake}):
            self.assertIn("Error deleting", self.fm.delete_file("e.txt"))

    def test_list_files_sizes_limits_and_errors(self):
        self.assertIn("Directory is empty", self.fm.list_files())
        self.write("small.txt", b"x")
        self.write("kb.bin", b"x" * 2048)
        self.write("mb.bin", b"x" * (1024 * 1024 + 1))
        listing = self.fm.list_files()
        self.assertIn("2.0 KB", listing)
        self.assertIn("1.0 MB", listing)
        for i in range(11):
            self.write(f"f{i:02}.txt")
            (self.work / f"d{i:02}").mkdir()
        listing = self.fm.list_files()
        self.assertIn("more files", listing)
        self.assertIn("more folders", listing)
        self.assertIn("does not exist", self.fm.list_files("missing_dir"))
        (self.work / "gone").mkdir()
        _dir_link(self.work / "broken", self.work / "gone")
        (self.work / "gone").rmdir()                             # leaves a dangling link
        with patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            self.assertIn("Error listing", self.fm.list_files())

    def test_list_files_skips_unreadable_entries(self):
        self.write("ok.txt")
        with patch.object(Path, "is_file", side_effect=PermissionError("no")):
            self.assertIn("Directory is empty", self.fm.list_files())

    def test_file_info_and_change_directory(self):
        self.write("i.txt", b"x" * 10)
        self.assertIn("10 bytes", self.fm.get_file_info("i.txt"))
        self.write("k.txt", b"x" * 5000)
        self.assertIn("KB", self.fm.get_file_info("k"))
        self.write("m.txt", b"x" * (2 * 1024 * 1024))
        self.assertIn("MB", self.fm.get_file_info("m.txt"))
        self.assertIn("not found", self.fm.get_file_info("none"))
        with patch.object(Path, "stat", side_effect=OSError("x")):
            self.assertIn("Error getting file info", self.fm.get_file_info("i.txt"))
        self.assertIn("does not exist", self.fm.change_directory("nowhere"))
        self.assertIn("not a directory", self.fm.change_directory("i.txt"))
        self.assertIn("Error changing", self.fm.change_directory("."))
        (self.work / "sub").mkdir()
        self.fm.change_directory("sub")
        self.assertIn("Changed directory", self.fm.change_directory(".."))
        self.assertEqual(self.fm.current_directory, str(self.work.resolve()))

    def test_open_path(self):
        self.write("o.txt")
        self.assertIn("Opened", self.fm.open_path("o.txt"))
        self.assertIn("not found", self.fm.open_path("missing.txt"))
        self.assertIn("Couldn't open", self.fm.open_path(""))
        start = Mock()
        with patch.object(fm_module, "os", _NtOs(startfile=start)):
            self.fm.open_path("o.txt")
        start.assert_called_once_with(str(self.work / "o.txt"))


class FileManagerReadTests(FileTestBase):
    def test_utf8_bom_is_stripped(self):
        self.write("bom.txt", b"\xef\xbb\xbfh\xc3\xa9llo")
        out = self.fm.read_file("bom.txt")
        self.assertIn("héllo", out)
        self.assertNotIn("﻿", out)

    def test_utf16_and_cp1252(self):
        self.write("u16.txt", "grüße".encode("utf-16"))
        self.assertIn("grüße", self.fm.read_file("u16.txt"))
        self.write("be.txt", b"\xfe\xff" + "hi".encode("utf-16-be"))
        self.assertIn("hi", self.fm.read_file("be.txt"))
        self.write("u32.txt", "wow".encode("utf-32"))
        self.assertIn("wow", self.fm.read_file("u32.txt"))
        self.write("ansi.txt", "café – naïve".encode("cp1252"))
        self.assertIn("café – naïve", self.fm.read_file("ansi.txt"))

    def test_binary_file_is_not_dumped(self):
        self.write("x.docx", b"PK\x03\x04\x00\x00binary")
        self.assertIn("binary file", self.fm.read_file("x.docx"))

    def test_large_file_is_truncated_without_reading_everything(self):
        self.write("big.txt", ("é" * 40000).encode("utf-8"))  # 80 KB; multibyte cut at the limit
        out = self.fm.read_file("big.txt")
        self.assertIn("(truncated)", out)
        self.assertNotIn("�", out)
        self.write("big16.txt", "ab".encode("utf-16") + b"a\x00" * 40000 + b"z")
        self.assertIn("(truncated)", self.fm.read_file("big16.txt"))

    def test_decode_helper_edge(self):
        # Invalid UTF-8 near the truncation point that is not a cut character.
        raw = b"abc\xff\xfe"
        self.assertEqual(FileManagerSkill._decode_text(b"ab\xe9", truncated=True), "ab")
        self.assertIsInstance(FileManagerSkill._decode_text(b"a" * 10 + b"\xc3\x28", truncated=True), str)
        self.assertIsInstance(FileManagerSkill._decode_text(raw[:3] + b"\x81"), str)

    def test_read_missing_and_directory_and_error(self):
        self.assertIn("not found", self.fm.read_file("none.txt"))
        (self.work / "d").mkdir()
        self.assertIn("not found", self.fm.read_file("d"))
        self.write("r.txt")
        with patch("builtins.open", side_effect=PermissionError("locked")):
            self.assertIn("Error reading", self.fm.read_file("r.txt"))


class FileManagerRoutingTests(FileTestBase):
    def test_natural_create_on_desktop_with_content(self):
        out = self.fm.route_command("create a file called my notes.txt on the desktop with hello world")
        self.assertIn("created successfully", out)
        self.assertEqual((self.home / "Desktop" / "my notes.txt").read_text(encoding="utf-8"), "hello world")

    def test_create_variants(self):
        self.fm.route_command("make a new text file named plan in documents containing step 1")
        self.assertEqual((self.home / "Documents" / "plan.txt").read_text(encoding="utf-8"), "step 1")
        self.fm.route_command("create file todo.txt on the desktop with content buy milk")
        self.assertEqual((self.home / "Desktop" / "todo.txt").read_text(encoding="utf-8"), "buy milk")
        self.fm.route_command("create file called x.txt")
        self.assertTrue((self.work / "x.txt").exists())
        self.assertFalse((self.work / "called x.txt").exists())

    def test_move_rename_list_open(self):
        self.write("report.pdf", b"%PDF")
        self.assertIn("Moved", self.fm.route_command("move report.pdf to downloads"))
        self.assertTrue((self.home / "Downloads" / "report.pdf").exists())
        self.write("a.txt")
        self.assertIn("renamed", self.fm.route_command("rename a.txt to b.txt"))
        (self.home / "Documents" / "q.md").write_text("q")
        self.assertIn("q.md", self.fm.route_command("list files in documents"))
        self.assertIn("Desktop", self.fm.route_command("show the files on my desktop"))
        self.assertIn("Contents of", self.fm.route_command("list files"))
        self.assertIn("Opened", self.fm.route_command("open the b.txt"))
        (self.home / "Downloads").mkdir(exist_ok=True)
        self.assertIn("Opened", self.fm.route_command("open the downloads folder"))
        self.assertIsNone(self.fm.route_command("move the window to the left"))

    def test_open_by_description(self):
        (self.home / "Documents" / "Budget 2026.xlsx").write_bytes(b"PK")
        older = self.work / "budget-old.csv"
        older.write_text("a,b")
        os.utime(older, (1, 1))
        out = self.fm.route_command("open the budget spreadsheet")
        self.assertIn("Budget 2026.xlsx", out)
        self.assertIsNone(self.fm.route_command("open the tax document"))
        self.assertIsNone(self.fm._find_by_description("the my", "pdf"))
        with patch.object(Path, "iterdir", side_effect=OSError):
            self.assertIsNone(self.fm._find_by_description("budget", "spreadsheet"))

    def test_verb_prefix_commands(self):
        self.write("v.txt", b"content")
        self.assertIn("content", self.fm.route_command("read file v.txt"))
        self.assertIn("File information", self.fm.route_command("file info v.txt"))
        self.assertIn("created", self.fm.route_command("create folder stuff"))
        self.assertIn("Changed", self.fm.route_command("change directory stuff"))
        self.assertIn("Current directory", self.fm.route_command("where am I"))


# --------------------------------------------------------------------------- scheduler
class SchedulerBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Jarvis" / "scheduled_tasks.json"
        self.now = FROZEN
        dt_patch = patch.object(ts_module, "datetime", frozen_datetime(self.now))
        dt_patch.start()
        self.addCleanup(dt_patch.stop)
        timer_patch = patch("skills.task_scheduler.threading.Timer")
        self.timer = timer_patch.start()
        self.addCleanup(timer_patch.stop)
        self.timer.side_effect = lambda *a, **k: Mock()

    def set_now(self, moment):
        self.now = moment
        p = patch.object(ts_module, "datetime", frozen_datetime(moment))
        p.start()
        self.addCleanup(p.stop)

    def make(self, jarvis=None):
        with patch.object(TaskScheduler, "start_scheduler"):
            scheduler = TaskScheduler(jarvis or Mock(), tasks_file=self.path)
        self.addCleanup(scheduler.stop_scheduler)
        return scheduler

    def stored(self):
        return json.loads(self.path.read_text(encoding="utf-8"))


class SchedulerParsingTests(SchedulerBase):
    def test_parse_formats(self):
        s = self.make()
        p = s._parse_schedule_time
        self.assertEqual(p("in 5 minutes"), FROZEN + timedelta(minutes=5))
        self.assertEqual(p("09:30"), real_datetime(2026, 9, 24, 9, 30))
        self.assertEqual(p("at 11:15"), real_datetime(2026, 9, 23, 11, 15))
        self.assertEqual(p("daily"), FROZEN + timedelta(days=1))
        self.assertEqual(p("every week"), FROZEN + timedelta(weeks=1))
        self.assertEqual(p("hourly"), FROZEN + timedelta(hours=1))
        self.assertEqual(p("monday"), real_datetime(2026, 9, 28, 10, 0))
        self.assertEqual(p("every wednesday"), real_datetime(2026, 9, 30, 10, 0))
        self.assertEqual(p("every monday at 08:00"), real_datetime(2026, 9, 28, 8, 0))
        self.assertEqual(p("every wednesday at 09:00"), real_datetime(2026, 9, 30, 9, 0))
        self.assertEqual(p("every wednesday at 11:00"), real_datetime(2026, 9, 23, 11, 0))
        self.assertEqual(p("every 2 hours"), FROZEN + timedelta(hours=2))
        self.assertEqual(p("every 15 minutes"), FROZEN + timedelta(minutes=15))
        self.assertEqual(p("once 2026-09-23T07:00:00"), real_datetime(2026, 9, 23, 7, 0))
        for bad in ("every 0 hours", "every monday at 25:00", "25:00", "sometime", "once nonsense", "in 0 minutes"):
            with self.subTest(bad=bad):
                self.assertIsNone(p(bad))

    def test_aware_once_is_converted_to_local_naive(self):
        s = self.make()
        value = s._parse_schedule_time("once 2026-09-23T07:00:00+00:00")
        self.assertIsNone(value.tzinfo)

    def test_describe_schedule(self):
        d = TaskScheduler._describe_schedule
        self.assertEqual(d("09:00"), "every day at 9:00 AM")
        self.assertEqual(d("every monday at 20:30"), "every Monday at 8:30 PM")
        self.assertEqual(d("every 2 hours"), "every 2 hours")


class SchedulerLifecycleTests(SchedulerBase):
    def test_once_alarm_fires_exactly_once_and_persists(self):
        jarvis = Mock()
        s = self.make(jarvis)
        out = s.schedule_alarm(FROZEN + timedelta(hours=2), "gym")
        self.assertEqual(out, "Alarm set for 12:00 PM today — gym.")
        self.assertEqual(self.timer.call_args.args[0], 7200)
        task = s.active_tasks["task_0"]
        self.assertIn("delivered", s._execute_task_wrapper(task))
        self.assertIsNone(s._execute_task_wrapper(task))
        jarvis.notify.assert_called_once()
        self.assertEqual(self.stored()["task_0"]["status"], "completed")
        self.assertIsNone(self.stored()["task_0"]["next_run"])
        other_day = s.schedule_alarm(FROZEN + timedelta(days=2))
        self.assertIn("Friday", other_day)

    def test_dst_uses_real_elapsed_time(self):
        s = self.make()
        deadline = FROZEN + timedelta(hours=9)
        with patch.object(ts_module, "datetime", frozen_datetime(FROZEN)):
            s.schedule_task("x", f"once {deadline.isoformat()}", "alarm")
        expected = (deadline.astimezone() - FROZEN.astimezone()).total_seconds()
        self.assertEqual(self.timer.call_args.args[0], expected)

    def test_reminder_wording(self):
        s = self.make()
        self.assertIn("remind you to stretch at 5:00 PM",
                      s.process_schedule_command("remind me at 5 p.m. to stretch"))
        self.assertIn("every day at 9:00 AM", s.process_schedule_command("remind me to take pills every day at 9"))
        self.assertEqual(s.active_tasks["task_1"]["description"], "reminder: take pills")
        self.assertIn("Timer set for 1 hour.", s.process_schedule_command("set a timer for an hour"))
        self.assertIn("in 1 hour", s.process_schedule_command("remind me in an hour to call"))
        self.assertIn("Task scheduled", s.schedule_task("do x", "daily"))

    def test_recurring_phrases(self):
        s = self.make()
        s.process_schedule_command("every monday at 8am to put the bins out")
        t = s.active_tasks["task_0"]
        self.assertEqual(t["schedule"], "every monday at 08:00")
        self.assertEqual(t["next_run"], "2026-09-28T08:00:00")
        self.assertEqual(s._schedule.get_jobs("task_0")[0].start_day, "monday")
        s.process_schedule_command("every 2 hours to drink water")
        t = s.active_tasks["task_1"]
        self.assertEqual(t["schedule"], "every 2 hours")
        job = s._schedule.get_jobs("task_1")[0]
        self.assertEqual((job.interval, job.unit), (2, "hours"))
        s.process_schedule_command("every hour stand up")
        self.assertEqual(s.active_tasks["task_2"]["schedule"], "every 1 hours")
        s.process_schedule_command("every friday at 12 am")
        self.assertEqual(s.active_tasks["task_3"]["schedule"], "every friday at 00:00")
        s.process_schedule_command("every sunday at 7 pm to call mum")
        self.assertEqual(s.active_tasks["task_4"]["schedule"], "every sunday at 19:00")
        self.assertIn("valid time", s.process_schedule_command("every tuesday at 30"))
        s.process_schedule_command("every evening check weather")
        self.assertEqual(s.active_tasks["task_5"]["type"], "weather")
        s.process_schedule_command("every day at 12 am")
        self.assertEqual(s.active_tasks["task_6"]["schedule"], "00:00")
        s.process_schedule_command("every morning at 7:30 pm")
        self.assertEqual(s.active_tasks["task_7"]["schedule"], "19:30")
        self.assertIn("valid time", s.process_schedule_command("every day at 99"))
        # Unpadded HH:MM from another caller must not crash schedule's .at().
        self.assertIn("Task scheduled", s.schedule_task("x", "9:05"))
        self.assertEqual(s._schedule.get_jobs("task_8")[0].at_time.minute, 5)

    def test_recurring_execution_reschedules(self):
        s = self.make()
        s.process_schedule_command("every 2 hours to drink water")
        task = s.active_tasks["task_0"]
        s._execute_task_wrapper(task)
        self.assertEqual(task["status"], "scheduled")
        self.assertIsNotNone(task["next_run"])

    def test_invalid_times_in_remind_at(self):
        s = self.make()
        self.assertIn("valid time", s.process_schedule_command("remind me at 25 to stretch"))
        self.assertIn("valid time", s.process_schedule_command("remind me to stretch at 9:75"))
        out = s.process_schedule_command("remind me to sleep at 12 am")
        self.assertIn("12:00 AM", out)
        self.assertIn("9:00 AM", s.process_schedule_command("remind me to wake at 9 am"))

    def test_cancel_spoken_task_number_and_list(self):
        s = self.make()
        self.assertEqual(s.list_scheduled_tasks(), "No scheduled tasks found.")
        self.assertEqual(s.process_schedule_command("cancel my reminder"), "There are no pending reminders or alarms.")
        s.schedule_reminder("a", "in 5 minutes")
        s.schedule_reminder("b", "in 10 minutes")
        self.assertIn("Which one?", s.process_schedule_command("cancel the reminder"))
        self.assertIn("Task cancelled: reminder: b", s.process_schedule_command("cancel task 1"))
        self.assertIn("already cancelled", s.process_schedule_command("cancel task number 1"))
        self.assertIn("Task cancelled", s.process_schedule_command("cancel my reminder"))
        self.assertIn("not found", s.process_schedule_command("cancel task_99"))
        self.assertEqual(s.process_schedule_command("list reminders"), "No scheduled tasks found.")
        s.schedule_reminder("c", "in 5 minutes")
        listing = s.process_schedule_command("show my reminders")
        self.assertIn("reminder: c", listing)
        self.assertNotIn("reminder: a", listing)

    def test_misc_schedulers_and_help(self):
        s = self.make()
        self.assertIn("backup", s.process_schedule_command("schedule a weekly backup"))
        self.assertIn("health", s.process_schedule_command("schedule a system health check"))
        self.assertIn("weather", s.schedule_weather_update())
        self.assertIn("Try:", s.process_schedule_command("blah"))
        self.assertIn("Unable to parse", s.schedule_task("x", "whenever"))

    def test_execute_now_and_unknown(self):
        s = self.make()
        self.assertIn("not found", s.execute_task_now("task_9"))
        s.schedule_task("x", "in 5 minutes", "mystery")
        self.assertEqual(s.execute_task_now("task_0"), "Unknown task type: mystery")
        self.assertEqual(s.execute_task_now("task_0"), "Task is not pending.")

    def test_task_types_execute(self):
        jarvis = Mock()
        jarvis.system_control.get_system_status.return_value = "CPU ok"
        jarvis.weather_skill.get_weather.return_value = "Sunny"
        s = self.make(jarvis)
        self.assertEqual(s._execute_task({"type": "system_check", "description": "c"}), "System health check completed")
        self.assertEqual(s._execute_task({"type": "weather", "description": "w"}), "Weather update completed")
        self.assertEqual(s._execute_task({"type": "command", "description": "open notepad"}),
                         "Command executed: open notepad")
        jarvis.process_command.assert_called_once_with("open notepad", use_voice=False)
        self.assertIn("Reminder delivered", s._execute_task({"type": "reminder", "description": "reminder: x"}))

    def test_notify_fallbacks_and_callback_raising(self):
        voice = Mock()
        jarvis = types.SimpleNamespace(voice_engine=voice)
        s = self.make(jarvis)
        with patch("builtins.print"):
            s._notify("hello", speak_text="hi")
        voice.speak.assert_called_once_with("hi")
        failing = Mock()
        failing.notify.side_effect = RuntimeError("gui gone")
        s = self.make(failing)
        s.schedule_reminder("x", "in 5 minutes")
        result = s._execute_task_wrapper(s.active_tasks["task_0"])
        self.assertIn("Task execution failed", result)
        self.assertEqual(s.active_tasks["task_0"]["status"], "failed")

    def test_wrapper_exception_marks_failed(self):
        s = self.make()
        s.schedule_reminder("x", "in 5 minutes")
        with patch.object(s, "_execute_task", side_effect=RuntimeError("boom")):
            self.assertIn("boom", s._execute_task_wrapper(s.active_tasks["task_0"]))

    def test_admission_save_failure_clears_recurring_job(self):
        s = self.make()
        s.schedule_reminder("x", "daily")
        with patch.object(s, "save_tasks", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                s._execute_task_wrapper(s.active_tasks["task_0"])
        self.assertEqual(s._schedule.get_jobs("task_0"), [])
        self.assertEqual(s.active_tasks["task_0"]["status"], "failed")

    def test_add_failure_is_rolled_back_on_disk(self):
        s = self.make()
        with patch.object(s, "_add_to_scheduler", side_effect=RuntimeError("bad")):
            self.assertIn("Error scheduling", s.schedule_reminder("x", "in 5 minutes"))
        self.assertEqual(self.stored(), {})
        self.assertEqual(s.active_tasks, {})

    def test_backup(self):
        s = self.make()
        s.schedule_backup()
        (self.path.parent / ".env").write_text("K=1")
        backups = self.path.parent / "backups"
        backups.mkdir()
        for i in range(12):
            (backups / f"2000010{i:02}").mkdir()
        out = s._perform_backup()
        self.assertIn("2 files backed up", out)
        self.assertEqual(len(list(backups.iterdir())), 10)
        with patch("shutil.copy2", side_effect=OSError("x")):
            self.assertIn("Backup failed", s._perform_backup())
        with patch.object(s, "_perform_backup", return_value="Backup failed: x"):
            self.assertEqual(s.execute_task_now("task_0"), "Backup failed: x")


class SchedulerStartupTests(SchedulerBase):
    def seed(self, tasks, bom=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(tasks)
        self.path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data.encode("utf-8"))

    def task(self, tid, schedule, next_run, status="scheduled", **extra):
        return dict(id=tid, description=f"reminder: {tid}", schedule=schedule, type="reminder",
                    created=FROZEN.isoformat(), next_run=next_run, status=status, **extra)

    def test_old_finished_tasks_are_pruned_on_load(self):
        old = (FROZEN - timedelta(days=30)).isoformat()
        recent = (FROZEN - timedelta(days=1)).isoformat()
        self.seed({"task_1": self.task("task_1", "once " + old, old, status="completed", last_run=old),
                   "task_2": self.task("task_2", "once " + recent, recent, status="completed", last_run=recent),
                   "task_3": self.task("task_3", "once " + old, old, status="missed"),            # not yet reported
                   "task_6": self.task("task_6", "once " + old, old, status="cancelled", reported=True)})
        s = self.make()
        self.assertEqual(sorted(s.active_tasks), ["task_2", "task_3"])
        self.assertEqual(sorted(self.stored()), ["task_2", "task_3"])
        self.assertEqual(s.task_counter, 7)                 # ids are never reused

    def test_missed_recurring_task_keeps_running_and_is_reported_once(self):
        yesterday = (FROZEN - timedelta(hours=1)).isoformat()
        self.seed({"task_0": self.task("task_0", "09:00", yesterday),
                   "task_4": self.task("task_4", "once 2026-09-23T08:00:00", "2026-09-23T08:00:00"),
                   "task_5": self.task("task_5", "every 2 hours", (FROZEN - timedelta(hours=3)).isoformat(),
                                       status="running")}, bom=True)
        s = self.make()
        t0 = s.active_tasks["task_0"]
        self.assertEqual(t0["status"], "scheduled")
        self.assertEqual(t0["next_run"], "2026-09-24T09:00:00")
        self.assertEqual(s._schedule.get_jobs("task_0")[0].next_run, real_datetime(2026, 9, 24, 9, 0))
        self.assertEqual(s.active_tasks["task_4"]["status"], "missed")
        self.assertEqual(s.active_tasks["task_5"]["status"], "scheduled")
        self.assertEqual(s.task_counter, 6)
        missed = s.missed_tasks()
        self.assertEqual({m["id"] for m in missed}, {"task_0", "task_4", "task_5"})
        by_id = {m["id"]: m for m in missed}
        self.assertEqual(by_id["task_0"]["next_run"], yesterday)
        self.assertNotIn("missed_at", self.stored()["task_0"])
        self.assertEqual(s.missed_tasks(), [])

    def test_interrupted_one_shot_and_invalid(self):
        self.seed({"task_1": self.task("task_1", "in 5 minutes", FROZEN.isoformat(), status="running"),
                   "task_2": self.task("task_2", "gibberish", (FROZEN + timedelta(hours=1)).isoformat()),
                   "task_3": self.task("task_3", "in 5 minutes", None),
                   "custom": self.task("custom", "in 5 minutes", (FROZEN + timedelta(hours=1)).isoformat(),
                                       status="completed")})
        s = self.make()
        self.assertEqual(s.active_tasks["task_1"]["status"], "interrupted")
        self.assertEqual(s.active_tasks["task_2"]["status"], "invalid")
        self.assertEqual(s.active_tasks["task_3"]["status"], "invalid")
        self.assertIn("❌", s.list_scheduled_tasks())

    def test_aware_stored_deadline_is_normalised(self):
        future = (FROZEN + timedelta(hours=1)).astimezone().isoformat()
        self.seed({"task_0": self.task("task_0", "in 5 minutes", future)})
        s = self.make()
        self.assertEqual(s.active_tasks["task_0"]["status"], "scheduled")
        self.assertNotIn("+", s.active_tasks["task_0"]["next_run"])

    def test_corrupt_or_malformed_store_is_set_aside_not_overwritten(self):
        for content in ("{broken", "[]", json.dumps({"task_0": {"id": "other"}})):
            with self.subTest(content=content):
                for old in self.path.parent.glob("*.corrupt-*"):
                    old.unlink()
                self.seed({})
                self.path.write_text(content, encoding="utf-8")
                s = self.make()
                self.assertEqual(s.active_tasks, {})
                self.assertIn("couldn't be read", s.storage_warning)
                kept = list(self.path.parent.glob("*.corrupt-*"))
                self.assertEqual([p.read_text(encoding="utf-8") for p in kept], [content])

    def test_missed_tasks_save_failure_is_ignored(self):
        self.seed({"task_0": self.task("task_0", "in 5 minutes", (FROZEN - timedelta(1)).isoformat())})
        s = self.make()
        with patch.object(s, "save_tasks", side_effect=OSError):
            self.assertEqual(len(s.missed_tasks()), 1)

    def test_default_store_under_appdata(self):
        with patch.dict(os.environ, {"APPDATA": self.temp.name}), \
             patch.object(TaskScheduler, "start_scheduler"):
            s = TaskScheduler(Mock())
        self.assertEqual(s.tasks_file, Path(self.temp.name) / "Jarvis" / "scheduled_tasks.json")


class SchedulerThreadTests(unittest.TestCase):
    """Real worker thread with real time (short)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tasks.json"

    def test_worker_runs_due_recurring_job_and_stops_on_shutdown(self):
        s = TaskScheduler(Mock(), tasks_file=self.path)
        self.addCleanup(s.stop_scheduler)
        ran = threading.Event()
        s._execute_task = Mock(side_effect=lambda task: ran.set() or "ok")
        s.schedule_reminder("tick", "every 1 minutes")
        job = s._schedule.get_jobs("task_0")[0]
        job.next_run = real_datetime.now() - timedelta(seconds=1)
        self.assertTrue(ran.wait(5))
        s.stop_scheduler()
        self.assertFalse(s.scheduler_thread.is_alive())
        self.assertFalse(s.is_running)
        self.assertIn("stopped", s.schedule_reminder("late", "in 5 minutes"))
        # Restart re-registers pending work.
        s.start_scheduler()
        s.start_scheduler()  # idempotent while running
        self.assertEqual(len(s._schedule.get_jobs("task_0")), 1)
        s.stop_scheduler()

    def test_loop_survives_job_errors(self):
        with patch.object(TaskScheduler, "start_scheduler"):
            s = TaskScheduler(Mock(), tasks_file=self.path)
        bad = Mock(should_run=True, job_func=Mock(side_effect=RuntimeError("x")))
        s._schedule.jobs.append(bad)
        calls = []
        original_wait = s._wake.wait

        def wait(timeout):
            calls.append(timeout)
            s._wake.set()
            return original_wait(0)
        s._wake.wait = wait
        with patch("builtins.print") as printed:
            s._scheduler_loop()
        printed.assert_called_once()
        self.assertEqual(calls, [1])

    def test_restart_refused_while_old_worker_alive(self):
        with patch.object(TaskScheduler, "start_scheduler"):
            s = TaskScheduler(Mock(), tasks_file=self.path)
        s.scheduler_thread = Mock(is_alive=Mock(return_value=True))
        with self.assertRaises(RuntimeError):
            s.start_scheduler()

    def test_concurrent_scheduling_is_consistent(self):
        with patch.object(TaskScheduler, "start_scheduler"), \
             patch("skills.task_scheduler.threading.Timer", side_effect=lambda *a, **k: Mock()):
            s = TaskScheduler(Mock(), tasks_file=self.path)
            errors = []

            def work(i):
                try:
                    s.schedule_reminder(f"r{i}", "in 5 minutes")
                    s.list_scheduled_tasks()
                except Exception as e:  # pragma: no cover - failure path
                    errors.append(e)
            threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(s.active_tasks), 20)
        self.assertEqual(len(json.loads(self.path.read_text())), 20)


if __name__ == "__main__":
    unittest.main()


class RouteSafetyTests(unittest.TestCase):
    def test_route_command_never_deletes_and_ignores_non_file_renames(self):
        from skills.file_manager import FileManagerSkill
        fm = FileManagerSkill.__new__(FileManagerSkill)
        import threading
        fm._write_lock = threading.RLock()
        fm._pending_overwrite = None
        from unittest.mock import Mock
        fm.delete_file = Mock()
        fm.rename_file = Mock(return_value="renamed")
        self.assertIsNone(fm.route_command("delete file a.txt"))
        fm.delete_file.assert_not_called()
        self.assertIsNone(fm.route_command("rename this playlist to chill"))
        self.assertEqual(fm.route_command("rename notes.txt to todo.txt"), "renamed")
        self.assertEqual(fm.route_command("rename file notes to todo"), "renamed")
        fm.rename_file.assert_called_with("notes", "todo")
