"""ServiceManager: sc.exe service control and psutil top-process breakdowns, all
mocked so these run without Windows."""
import subprocess
import unittest
from unittest.mock import Mock, patch

from skills.service_manager import ServiceManager


def proc(stdout="", returncode=0, stderr=""):
    return Mock(stdout=stdout, stderr=stderr, returncode=returncode)


class ServiceControlTests(unittest.TestCase):
    def setUp(self):
        self.sm = ServiceManager()

    def test_list_services(self):
        out = ("SERVICE_NAME: Spooler\nDISPLAY_NAME: Print Spooler\n"
               "SERVICE_NAME: wuauserv\nDISPLAY_NAME: Windows Update\n")
        with patch("subprocess.run", return_value=proc(out)):
            result = self.sm.list_services()
        self.assertIn("Print Spooler", result)
        self.assertIn("Windows Update", result)

    def test_list_services_filtered(self):
        out = "SERVICE_NAME: Spooler\nDISPLAY_NAME: Print Spooler\n"
        with patch("subprocess.run", return_value=proc(out)):
            result = self.sm.list_services(query="spool")
        self.assertIn("Print Spooler", result)

    def test_list_services_no_match(self):
        out = "SERVICE_NAME: Spooler\nDISPLAY_NAME: Print Spooler\n"
        with patch("subprocess.run", return_value=proc(out)):
            result = self.sm.list_services(query="nope")
        self.assertIn("No matching services", result)

    def test_list_services_missing_sc(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIn("Couldn't list", self.sm.list_services())

    def test_service_status_running(self):
        out = "SERVICE_NAME: Spooler\n        STATE              : 4  RUNNING\n"
        with patch("subprocess.run", return_value=proc(out)):
            result = self.sm.service_status("Spooler")
        self.assertIn("is running", result)

    def test_service_status_stopped(self):
        out = "SERVICE_NAME: Spooler\n        STATE              : 1  STOPPED\n"
        with patch("subprocess.run", return_value=proc(out)):
            result = self.sm.service_status("Spooler")
        self.assertIn("is stopped", result)

    def test_service_status_not_found(self):
        with patch("subprocess.run", return_value=proc("1060: The specified service does not exist", 1060)):
            result = self.sm.service_status("NopeSvc")
        self.assertIn("No service named", result)

    def test_service_status_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertIn("Couldn't check", self.sm.service_status("Spooler"))

    def test_start_service_success(self):
        with patch("subprocess.run", return_value=proc("", 0)):
            self.assertIn("Started 'Spooler'", self.sm.start_service("Spooler"))

    def test_stop_service_success(self):
        with patch("subprocess.run", return_value=proc("", 0)):
            self.assertIn("Stopped 'Spooler'", self.sm.stop_service("Spooler"))

    def test_start_service_not_found(self):
        with patch("subprocess.run", return_value=proc("", 1060, "1060 service does not exist")):
            result = self.sm.start_service("NopeSvc")
        self.assertIn("No service named", result)

    def test_start_service_access_denied_message(self):
        with patch("subprocess.run", return_value=proc("", 5, "Access is denied.")):
            result = self.sm.start_service("Spooler")
        self.assertIn("administrator rights", result)

    def test_start_service_failed_5_code(self):
        with patch("subprocess.run", return_value=proc("[SC] StartService FAILED 5:", 5)):
            result = self.sm.start_service("Spooler")
        self.assertIn("administrator rights", result)

    def test_start_service_other_error(self):
        with patch("subprocess.run", return_value=proc("", 1, "some other error")):
            result = self.sm.start_service("Spooler")
        self.assertIn("Couldn't start 'Spooler'", result)

    def test_start_service_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="sc", timeout=20)):
            self.assertIn("Couldn't start", self.sm.start_service("Spooler"))

    def test_restart_service_success(self):
        with patch("subprocess.run", return_value=proc("", 0)):
            result = self.sm.restart_service("Spooler")
        self.assertIn("Stopped 'Spooler'", result)
        self.assertIn("Started 'Spooler'", result)

    def test_restart_service_stop_fails_short_circuits(self):
        with patch("subprocess.run", return_value=proc("", 5, "Access is denied.")):
            result = self.sm.restart_service("Spooler")
        self.assertIn("administrator rights", result)
        self.assertNotIn("Started", result)


class TopProcessesTests(unittest.TestCase):
    def setUp(self):
        self.sm = ServiceManager()

    def _fake_proc(self, name, pid, cpu, mem_bytes):
        p = Mock()
        p.cpu_percent.return_value = cpu
        p.memory_info.return_value = Mock(rss=mem_bytes)
        p.name.return_value = name
        p.pid = pid
        return p

    def test_top_processes_by_cpu(self):
        procs = [self._fake_proc("chrome.exe", 100, 40.0, 200 * 1024 * 1024),
                 self._fake_proc("idle.exe", 200, 1.0, 10 * 1024 * 1024)]
        with patch("skills.service_manager.psutil") as mock_psutil:
            mock_psutil.process_iter.return_value = procs
            mock_psutil.cpu_count.return_value = 1
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception
            with patch("time.sleep"):
                result = self.sm.top_processes(by="cpu", limit=5)
        self.assertIn("chrome.exe", result)
        self.assertTrue(result.index("chrome.exe") < result.index("idle.exe"))

    def test_top_processes_by_memory(self):
        procs = [self._fake_proc("chrome.exe", 100, 5.0, 20 * 1024 * 1024),
                 self._fake_proc("big.exe", 200, 1.0, 900 * 1024 * 1024)]
        with patch("skills.service_manager.psutil") as mock_psutil:
            mock_psutil.process_iter.return_value = procs
            mock_psutil.cpu_count.return_value = 2
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception
            with patch("time.sleep"):
                result = self.sm.top_processes(by="memory", limit=5)
        self.assertTrue(result.index("big.exe") < result.index("chrome.exe"))

    def test_top_processes_no_psutil(self):
        with patch("skills.service_manager.psutil", None):
            result = self.sm.top_processes()
        self.assertIn("isn't available", result)

    def test_top_processes_invalid_by_defaults_to_cpu(self):
        procs = [self._fake_proc("a.exe", 1, 10.0, 1024 * 1024)]
        with patch("skills.service_manager.psutil") as mock_psutil:
            mock_psutil.process_iter.return_value = procs
            mock_psutil.cpu_count.return_value = 1
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception
            with patch("time.sleep"):
                result = self.sm.top_processes(by="bogus")
        self.assertIn("a.exe", result)

    def test_top_processes_skips_dead_procs(self):
        import psutil as real_psutil
        good = self._fake_proc("ok.exe", 1, 5.0, 1024 * 1024)
        bad = Mock()
        bad.cpu_percent.side_effect = Exception("gone")
        with patch("skills.service_manager.psutil") as mock_psutil:
            mock_psutil.process_iter.return_value = [good, bad]
            mock_psutil.cpu_count.return_value = 1
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception

            def iter_side_effect(attrs=None):
                return [good, bad]
            mock_psutil.process_iter.side_effect = iter_side_effect
            with patch("time.sleep"):
                result = self.sm.top_processes()
        self.assertIn("ok.exe", result)

    def test_top_processes_no_rows(self):
        with patch("skills.service_manager.psutil") as mock_psutil:
            mock_psutil.process_iter.return_value = []
            mock_psutil.cpu_count.return_value = 1
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception
            with patch("time.sleep"):
                result = self.sm.top_processes()
        self.assertIn("Couldn't read the process list", result)


if __name__ == "__main__":
    unittest.main()
