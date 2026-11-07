"""Edge cases across the system-management skills: injection into CLIs/PowerShell, empty or
option-like names, ambiguous package matches, console decoding and unreviewed generated code."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from skills.app_scripting import AppScripting, script_problems
from skills.network_manager import NetworkManager, console_encoding
from skills.power_manager import PowerManager
from skills.security_checks import SecurityChecks
from skills.service_manager import ServiceManager
from skills.software_manager import Package, SoftwareManager


def proc(stdout="", returncode=0, stderr=""):
    return Mock(stdout=stdout, stderr=stderr, returncode=returncode)


class InjectionTests(unittest.TestCase):
    def test_bitlocker_drive_cannot_break_out_of_the_powershell_string(self):
        with patch("subprocess.run") as run:
            reply = SecurityChecks().bitlocker_status("C'; Start-Process calc; '")
        self.assertIn("isn't a drive letter", reply)
        run.assert_not_called()
        with patch("subprocess.run", return_value=proc("ProtectionStatus : 1\n")) as run:
            SecurityChecks().bitlocker_status("d:\\")
        self.assertIn("-MountPoint 'd:'", run.call_args.args[0][-1])

    def test_ping_rejects_switch_like_hosts_and_bad_counts(self):
        net = NetworkManager()
        with patch("subprocess.run") as run:
            for host in ("-t", "/?", "a b"):
                self.assertIn("isn't a host", net.ping(host))
            run.assert_not_called()
        with patch("subprocess.run", return_value=proc("Reply")) as run:
            net.ping("example.com", count="lots")
        self.assertEqual(run.call_args.args[0][:3], ["ping", "-n", "4"])

    def test_port_and_vpn_validation(self):
        net = NetworkManager()
        self.assertIn("valid port", net.check_port("example.com", 70000))
        self.assertIn("which host", net.check_port("", 80).lower())
        with patch("subprocess.run") as run:
            self.assertIn("Which VPN", net.connect_vpn(""))
            self.assertIn("Which VPN", net.disconnect_vpn("/disconnect"))
            run.assert_not_called()

    def test_service_names_that_sc_would_misread_are_refused(self):
        sm = ServiceManager()
        with patch("subprocess.run") as run:
            for name in ("", "  ", "/?", "\\\\otherpc", "start= auto"):
                self.assertIn("Which service", sm.stop_service(name))
                self.assertIn("Which service", sm.service_status(name))
            run.assert_not_called()

    def test_cli_runs_never_wait_on_stdin_and_decode_the_console_code_page(self):
        with patch("subprocess.run", return_value=proc("")) as run:
            NetworkManager().current_wifi()
        self.assertEqual(run.call_args.kwargs["encoding"], console_encoding())
        self.assertIsNotNone(run.call_args.kwargs["stdin"])
        if os.name == "nt":                             # cp437's 0x82 is 'é', which UTF-8 turned into '�'
            self.assertEqual(b"caf\x82".decode(console_encoding()), "café") if console_encoding() == "cp437" \
                else "café".encode(console_encoding())


class EmptyNameTests(unittest.TestCase):
    def test_empty_power_plan_or_startup_name_matches_nothing(self):
        pm = PowerManager()
        listing = "Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced) *\n"
        with patch("subprocess.run", return_value=proc(listing)) as run:
            self.assertIn("No power plan", pm.set_power_plan(""))
        self.assertNotIn("/setactive", run.call_args.args[0])
        with patch.object(pm, "_all_run_entries", return_value=[("HKCU", "OneDrive", "x")]):
            self.assertIsNone(pm._find_run_entry(""))

    def test_power_plans_parse_on_non_english_windows(self):
        german = "Energieschema-GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Ausbalanciert) *\n"
        with patch("subprocess.run", return_value=proc(german)):
            self.assertIn("Ausbalanciert (active)", PowerManager().list_power_plans())


class SoftwareMatchTests(unittest.TestCase):
    def setUp(self):
        self.sm = SoftwareManager()
        self.sm._available = True

    def test_search_term_is_passed_as_query_not_option(self):
        with patch("subprocess.run", return_value=proc("")) as run:
            self.sm.search("--source=evil")
            self.sm.list_installed("--all")
        for call in run.call_args_list:
            args = call.args[0]
            self.assertEqual(args[args.index("--query") + 1][:2], "--")

    def test_uninstall_refuses_to_guess_between_several_matches(self):
        pkgs = [Package("Chrome Remote Desktop", "Google.ChromeRemoteDesktop"),
                Package("Google Chrome Beta", "Google.Chrome.Beta")]
        with patch.object(self.sm, "list_installed", return_value=pkgs), patch("subprocess.run") as run:
            reply = self.sm.uninstall("chrome")
            self.assertIn("More than one", reply)
            self.assertIn("upgrade", self.sm.upgrade("chrome"))
            run.assert_not_called()

    def test_exact_or_id_tail_match_still_works(self):
        pkgs = [Package("VLC media player", "VideoLAN.VLC"), Package("VLC skins", "Some.VLCSkins")]
        self.assertEqual(self.sm._best_match("vlc", pkgs, strict=True).id, "VideoLAN.VLC")
        self.assertEqual(self.sm._best_match("only", [Package("Only One", "X.Y")], strict=True).id, "X.Y")


class GeneratedScriptTests(unittest.TestCase):
    def test_safe_modeling_script_passes(self):
        self.assertEqual(script_problems("import bpy, math\nbpy.ops.mesh.primitive_cube_add()\n"), [])

    def test_risky_scripts_are_flagged(self):
        for code in ("import os\nos.system('x')", "import subprocess", "from shutil import rmtree",
                     "open('C:/x', 'w')", "__import__('os')", "bpy.__class__.__subclasses__()",
                     "def broken(:"):
            with self.subTest(code=code):
                self.assertTrue(script_problems(code))

    def test_risky_generated_script_is_saved_not_run(self):
        with tempfile.TemporaryDirectory() as d:
            app = AppScripting(Mock(brain=Mock(ask_text=Mock(return_value="import os\nos.remove('x')"))))
            app.scripts_dir = Path(d)
            with patch("skills.app_scripting.find_blender", return_value=r"C:\blender.exe"), \
                    patch("subprocess.Popen") as popen, patch("subprocess.run") as run:
                reply = app.blender_run("make a cube")
            popen.assert_not_called()
            run.assert_not_called()
            self.assertIn("didn't run", reply)
            self.assertEqual(len(list(Path(d).glob("blender_unreviewed_*.py"))), 1)


class PluginTests(unittest.TestCase):
    def test_plugin_calling_sys_exit_is_skipped_not_fatal(self):
        from core.plugins import discover_plugin_handlers, run_plugin_setup
        with tempfile.TemporaryDirectory() as d:
            Path(d, "quitter.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
            Path(d, "badsetup.py").write_text("import sys\ndef setup(app):\n    sys.exit(4)\n", encoding="utf-8")
            _classes, setups, names = discover_plugin_handlers(Path(d))
            self.assertEqual(names, ["badsetup"])
            run_plugin_setup(Mock(), setups)          # must not raise SystemExit


if __name__ == "__main__":
    unittest.main()
