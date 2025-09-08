#!/usr/bin/env python3
"""
Smart App Discovery System
Automatically discovers and matches installed apps to task requirements
"""

import subprocess
import os
import re
from typing import Dict, List, Optional, Tuple
import winreg

class SmartAppDiscovery:
    """Discovers and matches apps to task requirements"""
    
    def __init__(self):
        self.app_cache = {}
        self.task_app_mappings = {
            'alarm_timer': {
                'keywords': ['windowsclock', 'clock', 'alarm', 'timer'],
                'exact_matches': ['Microsoft.WindowsClock', 'Microsoft.WindowsAlarms'],
                'preferred_types': ['uwp', 'exe'],
                'fallbacks': ['notepad']
            },
            'email': {
                'keywords': ['outlook', 'mail', 'windowsmail'],
                'exact_matches': ['Microsoft.OutlookForWindows', 'microsoft.windowscommunicationsapps'],
                'preferred_types': ['exe', 'uwp'],
                'fallbacks': ['notepad']
            },
            'document': {
                'keywords': ['word', 'notepad', 'wordpad', 'writer', 'document', 'text'],
                'exact_matches': ['Microsoft.Office.Word', 'notepad', 'wordpad'],
                'preferred_types': ['exe'],
                'fallbacks': ['notepad']
            },
            'browser': {
                'keywords': ['edge', 'chrome', 'firefox', 'opera', 'brave', 'browser', 'microsoftedge'],
                'exact_matches': ['Microsoft.MicrosoftEdge', 'msedge', 'chrome', 'firefox', 'opera', 'brave'],
                'preferred_types': ['exe'],
                'fallbacks': ['msedge']
            },
            'calculator': {
                'keywords': ['windowscalculator', 'calc', 'calculator', 'math'],
                'exact_matches': ['Microsoft.WindowsCalculator', 'calc'],
                'preferred_types': ['uwp', 'exe'],
                'fallbacks': ['calc']
            }
        }
    
    def _get_registry_apps(self) -> List[Dict]:
        """Get installed applications from Windows registry"""
        registry_apps = []
        
        # Registry keys where installed programs are listed
        registry_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
        ]
        
        browsers_of_interest = ['opera', 'chrome', 'firefox', 'brave', 'edge', 'vivaldi']
        
        for hkey, reg_path in registry_keys:
            try:
                with winreg.OpenKey(hkey, reg_path) as key:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            i += 1
                            
                            try:
                                with winreg.OpenKey(key, subkey_name) as subkey:
                                    try:
                                        display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                                        
                                        # Check if it's a browser we're interested in
                                        if any(browser in display_name.lower() for browser in browsers_of_interest):
                                            try:
                                                install_location = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                                                
                                                # Look for executable in install location
                                                if install_location and os.path.exists(install_location):
                                                    for file in os.listdir(install_location):
                                                        if file.lower().endswith('.exe') and any(browser in file.lower() for browser in browsers_of_interest):
                                                            full_path = os.path.join(install_location, file)
                                                            registry_apps.append({
                                                                'name': display_name,
                                                                'type': 'exe',
                                                                'command': full_path,
                                                                'source': 'registry'
                                                            })
                                                            break
                                            except (FileNotFoundError, OSError):
                                                # Try to get direct executable path
                                                try:
                                                    display_icon = winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                                                    if display_icon.endswith('.exe'):
                                                        if os.path.exists(display_icon):
                                                            registry_apps.append({
                                                                'name': display_name,
                                                                'type': 'exe', 
                                                                'command': display_icon,
                                                                'source': 'registry'
                                                            })
                                                except (FileNotFoundError, OSError):
                                                    pass
                                    except (FileNotFoundError, OSError):
                                        pass
                            except (FileNotFoundError, OSError):
                                pass
                        except OSError:
                            break
            except Exception as e:
                continue
        
        return registry_apps
    
    def discover_all_apps(self) -> Dict[str, List[Dict]]:
        """Discover all installed applications"""
        print("🔍 Discovering installed applications...")
        
        apps = {
            'uwp_apps': self._get_uwp_apps(),
            'exe_apps': self._get_exe_apps(),
            'registry_apps': self._get_registry_apps(),
            'system_apps': self._get_system_apps()
        }
        
        # Cache the results
        self.app_cache = apps
        return apps
    
    def _get_uwp_apps(self) -> List[Dict]:
        """Get UWP/Store apps"""
        uwp_apps = []
        try:
            # Get UWP apps using PowerShell with better filtering
            ps_script = (
                'Get-AppxPackage | Where-Object {$_.Name -like "*Clock*" -or $_.Name -like "*Calculator*" -or '
                '$_.Name -like "*Mail*" -or $_.Name -like "*Edge*" -or $_.Name -like "*Outlook*"} | '
                'Select-Object Name, PackageFamilyName | ConvertTo-Json'
            )
            cmd = ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    import json
                    apps_data = json.loads(result.stdout)
                    
                    if isinstance(apps_data, list):
                        for app in apps_data:
                            if app and 'Name' in app:
                                # Filter for actual useful apps
                                app_name = app['Name']
                                if any(keyword in app_name.lower() for keyword in ['clock', 'calculator', 'mail', 'edge', 'outlook']):
                                    uwp_apps.append({
                                        'name': app_name,
                                        'type': 'uwp',
                                        'command': f"shell:AppsFolder\\{app.get('PackageFamilyName', '')}"
                                    })
                    elif isinstance(apps_data, dict) and 'Name' in apps_data:
                        app_name = apps_data['Name']
                        if any(keyword in app_name.lower() for keyword in ['clock', 'calculator', 'mail', 'edge', 'outlook']):
                            uwp_apps.append({
                                'name': app_name,
                                'type': 'uwp',
                                'command': f"shell:AppsFolder\\{apps_data.get('PackageFamilyName', '')}"
                            })
                except json.JSONDecodeError as je:
                    print(f"Could not parse UWP apps JSON: {je}")
        except Exception as e:
            print(f"Could not get UWP apps: {e}")
        
        return uwp_apps
    
    def _get_exe_apps(self) -> List[Dict]:
        """Get executable applications from common locations"""
        exe_apps = []
        
        # Common executable locations
        search_paths = [
            os.environ.get('PROGRAMFILES', 'C:\\Program Files'),
            os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'),
            os.environ.get('LOCALAPPDATA', '') + '\\Programs',
            'C:\\Windows\\System32'
        ]
        
        # Known apps to look for (including manually installed browsers)
        known_apps = [
            'notepad.exe', 'wordpad.exe', 'calc.exe', 'mspaint.exe',
            'msedge.exe', 'chrome.exe', 'firefox.exe', 'opera.exe', 'brave.exe',
            'winword.exe', 'outlook.exe', 'thunderbird.exe', 'code.exe'
        ]
        
        for path in search_paths:
            if not path or not os.path.exists(path):
                continue
                
            try:
                for root, dirs, files in os.walk(path):
                    # Limit depth to avoid too much scanning
                    level = root.replace(path, '').count(os.sep)
                    if level > 2:
                        continue
                        
                    for file in files:
                        if file.lower().endswith('.exe') and any(known in file.lower() for known in known_apps):
                            exe_apps.append({
                                'name': file.replace('.exe', ''),
                                'type': 'exe',
                                'command': os.path.join(root, file)
                            })
            except Exception:
                continue
        
        return exe_apps
    
    def _get_system_apps(self) -> List[Dict]:
        """Get system applications"""
        system_apps = []
        
        # Test common system commands
        system_commands = [
            'notepad', 'calc', 'mspaint', 'wordpad', 'msedge', 
            'control', 'regedit', 'cmd', 'powershell'
        ]
        
        for cmd in system_commands:
            try:
                if os.name == 'nt':  # Windows only
                    result = subprocess.run(['where', cmd], capture_output=True, text=True, timeout=2)
                    if result.returncode == 0:
                        system_apps.append({
                            'name': cmd,
                            'type': 'system',
                            'command': cmd
                        })
            except Exception:
                continue
        
        # Also try specific Clock app URIs
        clock_uris = [
            {'name': 'Windows Clock', 'command': 'ms-clock:', 'type': 'uri'},
            {'name': 'Windows Alarms', 'command': 'ms-clock://alarms', 'type': 'uri'},
            {'name': 'Windows Timer', 'command': 'ms-clock://timers', 'type': 'uri'},
        ]
        
        for clock_app in clock_uris:
            system_apps.append(clock_app)
        
        return system_apps
    
    def find_best_app_for_task(self, task_type: str) -> Optional[Dict]:
        """Find the best app for a specific task type"""
        if not self.app_cache:
            self.discover_all_apps()
        
        if task_type not in self.task_app_mappings:
            return None
        
        task_config = self.task_app_mappings[task_type]
        keywords = task_config['keywords']
        exact_matches = task_config.get('exact_matches', [])
        preferred_types = task_config['preferred_types']
        fallbacks = task_config['fallbacks']
        
        # Score apps based on keywords and type preference
        candidates = []
        
        for app_type, apps in self.app_cache.items():
            for app in apps:
                score = 0
                app_name_lower = app['name'].lower()
                
                # Highest priority: exact matches
                for exact_match in exact_matches:
                    if exact_match.lower() == app_name_lower:
                        score += 100
                        break
                    elif exact_match.lower() in app_name_lower:
                        score += 50
                
                # Score based on keyword matching
                for keyword in keywords:
                    if keyword in app_name_lower:
                        score += 10
                    elif any(part in app_name_lower for part in keyword.split()):
                        score += 5
                
                # Bonus for preferred types
                if app['type'] in preferred_types:
                    score += preferred_types.index(app['type']) + 1
                
                if score > 0:
                    candidates.append((score, app))
        
        # Sort by score and return best match
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        
        # Use fallback
        for fallback in fallbacks:
            try:
                result = subprocess.run(['where', fallback], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    return {
                        'name': fallback,
                        'type': 'system',
                        'command': fallback
                    }
            except Exception:
                continue
        
        return None
    
    def get_app_info_for_tasks(self) -> Dict[str, Dict]:
        """Get the best app for each task type"""
        results = {}
        
        for task_type in self.task_app_mappings.keys():
            best_app = self.find_best_app_for_task(task_type)
            results[task_type] = best_app
        
        return results
    
    def test_app_launch(self, app_info: Dict) -> bool:
        """Test if an app can be launched"""
        if not app_info:
            return False
        
        try:
            if app_info['type'] == 'uwp':
                # UWP apps use shell:AppsFolder
                subprocess.run(['explorer', app_info['command']], timeout=5)
            else:
                # Regular executables
                subprocess.run([app_info['command']], timeout=5)
            return True
        except Exception:
            return False

def test_app_discovery():
    """Test the app discovery system"""
    print("🚀 Testing Smart App Discovery System")
    print("=" * 60)
    
    discovery = SmartAppDiscovery()
    
    # Discover all apps
    print("\n🔍 Discovering installed applications...")
    all_apps = discovery.discover_all_apps()
    
    print(f"\nFound {len(all_apps['uwp_apps'])} UWP apps")
    print(f"Found {len(all_apps['exe_apps'])} executable apps") 
    print(f"Found {len(all_apps['system_apps'])} system apps")
    
    # Show some examples
    print("\n📱 Sample UWP Apps:")
    for app in all_apps['uwp_apps'][:5]:
        print(f"   • {app['name']}")
    
    print("\n💻 Sample System Apps:")
    for app in all_apps['system_apps'][:5]:
        print(f"   • {app['name']} -> {app['command']}")
    
    # Find best apps for each task
    print("\n🎯 Best Apps for Each Task Type:")
    print("-" * 40)
    
    task_apps = discovery.get_app_info_for_tasks()
    
    for task_type, app_info in task_apps.items():
        print(f"\n{task_type.upper()}:")
        if app_info:
            print(f"   ✅ {app_info['name']} ({app_info['type']})")
            print(f"   Command: {app_info['command']}")
        else:
            print(f"   ❌ No suitable app found")
    
    print("\n" + "=" * 60)
    print("🎉 App Discovery System Ready!")
    return task_apps

if __name__ == "__main__":
    test_app_discovery()
