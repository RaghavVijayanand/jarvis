"""Coverage / audit tests for app control, voice, streaming, executor and the screen/memory/schedule handlers.

Everything is mocked at the OS boundary (os.startfile, subprocess, psutil, winreg, requests,
speech_recognition, MCI) so the suite runs on Linux without hardware.
"""
import json
import os
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from core import executor as ex
from core import streaming as st
from core import voice as vm
from skills import app_control as ac
from skills.app_control import ApplicationControl


class FakeTools:
    def __init__(self):
        self.funcs = {}

    def add(self, name, description, func, parameters=None, **kw):
        self.funcs[name] = func


def control():
    c = ApplicationControl(scan=False)
    c._start_apps = []
    return c


# ── app_control ──────────────────────────────────────────────────────────────

class SiteUrlTests(unittest.TestCase):
    def test_domains_and_map(self):
        u = ApplicationControl._site_url
        self.assertEqual(u("github.com"), "https://github.com")
        self.assertEqual(u("www.python.org"), "https://www.python.org")
        self.assertEqual(u("youtube"), "https://www.youtube.com")
        self.assertEqual(u("the youtube music website"), "https://music.youtube.com")
        self.assertIsNone(u("notepad"))
        self.assertIsNone(u("x marks"))   # one-letter keys only match exactly

    def test_file_names_are_not_domains(self):
        self.assertIsNone(ApplicationControl._site_url("notepad.exe"))
        self.assertIsNone(ApplicationControl._site_url("report.pdf"))

    def test_url_case_and_trailing_words(self):
        u = ApplicationControl._site_url
        self.assertEqual(u("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
                         "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(u("https://example.com & calc"), "https://example.com")

    def test_site_action_urls(self):
        c = control()
        with patch.object(ac, "youtube_first_video", return_value=None):
            url, js = c._site_action_url("https://www.youtube.com", "a video called rick roll")
        self.assertEqual(url, "https://www.youtube.com/results?search_query=rick+roll")
        self.assertIn("click", js)
        with patch.object(ac, "youtube_first_video", return_value="https://www.youtube.com/watch?v=abcdefghijk"):
            self.assertEqual(c._site_action_url("https://www.youtube.com", "x")[0],
                             "https://www.youtube.com/watch?v=abcdefghijk")
        cases = {"https://open.spotify.com": "open.spotify.com/search/jazz+hits",
                 "https://www.reddit.com": "reddit.com/search/?q=jazz+hits",
                 "https://www.amazon.com": "amazon.com/s?k=jazz+hits",
                 "https://www.wikipedia.org": "wikipedia.org/w/index.php?search=jazz+hits",
                 "https://github.com": "github.com/search?q=jazz+hits",
                 "https://maps.google.com": "google.com/maps/search/jazz+hits",
                 "https://www.netflix.com": "google.com/search?q=jazz+hits"}
        for site, expect in cases.items():
            self.assertIn(expect, c._site_action_url(site, "jazz hits")[0])

    def test_query_encoding_prevents_url_injection(self):
        c = control()
        url, _ = c._site_action_url("https://github.com", "a&b=c #d")
        self.assertEqual(url, "https://github.com/search?q=a%26b%3Dc+%23d")


class YoutubeLookupTests(unittest.TestCase):
    def test_first_video(self):
        resp = Mock(status_code=200, text='..."videoRenderer":{"videoId":"abcdefghijk"...')
        with patch("requests.get", return_value=resp) as get:
            self.assertEqual(ac.youtube_first_video("q"), "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(get.call_args.kwargs["params"], {"search_query": "q"})
        with patch("requests.get", return_value=Mock(status_code=200, text="/watch?v=ABCDEFGHIJK")):
            self.assertEqual(ac.youtube_first_video("q"), "https://www.youtube.com/watch?v=ABCDEFGHIJK")
        with patch("requests.get", return_value=Mock(status_code=429, text="")):
            self.assertIsNone(ac.youtube_first_video("q"))
        with patch("requests.get", return_value=Mock(status_code=200, text="nothing")):
            self.assertIsNone(ac.youtube_first_video("q"))
        with patch("requests.get", side_effect=OSError("offline")):
            self.assertIsNone(ac.youtube_first_video("q"))


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.c = control()
        self.opened = []
        self.c.open_url = lambda url, then_js=None, browser=None: self.opened.append((url, browser)) or f"Opened {url}."

    def test_direct_url_keeps_case(self):
        self.c.launch_app_by_name("open https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(self.opened[-1][0], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.c.launch_app_by_name("Go to Example.com/SomePath")
        self.assertEqual(self.opened[-1][0], "https://Example.com/SomePath")

    def test_exe_name_launches_program_not_website(self):
        with patch.object(self.c, "_shell_open", return_value="Opened Notepad.exe.") as shell:
            self.c.launch_app_by_name("open notepad.exe")
        self.assertEqual(self.opened, [])
        self.assertEqual(shell.call_args.args[0], "notepad.exe")

    def test_empty_and_filler_only(self):
        self.assertIn("tell me what", self.c.launch_app_by_name("  "))
        self.assertIn("which app", self.c.launch_app_by_name("open the app"))
        self.assertIn("doesn't look like", self.c._launch_named_app("%%%"))

    def test_play_on_spotify_and_search_verbs(self):
        self.c.launch_app_by_name("play despacito on spotify")
        self.assertIn("open.spotify.com/search/despacito", self.opened[-1][0])
        with patch.object(ac, "youtube_first_video", return_value="https://www.youtube.com/watch?v=abcdefghijk"):
            reply = self.c.launch_app_by_name("open youtube and play lofi", browser="edge")
        self.assertIn("Playing: lofi", reply)
        self.assertEqual(self.opened[-1][1], "edge")
        self.c.launch_app_by_name("go to reddit and search for python")
        self.assertIn("reddit.com/search/?q=python", self.opened[-1][0])

    def test_folders_and_aliases(self):
        with patch.object(self.c, "_shell_open", return_value="ok") as shell:
            self.c.launch_app_by_name("open downloads")
            self.assertTrue(shell.call_args.args[0].endswith("Downloads"))
            self.c.launch_app_by_name("open document")
            self.assertTrue(shell.call_args.args[0].endswith("Documents"))
            self.c.launch_app_by_name("open settings")
            self.assertEqual(shell.call_args.args[0], "ms-settings:")

    def test_start_menu_shortcut_uwp_and_installed(self):
        c = self.c
        with patch.object(c, "_find_start_menu_shortcut", return_value=r"C:\sm\Blender 4.lnk"), \
                patch.object(c, "_shell_open", return_value="ok") as shell:
            c._launch_named_app("blender")
        self.assertEqual(shell.call_args.args[0], r"C:\sm\Blender 4.lnk")
        c._start_apps = [{"Name": "Windows Security", "AppID": "Microsoft.SecHealthUI_8wekyb3d8bbwe!SecHealthUI"},
                         {"Name": "Security Center Extra", "AppID": "x!y"},
                         {"Name": "Microsoft Defender Security", "AppID": "d!1"},
                         {"Name": "Old Defender Security Tools", "AppID": "d!2"}]
        with patch.object(c, "_shell_open", return_value="ok") as shell,                 patch.object(c, "_find_start_menu_shortcut", return_value=None):
            c._launch_named_app("windows security")
            self.assertEqual(shell.call_args.args[0], "shell:AppsFolder\\Microsoft.SecHealthUI_8wekyb3d8bbwe!SecHealthUI")
            self.assertTrue(shell.call_args.kwargs["via_explorer"])
            c._launch_named_app("security")     # prefix match beats word match
            self.assertEqual(shell.call_args.args[0], "shell:AppsFolder\\x!y")
            c._launch_named_app("defender")     # word match picks the shortest name
            self.assertEqual(shell.call_args.args[0], "shell:AppsFolder\\d!1")
        c._start_apps = []
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "npp.exe"
            exe.write_text("")
            (Path(d) / "unins000.exe").write_text("")
            c.installed_apps = {"notepad++ (64-bit x64)": {"name": "Notepad++", "location": d, "executable": str(exe)},
                                "foo tool": {"name": "Foo Tool", "location": d, "executable": None},
                                "ghost": {"name": "Ghost", "location": None, "executable": None}}
            with patch.object(c, "_shell_open", return_value="ok") as shell,                     patch.object(c, "_find_start_menu_shortcut", return_value=None):
                c._launch_named_app("notepad++")       # name ending in symbols still matches as a word
                self.assertEqual(shell.call_args.args[0], str(exe))
                c._launch_named_app("foo tool")
                self.assertEqual(shell.call_args.args[0], str(exe))   # uninstaller skipped
            self.assertIn("couldn't find its program", c._launch_named_app("ghost"))

    def test_unknown_app_tries_app_paths_quietly(self):
        with patch.object(self.c, "_shell_open", return_value="Opened Obsidian.") as shell:
            self.assertEqual(self.c._launch_named_app("obsidian"), "Opened Obsidian.")
        self.assertEqual(shell.call_args.args[0], "obsidian.exe")
        self.assertTrue(shell.call_args.kwargs["quiet_fail"])

    def test_launch_exception_is_reported(self):
        with patch.object(self.c, "_launch_named_app", side_effect=RuntimeError("boom")):
            self.assertIn("boom", self.c.launch_app_by_name("open thing"))
        self.assertIsNotNone(self.c.open_app)


@patch.object(ac.os, "name", "posix")       # the tests that mean Windows patch "nt" themselves
class ShellOpenTests(unittest.TestCase):
    def test_non_windows_uses_xdg_open_list_args(self):
        c = control()
        with patch.object(ac.subprocess, "Popen") as popen:
            self.assertEqual(c._shell_open("calc.exe & del x", "Calc"), "Opened Calc.")
        popen.assert_called_once_with(["xdg-open", "calc.exe & del x"])

    def test_windows_startfile_and_failures(self):
        c = control()
        with patch.object(ac.os, "name", "nt"), patch.object(ac.os, "startfile", create=True) as sf:
            self.assertEqual(c._shell_open("notepad.exe", "Notepad"), "Opened Notepad.")
            sf.assert_called_once_with("notepad.exe")
            sf.side_effect = FileNotFoundError(2, "The system cannot find the file specified")
            self.assertIsNone(c._shell_open("nope.exe", "Nope", quiet_fail=True))
            self.assertIn("cannot find", c._shell_open("nope.exe", "Nope"))

    def test_explorer_for_uwp(self):
        c = control()
        with patch.object(ac.subprocess, "Popen") as popen:
            c._shell_open("shell:AppsFolder\\A!B", "A", via_explorer=True)
        popen.assert_called_once_with(["explorer.exe", "shell:AppsFolder\\A!B"])

    def test_expect_process_polling(self):
        c = control()
        names = iter([set(), set(), {"notepad.exe"}])
        with patch.object(ac.subprocess, "Popen"), patch.object(c, "_process_names", side_effect=lambda: next(names)), \
                patch.object(ac.time, "sleep"):
            self.assertEqual(c._shell_open("notepad.exe", "Notepad", expect=["Notepad.exe"]), "Opened Notepad.")
        clock = iter([0, 0, 10])
        seen = iter([{"notepad.exe"}, set()])
        with patch.object(ac.subprocess, "Popen"), patch.object(c, "_process_names", side_effect=lambda: next(seen)), \
                patch.object(ac.time, "time", side_effect=lambda: next(clock)):
            self.assertIn("already running", c._shell_open("notepad.exe", "Notepad", expect=["notepad.exe"]))
        clock = iter([0, 10])
        with patch.object(ac.subprocess, "Popen"), patch.object(c, "_process_names", return_value=set()), \
                patch.object(ac.time, "time", side_effect=lambda: next(clock)):
            self.assertIn("hasn't appeared", c._shell_open("x.exe", "X", expect=["x.exe"]))

    def test_process_names(self):
        good, bad = Mock(info={"name": "Chrome.EXE"}), Mock()
        type(bad).info = property(lambda self: (_ for _ in ()).throw(RuntimeError("gone")))
        with patch.object(ac, "psutil") as ps:
            ps.process_iter.return_value = [good, bad, Mock(info={"name": None})]
            self.assertEqual(ApplicationControl._process_names(), {"chrome.exe", ""})
        with patch.object(ac, "psutil", None):
            self.assertEqual(ApplicationControl._process_names(), set())


class OpenUrlTests(unittest.TestCase):
    def test_named_browser_only_known_executables(self):
        c = control()
        with patch.object(ac.os, "name", "nt"), patch.object(ac.os, "startfile", create=True) as sf, \
                patch.object(ac.webbrowser, "open") as wb:
            self.assertIn("Chrome", c.open_url("https://a.com", browser="chrome"))
            sf.assert_called_once_with("chrome.exe", arguments="https://a.com")
            sf.reset_mock()
            c.open_url("https://a.com", browser="msedge.exe")
            sf.assert_called_once_with("msedge.exe", arguments="https://a.com")
            sf.reset_mock()
            c.open_url("https://a.com", browser="cmd.exe")      # never an arbitrary program
            sf.assert_not_called()
            wb.assert_called_once_with("https://a.com")

    def test_callback_and_errors(self):
        c = control()
        cb = Mock()
        c.set_browser_callback(cb)
        self.assertIn("JARVIS browser", c.open_url("https://a.com", "js()"))
        cb.assert_called_once_with("https://a.com", "js()")
        cb.side_effect = RuntimeError("dead")
        self.assertIn("Failed to open URL", c.open_url("https://a.com"))


class DiscoveryTests(unittest.TestCase):
    def test_registry_scan(self):
        reg = MagicMock()
        reg.HKEY_LOCAL_MACHINE, reg.HKEY_CURRENT_USER = 2, 1
        values = {
            ("k0", "DisplayName"): "Notepad++", ("k0", "InstallLocation"): r"C:\Program Files\Notepad++",
            ("k0", "DisplayIcon"): r'"C:\Program Files\Notepad++\notepad++.exe",0',
            ("k1", "DisplayName"): "Weird, Inc App", ("k1", "DisplayIcon"): r"C:\Apps\Weird, Inc\app.exe,0",
            ("k2", "DisplayName"): "Tool", ("k2", "DisplayIcon"): r"C:\Tool\unins000.exe",
        }

        def open_key(parent, path):
            if parent == 1:
                raise OSError("no HKCU")
            return path

        def query(key, name):
            if (key, name) in values:
                return values[(key, name)], 1
            raise OSError(name)
        reg.OpenKey.side_effect = open_key
        reg.QueryInfoKey.side_effect = lambda key: (4, 0, 0)
        reg.EnumKey.side_effect = lambda key, i: ["k0", "k1", "k2", "k3"][i]
        reg.QueryValueEx.side_effect = query
        c = control()
        with patch.object(ac, "winreg", reg):
            self.assertEqual(c.refresh_app_list(), 3)
        self.assertEqual(c.installed_apps["notepad++"]["executable"], r"C:\Program Files\Notepad++\notepad++.exe")
        self.assertEqual(c.installed_apps["weird, inc app"]["executable"], r"C:\Apps\Weird, Inc\app.exe")
        self.assertIsNone(c.installed_apps["tool"]["executable"])
        with patch.object(ac, "winreg", None):
            self.assertEqual(c._get_installed_applications(), {})
        with patch.object(c, "_get_installed_applications", side_effect=RuntimeError("x")):
            self.assertEqual(c.refresh_app_list(), 3)   # keeps the previous list

    def test_start_apps_parsing(self):
        c = control()
        out = Mock(stdout=json.dumps([{"Name": "Café App", "AppID": "a!b"}, None, {"Name": "NoId"}]))
        with patch.object(ac.os, "name", "nt"), patch.object(ac.subprocess, "run", return_value=out) as run:
            apps = c._get_start_apps(refresh=True)
        self.assertEqual(apps, [{"Name": "Café App", "AppID": "a!b"}])
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertIs(c._get_start_apps(), apps)                       # cached
        with patch.object(ac.os, "name", "nt"), \
                patch.object(ac.subprocess, "run", return_value=Mock(stdout='{"Name": "One", "AppID": "1"}')):
            self.assertEqual(c._get_start_apps(refresh=True), [{"Name": "One", "AppID": "1"}])
        with patch.object(ac.os, "name", "nt"), patch.object(ac.subprocess, "run", return_value=Mock(stdout="null")):
            self.assertEqual(c._get_start_apps(refresh=True), [])
        with patch.object(ac.os, "name", "nt"), patch.object(ac.subprocess, "run", side_effect=OSError("no ps")):
            self.assertEqual(c._get_start_apps(refresh=True), [])
        with patch.object(ac.os, "name", "posix"):
            self.assertEqual(c._get_start_apps(refresh=True), [])     # non-Windows

    def test_list_and_discover(self):
        c = control()
        c.installed_apps = {f"app{i}": {"name": f"App{i:02d}"} for i in range(55)}
        c._start_apps = [{"Name": "Zed", "AppID": "z"}]
        text = c.list_installed_apps()
        self.assertIn("… and 6 more", text)
        self.assertIn("Zed", c.list_installed_apps("ze"))
        self.assertIn("No applications", c.list_installed_apps("qqq"))
        with patch.object(c, "refresh_app_list", return_value=55), patch.object(c, "_get_start_apps", return_value=[1]):
            self.assertIn("Found 55 installed programs and 1", c.discover_applications())

    def test_start_menu_scan(self):
        c = control()
        with patch.object(ac.os, "name", "posix"):
            self.assertIsNone(c._find_start_menu_shortcut("x"))        # non-Windows
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "Microsoft/Windows/Start Menu/Programs"
            (base / "Sub").mkdir(parents=True)
            for n in ("Uninstall Foo.lnk", "Foo Bar Extras.lnk", "Sub/Foo Bar.lnk", "Paint.lnk", "Notepad++.lnk"):
                (base / n).write_text("")
            import pathlib
            with patch.object(ac.os, "name", "nt"), patch.object(ac, "Path", pathlib.Path), \
                    patch.dict(os.environ, {"APPDATA": d, "PROGRAMDATA": d + "/none"}):
                self.assertTrue(c._find_start_menu_shortcut("paint").endswith("Paint.lnk"))
                self.assertTrue(c._find_start_menu_shortcut("foo").endswith("Foo Bar.lnk"))
                self.assertTrue(c._find_start_menu_shortcut("notepad++").endswith("Notepad++.lnk"))
                self.assertIsNone(c._find_start_menu_shortcut("zzz"))
            with patch.object(ac.os, "name", "nt"), patch.object(ac, "Path", pathlib.Path), \
                    patch.dict(os.environ, {"APPDATA": "", "PROGRAMDATA": ""}):
                self.assertIsNone(c._find_start_menu_shortcut("zzz"))  # no relative-path scan

    def test_scan_thread_on_init(self):
        with patch.object(ApplicationControl, "refresh_app_list") as refresh:
            ApplicationControl(scan=True)
            deadline = time.time() + 2
            while not refresh.called and time.time() < deadline:
                time.sleep(0.01)
        refresh.assert_called()


class CloseAppTests(unittest.TestCase):
    def procs(self, *names):
        out = []
        for i, n in enumerate(names):
            p = Mock()
            p.info = {"pid": 1000 + i, "name": n}
            out.append(p)
        return out

    def test_resolve_names(self):
        c = control()
        self.assertEqual(c.resolve_process_names("the Chrome browser"), ["chrome.exe"])
        self.assertEqual(c.resolve_process_names("microsoft word"), ["winword.exe"])
        self.assertEqual(c.resolve_process_names("windows terminal"), ["windowsterminal.exe"])
        self.assertEqual(c.resolve_process_names("foo.exe"), ["foo.exe"])
        self.assertEqual(c.resolve_process_names("rm -rf /"), [])
        self.assertEqual(c.resolve_process_names("file explorer"), [])

    def test_close(self):
        c = control()
        ps = MagicMock()
        ps.NoSuchProcess, ps.AccessDenied = LookupError, PermissionError
        procs = self.procs("WINWORD.EXE", "winword.exe", "excel.exe", "winword.exe")
        procs[1].terminate.side_effect = PermissionError()
        procs[3].info["pid"] = os.getpid()
        ps.process_iter.return_value = procs
        ps.wait_procs.return_value = ([procs[0]], [])
        with patch.object(ac, "psutil", ps):
            self.assertEqual(c.close_app_by_name("word"), "Closed word (1 process).")
            procs[3].terminate.assert_not_called()                     # never ourselves
            procs[2].terminate.assert_not_called()
            ps.wait_procs.return_value = ([], [procs[0]])
            self.assertIn("1 process(es) did not exit", c.close_app_by_name("word"))
            self.assertIn("doesn't seem to be running", c.close_app_by_name("vlc"))
            self.assertIn("don't know which", c.close_app_by_name("file explorer"))
        with patch.object(ac, "psutil", None):
            self.assertIn("unavailable", c.close_app_by_name("word"))


class AppInfoTests(unittest.TestCase):
    def test_info_uninstall_shortcut(self):
        c = control()
        c.installed_apps = {"vlc media player": {"name": "VLC media player", "location": "/opt/vlc",
                                                 "executable": "/opt/vlc/vlc.exe"}}
        with patch.object(c, "_process_names", return_value={"vlc.exe"}):
            self.assertIn("Status: Running", c.get_app_info("vlc"))
        self.assertIn("not found", c.get_app_info("nothing"))
        with patch.object(ac.os, "startfile", create=True) as sf:
            self.assertIn("Settings", c.uninstall_app("vlc"))
            sf.assert_called_once_with("ms-settings:appsfeatures")
            sf.side_effect = OSError("x")
            self.assertIn("Could not open", c.uninstall_app("vlc"))
        self.assertIn("No executable", c.create_desktop_shortcut("nothing"))
        fake_client = MagicMock()
        with patch.dict("sys.modules", {"win32com.client": fake_client, "win32com": MagicMock(client=fake_client)}):
            self.assertIn("Created desktop shortcut", c.create_desktop_shortcut("vlc"))
            fake_client.Dispatch.side_effect = RuntimeError("com")
            self.assertIn("Error creating shortcut", c.create_desktop_shortcut("vlc"))


# ── voice ────────────────────────────────────────────────────────────────────

class SpeakableTests(unittest.TestCase):
    def test_make_speakable(self):
        self.assertEqual(vm.make_speakable(""), "")
        self.assertEqual(vm.make_speakable("**Hi** there 🚀 see https://x.com"), "Hi there see")
        long = " ".join(f"Sentence {i}." for i in range(10))
        self.assertTrue(vm.make_speakable(long).endswith("The full details are on screen."))
        spoken = vm.make_speakable("word " * 200, max_sentences=1)
        self.assertLessEqual(len(spoken), 420 + 40)


class PlaybackTests(unittest.TestCase):
    def test_playsound_then_fail(self):
        with patch.object(vm.os, "name", "posix"), patch.object(vm, "_PLAYSOUND_AVAILABLE", True), \
                patch.object(vm, "_playsound", create=True) as ps:
            self.assertTrue(vm._play_mp3_blocking("/tmp/a.mp3"))
            ps.side_effect = RuntimeError("no device")
            self.assertFalse(vm._play_mp3_blocking("/tmp/a.mp3"))

    def _winmm(self, modes, open_rc=0, play_rc=0):
        calls = []
        modes = iter(modes)

        def send(cmd, buf, n, cb):
            calls.append(cmd)
            if cmd.startswith("open"):
                return open_rc
            if cmd.startswith("play"):
                return play_rc
            if cmd.startswith("status"):
                buf.value = next(modes)
            return 0
        winmm = Mock()
        winmm.mciSendStringW.side_effect = send
        fake_ctypes = SimpleNamespace(windll=SimpleNamespace(winmm=winmm),
                                      create_unicode_buffer=lambda n: SimpleNamespace(value=""))
        return fake_ctypes, calls

    def test_mci_polls_until_stopped_and_closes(self):
        fake_ctypes, calls = self._winmm(["playing", "playing", "stopped"])
        with patch.object(vm.os, "name", "nt"), patch.dict("sys.modules", {"ctypes": fake_ctypes}), \
                patch.object(vm.time, "sleep"):
            self.assertTrue(vm._play_mp3_blocking(r"C:\t\a.mp3"))
        self.assertTrue(calls[0].startswith('open "C:\\t\\a.mp3"'))
        self.assertTrue(calls[-1].startswith("close"))
        self.assertEqual(sum(c.startswith("status") for c in calls), 3)

    def test_mci_stop_event_interrupts(self):
        fake_ctypes, calls = self._winmm(["playing"] * 1000)
        stop = threading.Event()
        stop.set()
        with patch.object(vm.os, "name", "nt"), patch.dict("sys.modules", {"ctypes": fake_ctypes}):
            self.assertTrue(vm._play_mp3_blocking("a.mp3", stop))
        self.assertTrue(calls[-1].startswith("close"))

    def test_mci_failure_falls_back_to_powershell_with_escaped_path(self):
        fake_ctypes, calls = self._winmm([], play_rc=263)
        with patch.object(vm.os, "name", "nt"), patch.dict("sys.modules", {"ctypes": fake_ctypes}), \
                patch.object(vm, "_PLAYSOUND_AVAILABLE", False), patch("subprocess.run") as run:
            run.return_value = Mock(returncode=0)
            self.assertTrue(vm._play_mp3_blocking(r"C:\Users\O'Brien\a.mp3"))
            script = run.call_args.args[0][-1]
            self.assertIn(r"[uri]'C:\Users\O''Brien\a.mp3'", script)
            self.assertTrue(calls[-1].startswith("close"))
            run.return_value = Mock(returncode=1)
            self.assertFalse(vm._play_mp3_blocking("a.mp3"))
            run.side_effect = OSError("no powershell")
            self.assertFalse(vm._play_mp3_blocking("a.mp3"))


def make_voice(sr_mock=None, tts=None):
    sr_mock = sr_mock or Mock()
    if tts is None:
        tts = Mock()
        voices = [SimpleNamespace(name="Microsoft Zira", id="zira"), SimpleNamespace(name="Microsoft George", id="george")]
        tts.init.return_value.getProperty.return_value = voices
    with patch.object(vm, "sr", sr_mock), patch.object(vm, "pyttsx3", tts):
        v = vm.VoiceEngine()
    return v, sr_mock


class SrErrors:
    class UnknownValueError(Exception):
        pass

    class RequestError(Exception):
        pass

    class WaitTimeoutError(Exception):
        pass


class VoiceEngineTTSTests(unittest.TestCase):
    def test_setup_and_voice_selection(self):
        v, _ = make_voice()
        v.tts_engine.setProperty.assert_any_call("voice", "george")
        self.assertTrue(v.change_voice(0))
        self.assertFalse(v.change_voice(9))
        self.assertTrue(v.change_voice("zira"))
        self.assertFalse(v.change_voice("nobody"))
        with patch("builtins.print"):
            self.assertEqual(len(v.list_available_voices()), 2)
        broken = Mock()
        broken.init.side_effect = RuntimeError("no sapi")
        v2, _ = make_voice(tts=broken)
        self.assertIsNone(v2.tts_engine)
        self.assertFalse(v2.change_voice(0))
        self.assertEqual(v2.list_available_voices(), [])
        v2.setup_tts()
        v2.stop_speaking()

    def test_speak_paths(self):
        v, _ = make_voice()
        with patch.object(vm.Config, "TTS_ENGINE", "sapi"):
            v.speak(None)
            v.speak("  ")
            v.speak("Hello 🚀   world")
        v.tts_engine.say.assert_called_once_with("Hello world")
        self.assertFalse(v.is_speaking)
        with patch.object(vm.Config, "TTS_ENGINE", "edge"), patch.object(vm, "_EDGE_TTS_AVAILABLE", True), \
                patch.object(v, "_speak_edge_tts", return_value=True) as edge:
            v.speak("**Done.** More.", summarize=True)
        edge.assert_called_once()
        v.tts_engine.say.assert_called_once()            # edge worked → no SAPI
        v.tts_engine.runAndWait.side_effect = RuntimeError("busy")
        with patch.object(vm.Config, "TTS_ENGINE", "sapi"):
            v.speak("again")
        self.assertFalse(v.is_speaking)
        with patch.dict(vm.Config.VOICE_SETTINGS, {"enabled": False}):
            v.speak("muted")
        self.assertEqual(v.tts_engine.say.call_count, 2)
        v.test_voice()
        v.test_current_voice()

    def test_stop_speaking_sets_event(self):
        v, _ = make_voice()
        v.stop_speaking()
        self.assertTrue(v._stop_speaking.is_set())
        v.tts_engine.stop.assert_called_once()

    def test_edge_tts_temp_file_always_removed(self):
        v, _ = make_voice()
        made = []

        class Comm:
            def __init__(self, text, voice):
                pass

            async def save(self, path):
                made.append(path)
                Path(path).write_bytes(b"ID3data")
        with patch.object(vm, "_edge_tts", SimpleNamespace(Communicate=Comm), create=True), \
                patch.object(vm, "_play_mp3_blocking", return_value=True) as play:
            self.assertTrue(v._speak_edge_tts("hi"))
            self.assertIs(play.call_args.args[1], v._stop_speaking)
            play.side_effect = RuntimeError("audio")
            self.assertFalse(v._speak_edge_tts("hi"))
        for p in made:
            self.assertFalse(os.path.exists(p))

        class Empty(Comm):
            async def save(self, path):
                made.append(path)
        with patch.object(vm, "_edge_tts", SimpleNamespace(Communicate=Empty), create=True):
            self.assertFalse(v._speak_edge_tts("hi"))
        self.assertFalse(os.path.exists(made[-1]))


class VoiceEngineMicTests(unittest.TestCase):
    def setUp(self):
        sr_mock = Mock()
        sr_mock.UnknownValueError = SrErrors.UnknownValueError
        sr_mock.RequestError = SrErrors.RequestError
        sr_mock.WaitTimeoutError = SrErrors.WaitTimeoutError
        sr_mock.Microphone.return_value = MagicMock()
        sr_mock.Microphone.list_microphone_names.return_value = ["Default", "USB"]
        self.sr = sr_mock
        patcher = patch.object(vm, "sr", sr_mock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.v, _ = make_voice(sr_mock)

    def test_recognize_errors(self):
        rec = self.v.recognizer
        rec.recognize_google.return_value = "Open Chrome"
        self.assertEqual(self.v._recognize(object()), "open chrome")
        for exc in (SrErrors.UnknownValueError(), SrErrors.RequestError("503"), ConnectionResetError()):
            rec.recognize_google.side_effect = exc
            self.assertIsNone(self.v._recognize(object()))

    def test_listen_timeouts_and_unplugged_device(self):
        rec = self.v.recognizer
        rec.recognize_google.return_value = "hi"
        self.assertEqual(self.v.listen_for_command(), "hi")
        rec.listen.side_effect = SrErrors.WaitTimeoutError()
        self.assertIsNone(self.v.listen_for_command())
        self.assertIsNone(self.v.listen_continuously(energy_threshold=400))
        self.assertEqual(rec.energy_threshold, 400)
        rec.listen.side_effect = OSError(-9988, "Stream closed")   # device unplugged
        self.assertIsNone(self.v.listen_continuously())
        self.assertIsNone(self.v.microphone)                         # reopened next time
        rec.listen.side_effect = None
        self.assertEqual(self.v.listen_for_command(), "hi")
        rec.listen.side_effect = ValueError("odd")
        self.assertIsNone(self.v.listen_for_command())
        self.assertIsNotNone(self.v.microphone)
        self.assertFalse(self.v.is_listening)

    def test_no_sr(self):
        with patch.object(vm, "sr", None), patch.object(vm, "pyttsx3", None):
            v = vm.VoiceEngine()
        self.assertFalse(v._ensure_microphone())
        self.assertIsNone(v.listen_for_command())
        self.assertIsNone(v.listen_continuously())
        self.assertFalse(v.calibrate_microphone())
        self.assertEqual(v.get_available_microphones(), [])
        self.assertFalse(v.set_microphone(0))
        self.assertIn("not available", v.get_current_microphone_info())

    def test_wake_word_online(self):
        v = self.v
        v._vosk = False
        v.recognizer.recognize_google.return_value = "hey Jarvis"
        with patch.object(vm.time, "sleep"):
            self.assertTrue(v.listen_for_wake_word())
            v.recognizer.recognize_google.return_value = "jarvisbot rocks"
            self.assertFalse(v.listen_for_wake_word())
            v.recognizer.recognize_google.side_effect = ConnectionError("net")
            self.assertFalse(v.listen_for_wake_word())                  # never raises
            v.recognizer.listen.side_effect = SrErrors.WaitTimeoutError()
            self.assertFalse(v.listen_for_wake_word())
            v.recognizer.listen.side_effect = OSError("gone")
            self.assertFalse(v.listen_for_wake_word())
            self.assertIsNone(v.microphone)
            self.sr.Microphone.side_effect = OSError("no mic")
            self.assertFalse(v.listen_for_wake_word())

    def test_wake_word_vosk(self):
        v = self.v
        vosk = MagicMock()
        vosk.KaldiRecognizer.return_value.FinalResult.return_value = json.dumps({"text": "jarvis"})
        v._vosk = ("model", "grammar")
        with patch.dict("sys.modules", {"vosk": vosk}):
            self.assertTrue(v.listen_for_wake_word("Jarvis"))
            vosk.KaldiRecognizer.side_effect = RuntimeError("bad model")
            v.recognizer.recognize_google.return_value = "nope"
            self.assertFalse(v.listen_for_wake_word("jarvis"))

    def test_vosk_recognizer_setup(self):
        v = self.v
        with patch("core.streaming.model_ready", return_value=False):
            self.assertIsNone(v._vosk_recognizer())
        self.assertIsNone(v._vosk_recognizer())                         # cached "unavailable"
        v._vosk = None
        vosk = MagicMock()
        with tempfile.TemporaryDirectory() as d, patch("core.streaming.model_ready", return_value=True), \
                patch("core.streaming.model_dir", return_value=Path(d)), patch.dict("sys.modules", {"vosk": vosk}):
            model, grammar = v._vosk_recognizer()
            self.assertIn("jarvis", json.loads(grammar))
            v._vosk = None
            vosk.Model.side_effect = RuntimeError("corrupt")
            self.assertIsNone(v._vosk_recognizer())

    def test_devices(self):
        v = self.v
        self.assertEqual(v.get_available_microphones()[1], {"index": 1, "name": "USB", "is_default": False})
        self.assertIn("Default microphone: Default", v.get_current_microphone_info())
        self.assertTrue(v.set_microphone(1))
        self.assertIn("USB (Index: 1)", v.get_current_microphone_info())
        self.assertTrue(v.calibrate_microphone())
        v.recognizer.adjust_for_ambient_noise.side_effect = OSError("x")
        self.assertFalse(v.calibrate_microphone())
        self.sr.Microphone.list_microphone_names.side_effect = OSError("pa")
        self.assertEqual(v.get_available_microphones(), [])
        self.assertIn("Error", v.get_current_microphone_info())
        self.assertFalse(v.set_microphone(0))

    def test_contains_wake_word(self):
        self.assertTrue(vm.VoiceEngine.contains_wake_word("ok JARVIS open", "jarvis"))
        self.assertFalse(vm.VoiceEngine.contains_wake_word("jarvisx", "jarvis"))
        self.assertFalse(vm.VoiceEngine.contains_wake_word("", "jarvis"))


# ── executor ─────────────────────────────────────────────────────────────────

def join_or_fail(tc, session, timeout=10):
    session.close()
    tc.assertTrue(session.wait(timeout), "executor deadlocked / lane did not finish")


class ExecutorTests(unittest.TestCase):
    def test_sequential_and_parallel_lanes(self):
        order = []
        lock = threading.Lock()

        def run(text, ctx):
            with lock:
                order.append((ctx["lane"], text))
            return f"ok {text}"
        s = ex.ExecutionSession(run)
        s.submit("a")
        s.submit("b")
        s.submit("c", parallel=True)
        s.submit("d")
        replies = s.close_and_wait(5)
        self.assertEqual(replies, ["ok a", "ok b", "ok c", "ok d"])
        self.assertEqual([st.lane for st in s.steps], [0, 0, 1, 1])
        self.assertLess(order.index((0, "a")), order.index((0, "b")))
        self.assertFalse(s.busy)
        with self.assertRaises(RuntimeError):
            s.submit("late")
        s.close()                                       # idempotent

    def test_parallel_first_step_uses_lane_zero(self):
        s = ex.ExecutionSession(lambda t, c: "x")
        self.assertEqual(s.submit("a", parallel=True).lane, 0)
        join_or_fail(self, s)

    def test_failure_skips_rest_of_lane_only(self):
        def run(text, ctx):
            if text == "boom":
                raise ValueError("kaput")
            if text == "soft":
                return "I couldn't do that."
            return None
        settle = Mock(side_effect=[None, RuntimeError("settle"), None, None, None])
        s = ex.ExecutionSession(run, settle)
        s.submit("boom")
        s.submit("after boom")
        s.submit("soft", parallel=True)
        s.submit("after soft")
        s.submit("ok", parallel=True)
        s.close_and_wait(5)
        status = {x.text: (x.status, x.reply) for x in s.steps}
        self.assertEqual(status["boom"], ("failed", "Step failed: kaput"))
        self.assertEqual(status["after boom"][0], "skipped")
        self.assertEqual(status["soft"][0], "failed")
        self.assertEqual(status["after soft"][0], "skipped")
        self.assertEqual(status["ok"], ("done", "Done."))

    def test_error_reply_object(self):
        class Err(str):
            is_error = True
        s = ex.ExecutionSession(lambda t, c: Err("nope"))
        s.submit("x")
        s.close_and_wait(5)
        self.assertEqual(s.steps[0].status, "failed")

    def test_wait_step_and_stop_interrupts_it(self):
        s = ex.ExecutionSession(lambda t, c: "ran")
        s.submit("pause", kind="wait", seconds=0.01)
        s.close_and_wait(5)
        self.assertEqual(s.steps[0].reply, "Waited 0.01 seconds.")
        s = ex.ExecutionSession(lambda t, c: "ran")
        s.submit("pause", kind="wait", seconds=30)
        s.submit("after")
        time.sleep(0.05)
        t0 = time.time()
        s.stop()
        join_or_fail(self, s, 5)
        self.assertLess(time.time() - t0, 3)
        self.assertEqual([x.status for x in s.steps], ["stopped", "stopped"])

    def test_event_callback_errors_do_not_break_lanes(self):
        kinds = []

        def on_event(kind, info):
            kinds.append(kind)
            raise RuntimeError("ui died")
        s = ex.ExecutionSession(lambda t, c: "ok", on_event=on_event)
        s.submit("a")
        self.assertEqual(s.close_and_wait(5), ["ok"])
        self.assertEqual(kinds, ["step_queued", "step_started", "step_done"])

    def test_wait_timeout_returns_false_while_busy(self):
        gate = threading.Event()
        s = ex.ExecutionSession(lambda t, c: gate.wait(5) and "ok")
        s.submit("slow")
        s.close()
        self.assertFalse(s.wait(0.05))
        self.assertTrue(s.busy)
        gate.set()
        self.assertTrue(s.wait(5))
        self.assertTrue(ex.ExecutionSession(lambda t, c: "").wait(0))

    def test_stress_50_steps_5_lanes_with_raising_step_and_stop(self):
        lock = threading.Lock()
        running = {"now": 0, "max": 0}

        def run(text, ctx):
            with lock:
                running["now"] += 1
                running["max"] = max(running["max"], running["now"])
            try:
                time.sleep(0.002)
                if text == "step 23":
                    raise RuntimeError("bad step")
                return f"done {text}"
            finally:
                with lock:
                    running["now"] -= 1
        events = []
        s = ex.ExecutionSession(run, on_event=lambda k, i: events.append(k))
        for i in range(50):
            s.submit(f"step {i}", parallel=(i % 10 == 0))
        join_or_fail(self, s, 20)
        self.assertEqual(len({x.lane for x in s.steps}), 5)
        self.assertGreater(running["max"], 1)                     # lanes really overlap
        by_text = {x.text: x for x in s.steps}
        self.assertEqual(by_text["step 23"].status, "failed")
        self.assertTrue(all(by_text[f"step {i}"].status == "skipped" for i in range(24, 30)))
        self.assertTrue(all(by_text[f"step {i}"].status == "done" for i in range(30, 50)))
        self.assertEqual(events.count("step_queued"), 50)
        self.assertEqual(events.count("step_done"), 50)

        # stop() mid-run: running steps finish, queued ones are reported stopped, nothing hangs.
        gate = threading.Event()
        started = threading.Semaphore(0)

        def slow(text, ctx):
            started.release()
            gate.wait(5)
            return "ok"
        s = ex.ExecutionSession(slow)
        for i in range(50):
            s.submit(f"s{i}", parallel=(i % 10 == 0))
        for _ in range(5):
            self.assertTrue(started.acquire(timeout=5))
        s.stop()
        gate.set()
        join_or_fail(self, s, 10)
        statuses = [x.status for x in s.steps]
        self.assertEqual(statuses.count("done"), 5)
        self.assertEqual(statuses.count("stopped"), 45)

    def test_concurrent_submit_and_close_never_strands_a_step(self):
        slow_ui = lambda kind, info: time.sleep(0.001) if kind == "step_queued" else None   # widens the race
        for _ in range(15):
            s = ex.ExecutionSession(lambda t, c: "ok", on_event=slow_ui)
            s.submit("first")
            barrier = threading.Barrier(9)
            accepted = []

            def producer(n):
                barrier.wait()
                for j in range(20):
                    try:
                        accepted.append(s.submit(f"{n}-{j}", parallel=(j % 5 == 0)))
                    except RuntimeError:
                        return
            threads = [threading.Thread(target=producer, args=(n,)) for n in range(8)]
            for t in threads:
                t.start()
            barrier.wait()
            time.sleep(0.004)          # close() lands while producers are between reserve and enqueue
            s.close()
            for t in threads:
                t.join(5)
            self.assertTrue(s.wait(10), "lane stuck")
            self.assertFalse(s.busy, [x for x in s.steps if x.status in ("queued", "running")])

    def test_submit_after_stop(self):
        s = ex.ExecutionSession(lambda t, c: "ok")
        s.stop()
        s.submit("x")
        s.close_and_wait(5)
        self.assertEqual(s.steps[0].status, "stopped")


# ── streaming ────────────────────────────────────────────────────────────────

class TrackerEdgeTests(unittest.TestCase):
    def test_empty_and_final_resets(self):
        t = st.ClauseTracker()
        self.assertEqual(t.update(""), [])
        self.assertEqual(t.update("", final=True), [])
        self.assertEqual(t.update("open chrome", final=True), [("start", "open chrome")])
        self.assertEqual(t._consumed, 0)
        self.assertEqual(t.update("open notepad", final=True), [("start", "open notepad")])

    def test_final_that_regroups_keeps_the_tail(self):
        # Partials closed "open chrome"; the final merges differently and adds more.
        t = st.ClauseTracker()
        for text in ["open chrome and go to youtube"] * 2:
            got = t.update(text)
        self.assertEqual(got, [("start", "open chrome")])
        final = t.update("open chrome and go to youtube then open notepad", final=True)
        self.assertEqual(final, [("seq", "go to youtube"), ("seq", "open notepad")])

    def test_final_that_rewrites_an_acted_clause_does_not_rerun_it(self):
        t = st.ClauseTracker()
        for text in ["open notepad and set volume to 40"] * 2:
            t.update(text)
        final = t.update("open note pad and set the volume to 40 and lock", final=True)
        self.assertNotIn("open", " ".join(c for _, c in final).split()[:1])
        self.assertEqual(final[-1], ("seq", "lock"))

    def test_repeated_words_and_revisions(self):
        t = st.ClauseTracker()
        out = []
        for p in ("open chrome and open chrome and", "open chrome and open chrome and open",
                  "open chrome and open chrome and open", "open chrome and open chrome and open notepad"):
            out += t.update(p)
        self.assertEqual([c for _, c in out], ["open chrome", "open chrome"])
        self.assertEqual(t.update("open chrome and open chrome and open notepad", final=True),
                         [("seq", "open notepad")])
        # A revision that removes a clause boundary never re-emits or double-emits.
        t = st.ClauseTracker()
        t.update("open chrome and go to")
        self.assertEqual(t.update("open chrome and go to"), [("start", "open chrome")])
        self.assertEqual(t.update("open chrome ant go to"), [])
        self.assertEqual(t.update("open chrome and go to youtube", final=True), [("seq", "go to youtube")])

    def test_very_long_utterance(self):
        t = st.ClauseTracker(stable_updates=1)
        words = " and then ".join(f"open app{i}" for i in range(200)).split()
        got = []
        for i in range(1, len(words) + 1):
            got += t.update(" ".join(words[:i]))
        got += t.update(" ".join(words), final=True)
        self.assertEqual([c for _, c in got], [f"open app{i}" for i in range(200)])


class FakeExecJarvis:
    def __init__(self, intents=None, run=None):
        self.intents = intents or {}
        self.sessions = []
        self.run = run or (lambda text, ctx: f"Opened {text}.")
        self.voice_engine = Mock()
        self.processed = []
        self._pending_actions = []

    def _classify_command_intent(self, clause):
        return self.intents.get(clause, "APP")

    def new_execution_session(self, on_event=None):
        s = ex.ExecutionSession(self.run, None, on_event)
        self.sessions.append(s)
        return s

    def process_command(self, text, use_voice=False):
        self.processed.append(text)
        return f"handled {text}"

    @staticmethod
    def format_session(session):
        return " | ".join(s.reply for s in session.steps)


class StreamingSessionEdgeTests(unittest.TestCase):
    def make(self, **kw):
        self.events = []
        j = FakeExecJarvis(**kw)
        return j, st.StreamingSession(j, on_event=lambda k, i: self.events.append((k, i)), beep=False)

    def test_empty_final_and_no_work(self):
        j, s = self.make()
        s.segment("")
        s.partial("   ")
        self.assertIsNone(s.end_utterance())
        self.assertEqual(self.events, [])

    def test_stop_mid_utterance_cancels_live_steps(self):
        gate = threading.Event()
        j, s = self.make(run=lambda text, ctx: gate.wait(5) and f"Opened {text}.")
        s.segment("open chrome and open notepad")
        s.segment("stop")
        gate.set()
        session = j.sessions[0]
        self.assertTrue(session.wait(5))
        self.assertTrue(session.stopped.is_set())
        self.assertEqual(session.steps[1].status, "stopped")
        done = [i for k, i in self.events if k == "utterance_done"]
        self.assertEqual(done[-1]["summary"], "Stopped.")
        self.assertEqual(j.processed, [])
        self.assertIsNone(s.end_utterance())                 # nothing left to report

    def test_cancel_drops_deferred_question(self):
        j, s = self.make(intents={"what is love": "CHAT"})
        s.segment("what is love")
        s.segment("cancel")
        self.assertIsNone(s.end_utterance())
        self.assertEqual(j.sessions, [])

    def test_no_answers_earlier_confirmation_when_nothing_live(self):
        j, s = self.make()
        s.segment("cancel")
        deadline = time.time() + 2
        while not j.processed and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(j.processed, ["cancel"])
        # a pending confirmation wins even while steps are live
        j.processed.clear()
        j._pending_actions = [{"prompt": "Delete?"}]
        s.segment("open chrome")
        s.segment("stop")
        deadline = time.time() + 2
        while not j.processed and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(j.processed, ["stop"])
        s.end_utterance()

    def test_deferred_question_joins_action_session(self):
        j, s = self.make(intents={"what time is it in tokyo": "CHAT"})
        s.segment("open chrome and what time is it in tokyo")
        summary = s.end_utterance()
        self.assertEqual(len(j.sessions), 1)
        self.assertEqual(len(j.sessions[0].steps), 2)
        self.assertEqual(j.sessions[0].steps[1].lane, 1)
        self.assertIn("Opened open chrome.", summary)
        done = [i for k, i in self.events if k == "utterance_done"][-1]
        self.assertIn(" | ", done["details"])

    def test_summarize_confirmation_prompt(self):
        steps = [SimpleNamespace(reply="Opened x. Extra text.", status="done"),
                 SimpleNamespace(reply="Change it? Reply yes to confirm, or no to cancel.", status="done"),
                 SimpleNamespace(reply="", status="skipped")]
        text = st.StreamingSession.summarize(SimpleNamespace(steps=steps))
        self.assertEqual(text, "Opened x. Change it? Say yes to confirm. skipped")
        self.assertEqual(st.StreamingSession.summarize(SimpleNamespace(steps=[])), "")

    def test_wake_word_and_follow_up_window(self):
        j, s = self.make()
        s.require_wake_word = True
        s.partial("open chrome and go")
        s.segment("hey jarvis, open chrome")
        s.end_utterance()
        self.assertEqual(j.sessions[0].steps[0].text, "open chrome")
        s.segment("open notepad")                         # within the 8 s follow-up window
        s.end_utterance()
        self.assertEqual(j.sessions[1].steps[0].text, "open notepad")

    def test_partials_and_end_utterance_race(self):
        j, s = self.make()
        stop = threading.Event()
        errors = []

        def talk():
            try:
                words = "open app1 and open app2 and open app3 and open app4".split()
                while not stop.is_set():
                    for i in range(1, len(words) + 1):
                        s.partial(" ".join(words[:i]))
            except Exception as exc:     # pragma: no cover - failure path
                errors.append(exc)
        t = threading.Thread(target=talk)
        t.start()
        for _ in range(20):
            s.end_utterance()
        stop.set()
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])
        s.end_utterance()
        for sess in j.sessions:
            self.assertTrue(sess.wait(5))

    def test_ask_timeout_and_speak_failure(self):
        j, s = self.make()
        j.voice_engine.speak.side_effect = RuntimeError("tts")
        self.assertFalse(s.ask_yes_no("Sure?", timeout=0.01))
        self.assertIsNone(s._ask)

    def test_event_callback_errors_and_beep(self):
        j = FakeExecJarvis()
        s = st.StreamingSession(j, on_event=Mock(side_effect=RuntimeError("ui")), beep=True)
        with patch.object(st.os, "name", "nt"), patch.dict("sys.modules", {"winsound": Mock()}):
            s.segment("open chrome")
        s.end_utterance()
        self.assertEqual(j.sessions[0].steps[0].status, "done")

    def test_pause_mode_ignores_partials(self):
        j, s = self.make()
        s.act_mode = "pause"
        s.partial("open chrome and open notepad and")
        self.assertEqual(j.sessions, [])


class ListenerTests(unittest.TestCase):
    def test_speaking_resets_and_end_detection(self):
        session = Mock()
        voice = SimpleNamespace(is_speaking=False)
        listener = st.StreamingListener(session, voice, end_silence=0.0, model_path=Path("/m"))
        # per audio chunk: (jarvis speaking?, recognizer final?, text)
        script = [(False, False, "open"), (False, True, "open chrome"), (True, False, "echo"),
                  (False, False, ""), (False, False, "")]
        state = {"n": -1}

        def read(*a, **k):
            state["n"] += 1
            if state["n"] >= len(script) - 1:
                listener.stop()
            speaking, final, text = script[min(state["n"], len(script) - 1)]
            voice.is_speaking = speaking
            state["final"], state["text"] = final, text
            return b"\0" * 4000
        rec = MagicMock()
        rec.AcceptWaveform.side_effect = lambda data: state["final"]
        rec.Result.side_effect = lambda: json.dumps({"text": state["text"]})
        rec.PartialResult.side_effect = lambda: json.dumps({"partial": state["text"]})
        vosk = MagicMock()
        vosk.KaldiRecognizer.return_value = rec
        pa = MagicMock()
        pa.PyAudio.return_value.open.return_value.read.side_effect = read
        with patch.dict("sys.modules", {"vosk": vosk, "pyaudio": pa}):
            listener.run()
        session.partial.assert_called_once_with("open")
        session.segment.assert_called_once_with("open chrome")
        rec.Reset.assert_called_once()                       # own voice ignored
        self.assertFalse(listener.running)
        pa.PyAudio.return_value.terminate.assert_called_once()


class ModelTests(unittest.TestCase):
    def test_model_dir_and_ready(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(st.Config, "VOSK_MODEL_PATH", d):
                self.assertEqual(st.model_dir(), Path(d))
                self.assertFalse(st.model_ready())
                (Path(d) / "conf").mkdir()
                self.assertTrue(st.model_ready())
                self.assertEqual(st.ensure_model(), Path(d))
            with patch.object(st.Config, "VOSK_MODEL_PATH", ""), patch.object(st.Config, "MODELS_DIR", Path(d)):
                self.assertEqual(st.model_dir("m"), Path(d) / "m")
        self.assertIsInstance(st.vosk_available(), bool)

    def _zip(self, folder):
        import io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(f"{folder}/am/final.mdl", "x")
        return buf.getvalue()

    def _resp(self, data):
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.headers = {"content-length": str(len(data))}
        resp.iter_content.return_value = [data[:10], data[10:]]
        return resp

    def test_download_unpack_and_rename(self):
        msgs = []
        with tempfile.TemporaryDirectory() as d, patch.object(st.Config, "VOSK_MODEL_PATH", ""), \
                patch.object(st.Config, "MODELS_DIR", Path(d)):
            with patch("requests.get", return_value=self._resp(self._zip("vosk-model-small-en-us-0.15"))):
                self.assertEqual(st.ensure_model("vosk-model-small-en-us-0.15", msgs.append),
                                 Path(d) / "vosk-model-small-en-us-0.15")
            self.assertIn("ready", msgs[-1])
            self.assertFalse(list(Path(d).glob("*.part")))
            with patch("requests.get", return_value=self._resp(self._zip("vosk-model-en-in-0.5-renamed"))):
                self.assertIsNotNone(st.ensure_model("vosk-model-en-in-0.5", msgs.append))
            with patch("requests.get", return_value=self._resp(self._zip("unrelated"))):
                self.assertIsNone(st.ensure_model("zzz-model", msgs.append))
            self.assertIn("looked wrong", msgs[-1])
            with patch("requests.get", side_effect=OSError("offline")):
                self.assertIsNone(st.ensure_model("other-model", msgs.append))
            self.assertIn("Couldn't download", msgs[-1])
            self.assertFalse(list(Path(d).glob("*.part")))


# ── handlers ─────────────────────────────────────────────────────────────────

class ParseAlarmTests(unittest.TestCase):
    NOW = datetime(2026, 9, 23, 21, 30, 15)

    def p(self, text, now=None):
        from handlers.schedule import parse_alarm_time
        return parse_alarm_time(text, now or self.NOW)

    def test_clock_times(self):
        d = datetime(2026, 9, 24)
        self.assertEqual(self.p("set an alarm for 10 am"), d.replace(hour=10))
        self.assertEqual(self.p("10:30pm"), datetime(2026, 9, 23, 22, 30))
        self.assertEqual(self.p("wake me at 10:30 p.m."), datetime(2026, 9, 23, 22, 30))
        self.assertEqual(self.p("22:15"), datetime(2026, 9, 23, 22, 15))
        self.assertEqual(self.p("alarm at 12 am"), d)
        self.assertEqual(self.p("alarm at 12 pm"), d.replace(hour=12))
        self.assertEqual(self.p("alarm for 9:30"), d.replace(hour=9, minute=30))    # already passed → tomorrow
        self.assertEqual(self.p("alarm at 21:30"), d.replace(hour=21, minute=30))  # the current minute has passed

    def test_words(self):
        self.assertEqual(self.p("alarm at noon"), datetime(2026, 9, 24, 12))
        self.assertEqual(self.p("wake me at midnight"), datetime(2026, 9, 24, 0))
        self.assertEqual(self.p("midnight", datetime(2026, 9, 23, 0, 0, 0)), datetime(2026, 9, 24, 0))
        self.assertEqual(self.p("tomorrow at 7"), datetime(2026, 9, 24, 7))
        self.assertEqual(self.p("tomorrow at 7", datetime(2026, 9, 23, 1, 0)), datetime(2026, 9, 24, 7))
        self.assertEqual(self.p("tomorrow at noon", datetime(2026, 9, 23, 1, 0)), datetime(2026, 9, 24, 12))

    def test_relative(self):
        self.assertEqual(self.p("in 5 minutes"), self.NOW + timedelta(minutes=5))
        self.assertEqual(self.p("alarm in 2 hrs"), self.NOW + timedelta(hours=2))
        self.assertEqual(self.p("in an hour"), self.NOW + timedelta(hours=1))
        self.assertEqual(self.p("in half an hour"), self.NOW + timedelta(minutes=30))
        self.assertEqual(self.p("in 1 hour and 30 minutes"), self.NOW + timedelta(minutes=90))
        self.assertEqual(self.p("in 45 mins", datetime(2026, 12, 31, 23, 50)), datetime(2027, 1, 1, 0, 35))
        self.assertIsNone(self.p("in 0 minutes"))

    def test_rollover_at_year_end(self):
        self.assertEqual(self.p("7 am", datetime(2026, 12, 31, 23, 0)), datetime(2027, 1, 1, 7))

    def test_invalid(self):
        for text in ("13 pm", "25:00", "10:75", "0 am", "no time here", ""):
            self.assertIsNone(self.p(text), text)


class ScheduleHandlerTests(unittest.TestCase):
    def make(self, scheduler=True):
        from handlers.schedule import ScheduleHandler
        app = Mock()
        if scheduler:
            app.task_scheduler.schedule_alarm.side_effect = lambda at, label="": f"Alarm {at:%H:%M} {label}".strip()
            app.task_scheduler.process_schedule_command.side_effect = lambda t: f"sched:{t}"
        else:
            app.task_scheduler = None
        return ScheduleHandler(app), app

    def test_set_alarm_with_label(self):
        h, app = self.make()
        self.assertTrue(h.handle("Set an alarm for 7 am to go running", "SCHEDULE").endswith("go running"))
        self.assertIn("couldn't find a time", h.handle("set an alarm", "SCHEDULE"))

    def test_delete_alarm_never_sets_one(self):
        h, app = self.make()
        for text in ("delete my 7 am alarm", "turn off the alarm", "remove alarms", "cancel the alarm",
                     "show my alarms"):
            reply = h.handle(text, "SCHEDULE")
            self.assertTrue(reply.startswith("sched:"), text)
        app.task_scheduler.schedule_alarm.assert_not_called()
        self.assertEqual(h.handle("delete my 7 am alarm", "SCHEDULE"), "sched:cancel my 7 am alarm")
        self.assertEqual(h.handle("remind me to call mom in 5 minutes", "SCHEDULE"),
                         "sched:remind me to call mom in 5 minutes")

    def test_fallback_timer_without_scheduler(self):
        h, app = self.make(scheduler=False)
        with patch("handlers.schedule.threading.Thread") as th:
            reply = h.handle("wake me in 1 minute", "SCHEDULE")
        self.assertIn("JARVIS must stay open", reply)
        th.return_value.start.assert_called_once()
        ring = th.call_args.kwargs["target"]
        with patch("handlers.schedule.threading.Event") as ev:
            ring()
        ev.return_value.wait.assert_called_once()
        app.notify.assert_called_once()
        self.assertIn("isn't available", h.handle("list reminders", "SCHEDULE"))

    def test_tools(self):
        h, app = self.make()
        tools = FakeTools()
        h.register_tools(tools)
        self.assertEqual(tools.funcs["set_reminder"]("stretch", "in 5 minutes"), "sched:remind me to stretch in 5 minutes")
        self.assertTrue(tools.funcs["set_alarm"]("7 am").startswith("Alarm 07:00"))
        empty = FakeTools()
        self.make(scheduler=False)[0].register_tools(empty)
        self.assertEqual(empty.funcs, {})


class MemoryHandlerTests(unittest.TestCase):
    def make(self):
        from handlers.memory import MemoryHandler
        app = Mock()
        mem = app.brain.memory
        mem.memory = {"user_name": "Raghav"}
        mem.summary.return_value = "summary"
        mem.forget.return_value = 2
        mem.remember_fact.return_value = True
        app._ask_to_confirm.side_effect = lambda prompt, fn, kind: (prompt, fn())
        return MemoryHandler(app), app, mem

    def test_routes(self):
        h, app, mem = self.make()
        self.assertEqual(h.handle("What do you know about me?", "MEMORY"), "summary")
        self.assertEqual(h.handle("what's my name", "MEMORY"), "Your name is Raghav.")
        mem.memory = {}
        self.assertIn("haven't told me", h.handle("what is my name", "MEMORY"))
        prompt, reply = h.handle("forget everything", "MEMORY")
        mem.forget_all.assert_called_once()
        self.assertIn("wiped", reply)
        self.assertEqual(h.handle("forget that I like tea", "MEMORY"), "Forgotten (2 items).")
        mem.forget.return_value = 0
        self.assertIn("don't have anything", h.handle("forget fact tea", "MEMORY"))
        self.assertIn("call you Raghav V", h.handle("remember that my name is raghav v", "MEMORY"))
        self.assertIn("live in Pune", h.handle("Remember I live in Pune", "MEMORY"))
        mem.set_preference.assert_called_once_with("location", "Pune")
        self.assertEqual(h.handle("don't forget I like jazz", "MEMORY"), "Noted. I'll remember that.")
        mem.remember_fact.return_value = False
        self.assertEqual(h.handle("note that I like jazz", "MEMORY"), "I already know that.")
        self.assertIsNone(h.handle("how are you", "MEMORY"))

    def test_forget_it_does_not_delete_facts(self):
        h, app, mem = self.make()
        for text in ("forget it", "Forget that.", "forget about it"):
            self.assertIn("never mind", h.handle(text, "MEMORY"))
        mem.forget.assert_not_called()

    def test_no_brain_and_tools(self):
        from handlers.memory import MemoryHandler
        h = MemoryHandler(SimpleNamespace(brain=None))
        self.assertIn("unavailable", h.handle("remember x", "MEMORY"))
        tools = FakeTools()
        h.register_tools(tools)
        self.assertEqual(tools.funcs, {})
        h, app, mem = self.make()
        h.register_tools(tools)
        self.assertEqual(tools.funcs["remember_fact"]("x"), "Noted.")
        mem.remember_fact.return_value = False
        self.assertEqual(tools.funcs["remember_fact"]("x"), "Already known.")


class ScreenHandlerTests(unittest.TestCase):
    def make(self, sa=True):
        from handlers.screen import ScreenHandler
        app = Mock()
        app.windows.type_text.side_effect = lambda t: f"typed:{t}"
        if sa:
            app.screen_automation.execute_action.return_value = (True, "pressed ctrl+s")
            app.screen_automation.find_and_click_element.return_value = {"message": "clicked"}
        else:
            app.screen_automation = None
        return ScreenHandler(app), app

    def test_type_and_press(self):
        h, app = self.make()
        self.assertEqual(h.handle('type "hello world"', "SCREEN_AUTOMATION"), "typed:hello world")
        self.assertEqual(h.handle("Press ctrl s", "SCREEN_AUTOMATION"), "Pressed ctrl+s")
        app.screen_automation.execute_action.assert_called_with({"type": "press", "keys": "ctrl+s"})
        app.screen_automation.execute_action.return_value = (False, "unknown key")
        self.assertIn("Couldn't press", h.handle("hit the zork key", "SCREEN_AUTOMATION"))
        with patch("skills.screen_automation.process_automation_command", return_value="auto") as pac:
            self.assertEqual(h.handle("type hello into the search box", "SCREEN_AUTOMATION"), "auto")
        pac.assert_called_once()

    def test_without_automation_and_tools(self):
        h, app = self.make(sa=False)
        self.assertIn("isn't available", h.handle("click the save button", "SCREEN_AUTOMATION"))
        tools = FakeTools()
        h.register_tools(tools)
        self.assertEqual(tools.funcs, {})
        h, app = self.make()
        h.register_tools(tools)
        self.assertEqual(tools.funcs["click_on_screen"]("save"), "clicked")
        app.screen_automation.execute_action.return_value = (True, "ok")
        self.assertEqual(tools.funcs["press_keys"]("enter"), "ok")


if __name__ == "__main__":
    unittest.main()
