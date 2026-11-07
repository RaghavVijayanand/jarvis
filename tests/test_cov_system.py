"""Offline coverage for system monitor/control, utility, weather and the info handler.

psutil, WMI and requests are mocked at the module boundary with payloads shaped
like the real libraries/APIs return, so nothing touches hardware or network.
"""
import json
import os
import socket
import tempfile
import unittest
from collections import namedtuple
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import psutil
import requests

import skills.system_control as sc_mod
import skills.system_monitor as sm_mod
import skills.weather as weather_mod
from core.tools import ToolRegistry
from handlers.info import InfoHandler
from skills.system_control import SystemControl
from skills.system_monitor import SystemMonitor
from skills.utility import UtilitySkill
from skills.weather import WeatherSkill

GB = 1024 ** 3

# ── psutil-shaped records ────────────────────────────────────────────────────
svmem = namedtuple("svmem", "total available percent used free")
sswap = namedtuple("sswap", "total used free percent sin sout")
sdiskusage = namedtuple("sdiskusage", "total used free percent")
sdiskpart = namedtuple("sdiskpart", "device mountpoint fstype opts")
scpufreq = namedtuple("scpufreq", "current min max")
sdiskio = namedtuple("sdiskio", "read_count write_count read_bytes write_bytes read_time write_time")
snetio = namedtuple("snetio", "bytes_sent bytes_recv packets_sent packets_recv errin errout dropin dropout")
sconn = namedtuple("sconn", "fd family type laddr raddr status pid")
snicaddr = namedtuple("snicaddr", "family address netmask broadcast ptp")
snicstats = namedtuple("snicstats", "isup duplex speed mtu flags")
sbattery = namedtuple("sbattery", "percent secsleft power_plugged")


class FakeProc:
    def __init__(self, pid, name, cpu=(0.0, 0.0), mem=1.0, kill_exc=None, cpu_exc=None):
        self.info = {"pid": pid, "name": name, "memory_percent": mem, "status": "running"}
        self._cpu = list(cpu)
        self._cpu_exc = cpu_exc
        self.kill = Mock(side_effect=kill_exc)

    def cpu_percent(self, interval=None):
        if self._cpu_exc:
            raise self._cpu_exc
        return self._cpu.pop(0) if self._cpu else 0.0


def fake_psutil(**overrides):
    """A psutil stand-in with realistic Windows-ish return values."""
    p = MagicMock()
    p.NoSuchProcess, p.AccessDenied, p.ZombieProcess = (psutil.NoSuchProcess, psutil.AccessDenied,
                                                        psutil.ZombieProcess)
    p.POWER_TIME_UNKNOWN, p.POWER_TIME_UNLIMITED = psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED
    p.CONN_NONE = psutil.CONN_NONE

    def cpu_percent(interval=None, percpu=False):
        return [30.0, 50.0, 10.0, 10.0] if percpu else 25.0

    p.cpu_percent.side_effect = cpu_percent
    p.cpu_count.return_value = 4
    p.cpu_freq.return_value = scpufreq(2893.0, 0.0, 2893.0)
    p.virtual_memory.return_value = svmem(16 * GB, 6 * GB, 62.5, 10 * GB, 6 * GB)
    p.swap_memory.return_value = sswap(2 * GB, 0, 2 * GB, 0.0, 0, 0)
    p.disk_usage.return_value = sdiskusage(500 * GB, 200 * GB, 300 * GB, 40.0)
    p.disk_partitions.return_value = [sdiskpart("C:\\", "C:\\", "NTFS", "rw,fixed")]
    p.disk_io_counters.return_value = sdiskio(1, 2, 3, 4, 5, 6)
    p.net_io_counters.return_value = snetio(10 * 1024 ** 2, 50 * 1024 ** 2, 1000, 2000, 0, 0, 0, 0)
    p.net_connections.return_value = [
        sconn(-1, socket.AF_INET, socket.SOCK_STREAM, ("10.0.0.5", 50000), ("1.2.3.4", 443), "ESTABLISHED", 10),
        sconn(-1, socket.AF_INET, socket.SOCK_DGRAM, ("0.0.0.0", 5353), (), psutil.CONN_NONE, 11),
    ]
    p.net_if_addrs.return_value = {
        "Wi-Fi": [snicaddr(psutil.AF_LINK, "AA-BB-CC-DD-EE-FF", None, None, None),
                  snicaddr(socket.AF_INET, "192.168.1.20", "255.255.255.0", None, None)],
        "vEthernet (WSL)": [snicaddr(socket.AF_INET, "172.20.0.1", "255.255.240.0", None, None)],
    }
    p.net_if_stats.return_value = {"Wi-Fi": snicstats(True, 2, 866, 1500, "")}
    p.boot_time.return_value = 1_700_000_000
    p.pids.return_value = list(range(150))
    p.process_iter.return_value = []
    p.sensors_battery.return_value = None
    for key, value in overrides.items():
        setattr(p, key, value)
    return p


class _Base(unittest.TestCase):
    def patch(self, *args, **kwargs):
        patcher = patch(*args, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value


# ── SystemMonitor ────────────────────────────────────────────────────────────
class SystemMonitorTests(_Base):
    def setUp(self):
        self.ps = fake_psutil()
        self.patch("skills.system_monitor.psutil", self.ps)
        self.patch("skills.system_monitor.time.sleep")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mon = SystemMonitor()
        self.mon.alerts_file = os.path.join(self.tmp.name, "alerts.json")
        self.mon.wmi_available = False

    def test_cpu_memory_info(self):
        self.assertEqual(self.mon.get_cpu_info(), {"usage": 25.0, "cores": 4, "frequency": 2893.0})
        self.ps.cpu_freq.return_value = None
        self.assertEqual(self.mon.get_cpu_info()["frequency"], 0)
        mem = self.mon.get_memory_info()
        self.assertAlmostEqual(mem["used_gb"], 10.0)
        self.assertEqual(mem["percentage"], 62.5)

    def test_cpu_memory_info_errors(self):
        self.ps.cpu_percent.side_effect = OSError("boom")
        self.assertIn("error", self.mon.get_cpu_info())
        self.ps.virtual_memory.side_effect = OSError("boom")
        self.assertEqual(self.mon.get_memory_info()["total_gb"], 0)

    def test_system_info_uses_system_drive(self):
        with patch.object(sm_mod.os, "name", "nt"), patch.dict(os.environ, {"SystemDrive": "D:"}):
            text = self.mon.get_system_info()
        self.ps.disk_usage.assert_called_with("D:\\")
        self.assertIn("Disk Usage: 40.0%", text)
        self.assertIn("Processes: 150", text)

    def test_system_info_disk_failure_and_total_failure(self):
        self.ps.disk_usage.side_effect = OSError("no drive")
        self.assertIn("Disk Usage: 0.0%", self.mon.get_system_info())
        self.ps.virtual_memory.side_effect = RuntimeError("x")
        self.assertTrue(self.mon.get_system_info().startswith("Error getting system info"))

    def test_top_processes_primes_cpu_and_skips_idle(self):
        idle = FakeProc(0, "System Idle Process", cpu=(0.0, 390.0))
        busy = FakeProc(100, "chrome.exe", cpu=(0.0, 200.0))
        quiet = FakeProc(101, None, cpu=(0.0, 4.0))
        gone = FakeProc(102, "x.exe", cpu_exc=psutil.NoSuchProcess(102))
        self.ps.process_iter.return_value = [idle, busy, quiet, gone]
        top = self.mon._get_top_processes()
        self.assertEqual([p["pid"] for p in top], [100, 101])
        self.assertEqual(top[0]["cpu_percent"], 50.0)  # 200% of one core / 4 cores
        self.assertEqual(top[1]["name"], "PID 101")

    def test_top_processes_failure_returns_empty(self):
        self.ps.process_iter.side_effect = RuntimeError("x")
        self.assertEqual(self.mon._get_top_processes(), [])

    def test_performance_metrics_single_cpu_sample_and_skips_cdrom(self):
        self.ps.disk_partitions.return_value = [
            sdiskpart("C:\\", "C:\\", "NTFS", "rw,fixed"),
            sdiskpart("E:\\", "E:\\", "UDF", "ro,cdrom"),
            sdiskpart("F:\\", "F:\\", "", "rw,removable"),
        ]
        self.ps.disk_usage.side_effect = lambda m: (_ for _ in ()).throw(OSError("not ready")) if m == "F:\\" \
            else sdiskusage(500 * GB, 200 * GB, 300 * GB, 40.0)
        metrics = self.mon.get_performance_metrics()
        self.assertEqual(metrics["cpu"]["usage_percent"], 25.0)
        self.assertEqual(self.ps.cpu_percent.call_count, 1)
        self.assertEqual(set(metrics["disk"]) - {"io"}, {"C:\\"})
        self.assertEqual(metrics["network"]["connections"], 2)

    def test_performance_metrics_denied_connections_and_empty_disk(self):
        self.ps.net_connections.side_effect = psutil.AccessDenied()
        self.ps.disk_usage.return_value = sdiskusage(0, 0, 0, 0)
        self.ps.cpu_percent.side_effect = lambda interval=None, percpu=False: [] if percpu else 12.0
        metrics = self.mon.get_performance_metrics()
        self.assertNotIn("connections", metrics["network"])
        self.assertEqual(metrics["disk"]["C:\\"]["percent"], 0.0)
        self.assertEqual(metrics["cpu"]["usage_percent"], 12.0)
        self.ps.virtual_memory.side_effect = RuntimeError("bad")
        self.assertIn("error", self.mon.get_performance_metrics())

    def test_health_check_good(self):
        self.ps.process_iter.return_value = [FakeProc(4321, "python.exe", cpu=(0.0, 8.0))]
        report = self.mon.check_system_health()
        self.assertIn("System health is GOOD", report)
        self.assertIn("python.exe (PID: 4321): 2.0% CPU", report)
        self.assertFalse(os.path.exists(self.mon.alerts_file))

    def test_health_check_alerts_and_saves(self):
        self.ps.cpu_percent.side_effect = lambda interval=None, percpu=False: [99.0] * 4 if percpu else 99.0
        self.ps.virtual_memory.return_value = svmem(16 * GB, GB, 94.0, 15 * GB, GB)
        self.ps.disk_usage.return_value = sdiskusage(100 * GB, 97 * GB, 3 * GB, 97.0)
        self.ps.net_connections.return_value = [self.ps.net_connections.return_value[0]] * 1001
        report = self.mon.check_system_health()
        for text in ("CRITICAL: CPU", "CRITICAL: Memory", "CRITICAL: Disk C:\\", "High number of network"):
            self.assertIn(text, report)
        with open(self.mon.alerts_file, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(len(saved), 1)

    def test_health_check_warnings(self):
        self.ps.cpu_percent.side_effect = lambda interval=None, percpu=False: [85.0] * 4 if percpu else 85.0
        self.ps.virtual_memory.return_value = svmem(16 * GB, 3 * GB, 85.0, 13 * GB, 3 * GB)
        self.ps.disk_usage.return_value = sdiskusage(100 * GB, 90 * GB, 10 * GB, 90.0)
        report = self.mon.check_system_health()
        self.assertIn("WARNING: CPU", report)
        self.assertIn("WARNING: Memory", report)
        self.assertIn("getting full", report)

    def test_health_check_metric_error(self):
        self.ps.virtual_memory.side_effect = RuntimeError("wmi down")
        self.assertIn("Error getting system metrics", self.mon.check_system_health())

    def test_health_check_with_temperature(self):
        self.mon.wmi_available = True
        with patch.object(self.mon, "_get_temperature_info", return_value="45.0°C"):
            self.assertIn("45.0°C", self.mon.check_system_health())

    def test_save_alerts_recovers_from_corrupt_file(self):
        with open(self.mon.alerts_file, "w") as f:
            f.write("{not json")
        self.mon._save_alerts(["x"])
        with open(self.mon.alerts_file) as f:
            self.assertEqual(json.load(f)[0]["alerts"], ["x"])
        with open(self.mon.alerts_file, "w") as f:
            json.dump({"a": 1}, f)
        self.mon._save_alerts(["y"])
        with open(self.mon.alerts_file) as f:
            self.assertEqual(len(json.load(f)), 1)
        self.mon.alerts_file = os.path.join(self.tmp.name, "missing", "dir", "a.json")
        with patch("builtins.print"):
            self.mon._save_alerts(["z"])  # unwritable: logs, never raises

    def test_temperature_reads_root_wmi_namespace(self):
        self.mon.wmi_available = True
        conn = Mock()
        conn.MSAcpi_ThermalZoneTemperature.return_value = [SimpleNamespace(CurrentTemperature=3182),
                                                           SimpleNamespace(CurrentTemperature=None)]
        with patch.object(self.mon, "_wmi", return_value=conn) as opener:
            self.assertEqual(self.mon._get_temperature_info(), "45.1°C")
        opener.assert_called_once_with(namespace="root\\wmi")
        with patch.object(self.mon, "_wmi", side_effect=RuntimeError("access denied")):
            self.assertIsNone(self.mon._get_temperature_info())
        self.mon.wmi_available = False
        self.assertIsNone(self.mon._get_temperature_info())

    def test_wmi_connection_per_thread(self):
        fake_wmi = Mock()
        with patch.object(sm_mod, "wmi", fake_wmi), patch.dict("sys.modules", {"pythoncom": Mock()}):
            self.mon._wmi()
            self.mon._wmi(namespace="root\\wmi")
        fake_wmi.WMI.assert_any_call()
        fake_wmi.WMI.assert_any_call(namespace="root\\wmi")

    def test_hardware_info(self):
        self.assertIn("WMI not available", self.mon.get_hardware_info())
        self.mon.wmi_available = True
        conn = Mock()
        conn.Win32_Processor.return_value = [SimpleNamespace(
            Name="Intel(R) Core(TM) i7-8650U", Manufacturer="GenuineIntel", Architecture=9, MaxClockSpeed=2112,
            NumberOfCores=4, NumberOfLogicalProcessors=8, SocketDesignation="U3E1")]
        conn.Win32_PhysicalMemory.return_value = [
            SimpleNamespace(Capacity="8589934592", Speed=2400, Manufacturer="Samsung", PartNumber="M471",
                            DeviceLocator="ChannelA-DIMM0"),
            SimpleNamespace(Capacity=None, Speed=None, Manufacturer=None, PartNumber=None, DeviceLocator="B")]
        conn.Win32_BaseBoard.return_value = [SimpleNamespace(Manufacturer="LENOVO", Product="20L8", Version="1",
                                                             SerialNumber="X")]
        conn.Win32_VideoController.return_value = [
            SimpleNamespace(Name="Intel UHD 620", AdapterRAM=1073741824, DriverVersion="27.20"),
            SimpleNamespace(Name=None, AdapterRAM=None, DriverVersion=None)]
        conn.Win32_DiskDrive.return_value = [
            SimpleNamespace(Size="512105932800", Model="SAMSUNG MZVLB512", InterfaceType="SCSI",
                            MediaType="Fixed hard disk media"),
            SimpleNamespace(Size=None, Model="Card reader", InterfaceType="USB", MediaType=None)]
        with patch.object(self.mon, "_wmi", return_value=conn):
            text = self.mon.get_hardware_info()
        self.assertIn("Total RAM: 8.0 GB", text)
        self.assertIn("VRAM: 1.0 GB", text)
        self.assertIn("SAMSUNG MZVLB512", text)
        self.assertNotIn("Card reader", text)
        with patch.object(self.mon, "_wmi", side_effect=RuntimeError("marshalled")):
            self.assertIn("Error getting hardware information", self.mon.get_hardware_info())

    def test_format_helpers(self):
        from datetime import timedelta
        self.assertEqual(self.mon._format_bytes(512), "512.0 B")
        self.assertEqual(self.mon._format_bytes(1024 ** 5), "1.0 PB")
        self.assertEqual(self.mon._format_timedelta(timedelta(days=1, hours=2, minutes=1)),
                         "1 day, 2 hours, 1 minute")
        self.assertEqual(self.mon._format_timedelta(timedelta(seconds=20)), "Less than a minute")

    def test_network_analysis(self):
        self.ps.net_if_stats.return_value = {"Wi-Fi": snicstats(True, 2, 866, 1500, ""),
                                             "Ethernet": snicstats(False, 0, 0, 1500, "")}
        self.ps.net_io_counters.return_value = snetio(1, 2, 3, 4, 5, 6, 7, 8)
        text = self.mon.get_network_analysis()
        self.assertIn("TCP: 1", text)
        self.assertIn("UDP: 1", text)
        self.assertIn("ESTABLISHED: 1", text)
        self.assertNotIn("NONE", text)
        self.assertIn("Speed: 866 Mbps", text)
        self.assertIn("Speed: Unknown", text)
        self.assertIn("Errors In: 5", text)
        self.assertIn("Dropped In: 7", text)

    def test_network_analysis_access_denied_and_failure(self):
        self.ps.net_connections.side_effect = psutil.AccessDenied()
        self.assertIn("access denied", self.mon.get_network_analysis())
        self.ps.net_if_stats.side_effect = RuntimeError("x")
        self.assertIn("Error analyzing network", self.mon.get_network_analysis())

    def test_init_without_wmi(self):
        with patch.object(sm_mod, "wmi", Mock(WMI=Mock(side_effect=RuntimeError("no com")))):
            self.assertFalse(SystemMonitor().wmi_available)
        with patch.object(sm_mod, "wmi", Mock()):
            self.assertTrue(SystemMonitor().wmi_available)


# ── SystemControl ────────────────────────────────────────────────────────────
class SystemControlTests(_Base):
    def setUp(self):
        self.ps = fake_psutil()
        self.patch("skills.system_control.psutil", self.ps)
        self.patch("skills.system_control.time.sleep")
        self.ctl = SystemControl()

    def test_system_status(self):
        with patch.object(sc_mod.socket, "gethostname", return_value="DESKTOP-1"), \
             patch.object(sc_mod.socket, "gethostbyname", return_value="192.168.1.20"):
            text = self.ctl.get_system_status()
        self.assertIn("Hostname: DESKTOP-1", text)
        self.assertIn("200 GB of 500 GB, 300 GB free", text)

    def test_system_status_offline_hostname(self):
        with patch.object(sc_mod.socket, "gethostbyname", side_effect=socket.gaierror("no")):
            self.assertIn("IP Address: unavailable", self.ctl.get_system_status())
        self.ps.virtual_memory.side_effect = RuntimeError("x")
        self.assertIn("Error getting system status", self.ctl.get_system_status())

    def test_system_drive(self):
        with patch.object(sc_mod.os, "name", "nt"), patch.dict(os.environ, {"SystemDrive": "E:"}):
            self.assertEqual(SystemControl._system_drive(), "E:\\")
        with patch.object(sc_mod.os, "name", "posix"):
            self.assertEqual(SystemControl._system_drive(), "/")

    def test_running_processes(self):
        self.ps.process_iter.return_value = [
            FakeProc(0, "System Idle Process", cpu=(0.0, 380.0)),
            FakeProc(10, "chrome.exe", cpu=(0.0, 40.0), mem=None),
            FakeProc(11, None, cpu=(0.0, 80.0)),
            FakeProc(12, "gone.exe", cpu_exc=psutil.AccessDenied(12)),
        ]
        text = self.ctl.get_running_processes()
        lines = text.splitlines()[3:]
        self.assertTrue(lines[0].startswith("11\t\tPID 11"))
        self.assertIn("chrome.exe", lines[1])
        self.assertIn("10.0", lines[1])
        self.assertNotIn("Idle", text)
        self.ps.process_iter.side_effect = RuntimeError("x")
        self.assertIn("Error getting processes", self.ctl.get_running_processes())

    def test_disk_usage_windows_skips_unready_drives(self):
        self.ctl.system = "Windows"
        self.ps.disk_partitions.return_value = [
            sdiskpart("C:\\", "C:\\", "NTFS", "rw,fixed"), sdiskpart("D:\\", "D:\\", "", "cdrom"),
            sdiskpart("G:\\", "G:\\", "NTFS", "rw,fixed"), sdiskpart("Z:\\", "Z:\\", "NTFS", "rw,remote")]

        def usage(path):
            if path == "D:\\":
                raise OSError(21, "The device is not ready")
            if path == "G:\\":
                raise PermissionError("denied")
            if path == "Z:\\":
                return sdiskusage(0, 0, 0, 0)
            return sdiskusage(500 * GB, 200 * GB, 300 * GB, 40.0)

        self.ps.disk_usage.side_effect = usage
        text = self.ctl.get_disk_usage()
        self.assertIn("C:\\\t500 GB", text)
        self.assertIn("G:\\\t\tAccess Denied", text)
        self.assertNotIn("D:\\", text)
        self.assertNotIn("Z:\\", text)

    def test_disk_usage_posix_and_failure(self):
        self.ctl.system = "Linux"
        self.ps.disk_partitions.return_value = [sdiskpart("/dev/sda1", "/", "ext4", "rw")]
        self.assertIn("/dev/sda1\t500 GB", self.ctl.get_disk_usage())
        self.ps.disk_partitions.side_effect = RuntimeError("x")
        self.assertIn("Error getting disk usage", self.ctl.get_disk_usage())

    def test_cpu_and_memory_usage(self):
        self.assertEqual(self.ctl.get_cpu_usage(), "CPU Usage: 25.0%")
        self.assertEqual(self.ctl.get_memory_usage(), "Memory: 62.5% used (10 GB / 16 GB)")
        self.ps.cpu_percent.side_effect = RuntimeError("x")
        self.ps.virtual_memory.side_effect = RuntimeError("x")
        self.assertIn("Error", self.ctl.get_cpu_usage())
        self.assertIn("Error", self.ctl.get_memory_usage())

    def test_kill_process(self):
        target = FakeProc(900, "Notepad.exe")
        other = FakeProc(901, "notepad++.exe")
        self.ps.process_iter.return_value = [target, other]
        self.assertIn("Killed 1", self.ctl.kill_process("notepad"))
        target.kill.assert_called_once_with()
        other.kill.assert_not_called()
        self.assertIn("exact executable name", self.ctl.kill_process("../x"))
        self.ps.process_iter.side_effect = RuntimeError("x")
        self.assertIn("Error killing process", self.ctl.kill_process("notepad"))

    def test_network_info_handles_missing_stats(self):
        text = self.ctl.get_network_info()
        self.assertIn("Wi-Fi\t\t192.168.1.20\t\tUp", text)
        self.assertIn("172.20.0.1\t\tUnknown", text)
        self.assertNotIn("AA-BB", text)
        self.ps.net_if_addrs.side_effect = RuntimeError("x")
        self.assertIn("Error getting network info", self.ctl.get_network_info())

    def test_battery(self):
        self.assertIn("No battery found", self.ctl.get_battery_info())
        self.ps.sensors_battery.return_value = sbattery(57.3, 5400, False)
        text = self.ctl.get_battery_info()
        self.assertIn("Charge: 57%", text)
        self.assertIn("Discharging", text)
        self.assertIn("Time remaining: 1h 30m", text)
        self.ps.sensors_battery.return_value = sbattery(80, psutil.POWER_TIME_UNLIMITED, True)
        text = self.ctl.get_battery_info()
        self.assertIn("Charging", text)
        self.assertNotIn("remaining", text)
        self.ps.sensors_battery.return_value = sbattery(100, psutil.POWER_TIME_UNLIMITED, True)
        self.assertIn("fully charged", self.ctl.get_battery_info())
        self.ps.sensors_battery.return_value = sbattery(40, psutil.POWER_TIME_UNKNOWN, None)
        text = self.ctl.get_battery_info()
        self.assertIn("Status: Unknown", text)
        self.assertNotIn("remaining", text)
        self.ps.sensors_battery.side_effect = RuntimeError("acpi")
        self.assertIn("Error getting battery info", self.ctl.get_battery_info())

    def test_recycle_bin_and_shell(self):
        self.ctl.system = "Linux"
        self.assertIn("only supported on Windows", self.ctl.empty_recycle_bin())
        self.ctl.system = "Windows"
        fake = Mock()
        with patch.dict("sys.modules", {"winshell": fake}):
            self.assertIn("emptied", self.ctl.empty_recycle_bin())
        fake.recycle_bin.return_value.empty.assert_called_once_with(confirm=False, show_progress=False,
                                                                     sound=False)
        fake.recycle_bin.side_effect = OSError("busy")
        with patch.dict("sys.modules", {"winshell": fake}):
            self.assertIn("Error emptying", self.ctl.empty_recycle_bin())
        with patch.dict("sys.modules", {"winshell": None}):
            self.assertIn("requires winshell", self.ctl.empty_recycle_bin())
        self.assertIn("disabled", self.ctl.run_command("del /s C:\\"))


# ── Utility ──────────────────────────────────────────────────────────────────
class UtilityTests(unittest.TestCase):
    def setUp(self):
        self.u = UtilitySkill()

    def result(self, text):
        return self.u.calculate(text).rsplit("= ", 1)[-1]

    def test_phrases(self):
        cases = {"what is 7 times 8?": "56", "5x3": "15", "2 x 3": "6", "what is 2 to the power of 10": "1024",
                 "2 raised to 8": "256", "10 mod 3": "1", "what is 3 over 4": "0.75", "0.1+0.2": "0.3",
                 "1,000 + 1": "1001", "round(2.555, 2)": "2.56", "15% of 200": "30", "5 squared": "25",
                 "3 cubed": "27", "what is the square root of 144": "12", "cube root of 27": "3",
                 "10 minus 4 plus 1": "7", "12 divided by 4": "3", "log(100)": "2", "pi*2": "6.2831853072",
                 "-2**2": "-4", "2**-1": "0.5", "abs(-3)": "3", "7//2": "3"}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.result(text), expected)

    def test_rejects_code_and_resource_bombs(self):
        for text in ('open("/etc/passwd").read()', '__import__("os").system("x")', "().__class__",
                     '"a"*10**10', "[1]*10**9", "x = 5", "lambda: 1", "True+1", "(-8)**0.5", "sqrt(-1)",
                     "round(1, ndigits=2)", "hello there", "1" * 300):
            with self.subTest(text=text):
                self.assertIn("Could not calculate", self.u.calculate(text))
        for text in ("9**9**9**9", "(9**9999)**9999", "10**12000", "1e308*10", "2.0**5000", "10**20000"):
            with self.subTest(text=text):
                self.assertEqual(self.u.calculate(text), "Error: The result is too large to calculate.")
        self.assertEqual(self.u.calculate("10 divided by 0"), "Error: Division by zero")

    def test_password_uses_secrets(self):
        with patch("skills.utility.secrets.choice", return_value="Q") as choice:
            self.assertEqual(self.u.generate_password(10), "Generated password: " + "Q" * 10)
        self.assertEqual(choice.call_count, 10)
        self.assertEqual(len(self.u.generate_password(2).split(": ")[1]), 8)
        self.assertEqual(len(self.u.generate_password(500).split(": ")[1]), 50)
        pw = self.u.generate_password(40, include_symbols=False).split(": ")[1]
        self.assertTrue(pw.isalnum())
        self.assertIn("Error", self.u.generate_password("abc"))

    def test_random_helpers(self):
        self.assertIn(self.u.tell_joke(), self.u.jokes)
        self.assertRegex(self.u.flip_coin(), r"Coin flip result: (Heads|Tails)")
        self.assertRegex(self.u.roll_dice(20), r"Rolled a 20-sided die: \d+")
        self.assertRegex(self.u.roll_dice(1, 3), r"Rolled 3 6-sided dice: .* \(Total: \d+\)")
        self.assertRegex(self.u.roll_dice(6, 99), r"Rolled a 6-sided die")
        self.assertIn("Error", self.u.roll_dice("x"))
        self.assertIn("between 5 and 10", self.u.get_random_number(10, 5))
        self.assertIn("Error", self.u.get_random_number("a", 2))


# ── Weather ──────────────────────────────────────────────────────────────────
GEOCODE_NY = {"results": [{"id": 5128581, "name": "New York", "latitude": 40.71427, "longitude": -74.00597,
                           "elevation": 10.0, "feature_code": "PPL", "country_code": "US",
                           "timezone": "America/New_York", "population": 8175133,
                           "country": "United States", "admin1": "New York"}],
              "generationtime_ms": 0.9}
GEOCODE_PUNE = {"results": [
    {"name": "Pune", "latitude": 7.1, "longitude": 125.3, "country_code": "PH", "country": "Philippines",
     "admin1": "Davao"},
    {"name": "Pune", "latitude": 18.51957, "longitude": 73.85535, "country_code": "IN", "country": "India",
     "admin1": "Maharashtra"}]}
FORECAST = {"latitude": 40.71, "longitude": -74.0, "utc_offset_seconds": -14400, "timezone": "America/New_York",
            "current_units": {"temperature_2m": "°C"},
            "current": {"time": "2026-09-23T08:15", "interval": 900, "temperature_2m": 18.4,
                        "apparent_temperature": 17.9, "relative_humidity_2m": 72, "weather_code": 3,
                        "wind_speed_10m": 11.2},
            "daily_units": {"temperature_2m_max": "°C"},
            "daily": {"time": ["2026-09-23", "2026-09-24"], "temperature_2m_max": [22.1, 24.0],
                      "temperature_2m_min": [15.3, 16.8], "precipitation_probability_max": [20, 65],
                      "weather_code": [3, 61]}}
FORECAST_ERROR = {"error": True, "reason": "Cannot initialize WeatherVariable from invalid String value"}
WTTR = {"current_condition": [{"FeelsLikeC": "17", "humidity": "72", "temp_C": "18", "temp_F": "64",
                               "weatherCode": "116", "weatherDesc": [{"value": "Partly cloudy"}],
                               "winddir16Point": "SW", "windspeedKmph": "11"}],
        "nearest_area": [{"areaName": [{"value": "New York"}], "country": [{"value": "United States of America"}],
                          "region": [{"value": "New York"}]}],
        "request": [{"query": "Lat 40.71 and Lon -74.01", "type": "LatLon"}], "weather": []}


class FakeResponse:
    def __init__(self, payload=None, status=200, bad_json=False):
        self.status_code, self._payload, self._bad = status, payload, bad_json

    def json(self):
        if self._bad:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")


class WeatherTests(_Base):
    def setUp(self):
        self.w = WeatherSkill()
        self.calls = []
        self.routes = {}
        self.get = self.patch("skills.weather.requests.get", side_effect=self.route)
        self.patch("core.config.get_location_preference", return_value=None)

    def route(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, timeout))
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                if isinstance(response, Exception):
                    raise response
                return response
        raise requests.ConnectionError("unrouted " + url)

    def test_city_parsing(self):
        cases = {"weather in New York tomorrow": "New York", "weather in New York next week": "New York",
                 "weather in Paris on Friday": "Paris", "how is the weather in San Francisco right now":
                 "San Francisco", "weather in Pune, India": "Pune, India", "weather for tomorrow": "",
                 "weather at the moment": "", "London weather tomorrow": "London", "weather in NYC": "NYC",
                 "what is the forecast for the weekend": "", "weather in Paris for tomorrow": "Paris",
                 "weather in London later": "London", "": "", None: ""}
        for query, city in cases.items():
            with self.subTest(query=query):
                self.assertEqual(self.w._extract_city_from_query(query), city)

    def test_open_meteo_happy_path(self):
        self.routes = {"https://geocoding-api.open-meteo.com": FakeResponse(GEOCODE_NY),
                       "https://api.open-meteo.com": FakeResponse(FORECAST)}
        text = self.w.get_weather("weather in New York tomorrow")
        self.assertIn("Weather in New York, New York, United States: overcast, 18.4°C (feels like 17.9°C).", text)
        self.assertIn("Today: 15.3–22.1°C, 20% chance of rain.", text)
        self.assertIn("Tomorrow: light rain, 16.8–24.0°C.", text)
        geo_url, geo_params, _ = self.calls[0]
        self.assertEqual(geo_params["name"], "New York")
        fc_params = self.calls[1][1]
        self.assertEqual((fc_params["latitude"], fc_params["longitude"]), (40.71427, -74.00597))
        self.assertEqual(fc_params["timezone"], "auto")
        self.assertTrue(all(timeout for _, _, timeout in self.calls))

    def test_open_meteo_country_qualifier_picks_right_place(self):
        self.routes = {"https://geocoding-api.open-meteo.com": FakeResponse(GEOCODE_PUNE),
                       "https://api.open-meteo.com": FakeResponse(FORECAST)}
        text = self.w.get_weather("weather in Pune, India")
        self.assertIn("Pune, Maharashtra, India", text)
        self.assertEqual(self.calls[0][1]["name"], "Pune")
        self.assertEqual(self.calls[1][1]["latitude"], 18.51957)
        self.assertEqual(WeatherSkill._pick_place(GEOCODE_PUNE["results"], "Atlantis")["country"], "Philippines")

    def test_open_meteo_partial_daily(self):
        data = json.loads(json.dumps(FORECAST))
        data["daily"] = {"temperature_2m_max": [20.0], "temperature_2m_min": [10.0],
                         "precipitation_probability_max": [None], "weather_code": [0]}
        self.routes = {"https://geocoding-api.open-meteo.com": FakeResponse(GEOCODE_NY),
                       "https://api.open-meteo.com": FakeResponse(data)}
        text = self.w._get_weather_open_meteo("New York")
        self.assertIn("Today: 10.0–20.0°C.", text)
        self.assertNotIn("None", text)
        self.assertNotIn("Tomorrow", text)

    def test_open_meteo_error_payload_falls_back_to_wttr(self):
        self.routes = {"https://geocoding-api.open-meteo.com": FakeResponse(GEOCODE_NY),
                       "https://api.open-meteo.com": FakeResponse(FORECAST_ERROR, status=400),
                       "https://wttr.in/": FakeResponse(WTTR)}
        text = self.w.get_weather("weather in New York")
        self.assertIn("Weather for New York, United States of America", text)
        self.assertIn("18°C (64°F)", text)
        self.assertNotIn("None", text)
        self.assertEqual(self.calls[-1][0], "https://wttr.in/New%20York?format=j1")

    def test_open_meteo_200_without_current_is_not_reported(self):
        self.routes = {"https://geocoding-api.open-meteo.com": FakeResponse(GEOCODE_NY),
                       "https://api.open-meteo.com": FakeResponse({"daily": {}})}
        self.assertIsNone(self.w._get_weather_open_meteo("New York"))

    def test_unknown_city_and_bad_json(self):
        self.routes = {"https://geocoding-api.open-meteo.com": FakeResponse({"generationtime_ms": 0.3}),
                       "https://wttr.in/": FakeResponse(None, bad_json=True)}
        # No such place: say so, never report whatever location wttr.in guesses instead.
        self.assertIn("couldn't find a place called 'Zzyzxq'", self.w.get_weather("weather in zzyzxq"))
        self.assertFalse(any(url.startswith("https://wttr.in/") for url, *_ in self.calls))
        self.routes = {"https://geocoding-api.open-meteo.com": FakeResponse(None, bad_json=True),
                       "https://wttr.in/": FakeResponse(WTTR, status=503)}
        self.assertIn("unavailable", self.w.get_weather("weather in Oslo"))
        self.routes = {"https://wttr.in/": FakeResponse({"current_condition": []})}
        self.assertIn("unavailable", self.w.get_weather("weather in Oslo"))

    def test_network_down(self):
        self.routes = {}
        self.assertIn("Weather information unavailable for London", self.w.get_weather("weather in London"))

    def test_auto_location_via_ip(self):
        self.routes = {"http://ip-api.com/json/": FakeResponse({"status": "success", "country": "India",
                                                                "city": "Pune", "query": "1.2.3.4"}),
                       "https://geocoding-api.open-meteo.com": FakeResponse(GEOCODE_PUNE),
                       "https://api.open-meteo.com": FakeResponse(FORECAST)}
        self.assertIn("Pune", self.w.get_weather("what's the weather like"))
        self.assertEqual(self.w.location_cache, "Pune, India")

    def test_auto_location_failures(self):
        self.routes = {"http://ip-api.com/json/": FakeResponse({"status": "fail", "message": "reserved range"})}
        self.assertIn("couldn't determine your location", self.w.get_weather("weather"))
        self.assertIsNone(self.w.location_cache)
        with patch("core.config.get_location_preference", return_value="Lyon, France"):
            self.assertEqual(self.w._get_auto_location(), "Lyon, France")     # qualifier kept
        with patch("core.config.get_location_preference", side_effect=RuntimeError("cfg")):
            self.routes = {}
            self.assertEqual(self.w._get_auto_location(), "")

    def test_unexpected_error_is_friendly(self):
        with patch.object(self.w, "_extract_city_from_query", side_effect=RuntimeError("boom")):
            self.assertIn("Unable to fetch weather data", self.w.get_weather("weather in X"))
        with patch.object(self.w, "_get_weather_open_meteo", side_effect=RuntimeError("x")), \
             patch.object(self.w, "_get_weather_wttr", side_effect=RuntimeError("y")):
            self.assertIn("unavailable", self.w._get_weather_from_web("Oslo"))


# ── InfoHandler ──────────────────────────────────────────────────────────────
class InfoHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        self.app.utility_skill = UtilitySkill()
        self.h = InfoHandler(self.app)

    def test_time_and_date(self):
        self.assertTrue(self.h.handle("what time is it", "TIME").startswith("It's "))
        self.assertTrue(self.h.handle("what's the date today", "TIME").startswith("Today is "))

    def test_math(self):
        self.assertEqual(self.h.handle("what is 6 times 7", "MATH"), "6 times 7 = 42")
        self.assertIsNone(self.h.handle("convert 5 miles to km", "MATH"))

    def test_weather_and_search(self):
        self.app.weather_skill.get_weather.return_value = "Sunny"
        self.assertEqual(self.h.handle("weather in Oslo", "WEATHER"), "Sunny")
        self.h.handle("latest news headlines", "SEARCH")
        self.app.web_skill.get_news_headlines.assert_called_once_with()
        self.h.handle("search wikipedia for alan turing", "SEARCH")
        self.app.web_skill.search_wikipedia.assert_called_once_with("alan turing")
        self.h.handle("search the web for python 3.14 release", "SEARCH")
        self.assertEqual(self.app.web_skill.search_web.call_args.args[0], "python 3.14 release")

    def test_system_routing(self):
        mon, ctl = self.app.system_monitor, self.app.system_control
        routes = {"battery level": ctl.get_battery_info, "what's my ip address": ctl.get_network_info,
                  "show my ip": ctl.get_network_info, "network status": mon.get_network_analysis,
                  "list processes": ctl.get_running_processes, "disk space": ctl.get_disk_usage,
                  "system health": mon.check_system_health, "hardware details": mon.get_hardware_info,
                  "system status": mon.get_system_info}
        for text, fn in routes.items():
            with self.subTest(text=text):
                fn.return_value = text.upper()
                self.assertEqual(self.h.handle(text, "SYSTEM"), text.upper())
        mon.get_cpu_info.return_value = {"usage": 12.5, "cores": 8}
        self.assertEqual(self.h.handle("cpu usage", "SYSTEM"), "CPU usage is 12.5% across 8 cores.")
        mon.get_memory_info.return_value = {"used_gb": 6.04, "total_gb": 16.0, "percentage": 37.8}
        self.assertEqual(self.h.handle("how much ram", "SYSTEM"), "Memory: 6.0 GB of 16.0 GB used (37.8%).")

    def test_system_routing_without_monitor(self):
        self.app.system_monitor = None
        ctl = self.app.system_control
        ctl.get_cpu_usage.return_value = "CPU Usage: 3.0%"
        ctl.get_memory_usage.return_value = "Memory: 1%"
        ctl.get_network_info.return_value = "NET"
        ctl.get_system_status.return_value = "STATUS"
        self.assertEqual(self.h.handle("cpu", "SYSTEM"), "CPU Usage: 3.0%")
        self.assertEqual(self.h.handle("memory", "SYSTEM"), "Memory: 1%")
        self.assertEqual(self.h.handle("wifi", "SYSTEM"), "NET")
        self.assertEqual(self.h.handle("status report", "SYSTEM"), "STATUS")
        self.assertEqual(self.h.handle("health", "SYSTEM"), "STATUS")

    def test_utility_routing(self):
        u = self.app.utility_skill = Mock()
        self.h.handle("tell me a joke", "UTILITY")
        u.tell_joke.assert_called_once_with()
        self.h.handle("flip a coin", "UTILITY")
        u.flip_coin.assert_called_once_with()
        self.h.handle("roll 2d20", "UTILITY")
        u.roll_dice.assert_called_with(sides=20, count=2)
        self.h.handle("roll two dice", "UTILITY")
        u.roll_dice.assert_called_with(sides=6, count=2)
        self.h.handle("random number between 5 and 50", "UTILITY")
        u.get_random_number.assert_called_with(5, 50)
        self.h.handle("random number", "UTILITY")
        u.get_random_number.assert_called_with()
        self.h.handle("generate a 24 character password", "UTILITY")
        u.generate_password.assert_called_with(length=24)
        self.h.handle("make me a password", "UTILITY")
        u.generate_password.assert_called_with(length=16)
        self.assertIsNone(self.h.handle("something else", "UTILITY"))

    def test_tools(self):
        reg = ToolRegistry()
        self.app.weather_skill.get_weather.return_value = "Rainy"
        self.app.system_control.get_battery_info.return_value = "Charge: 50%"
        self.h.register_tools(reg)
        self.assertEqual(reg.execute("get_weather", {"location": "London"}), "Rainy")
        self.app.weather_skill.get_weather.assert_called_with("weather in London")
        self.assertIn("missing required", reg.execute("get_weather", {}))
        self.assertEqual(reg.execute("calculate", {"expression": "2+2"}), "2+2 = 4")
        self.assertEqual(reg.execute("get_battery", {}), "Charge: 50%")
        self.assertTrue(reg.execute("get_time", {}).startswith("It's "))
        reg.execute("web_search", {"query": "x"})
        self.app.web_skill.search_web.assert_called_with("x", llm_brain=None)
        self.app.system_monitor.get_system_info.return_value = "SYS"
        self.assertEqual(reg.execute("get_system_status", {}), "SYS")

    def test_tools_without_monitor_or_weather(self):
        self.app.system_monitor = None
        self.app.weather_skill = None
        self.app.system_control.get_system_status.return_value = "CTL"
        reg = ToolRegistry()
        self.h.register_tools(reg)
        self.assertNotIn("get_weather", reg)
        self.assertEqual(reg.execute("get_system_status", {}), "CTL")


if __name__ == "__main__":
    unittest.main()
