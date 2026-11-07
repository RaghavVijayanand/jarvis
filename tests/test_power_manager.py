"""PowerManager: power plans (powercfg) and startup app entries (winreg Run +
StartupApproved), both mocked so these run without Windows."""
import subprocess
import unittest
from unittest.mock import MagicMock, Mock, patch

import skills.power_manager as power_mod
from skills.power_manager import PowerManager


def proc(stdout="", returncode=0, stderr=""):
    return Mock(stdout=stdout, stderr=stderr, returncode=returncode)


_PLAN_LIST = (
    "Existing Power Schemes (* Active)\n-----------------------------------\n"
    "Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced) *\n"
    "Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (High performance)\n"
    "Power Scheme GUID: a1841308-3541-4fab-bc81-f71556f20b4a  (Power saver)\n"
)


class PowerPlanTests(unittest.TestCase):
    def setUp(self):
        self.pm = PowerManager()

    def test_list_power_plans(self):
        with patch("subprocess.run", return_value=proc(_PLAN_LIST)):
            result = self.pm.list_power_plans()
        self.assertIn("Balanced (active)", result)
        self.assertIn("High performance", result)
        self.assertIn("Power saver", result)

    def test_list_power_plans_missing_powercfg(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIn("Couldn't list", self.pm.list_power_plans())

    def test_list_power_plans_none_found(self):
        with patch("subprocess.run", return_value=proc("nothing here")):
            self.assertIn("No power plans found", self.pm.list_power_plans())

    def test_active_power_plan(self):
        out = "Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)"
        with patch("subprocess.run", return_value=proc(out)):
            result = self.pm.active_power_plan()
        self.assertIn("Balanced", result)

    def test_active_power_plan_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIn("Couldn't check", self.pm.active_power_plan())

    def test_set_power_plan_exact_match(self):
        with patch("subprocess.run", side_effect=[proc(_PLAN_LIST), proc("", 0)]) as run:
            result = self.pm.set_power_plan("High performance")
        self.assertIn("Switched to the 'High performance' power plan", result)
        second_call_args = run.call_args_list[1].args[0]
        self.assertEqual(second_call_args, ["powercfg", "/setactive", "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"])

    def test_set_power_plan_partial_match(self):
        with patch("subprocess.run", side_effect=[proc(_PLAN_LIST), proc("", 0)]):
            result = self.pm.set_power_plan("saver")
        self.assertIn("Switched to the 'saver' power plan", result)

    def test_set_power_plan_no_match(self):
        with patch("subprocess.run", return_value=proc(_PLAN_LIST)):
            result = self.pm.set_power_plan("turbo nonsense")
        self.assertIn("No power plan matching", result)

    def test_set_power_plan_setactive_fails(self):
        with patch("subprocess.run", side_effect=[proc(_PLAN_LIST), proc("", 1, "access denied")]):
            result = self.pm.set_power_plan("Balanced")
        self.assertIn("Couldn't switch power plans", result)


class StartupAppTests(unittest.TestCase):
    def setUp(self):
        self.pm = PowerManager()
        self.winreg = MagicMock()
        self.winreg.HKEY_CURRENT_USER = 1
        self.winreg.HKEY_LOCAL_MACHINE = 2
        self.winreg.REG_BINARY = "REG_BINARY"
        self.patcher = patch.object(power_mod, "winreg", self.winreg)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_list_startup_apps_no_winreg(self):
        with patch.object(power_mod, "winreg", None):
            result = self.pm.list_startup_apps()
        self.assertIn("isn't available", result)

    def test_list_startup_apps(self):
        run_entries = [("OneDrive", r"C:\OneDrive.exe"), ("Spotify", r"C:\Spotify.exe")]

        def open_key(const, path):
            key = MagicMock()
            key.__enter__.return_value = key
            if path == power_mod._RUN_PATH:
                def enum_value(k, i):
                    if i >= len(run_entries):
                        raise OSError()
                    return run_entries[i][0], run_entries[i][1], 1
                key.__exit__ = Mock(return_value=False)
                self.winreg.EnumValue.side_effect = enum_value
            return key

        self.winreg.OpenKey.side_effect = open_key
        # StartupApproved lookups: OneDrive enabled (0x02), Spotify disabled (0x03)
        approved_data = {"OneDrive": b"\x02" + bytes(11), "Spotify": b"\x03" + bytes(11)}

        def query_value_ex(key, name):
            return approved_data[name], "REG_BINARY"
        self.winreg.QueryValueEx.side_effect = query_value_ex

        result = self.pm.list_startup_apps()
        # Both HKCU and HKLM Run keys are checked; this mock answers the same for both,
        # so each app shows up once per hive — the important thing is the enabled/disabled split.
        self.assertIn("OneDrive (HKCU) — enabled", result)
        self.assertIn("Spotify (HKCU) — disabled", result)

    def test_enable_disable_no_match(self):
        self.winreg.OpenKey.side_effect = OSError()
        self.assertIn("No startup app matching", self.pm.enable_startup_app("Nope"))
        self.assertIn("No startup app matching", self.pm.disable_startup_app("Nope"))

    def test_disable_startup_app_writes_flag(self):
        run_entries = [("Spotify", r"C:\Spotify.exe")]

        def open_key(const, path):
            key = MagicMock()
            key.__enter__.return_value = key
            if path == power_mod._RUN_PATH:
                def enum_value(k, i):
                    if i >= len(run_entries):
                        raise OSError()
                    return run_entries[i][0], run_entries[i][1], 1
                self.winreg.EnumValue.side_effect = enum_value
            return key
        self.winreg.OpenKey.side_effect = open_key

        create_key = MagicMock()
        create_key.__enter__.return_value = create_key
        self.winreg.CreateKeyEx.return_value = create_key

        result = self.pm.disable_startup_app("Spotify")
        self.assertIn("Disabled 'Spotify' at startup", result)
        self.winreg.SetValueEx.assert_called_once()
        args = self.winreg.SetValueEx.call_args.args
        self.assertEqual(args[1], "Spotify")
        self.assertEqual(args[4][0], 0x03)

    def test_enable_startup_app_writes_flag(self):
        run_entries = [("Spotify", r"C:\Spotify.exe")]

        def open_key(const, path):
            key = MagicMock()
            key.__enter__.return_value = key
            if path == power_mod._RUN_PATH:
                def enum_value(k, i):
                    if i >= len(run_entries):
                        raise OSError()
                    return run_entries[i][0], run_entries[i][1], 1
                self.winreg.EnumValue.side_effect = enum_value
            return key
        self.winreg.OpenKey.side_effect = open_key
        create_key = MagicMock()
        create_key.__enter__.return_value = create_key
        self.winreg.CreateKeyEx.return_value = create_key

        result = self.pm.enable_startup_app("spotify")
        self.assertIn("Enabled 'Spotify' at startup", result)
        args = self.winreg.SetValueEx.call_args.args
        self.assertEqual(args[4][0], 0x02)

    def test_set_startup_enabled_permission_error(self):
        run_entries = [("Spotify", r"C:\Spotify.exe")]

        def open_key(const, path):
            key = MagicMock()
            key.__enter__.return_value = key
            if path == power_mod._RUN_PATH:
                def enum_value(k, i):
                    if i >= len(run_entries):
                        raise OSError()
                    return run_entries[i][0], run_entries[i][1], 1
                self.winreg.EnumValue.side_effect = enum_value
            return key
        self.winreg.OpenKey.side_effect = open_key
        self.winreg.CreateKeyEx.side_effect = PermissionError()

        result = self.pm.disable_startup_app("Spotify")
        self.assertIn("administrator rights", result)

    def test_enable_startup_app_no_winreg(self):
        with patch.object(power_mod, "winreg", None):
            self.assertIn("isn't available", self.pm.enable_startup_app("x"))


if __name__ == "__main__":
    unittest.main()
