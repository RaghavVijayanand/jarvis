import os
import psutil
import subprocess
import platform
import socket
import time
from datetime import datetime
import json
import winreg
import ctypes
from pathlib import Path

class SystemControl:
    def __init__(self):
        self.system = platform.system()
        
    def get_system_status(self):
        """Get comprehensive system status"""
        try:
            # CPU and Memory info
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Network info
            hostname = socket.gethostname()
            ip_address = socket.gethostbyname(hostname)
            
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
Disk: {disk.percent}% used ({disk.used // (1024**3)} GB / {disk.total // (1024**3)} GB free)

Boot Time: {datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S')}
            """
            return status.strip()
        except Exception as e:
            return f"Error getting system status: {e}"
    
    def get_running_processes(self, limit=10):
        """Get top running processes"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    processes.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            # Sort by CPU usage
            processes.sort(key=lambda x: x['cpu_percent'] or 0, reverse=True)
            
            result = "Top Running Processes:\n"
            result += "PID\t\tName\t\t\tCPU%\tMemory%\n"
            result += "-" * 60 + "\n"
            
            for proc in processes[:limit]:
                pid = proc['pid']
                name = proc['name'][:20]
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
            
            if self.system == "Windows":
                import string
                drives = ['%s:' % d for d in string.ascii_uppercase if os.path.exists('%s:' % d)]
                for drive in drives:
                    try:
                        usage = psutil.disk_usage(drive)
                        total_gb = usage.total // (1024**3)
                        used_gb = usage.used // (1024**3)
                        free_gb = usage.free // (1024**3)
                        percent = (usage.used / usage.total) * 100
                        result += f"{drive}\t\t{total_gb} GB\t\t{used_gb} GB\t\t{free_gb} GB\t\t{percent:.1f}%\n"
                    except PermissionError:
                        result += f"{drive}\t\tAccess Denied\n"
            else:
                # Unix-like systems
                partitions = psutil.disk_partitions()
                for partition in partitions:
                    try:
                        usage = psutil.disk_usage(partition.mountpoint)
                        total_gb = usage.total // (1024**3)
                        used_gb = usage.used // (1024**3)
                        free_gb = usage.free // (1024**3)
                        percent = (usage.used / usage.total) * 100
                        result += f"{partition.device}\t{total_gb} GB\t\t{used_gb} GB\t\t{free_gb} GB\t\t{percent:.1f}%\n"
                    except PermissionError:
                        continue
            
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
    
    def launch_application(self, app_name):
        """Launch an application with intelligent detection and verification"""
        try:
            app_name = app_name.lower().strip()

            # Whitelist of built-in apps we allow launching unconditionally
            builtin_apps = {
                'calculator': 'calc.exe',
                'calc': 'calc.exe',
                'settings': 'ms-settings:'
            }

            # Handle built-ins first
            if app_name in builtin_apps:
                command = builtin_apps[app_name]
                success, message = self._try_launch_command(command, app_name)
                return message if success else message

            # For all other apps, verify installation via registry first
            try:
                from skills.app_control import ApplicationControl
                app_control = ApplicationControl()
                
                # exact match
                if app_name in app_control.installed_apps:
                    app_info = app_control.installed_apps[app_name]
                    if app_info.get('executable') and os.path.exists(app_info['executable']):
                        success, message = self._try_launch_executable(app_info['executable'], app_name)
                        return message if success else message
                    elif app_info.get('location'):
                        # Try to find an executable in the install directory
                        install_path = Path(app_info['location'])
                        if install_path.exists():
                            exe_files = list(install_path.glob('*.exe'))
                            if exe_files:
                                success, message = self._try_launch_executable(str(exe_files[0]), app_name)
                                return message if success else message
                        return f"Could not find executable for {app_info['name']}"
                # partial match (best-effort)
                matches = [k for k in app_control.installed_apps.keys() if app_name in k]
                if matches:
                    # Prefer the shortest match
                    matches.sort(key=len)
                    app_info = app_control.installed_apps[matches[0]]
                    if app_info.get('executable') and os.path.exists(app_info['executable']):
                        success, message = self._try_launch_executable(app_info['executable'], app_name)
                        return message if success else message
                    elif app_info.get('location'):
                        install_path = Path(app_info['location'])
                        if install_path.exists():
                            exe_files = list(install_path.glob('*.exe'))
                            if exe_files:
                                success, message = self._try_launch_executable(str(exe_files[0]), app_name)
                                return message if success else message
                        return f"Could not find executable for {app_info['name']}"
                # Try Start Menu shortcuts (.lnk /.appref-ms)
                shortcut_path = self._find_start_menu_shortcut(app_name)
                if shortcut_path:
                    success, message = self._try_launch_shortcut(shortcut_path, app_name)
                    return message if success else message

                # Try UWP/Store apps via AUMID using PowerShell Get-StartApps
                uwp_success, uwp_message = self._launch_uwp_app_by_name(app_name)
                if uwp_success:
                    return uwp_message

                # Last resort: search common install folders for a matching executable
                exe_path = self._search_executable_by_name(app_name)
                if exe_path and os.path.exists(exe_path):
                    success, message = self._try_launch_executable(exe_path, app_name)
                    return message if success else message

                # If we reach here, we could not find the app installed
                return f"'{app_name}' does not appear to be installed on this system."
            except:
                # If we cannot access registry-based detection, fall back to a conservative message
                return f"Could not verify installation of '{app_name}'. I won't attempt to launch it."
            
        except Exception as e:
            return f"Error launching {app_name}: {e}"

    def _find_start_menu_shortcut(self, app_name: str):
        """Search Start Menu for a shortcut matching the app name (Windows)."""
        try:
            if self.system != "Windows":
                return None
            user = os.getenv('USERNAME') or ""
            start_menu_paths = [
                fr"C:\\Users\\{user}\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs",
                r"C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs",
            ]
            needle = app_name.lower()
            for base in start_menu_paths:
                if not os.path.exists(base):
                    continue
                for root, _dirs, files in os.walk(base):
                    for fname in files:
                        name_l = fname.lower()
                        if needle in name_l and (name_l.endswith('.lnk') or name_l.endswith('.appref-ms') or name_l.endswith('.url')):
                            return os.path.join(root, fname)
        except Exception:
            return None
        return None

    def _try_launch_shortcut(self, shortcut_path: str, app_name: str):
        """Open a .lnk/.appref-ms/.url shortcut via shell."""
        try:
            os.startfile(shortcut_path)
            time.sleep(1)
            return True, f"Successfully launched {app_name}."
        except Exception as e:
            return False, f"Error launching {app_name}: {e}"

    def _launch_uwp_app_by_name(self, app_name: str):
        """Attempt to launch a UWP/Store app by display name using PowerShell Get-StartApps."""
        try:
            if self.system != "Windows":
                return False, "UWP apps not supported on this OS"
            # Query AppID (AUMID) for app names containing the query
            ps_cmd = (
                "powershell -NoProfile -Command "
                f"\"$app=(Get-StartApps | Where-Object {{$_.Name -like '*{app_name}*'}} | Select-Object -First 1); if($app){{$app.AppID}}\""
            )
            result = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=10)
            appid = (result.stdout or "").strip()
            if appid:
                # Use shell AppsFolder to launch by AUMID
                launch_cmd = f"explorer.exe shell:AppsFolder\\{appid}"
                run = subprocess.run(launch_cmd, shell=True, capture_output=True, text=True, timeout=10)
                if run.returncode == 0:
                    return True, f"Successfully launched {app_name}."
                return False, f"Failed to launch {app_name} via UWP AppID."
            return False, "AppID not found"
        except subprocess.TimeoutExpired:
            return False, f"Timeout resolving UWP AppID for {app_name}"
        except Exception as e:
            return False, f"Error launching UWP app {app_name}: {e}"

    def _search_executable_by_name(self, app_name: str) -> str | None:
        """Safely search for an executable whose name matches the query in common install locations."""
        try:
            if self.system != "Windows":
                return None
            user = os.getenv('USERNAME') or ""
            base_paths = [
                r"C:\\Program Files",
                r"C:\\Program Files (x86)",
                fr"C:\\Users\\{user}\\AppData\\Local",
                fr"C:\\Users\\{user}\\AppData\\Local\\Programs",
                fr"C:\\Users\\{user}\\AppData\\Roaming",
            ]
            needle = app_name.lower()
            # Limit recursion depth: only look 2 levels deep to keep it fast
            for base in base_paths:
                if not os.path.exists(base):
                    continue
                # First pass: directories whose name contains app_name
                try:
                    for entry in os.scandir(base):
                        if not entry.is_dir():
                            continue
                        name_l = entry.name.lower()
                        if needle in name_l:
                            # Look for app_name*.exe in this directory
                            try:
                                for sub in os.scandir(entry.path):
                                    if sub.is_file():
                                        fname = sub.name.lower()
                                        if fname.endswith('.exe') and (fname == f"{needle}.exe" or fname.startswith(f"{needle}")):
                                            return sub.path
                                    elif sub.is_dir():
                                        # One level deeper
                                        for sub2 in os.scandir(sub.path):
                                            if sub2.is_file():
                                                fname2 = sub2.name.lower()
                                                if fname2.endswith('.exe') and (fname2 == f"{needle}.exe" or fname2.startswith(f"{needle}")):
                                                    return sub2.path
                            except Exception:
                                continue
                except Exception:
                    continue
        except Exception:
            return None
        return None
    
    def _try_launch_command(self, command, app_name):
        """Try to launch a command and verify it started"""
        try:
            if self.system == "Windows":
                if command.startswith('ms-settings:'):
                    os.startfile(command)
                    return True, f"Opened {app_name} settings successfully."
                else:
                    # Use subprocess with proper error handling
                    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=5)
                    
                    # Wait a moment for the process to start
                    time.sleep(1)
                    
                    # Check if a new process started
                    new_processes = set(proc.info['name'].lower() for proc in psutil.process_iter(['name']))
                    
                    # Look for the expected process name
                    expected_process = command.lower().replace('.exe', '')
                    if any(expected_process in proc for proc in new_processes):
                        return True, f"Successfully launched {app_name}."
                    
                    # If return code is 0 and no error, assume success
                    if result.returncode == 0 and not result.stderr:
                        return True, f"Successfully launched {app_name}."
                    
                    return False, f"Failed to launch {app_name}: {result.stderr if result.stderr else 'Unknown error'}"
            else:
                subprocess.Popen(command, shell=True)
                return True, f"Launched {app_name} successfully."
                
        except subprocess.TimeoutExpired:
            return False, f"Timeout launching {app_name}"
        except Exception as e:
            return False, f"Error launching {app_name}: {e}"
    
    def _try_launch_executable(self, executable_path, app_name):
        """Try to launch an executable and verify it started"""
        try:
            subprocess.Popen([executable_path])
            time.sleep(1)  # Wait for process to start
            
            # Check if the process is running
            exe_name = os.path.basename(executable_path).lower()
            for proc in psutil.process_iter(['name']):
                if proc.info['name'].lower() == exe_name:
                    return True, f"Successfully launched {app_name}."
            
            return False, f"Launched {app_name} but could not verify it started."
            
        except Exception as e:
            return False, f"Error launching {app_name}: {e}"
    
    def kill_process(self, process_name):
        """Kill a process by name"""
        try:
            killed_count = 0
            for proc in psutil.process_iter(['pid', 'name']):
                if process_name.lower() in proc.info['name'].lower():
                    try:
                        proc.kill()
                        killed_count += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            
            if killed_count > 0:
                return f"Killed {killed_count} process(es) matching '{process_name}'"
            else:
                return f"No processes found matching '{process_name}'"
                
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
                        status = "Up" if stats[interface_name].isup else "Down"
                        result += f"{interface_name[:15]}\t\t{ip}\t\t{status}\n"
                        break
            
            return result
        except Exception as e:
            return f"Error getting network info: {e}"
    
    def set_volume(self, level):
        """Set system volume (Windows only)"""
        try:
            if self.system != "Windows":
                return "Volume control only supported on Windows"
            
            level = max(0, min(100, int(level)))
            
            # Use Windows API to set volume
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            
            volume.SetMasterScalarVolume(level / 100.0, None)
            return f"Volume set to {level}%"
            
        except ImportError:
            return "Volume control requires pycaw library: pip install pycaw"
        except Exception as e:
            return f"Error setting volume: {e}"
    
    def take_screenshot(self, filename=None):
        """Take a screenshot"""
        try:
            import PIL.ImageGrab as ImageGrab
            
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"
            
            screenshot = ImageGrab.grab()
            filepath = Path.cwd() / filename
            screenshot.save(filepath)
            
            return f"Screenshot saved as {filepath}"
            
        except ImportError:
            return "Screenshot requires Pillow library: pip install Pillow"
        except Exception as e:
            return f"Error taking screenshot: {e}"
    
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
            
            status = "Charging" if plugged else "Discharging"
            
            result = f"Battery Status:\n"
            result += f"Charge: {percent}%\n"
            result += f"Status: {status}\n"
            
            if time_left != psutil.POWER_TIME_UNLIMITED and time_left != psutil.POWER_TIME_UNKNOWN:
                hours = time_left // 3600
                minutes = (time_left % 3600) // 60
                result += f"Time remaining: {hours}h {minutes}m\n"
            
            return result
            
        except Exception as e:
            return f"Error getting battery info: {e}"
    
    def run_command(self, command):
        """Run a system command and return output"""
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            
            output = ""
            if result.stdout:
                output += f"Output:\n{result.stdout}\n"
            if result.stderr:
                output += f"Errors:\n{result.stderr}\n"
            
            output += f"Return code: {result.returncode}"
            
            return output
            
        except subprocess.TimeoutExpired:
            return "Command timed out after 30 seconds"
        except Exception as e:
            return f"Error running command: {e}"
