"""SystemAdmin: registry, firewall and scheduled-task actions, with winreg/subprocess/ctypes
mocked so these run without Windows."""
import subprocess
import sys
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

import skills.system_admin as admin_mod
from skills.system_admin import SystemAdmin


def proc(stdout="", returncode=0, stderr=""):
    return Mock(stdout=stdout, stderr=stderr, returncode=returncode)


class ElevationTests(unittest.TestCase):
    def test_is_admin_true_and_false(self):
        windll = MagicMock()
        windll.shell32.IsUserAnAdmin.return_value = 1
        with patch.object(admin_mod, "ctypes", MagicMock(windll=windll)):
            self.assertTrue(SystemAdmin.is_admin())
        windll.shell32.IsUserAnAdmin.return_value = 0
        with patch.object(admin_mod, "ctypes", MagicMock(windll=windll)):
            self.assertFalse(SystemAdmin.is_admin())

    def test_is_admin_false_without_ctypes(self):
        with patch.object(admin_mod, "ctypes", None):
            self.assertFalse(SystemAdmin.is_admin())

    def test_run_elevated_success(self):
        windll = MagicMock()
        windll.shell32.ShellExecuteW.return_value = 42
        with patch.object(admin_mod, "ctypes", MagicMock(windll=windll)):
            result = SystemAdmin.request_elevated("ipconfig /flushdns")
        self.assertIn("Started", result)
        windll.shell32.ShellExecuteW.assert_called_once()
        self.assertEqual(windll.shell32.ShellExecuteW.call_args.args[2], "cmd.exe")

    def test_run_elevated_declined(self):
        windll = MagicMock()
        windll.shell32.ShellExecuteW.return_value = 5   # <= 32: failure/decline per Win32 docs
        with patch.object(admin_mod, "ctypes", MagicMock(windll=windll)):
            result = SystemAdmin.request_elevated("whoami")
        self.assertIn("wasn't granted", result)

    def test_run_elevated_without_ctypes(self):
        with patch.object(admin_mod, "ctypes", None):
            self.assertIn("isn't available", SystemAdmin.request_elevated("whoami"))


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.admin = SystemAdmin()
        self.winreg = MagicMock()
        self.winreg.HKEY_CURRENT_USER = 1
        self.winreg.HKEY_LOCAL_MACHINE = 2
        for name in ("REG_SZ", "REG_EXPAND_SZ", "REG_DWORD", "REG_QWORD", "REG_MULTI_SZ", "REG_BINARY"):
            setattr(self.winreg, name, name)
        self.patcher = patch.object(admin_mod, "winreg", self.winreg)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_unknown_hive(self):
        self.assertIn("Unknown registry hive", self.admin.read_registry_value("hkxx", "a", "b"))

    def test_read_value(self):
        key = MagicMock()
        key.__enter__.return_value = key
        self.winreg.OpenKey.return_value = key
        self.winreg.QueryValueEx.return_value = ("hello", "REG_SZ")
        self.assertEqual(self.admin.read_registry_value("HKCU", r"Software\X", "Name"), "hello")

    def test_read_missing_value(self):
        self.winreg.OpenKey.side_effect = FileNotFoundError()
        self.assertIn("doesn't exist", self.admin.read_registry_value("HKCU", r"Software\X", "Name"))

    def test_write_value_success(self):
        key = MagicMock()
        key.__enter__.return_value = key
        self.winreg.CreateKeyEx.return_value = key
        result = self.admin.write_registry_value("HKCU", r"Software\X", "Name", "hi")
        self.assertIn("Set HKCU", result)
        self.winreg.SetValueEx.assert_called_once_with(key, "Name", 0, "REG_SZ", "hi")

    def test_write_dword_casts_to_int(self):
        key = MagicMock()
        key.__enter__.return_value = key
        self.winreg.CreateKeyEx.return_value = key
        self.admin.write_registry_value("HKCU", r"Software\X", "N", "5", value_type="dword")
        self.winreg.SetValueEx.assert_called_once_with(key, "N", 0, "REG_DWORD", 5)

    def test_write_permission_denied_offers_elevation(self):
        self.winreg.CreateKeyEx.side_effect = PermissionError()
        with patch.object(admin_mod, "run_elevated_args", return_value="Started.") as run_elev:
            result = self.admin.write_registry_value("HKLM", r"Software\X", "N", "1")
        self.assertIn("needs administrator rights", result)
        run_elev.assert_called_once()

    def test_elevated_fallback_never_goes_through_a_shell(self):
        """An approved value like 'x" & calc & "' must stay one reg.exe argument, not a command."""
        self.winreg.CreateKeyEx.side_effect = PermissionError()
        windll = MagicMock()
        windll.shell32.ShellExecuteW.return_value = 42
        with patch.object(admin_mod, "ctypes", MagicMock(windll=windll)):
            self.admin.write_registry_value("HKLM", r"Software\X", "N", 'x" & calc & "')
        args = windll.shell32.ShellExecuteW.call_args.args
        self.assertEqual(args[2], "reg")
        self.assertIn('"x\\\" & calc & \\\""', args[3])

    def test_bad_typed_values_are_rejected_not_raised(self):
        self.assertIn("isn't a valid REG_DWORD", self.admin.write_registry_value("HKCU", "S", "N", "abc", "dword"))
        self.assertIn("isn't a valid REG_DWORD", self.admin.write_registry_value("HKCU", "S", "N", "-1", "dword"))
        self.assertIn("isn't a valid REG_BINARY", self.admin.write_registry_value("HKCU", "S", "N", "zz", "binary"))
        self.winreg.CreateKeyEx.assert_not_called()

    def test_delete_value_success(self):
        key = MagicMock()
        key.__enter__.return_value = key
        self.winreg.OpenKey.return_value = key
        result = self.admin.delete_registry_value("HKCU", r"Software\X", "Name")
        self.assertIn("Deleted", result)
        self.winreg.DeleteValue.assert_called_once_with(key, "Name")

    def test_delete_missing_value(self):
        self.winreg.OpenKey.side_effect = FileNotFoundError()
        self.assertIn("doesn't exist", self.admin.delete_registry_value("HKCU", r"Software\X", "Name"))

    def test_no_winreg_module(self):
        with patch.object(admin_mod, "winreg", None):
            self.assertIn("isn't available", SystemAdmin().read_registry_value("HKCU", "a", "b"))


class FirewallTests(unittest.TestCase):
    def setUp(self):
        self.admin = SystemAdmin()

    def test_list_rules(self):
        out = "Rule Name:                           Allow VLC\n----\nRule Name:                           Block Telnet\n"
        with patch("subprocess.run", return_value=proc(out)):
            result = self.admin.list_firewall_rules()
        self.assertIn("Allow VLC", result)
        self.assertIn("Block Telnet", result)

    def test_add_rule_success(self):
        with patch("subprocess.run", return_value=proc("Ok.", 0)):
            result = self.admin.add_firewall_rule("Allow 8080", port="8080")
        self.assertIn("Added firewall rule", result)

    def test_add_rule_needs_elevation(self):
        with patch("subprocess.run", return_value=proc("", 1, "Access is denied.")), \
                patch.object(admin_mod, "run_elevated_args", return_value="Started.") as run_elev:
            result = self.admin.add_firewall_rule("Allow 8080", port="8080")
        self.assertIn("needs administrator rights", result)
        run_elev.assert_called_once()

    def test_remove_rule_success(self):
        with patch("subprocess.run", return_value=proc("Ok.", 0)):
            self.assertIn("Removed firewall rule", self.admin.remove_firewall_rule("Allow 8080"))

    def test_netsh_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIn("Couldn't list firewall rules", self.admin.list_firewall_rules())


class ScheduledTaskTests(unittest.TestCase):
    def setUp(self):
        self.admin = SystemAdmin()

    def test_list_tasks_filters_by_query(self):
        csv_out = '"\\Backup Nightly","Ready","..."\r\n"\\JARVIS Ping","Ready","..."\r\n'
        with patch("subprocess.run", return_value=proc(csv_out)):
            result = self.admin.list_scheduled_tasks("jarvis")
        self.assertIn("JARVIS Ping", result)
        self.assertNotIn("Backup Nightly", result)

    def test_create_task_success(self):
        with patch("subprocess.run", return_value=proc("SUCCESS", 0)):
            result = self.admin.create_scheduled_task("Nightly Backup", "backup.exe", schedule="DAILY")
        self.assertIn("Created scheduled task 'Nightly Backup'", result)

    def test_create_task_needs_elevation(self):
        with patch("subprocess.run", return_value=proc("", 1, "Access is denied.")), \
                patch.object(admin_mod, "run_elevated_args", return_value="Started.") as run_elev:
            result = self.admin.create_scheduled_task("Nightly Backup", "backup.exe")
        self.assertIn("needs administrator rights", result)
        run_elev.assert_called_once()

    def test_delete_task_success(self):
        with patch("subprocess.run", return_value=proc("SUCCESS", 0)):
            self.assertIn("Deleted scheduled task", self.admin.delete_scheduled_task("Nightly Backup"))

    def test_schtasks_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIn("isn't available", self.admin.delete_scheduled_task("X"))

    def test_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("schtasks", 20)):
            self.assertIn("timed out", self.admin.delete_scheduled_task("X"))


if __name__ == "__main__":
    unittest.main()
