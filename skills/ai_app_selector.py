#!/usr/bin/env python3
"""
AI-Powered App Selection System
Uses LLM to intelligently choose the best application for any task
"""

import subprocess
import os
import time
import json
from typing import Dict, List, Optional
from pathlib import Path

class AIAppSelector:
    """Intelligent app selection using AI decision making"""
    
    def __init__(self, brain=None):
        self.brain = brain
        self.app_cache = []
        self.cache_file = "cache/app_cache.json"
        print("🧠 Initializing AI App Selector...")
        self._ensure_cache_dir()
        self._load_or_build_app_cache()
        
    def _ensure_cache_dir(self):
        """Ensure cache directory exists"""
        os.makedirs("cache", exist_ok=True)
        
    def _load_or_build_app_cache(self):
        """Load app cache from file or build it if it doesn't exist"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.app_cache = json.load(f)
                print(f"📱 Loaded {len(self.app_cache)} apps from cache")
                return
            except Exception as e:
                print(f"Error loading cache: {e}")
        
        # Build cache if it doesn't exist or failed to load
        self._build_app_cache()
        
    def _build_app_cache(self):
        """Build comprehensive app cache"""
        print("🔍 Building comprehensive app cache...")
        
        apps = []
        
        # Get all types of apps
        apps.extend(self._get_registry_apps())
        apps.extend(self._get_system_apps())
        apps.extend(self._get_uwp_apps())
        apps.extend(self._get_common_paths_apps())
        
        # Remove duplicates and invalid entries
        seen_names = set()
        unique_apps = []
        
        for app in apps:
            if app.get('name') and app.get('command'):
                app_key = app['name'].lower()
                if app_key not in seen_names:
                    seen_names.add(app_key)
                    unique_apps.append(app)
        
        self.app_cache = unique_apps
        
        # Save to cache file
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.app_cache, f, indent=2, ensure_ascii=False)
            print(f"💾 Cached {len(self.app_cache)} apps")
        except Exception as e:
            print(f"Error saving cache: {e}")
    
    def _get_registry_apps(self) -> List[Dict]:
        """Get apps from Windows registry"""
        apps = []
        try:
            import winreg
            
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
                                executable = None
                                
                                # Try to get executable path
                                try:
                                    executable = winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                                    if executable and '.exe' in executable:
                                        executable = executable.split(',')[0].strip('"')
                                except FileNotFoundError:
                                    pass
                                
                                if executable and os.path.exists(executable):
                                    apps.append({
                                        'name': display_name,
                                        'command': executable,
                                        'type': 'exe',
                                        'source': 'registry'
                                    })
                            except FileNotFoundError:
                                pass
                            
                            winreg.CloseKey(subkey)
                        except Exception:
                            continue
                    
                    winreg.CloseKey(key)
                except Exception:
                    continue
                    
        except ImportError:
            print("Registry access not available")
        except Exception as e:
            print(f"Registry scan error: {e}")
            
        return apps
    
    def _get_system_apps(self) -> List[Dict]:
        """Get system applications"""
        apps = []
        
        system_commands = [
            ('Calculator', 'calc.exe'),
            ('Notepad', 'notepad.exe'),
            ('Paint', 'mspaint.exe'),
            ('Command Prompt', 'cmd.exe'),
            ('PowerShell', 'powershell.exe'),
            ('File Explorer', 'explorer.exe'),
            ('Task Manager', 'taskmgr.exe'),
            ('Control Panel', 'control.exe'),
            ('Registry Editor', 'regedit.exe'),
            ('Microsoft Edge', 'msedge.exe')
        ]
        
        for name, cmd in system_commands:
            try:
                result = subprocess.run(['where', cmd], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    path = result.stdout.strip().split('\n')[0]
                    apps.append({
                        'name': name,
                        'command': path,
                        'type': 'system',
                        'source': 'system'
                    })
            except Exception:
                continue
                
        return apps
    
    def _get_uwp_apps(self) -> List[Dict]:
        """Get UWP/Store applications"""
        apps = []
        
        try:
            result = subprocess.run([
                'powershell', '-Command', 
                'Get-AppxPackage | Select-Object Name,InstallLocation | ConvertTo-Json'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                try:
                    uwp_data = json.loads(result.stdout)
                    if isinstance(uwp_data, list):
                        for app in uwp_data:
                            if app.get('Name'):
                                apps.append({
                                    'name': app['Name'],
                                    'command': f"shell:AppsFolder\\{app['Name']}",
                                    'type': 'uwp',
                                    'source': 'store'
                                })
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            print(f"UWP scan error: {e}")
            
        return apps
    
    def _get_common_paths_apps(self) -> List[Dict]:
        """Scan common installation paths for applications"""
        apps = []
        
        search_paths = [
            "C:\\Program Files",
            "C:\\Program Files (x86)", 
            f"C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Local\\Programs"
        ]
        
        for base_path in search_paths:
            if not os.path.exists(base_path):
                continue
                
            try:
                for item in os.listdir(base_path):
                    item_path = os.path.join(base_path, item)
                    if os.path.isdir(item_path):
                        # Look for main executable
                        for file in os.listdir(item_path):
                            if file.lower().endswith('.exe'):
                                # Skip obvious system/utility files
                                if any(skip in file.lower() for skip in ['uninstall', 'update', 'setup', 'installer']):
                                    continue
                                    
                                exe_path = os.path.join(item_path, file)
                                apps.append({
                                    'name': item,
                                    'command': exe_path,
                                    'type': 'exe',
                                    'source': 'path_scan'
                                })
                                break  # Only take first exe per directory
            except Exception:
                continue
                
        return apps
    
    def find_best_app_for_task(self, task_description: str) -> Optional[Dict]:
        """Use AI to find the best app for a task"""
        if not self.app_cache:
            print("❌ No apps in cache")
            return None
            
        print(f"🎯 AI is selecting the best app for: '{task_description}'")
        print(f"📱 Choosing from {len(self.app_cache)} available apps")
        
        # Create a simplified list for the AI
        app_list = []
        for i, app in enumerate(self.app_cache[:50]):  # Limit to first 50 to avoid token limits
            app_list.append(f"{i+1}. {app['name']} ({app['type']})")
        
        # Create AI prompt
        prompt = f"""You are an intelligent app selector. Choose the BEST application for this task:

TASK: "{task_description}"

AVAILABLE APPLICATIONS:
{chr(10).join(app_list)}

INSTRUCTIONS:
- If the user mentions a specific app name (like "edge", "opera", "chrome"), prioritize exact matches
- For web browsing tasks (youtube, websites), choose browsers
- For document tasks, choose text editors or Word
- For calculations, choose Calculator
- Consider the task context carefully

Respond with ONLY the number (1-{len(app_list)}) of the best application. No explanation."""
        
        try:
            if self.brain:
                # Use the brain to get AI decision
                if hasattr(self.brain, 'process_command'):
                    response = self.brain.process_command(prompt)
                elif hasattr(self.brain, 'process_request'):
                    response = self.brain.process_request(prompt)
                else:
                    response = self._fallback_selection(task_description)
            else:
                response = self._fallback_selection(task_description)
            
            # Extract number from response
            import re
            numbers = re.findall(r'\d+', str(response))
            if numbers:
                choice_num = int(numbers[0])
                if 1 <= choice_num <= len(app_list):
                    selected_app = self.app_cache[choice_num - 1]
                    print(f"🏆 AI selected: {selected_app['name']} ({selected_app['type']})")
                    return selected_app
            
            # Fallback to heuristic selection
            return self._fallback_selection(task_description)
                
        except Exception as e:
            print(f"AI selection error: {e}")
            return self._fallback_selection(task_description)
    
    def _fallback_selection(self, task_description: str) -> Optional[Dict]:
        """Fallback selection using simple heuristics"""
        task_lower = task_description.lower()
        
        # Browser tasks
        if any(keyword in task_lower for keyword in ['browser', 'web', 'youtube', 'website', 'edge', 'opera', 'chrome']):
            for app in self.app_cache:
                app_name = app['name'].lower()
                if 'edge' in task_lower and 'edge' in app_name:
                    return app
                elif 'opera' in task_lower and 'opera' in app_name:
                    return app
                elif 'chrome' in task_lower and 'chrome' in app_name:
                    return app
                elif any(browser in app_name for browser in ['chrome', 'edge', 'opera', 'firefox']):
                    return app
        
        # Calculator tasks
        if any(keyword in task_lower for keyword in ['calc', 'calculator', 'math']):
            for app in self.app_cache:
                if 'calculator' in app['name'].lower():
                    return app
        
        # Notepad tasks
        if any(keyword in task_lower for keyword in ['notepad', 'text', 'note']):
            for app in self.app_cache:
                if 'notepad' in app['name'].lower():
                    return app
        
        # Return first app as last resort
        return self.app_cache[0] if self.app_cache else None
    
    def launch_app(self, app_info: Dict) -> bool:
        """Launch an application"""
        try:
            cmd = app_info.get('command')
            app_type = app_info.get('type')
            
            if not cmd:
                return False
                
            print(f"🚀 Launching {app_info['name']}...")
            
            if app_type == 'uwp':
                subprocess.Popen(['explorer', cmd])
            elif app_type == 'system':
                subprocess.Popen([cmd])
            elif app_type == 'exe':
                if os.path.exists(cmd):
                    subprocess.Popen([cmd])
                else:
                    print(f"Executable not found: {cmd}")
                    return False
            else:
                # Default handling
                subprocess.Popen([cmd])
            
            return True
            
        except Exception as e:
            print(f"Launch error: {e}")
            return False
    
    def refresh_cache(self):
        """Refresh the app cache"""
        print("🔄 Refreshing app cache...")
        self._build_app_cache()
