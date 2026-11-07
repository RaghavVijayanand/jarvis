import os
import psutil
import subprocess
import platform
import socket
import time
from datetime import datetime
import json
import ctypes
from pathlib import Path


class SystemControl:
    @staticmethod
    def _system_drive():
        """Root of the Windows system drive (not always C:), or '/' elsewhere."""
        if os.name == 'nt':
            return os.environ.get('SystemDrive', 'C:').rstrip('\\') + '\\'
        return '/'

    def __init__(self, app_control=None):
        self.system = platform.system()
        self.app_control = app_control
        
    def get_system_status(self):
        """Get comprehensive system status"""
        try:
            # CPU and Memory info
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(self._system_drive())

            # Network info (hostname resolution fails offline / on some VPNs)
            hostname = socket.gethostname()
            try:
                ip_address = socket.gethostbyname(hostname)
            except OSError:
                ip_address = "unavailable"
            
            # System info
            system_info = platform.uname()
            
            status = f"""
System Status Report:
===================
Hostname: {hostname}
IP Address: {ip_address}
OS: {system_info.system} {system_info.release}
Architecture: {system_info.machine}
Processor: {system_info.processor}

Performance:
CPU Usage: {cpu_percent}%
Memory: {memory.percent}% used ({memory.used // (1024**3)} GB / {memory.total // (1024**3)} GB)
Disk: {disk.percent}% used ({disk.used // (1024**3)} GB of {disk.total // (1024**3)} GB, {disk.free // (1024**3)} GB free)

Boot Time: {datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S')}
            """
            return status.strip()
        except Exception as e:
            return f"Error getting system status: {e}"
    
    def get_running_processes(self, limit=10):
        """Get top running processes"""
        try:
            # cpu_percent() is 0.0 on the first call for every process, so
            # prime all of them, wait, then take the real reading.
            procs = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
                try:
                    if proc.info.get('pid') == 0:  # Windows "System Idle Process"
                        continue
                    proc.cpu_percent(None)
                    procs.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            time.sleep(0.5)
            cores = psutil.cpu_count() or 1
            processes = []
            for proc in procs:
                try:
                    info = dict(proc.info)
                    info['cpu_percent'] = (proc.cpu_percent(None) or 0.0) / cores
                    processes.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass

            # Sort by CPU usage
            processes.sort(key=lambda x: x['cpu_percent'] or 0, reverse=True)
            
            result = "Top Running Processes:\n"
            result += "PID\t\tName\t\t\tCPU%\tMemory%\n"
            result += "-" * 60 + "\n"
            
            for proc in processes[:limit]:
                pid = proc['pid']
                name = (proc.get('name') or f"PID {pid}")[:20]
                cpu = proc['cpu_percent'] or 0
                mem = proc['memory_percent'] or 0
                result += f"{pid}\t\t{name:<20}\t{cpu:.1f}\t{mem:.1f}\n"
            
            return result
        except Exception as e:
            return f"Error getting processes: {e}"
    
    def get_disk_usage(self):
        """Get disk usage for all drives"""
        try:
            result = "Disk Usage Information:\n"
            result += "Drive\t\tTotal\t\tUsed\t\tFree\t\tUsage%\n"
            result += "-" * 70 + "\n"
            
            # disk_partitions() lists mounted volumes on every OS (on Windows
            # the mountpoint is e.g. "D:\\"). Empty card readers / DVD drives
            # raise OSError from disk_usage and are skipped rather than
            # aborting the whole report.
            for partition in psutil.disk_partitions():
                label = partition.mountpoint if self.system == "Windows" else partition.device
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                except PermissionError:
                    result += f"{label}\t\tAccess Denied\n"
                    continue
                except OSError:
                    continue
                if not usage.total:
                    continue
                total_gb = usage.total // (1024**3)
                used_gb = usage.used // (1024**3)
                free_gb = usage.free // (1024**3)
                percent = (usage.used / usage.total) * 100
                result += f"{label}\t{total_gb} GB\t\t{used_gb} GB\t\t{free_gb} GB\t\t{percent:.1f}%\n"
            
            return result
        except Exception as e:
            return f"Error getting disk usage: {e}"

    def get_cpu_usage(self):
        """Get only current CPU usage percentage"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            return f"CPU Usage: {cpu_percent:.1f}%"
        except Exception as e:
            return f"Error getting CPU usage: {e}"

    def get_memory_usage(self):
        """Get only current memory usage summary"""
        try:
            memory = psutil.virtual_memory()
            used_gb = memory.used // (1024**3)
            total_gb = memory.total // (1024**3)
            return f"Memory: {memory.percent:.1f}% used ({used_gb} GB / {total_gb} GB)"
        except Exception as e:
            return f"Error getting memory usage: {e}"
    
    def kill_process(self, process_name):
        """Kill exact executable-name matches, never substrings or blank input."""
        if not isinstance(process_name, str) or not process_name.strip():
            return "Please specify an exact executable name."
        requested = process_name.strip().casefold()
        if any(char in requested for char in ('/', '\\', '*', '?', '\x00')):
            return "Please specify an exact executable name, not a path or wildcard."
        # Windows callers commonly omit .exe. Do not strip other extensions.
        names = {requested}
        if not requested.endswith('.exe'):
            names.add(requested + '.exe')
        try:
            killed_count = 0
            denied_count = 0
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    name = (proc.info.get('name') or '').casefold()
                    if name not in names:
                        continue
                    # Never terminate this JARVIS process or Windows system PIDs.
                    if proc.info['pid'] in (0, 4, os.getpid()):
                        denied_count += 1
                        continue
                    proc.kill()
                    killed_count += 1
                except psutil.NoSuchProcess:
                    continue
                except psutil.AccessDenied:
                    denied_count += 1
            result = (f"Killed {killed_count} process(es) named '{process_name}'"
                      if killed_count else f"No processes killed for exact name '{process_name}'")
            if denied_count:
                result += f"; {denied_count} protected or access-denied process(es) skipped"
            return result
        except Exception as e:
            return f"Error killing process: {e}"
    
    def get_network_info(self):
        """Get network interface information"""
        try:
            result = "Network Interfaces:\n"
            result += "Interface\t\tIP Address\t\tStatus\n"
            result += "-" * 50 + "\n"
            
            interfaces = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            
            for interface_name, interface_addresses in interfaces.items():
                for address in interface_addresses:
                    if address.family == socket.AF_INET:  # IPv4
                        ip = address.address
                        st = stats.get(interface_name)
                        status = "Unknown" if st is None else ("Up" if st.isup else "Down")
                        result += f"{interface_name[:15]}\t\t{ip}\t\t{status}\n"
                        break
            
            return result
        except Exception as e:
            return f"Error getting network info: {e}"
    
    def empty_recycle_bin(self):
        """Empty the recycle bin (Windows only)"""
        try:
            if self.system != "Windows":
                return "Recycle bin control only supported on Windows"
            
            import winshell
            winshell.recycle_bin().empty(confirm=False, show_progress=False, sound=False)
            return "Recycle bin emptied successfully"
            
        except ImportError:
            return "Recycle bin control requires winshell library: pip install winshell"
        except Exception as e:
            return f"Error emptying recycle bin: {e}"
    
    def get_battery_info(self):
        """Get battery information for laptops"""
        try:
            battery = psutil.sensors_battery()
            if battery is None:
                return "No battery found (desktop computer or no battery sensor)"
            
            percent = battery.percent
            plugged = battery.power_plugged
            time_left = battery.secsleft
            
            if plugged is None:
                status = "Unknown"
            elif plugged:
                status = "Plugged in, fully charged" if percent >= 100 else "Charging"
            else:
                status = "Discharging"
            
            result = f"Battery Status:\n"
            result += f"Charge: {percent:.0f}%\n"
            result += f"Status: {status}\n"
            
            if (not plugged and isinstance(time_left, (int, float)) and time_left >= 0
                    and time_left not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN)):
                time_left = int(time_left)
                hours = time_left // 3600
                minutes = (time_left % 3600) // 60
                result += f"Time remaining: {hours}h {minutes}m\n"
            
            return result
            
        except Exception as e:
            return f"Error getting battery info: {e}"
    
    def run_command(self, command):
        """Refuse arbitrary shell execution; use purpose-specific skills instead."""
        return "Arbitrary shell commands are disabled. Use a dedicated JARVIS skill instead."
