"""SecurityChecks: Defender/BitLocker via PowerShell, Windows Update via the COM
Update Agent, and elevated update installs — all mocked so these run without Windows."""
import subprocess
import sys
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

import skills.security_checks as sec_mod
from skills.security_checks import SecurityChecks


def proc(stdout="", returncode=0, stderr=""):
    return Mock(stdout=stdout, stderr=stderr, returncode=returncode)


class DefenderTests(unittest.TestCase):
    def setUp(self):
        self.sec = SecurityChecks()

    def test_defender_status(self):
        out = ("AntivirusEnabled              : True\n"
               "RealTimeProtectionEnabled     : True\n"
               "AntivirusSignatureLastUpdated : 9/20/2026 3:00:00 AM\n")
        with patch("subprocess.run", return_value=proc(out)):
            result = self.sec.defender_status()
        self.assertIn("Antivirus enabled: True", result)
        self.assertIn("Real-time protection: True", result)
        self.assertIn("9/20/2026", result)

    def test_defender_status_missing_powershell(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIn("isn't available", self.sec.defender_status())

    def test_defender_status_empty_output(self):
        with patch("subprocess.run", return_value=proc("")):
            self.assertIn("Couldn't read", self.sec.defender_status())

    def test_defender_status_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="powershell", timeout=30)):
            self.assertIn("Couldn't check Defender status", self.sec.defender_status())

    def test_start_defender_scan_quick(self):
        with patch("subprocess.Popen") as popen:
            result = self.sec.start_defender_scan("quick")
        self.assertIn("quick scan", result)
        args = popen.call_args.args[0]
        self.assertIn("QuickScan", " ".join(args))

    def test_start_defender_scan_full(self):
        with patch("subprocess.Popen") as popen:
            result = self.sec.start_defender_scan("full")
        self.assertIn("full scan", result)
        args = popen.call_args.args[0]
        self.assertIn("FullScan", " ".join(args))

    def test_start_defender_scan_defaults_to_quick(self):
        with patch("subprocess.Popen") as popen:
            self.sec.start_defender_scan("")
        args = popen.call_args.args[0]
        self.assertIn("QuickScan", " ".join(args))

    def test_start_defender_scan_missing_powershell(self):
        with patch("subprocess.Popen", side_effect=FileNotFoundError()):
            self.assertIn("isn't available", self.sec.start_defender_scan())

    def test_start_defender_scan_other_error(self):
        with patch("subprocess.Popen", side_effect=OSError("boom")):
            self.assertIn("Couldn't start the scan", self.sec.start_defender_scan())


class BitlockerTests(unittest.TestCase):
    def setUp(self):
        self.sec = SecurityChecks()

    def test_bitlocker_status_protected(self):
        out = "VolumeStatus         : FullyEncrypted\nProtectionStatus     : 1\nEncryptionPercentage : 100\n"
        with patch("subprocess.run", return_value=proc(out)):
            result = self.sec.bitlocker_status("C:")
        self.assertIn("protection is on", result)
        self.assertIn("100%", result)

    def test_bitlocker_status_adds_colon(self):
        out = "VolumeStatus         : FullyEncrypted\nProtectionStatus     : 0\nEncryptionPercentage : 0\n"
        with patch("subprocess.run", return_value=proc(out)) as run:
            self.sec.bitlocker_status("D")
        args = run.call_args.args[0]
        self.assertIn("D:", " ".join(args))

    def test_bitlocker_status_missing_powershell(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIn("isn't available", self.sec.bitlocker_status())

    def test_bitlocker_status_no_such_drive(self):
        with patch("subprocess.run", return_value=proc("", 1, "not found")):
            self.assertIn("Couldn't read BitLocker status", self.sec.bitlocker_status("Z:"))

    def test_bitlocker_status_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="powershell", timeout=30)):
            self.assertIn("Couldn't check BitLocker status", self.sec.bitlocker_status())


class WindowsUpdateTests(unittest.TestCase):
    def setUp(self):
        self.sec = SecurityChecks()

    def _fake_win32com(self, dispatch_result):
        fake_client = types.ModuleType("win32com.client")
        fake_client.Dispatch = Mock(return_value=dispatch_result)
        fake_win32com = types.ModuleType("win32com")
        fake_win32com.client = fake_client
        return {"win32com": fake_win32com, "win32com.client": fake_client}

    def test_check_windows_update_none_available(self):
        session = MagicMock()
        search_result = MagicMock()
        search_result.Updates.Count = 0
        session.CreateUpdateSearcher.return_value.Search.return_value = search_result
        with patch.dict(sys.modules, self._fake_win32com(session)):
            result = self.sec.check_windows_update()
        self.assertIn("up to date", result)

    def test_check_windows_update_available(self):
        session = MagicMock()
        search_result = MagicMock()
        search_result.Updates.Count = 2
        item0, item1 = Mock(Title="Update A"), Mock(Title="Update B")
        search_result.Updates.Item.side_effect = lambda i: [item0, item1][i]
        session.CreateUpdateSearcher.return_value.Search.return_value = search_result
        with patch.dict(sys.modules, self._fake_win32com(session)):
            result = self.sec.check_windows_update()
        self.assertIn("2 update(s) available", result)
        self.assertIn("Update A", result)
        self.assertIn("Update B", result)

    def test_check_windows_update_no_pywin32(self):
        with patch.dict(sys.modules, {"win32com": None, "win32com.client": None}):
            result = self.sec.check_windows_update()
        self.assertIn("pywin32", result)

    def test_check_windows_update_search_error(self):
        fake_client = types.ModuleType("win32com.client")
        fake_client.Dispatch = Mock(side_effect=Exception("COM error"))
        fake_win32com = types.ModuleType("win32com")
        fake_win32com.client = fake_client
        with patch.dict(sys.modules, {"win32com": fake_win32com, "win32com.client": fake_client}):
            result = self.sec.check_windows_update()
        self.assertIn("Couldn't check for updates", result)

    def test_install_windows_updates(self):
        with patch.object(sec_mod, "run_elevated", return_value="Started with administrator rights.") as elevated:
            result = self.sec.install_windows_updates()
        elevated.assert_called_once_with("UsoClient.exe StartInstall")
        self.assertIn("Requested Windows Update installation", result)
        self.assertIn("Started with administrator rights", result)


if __name__ == "__main__":
    unittest.main()
