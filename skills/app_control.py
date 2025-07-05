import subprocess
import os
import time
import psutil
import winreg
from pathlib import Path
import json

class ApplicationControl:
    def __init__(self):
        self.installed_apps = {}
        self.refresh_app_list()
    
    def refresh_app_list(self):
        """Refresh the list of installed applications"""
        try:
            self.installed_apps = self._get_installed_applications()
        except Exception as e:
            print(f"Error refreshing app list: {e}")
    
    def _get_installed_applications(self):
        """Get list of installed applications from Windows registry"""
        apps = {}
        
        # Registry keys to check for installed programs
        registry_keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
        ]
        
        for registry_key in registry_keys:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_key)
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        subkey = winreg.OpenKey(key, subkey_name)
                        
                        try:
                            display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                            install_location = None
                            executable = None
                            
                            try:
                                install_location = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                            except FileNotFoundError:
                                pass
                            
                            try:
                                executable = winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                                if executable and executable.endswith('.exe'):
                                    executable = executable.split(',')[0]  # Remove icon index
                            except FileNotFoundError:
                                pass
                            
                            apps[display_name.lower()] = {
                                'name': display_name,
                                'location': install_location,
                                'executable': executable
                            }
                        except FileNotFoundError:
                            pass
                        
                        winreg.CloseKey(subkey)
                    except Exception:
                        continue
                
                winreg.CloseKey(key)
            except Exception:
                continue
        
        return apps
    
    def list_installed_apps(self, filter_text=""):
        """List installed applications"""
        try:
            if filter_text:
                filtered_apps = {k: v for k, v in self.installed_apps.items() 
                               if filter_text.lower() in k}
            else:
                filtered_apps = self.installed_apps
            
            if not filtered_apps:
                return "No applications found matching the filter."
            
            result = "Installed Applications:\n"
            result += "-" * 50 + "\n"
            
            count = 0
            for app_key, app_info in sorted(filtered_apps.items()):
                if count >= 50:  # Limit output
                    result += f"... and {len(filtered_apps) - count} more applications\n"
                    break
                result += f"{app_info['name']}\n"
                count += 1
            
            return result
        except Exception as e:
            return f"Error listing applications: {e}"
    
    def launch_app_by_name(self, app_name):
        """Launch an application by name with enhanced detection"""
        try:
            app_name_lower = app_name.lower()
            
            # Enhanced common applications with Riot Games and others
            common_apps = {
                'notepad': 'notepad.exe',
                'calculator': 'calc.exe',
                'calc': 'calc.exe',
                'paint': 'mspaint.exe',
                'wordpad': 'wordpad.exe',
                'cmd': 'cmd.exe',
                'command prompt': 'cmd.exe',
                'powershell': 'powershell.exe',
                'explorer': 'explorer.exe',
                'file explorer': 'explorer.exe',
                'task manager': 'taskmgr.exe',
                'control panel': 'control.exe',
                'registry editor': 'regedit.exe',
                'system configuration': 'msconfig.exe',
                'device manager': 'devmgmt.msc',
                'disk management': 'diskmgmt.msc',
                'services': 'services.msc',
                'event viewer': 'eventvwr.msc',
                
                # Popular applications
                'chrome': 'chrome.exe',
                'google chrome': 'chrome.exe',
                'firefox': 'firefox.exe',
                'edge': 'msedge.exe',
                'microsoft edge': 'msedge.exe',
                'discord': 'Discord.exe',
                'steam': 'steam.exe',
                'spotify': 'Spotify.exe',
                'vs code': 'Code.exe',
                'visual studio code': 'Code.exe',
                'vscode': 'Code.exe',
                'word': 'WINWORD.EXE',
                'excel': 'EXCEL.EXE',
                'powerpoint': 'POWERPNT.EXE',
                'outlook': 'OUTLOOK.EXE',
                'teams': 'Teams.exe',
                'zoom': 'Zoom.exe',
                'skype': 'Skype.exe',
                'telegram': 'Telegram.exe',
                'whatsapp': 'WhatsApp.exe',
                'whatsapp desktop': 'WhatsApp.exe',
                'desktop': 'explorer.exe shell:desktop',
                
                # Gaming applications
                'riot games': 'RiotClientServices.exe',
                'riot': 'RiotClientServices.exe',
                'riot client': 'RiotClientServices.exe',
                'league of legends': 'RiotClientServices.exe',
                'valorant': 'RiotClientServices.exe',
                'epic games': 'EpicGamesLauncher.exe',
                'epic': 'EpicGamesLauncher.exe',
                'origin': 'Origin.exe',
                'uplay': 'upc.exe',
                'battle.net': 'Battle.net.exe',
                'battlenet': 'Battle.net.exe'
            }
            
            # Try common apps first
            if app_name_lower in common_apps:
                return self._launch_with_verification(common_apps[app_name_lower], app_name)
            
            # Special handling for specific apps
            if app_name_lower in ['whatsapp', 'whatsapp desktop']:
                return self._launch_whatsapp()
            
            if app_name_lower in ['desktop']:
                return self._open_desktop()
            
            # First try to find exact match in installed apps
            if app_name_lower in self.installed_apps:
                app_info = self.installed_apps[app_name_lower]
                return self._launch_application_verified(app_info)
            
            # Try partial match in installed apps
            matches = [k for k in self.installed_apps.keys() if app_name_lower in k]
            if matches:
                # Sort by relevance (shorter matches first)
                matches.sort(key=len)
                app_info = self.installed_apps[matches[0]]
                return self._launch_application_verified(app_info)
            
            # Try to find in common installation paths
            search_paths = [
                "C:\\Program Files",
                "C:\\Program Files (x86)",
                f"C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Local",
                f"C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Roaming"
            ]
            
            for base_path in search_paths:
                if os.path.exists(base_path):
                    for item in os.listdir(base_path):
                        if app_name_lower in item.lower():
                            potential_path = os.path.join(base_path, item)
                            if os.path.isdir(potential_path):
                                # Look for executable in this directory
                                for file in os.listdir(potential_path):
                                    if file.lower().endswith('.exe') and (app_name_lower in file.lower() or 'launcher' in file.lower()):
                                        exe_path = os.path.join(potential_path, file)
                                        return self._launch_with_verification(exe_path, app_name)
            
            # Try direct execution
            try:
                result = subprocess.run(app_name_lower, shell=True, capture_output=True, text=True, timeout=3)
                if result.returncode == 0:
                    return f"Launched {app_name} successfully."
                else:
                    return f"Failed to launch {app_name}: {result.stderr if result.stderr else 'Command not found'}"
            except subprocess.TimeoutExpired:
                return f"Timeout attempting to launch {app_name}"
            except Exception:
                pass
            
            return f"Could not find '{app_name}'. Application may not be installed or accessible. Try 'list apps {app_name}' to search for similar applications."
            
        except Exception as e:
            return f"Error launching application: {e}"
    
    def _launch_with_verification(self, command_or_path, app_name):
        """Launch command/executable and verify it started"""
        try:
            import time
            
            # Get current processes
            current_processes = set(proc.info['name'].lower() for proc in psutil.process_iter(['name']))
            
            # Launch the application
            if os.path.isfile(command_or_path):
                subprocess.Popen([command_or_path])
            else:
                result = subprocess.run(command_or_path, shell=True, capture_output=True, text=True, timeout=5)
                if result.returncode != 0 and result.stderr:
                    return f"Failed to launch {app_name}: {result.stderr}"
            
            # Wait for process to start
            time.sleep(2)
            
            # Check if new processes appeared
            new_processes = set(proc.info['name'].lower() for proc in psutil.process_iter(['name']))
            started_processes = new_processes - current_processes
            
            if started_processes:
                return f"Successfully launched {app_name}. New processes: {', '.join(started_processes)}"
            else:
                return f"Attempted to launch {app_name}, but could not verify it started."
                
        except subprocess.TimeoutExpired:
            return f"Timeout launching {app_name}"
        except Exception as e:
            return f"Error launching {app_name}: {e}"
    
    def _launch_application_verified(self, app_info):
        """Launch application with verification using app info"""
        if app_info['executable'] and os.path.exists(app_info['executable']):
            return self._launch_with_verification(app_info['executable'], app_info['name'])
        elif app_info['location']:
            # Try to find executable in install location
            install_path = Path(app_info['location'])
            if install_path.exists():
                exe_files = list(install_path.glob("*.exe"))
                if exe_files:
                    return self._launch_with_verification(str(exe_files[0]), app_info['name'])
        
        return f"Could not find executable for {app_info['name']}"
    
    def _launch_application(self, app_info):
        """Helper method to launch an application"""
        try:
            if app_info['executable'] and os.path.exists(app_info['executable']):
                subprocess.Popen([app_info['executable']], shell=True)
                return f"Launched {app_info['name']} successfully."
            elif app_info['location']:
                # Try to find executable in install location
                install_path = Path(app_info['location'])
                if install_path.exists():
                    exe_files = list(install_path.glob("*.exe"))
                    if exe_files:
                        subprocess.Popen([str(exe_files[0])], shell=True)
                        return f"Launched {app_info['name']} successfully."
            
            return f"Could not find executable for {app_info['name']}"
            
        except Exception as e:
            return f"Error launching {app_info['name']}: {e}"
    
    def close_app_by_name(self, app_name):
        """Close an application by name"""
        try:
            app_name_lower = app_name.lower()
            killed_count = 0
            
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    proc_name = proc.info['name'].lower()
                    proc_exe = proc.info['exe']
                    
                    # Check if process name matches
                    if (app_name_lower in proc_name or 
                        (proc_exe and app_name_lower in Path(proc_exe).stem.lower())):
                        proc.terminate()
                        killed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if killed_count > 0:
                return f"Closed {killed_count} process(es) for {app_name}"
            else:
                return f"No running processes found for {app_name}"
                
        except Exception as e:
            return f"Error closing application: {e}"
    
    def get_app_info(self, app_name):
        """Get detailed information about an application"""
        try:
            app_name_lower = app_name.lower()
            
            # Find the application
            if app_name_lower in self.installed_apps:
                app_info = self.installed_apps[app_name_lower]
            else:
                matches = [k for k in self.installed_apps.keys() if app_name_lower in k]
                if not matches:
                    return f"Application '{app_name}' not found."
                app_info = self.installed_apps[matches[0]]
            
            result = f"Application Information:\n"
            result += f"Name: {app_info['name']}\n"
            result += f"Install Location: {app_info['location'] or 'Unknown'}\n"
            result += f"Executable: {app_info['executable'] or 'Unknown'}\n"
            
            # Check if it's currently running
            running_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    if (app_info['executable'] and 
                        proc.info['exe'] and 
                        Path(proc.info['exe']).name.lower() == Path(app_info['executable']).name.lower()):
                        running_processes.append(proc.info['pid'])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if running_processes:
                result += f"Status: Running (PIDs: {', '.join(map(str, running_processes))})\n"
            else:
                result += "Status: Not running\n"
            
            return result
            
        except Exception as e:
            return f"Error getting app info: {e}"
    
    def install_app_from_web(self, app_name, download_url):
        """Download and install an application (basic implementation)"""
        try:
            import requests
            
            # Create downloads directory
            downloads_dir = Path.home() / "Downloads" / "JARVIS_Downloads"
            downloads_dir.mkdir(exist_ok=True)
            
            # Download the file
            response = requests.get(download_url, stream=True)
            response.raise_for_status()
            
            # Determine file extension
            content_type = response.headers.get('content-type', '')
            if 'application/x-msdos-program' in content_type or download_url.endswith('.exe'):
                filename = f"{app_name}.exe"
            elif download_url.endswith('.msi'):
                filename = f"{app_name}.msi"
            else:
                filename = f"{app_name}_installer"
            
            filepath = downloads_dir / filename
            
            # Save the file
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            result = f"Downloaded {app_name} to {filepath}\n"
            result += "To install, you can run the installer manually or use 'run installer' command."
            
            return result
            
        except Exception as e:
            return f"Error downloading application: {e}"
    
    def run_installer(self, installer_path):
        """Run an installer file"""
        try:
            if not os.path.exists(installer_path):
                return f"Installer file not found: {installer_path}"
            
            # Run the installer
            subprocess.Popen([installer_path], shell=True)
            return f"Started installer: {installer_path}"
            
        except Exception as e:
            return f"Error running installer: {e}"
    
    def uninstall_app(self, app_name):
        """Attempt to uninstall an application"""
        try:
            app_name_lower = app_name.lower()
            
            # Find the application
            if app_name_lower in self.installed_apps:
                app_info = self.installed_apps[app_name_lower]
            else:
                matches = [k for k in self.installed_apps.keys() if app_name_lower in k]
                if not matches:
                    return f"Application '{app_name}' not found."
                app_info = self.installed_apps[matches[0]]
            
            # Try to find uninstaller
            if app_info['location']:
                uninstall_paths = [
                    Path(app_info['location']) / "uninstall.exe",
                    Path(app_info['location']) / "Uninstall.exe",
                    Path(app_info['location']) / "unins000.exe"
                ]
                
                for uninstall_path in uninstall_paths:
                    if uninstall_path.exists():
                        subprocess.Popen([str(uninstall_path)], shell=True)
                        return f"Started uninstaller for {app_info['name']}"
            
            # Fall back to Windows Add/Remove Programs
            subprocess.Popen(['appwiz.cpl'], shell=True)
            return f"Opened Add/Remove Programs. Please manually uninstall {app_info['name']}"
            
        except Exception as e:
            return f"Error uninstalling application: {e}"
    
    def create_desktop_shortcut(self, app_name):
        """Create a desktop shortcut for an application"""
        try:
            import win32com.client
            
            app_name_lower = app_name.lower()
            
            # Find the application
            if app_name_lower in self.installed_apps:
                app_info = self.installed_apps[app_name_lower]
            else:
                matches = [k for k in self.installed_apps.keys() if app_name_lower in k]
                if not matches:
                    return f"Application '{app_name}' not found."
                app_info = self.installed_apps[matches[0]]
            
            if not app_info['executable']:
                return f"No executable found for {app_info['name']}"
            
            # Create shortcut
            desktop = Path.home() / "Desktop"
            shortcut_path = desktop / f"{app_info['name']}.lnk"
            
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(str(shortcut_path))
            shortcut.Targetpath = app_info['executable']
            shortcut.WorkingDirectory = str(Path(app_info['executable']).parent)
            shortcut.save()
            
            return f"Created desktop shortcut for {app_info['name']}"
            
        except ImportError:
            return "Creating shortcuts requires pywin32 library: pip install pywin32"
        except Exception as e:
            return f"Error creating shortcut: {e}"
    
    def _launch_whatsapp(self):
        """Special handler for WhatsApp with multiple launch methods"""
        try:
            # Method 1: Try Windows Store app
            try:
                result = subprocess.run('start ms-windows-store://pdp/?ProductId=9NKSQGP7F2NH', 
                                      shell=True, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    time.sleep(3)  # Wait for app to launch
                    # Check if WhatsApp process is running
                    for proc in psutil.process_iter(['name']):
                        if 'whatsapp' in proc.info['name'].lower():
                            return "Successfully launched WhatsApp from Microsoft Store."
            except:
                pass
            
            # Method 2: Try direct executable paths
            whatsapp_paths = [
                f"C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Local\\WhatsApp\\WhatsApp.exe",
                f"C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Roaming\\WhatsApp\\WhatsApp.exe",
                "C:\\Program Files\\WhatsApp\\WhatsApp.exe",
                "C:\\Program Files (x86)\\WhatsApp\\WhatsApp.exe"
            ]
            
            for path in whatsapp_paths:
                if os.path.exists(path):
                    return self._launch_with_verification(path, "WhatsApp")
            
            # Method 3: Try launch via protocol
            try:
                subprocess.run('start whatsapp:', shell=True, timeout=3)
                time.sleep(2)
                for proc in psutil.process_iter(['name']):
                    if 'whatsapp' in proc.info['name'].lower():
                        return "Successfully launched WhatsApp via protocol."
            except:
                pass
            
            # Method 4: Search for WhatsApp in installed apps more thoroughly
            for app_key, app_info in self.installed_apps.items():
                if 'whatsapp' in app_key or 'whatsapp' in app_info['name'].lower():
                    return self._launch_application_verified(app_info)
            
            return "WhatsApp not found. Please install WhatsApp Desktop from the Microsoft Store or official website."
            
        except Exception as e:
            return f"Error launching WhatsApp: {e}"
    
    def _open_desktop(self):
        """Open desktop folder in File Explorer"""
        try:
            desktop_path = str(Path.home() / "Desktop")
            subprocess.run(f'explorer "{desktop_path}"', shell=True)
            return "Opened Desktop folder in File Explorer."
        except Exception as e:
            return f"Error opening desktop: {e}"
