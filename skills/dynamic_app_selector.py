#!/usr/bin/env python3
"""
Dynamic App Selection System
Dynamically chooses the best app for each task from all available applications
"""

import subprocess
import os
import re
import time
import json
from typing import Dict, List, Optional, Tuple, Any
import winreg
from pathlib import Path
from skills.screen_automation import ScreenAutomationSkill
try:
    from config import Config
except Exception:
    Config = None

class DynamicAppSelector:
    """Dynamically selects the best app for any given task"""
    
    def __init__(self):
        self.screen_automation = ScreenAutomationSkill()
        self.all_apps = {}
        self.task_keywords = {
            'alarm_timer': ['alarm', 'clock', 'timer', 'time', 'wake', 'reminder'],
            'email': ['mail', 'email', 'outlook', 'thunderbird', 'gmail', 'message'],
            'document': ['word', 'note', 'text', 'document', 'write', 'editor'],
            'browser': ['browser', 'web', 'internet', 'edge', 'chrome', 'firefox', 'opera', 'youtube', 'website', 'url'],
            'calculator': ['calc', 'calculator', 'math', 'compute'],
            'media': ['media', 'player', 'music', 'video', 'vlc', 'winamp'],
            'photo': ['photo', 'image', 'picture', 'paint', 'gimp', 'photoshop'],
            'file_manager': ['file', 'explorer', 'folder', 'directory'],
            'settings': ['setting', 'control', 'config', 'preference'],
            'communication': ['chat', 'skype', 'discord', 'teams', 'zoom']
        }
        
        # Known browser applications with their common executable names
        self.known_browsers = {
            'opera': ['opera.exe', 'Opera'],
            'chrome': ['chrome.exe', 'Google Chrome'],
            'firefox': ['firefox.exe', 'Mozilla Firefox'],
            'edge': ['msedge.exe', 'Microsoft Edge'],
            'brave': ['brave.exe', 'Brave'],
            'vivaldi': ['vivaldi.exe', 'Vivaldi']
        }
    
    def discover_all_applications(self) -> Dict[str, List[Dict]]:
        """Discover all available applications on the system"""
        print("🔍 Discovering all available applications...")
        
        apps = {
            'uwp_apps': self._get_all_uwp_apps(),
            'exe_apps': self._get_all_exe_apps(),
            'browsers': self._find_browsers_specifically(),
            'system_apps': self._get_system_apps(),
            'uri_apps': self._get_uri_apps()
        }
        
        self.all_apps = apps
        total_apps = sum(len(category) for category in apps.values())
        print(f"📱 Found {total_apps} total applications")
        
        return apps
    
    def _get_all_uwp_apps(self) -> List[Dict]:
        """Get all UWP/Store apps"""
        uwp_apps = []
        try:
            ps_script = (
                'Get-AppxPackage | Where-Object { $_.InstallLocation -ne $null } | '
                'Select-Object Name, PackageFamilyName, DisplayName | ConvertTo-Json'
            )
            cmd = [
                'powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    apps_data = json.loads(result.stdout)
                    
                    if isinstance(apps_data, list):
                        for app in apps_data:
                            if app and app.get('Name'):
                                uwp_apps.append({
                                    'name': app.get('DisplayName') or app.get('Name'),
                                    'package_name': app['Name'],
                                    'type': 'uwp',
                                    'command': (f"shell:AppsFolder\\{app.get('PackageFamilyName')}" if app.get('PackageFamilyName') else None)
                                })
                    elif isinstance(apps_data, dict) and apps_data.get('Name'):
                        uwp_apps.append({
                            'name': apps_data.get('DisplayName') or apps_data['Name'],
                            'package_name': apps_data['Name'],
                            'type': 'uwp',
                            'command': (f"shell:AppsFolder\\{apps_data.get('PackageFamilyName')}" if apps_data.get('PackageFamilyName') else None)
                        })
                except json.JSONDecodeError as je:
                    print(f"Could not parse UWP apps JSON: {je}")
        except Exception as e:
            print(f"Could not get UWP apps: {e}")
        
        return uwp_apps
    
    def _get_all_exe_apps(self) -> List[Dict]:
        """Get all executable applications"""
        exe_apps = []
        
        # Enhanced search paths
        search_paths = [
            os.environ.get('PROGRAMFILES', 'C:\\Program Files'),
            os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs'),
            'C:\\Windows\\System32',
            'C:\\Windows\\SysWOW64'
        ]
        
        for path in search_paths:
            if not path or not os.path.exists(path):
                continue
                
            try:
                for root, dirs, files in os.walk(path):
                    # Limit depth to avoid excessive scanning
                    level = root.replace(path, '').count(os.sep)
                    if level > 3:
                        continue
                    
                    for file in files:
                        if file.lower().endswith('.exe'):
                            full_path = os.path.join(root, file)
                            exe_apps.append({
                                'name': file.replace('.exe', ''),
                                'type': 'exe',
                                'command': full_path
                            })
            except Exception:
                continue
        
        return exe_apps
    
    def _find_browsers_specifically(self) -> List[Dict]:
        """Find browser applications specifically in their common locations"""
        browsers = []
        
        # Microsoft Edge paths
        edge_paths = [
            "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
            "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
            f"C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Local\\Microsoft\\Edge\\Application\\msedge.exe"
        ]
        
        for path in edge_paths:
            if os.path.exists(path):
                browsers.append({
                    'name': 'Microsoft Edge',
                    'type': 'browser',
                    'command': path,
                    'keywords': ['edge', 'microsoft', 'browser', 'web', 'internet']
                })
                break
        
        # Opera specific paths
        opera_paths = [
            "C:\\Program Files\\Opera\\opera.exe",
            "C:\\Program Files (x86)\\Opera\\opera.exe",
            f"C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Local\\Programs\\Opera\\opera.exe",
            f"C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Roaming\\Opera Software\\Opera Stable\\opera.exe"
        ]
        
        for path in opera_paths:
            if os.path.exists(path):
                browsers.append({
                    'name': 'Opera',
                    'type': 'browser',
                    'command': path,
                    'keywords': ['opera', 'browser', 'web', 'internet', 'youtube']
                })
                break
        
        # Chrome paths
        chrome_paths = [
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            f"C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"
        ]
        
        for path in chrome_paths:
            if os.path.exists(path):
                browsers.append({
                    'name': 'Google Chrome',
                    'type': 'browser',
                    'command': path,
                    'keywords': ['chrome', 'google', 'browser', 'web', 'internet']
                })
                break
        
        # Firefox paths
        firefox_paths = [
            "C:\\Program Files\\Mozilla Firefox\\firefox.exe",
            "C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe"
        ]
        
        for path in firefox_paths:
            if os.path.exists(path):
                browsers.append({
                    'name': 'Mozilla Firefox',
                    'type': 'browser',
                    'command': path,
                    'keywords': ['firefox', 'mozilla', 'browser', 'web', 'internet']
                })
                break
        
        return browsers
    
    def _get_system_apps(self) -> List[Dict]:
        """Get system applications"""
        system_apps = []
        
        system_commands = [
            'notepad', 'calc', 'mspaint', 'wordpad', 'msedge', 'control',
            'explorer', 'cmd', 'powershell', 'regedit', 'msconfig',
            'taskmgr', 'services.msc', 'mmc', 'perfmon'
        ]
        
        if os.name == 'nt':  # Windows only
            for cmd in system_commands:
                try:
                    result = subprocess.run(['where', cmd], capture_output=True, text=True, timeout=2)
                    if result.returncode == 0:
                        system_apps.append({
                            'name': cmd,
                            'type': 'system',
                            'command': cmd
                        })
                except Exception:
                    continue
        
        return system_apps
    
    def _get_uri_apps(self) -> List[Dict]:
        """Get URI-based applications"""
        uri_apps = [
            {'name': 'Windows Clock', 'type': 'uri', 'command': 'ms-clock:'},
            {'name': 'Windows Calendar', 'type': 'uri', 'command': 'outlookcal:'},
            {'name': 'Windows Mail', 'type': 'uri', 'command': 'mailto:'},
            {'name': 'Windows Calculator', 'type': 'uri', 'command': 'calculator:'},
            {'name': 'Windows Settings', 'type': 'uri', 'command': 'ms-settings:'},
            {'name': 'Windows Store', 'type': 'uri', 'command': 'ms-windows-store:'},
            {'name': 'Windows Maps', 'type': 'uri', 'command': 'bingmaps:'},
            {'name': 'Windows Camera', 'type': 'uri', 'command': 'microsoft.windows.camera:'},
            {'name': 'Windows Photos', 'type': 'uri', 'command': 'ms-photos:'}
        ]
        
        return uri_apps
    
    def find_best_app_for_task(self, task_description: str) -> Optional[Dict]:
        """Dynamically find the best app for a given task description"""
        if not self.all_apps:
            self.discover_all_applications()
        
        task_lower = task_description.lower()
        print(f"🎯 Finding best app for task: '{task_description}'")
        
        # Determine task category
        task_category = self._categorize_task(task_description)
        print(f"📂 Task category: {task_category}")
        
        # Score all apps
        candidates = []
        
        for app_type, apps in self.all_apps.items():
            for app in apps:
                score = self._score_app_for_task(app, task_category, task_lower)
                if score > 0:
                    candidates.append((score, app))
        
        # Sort by score and return best match
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_app = candidates[0][1]
            print(f"🏆 Best app: {best_app['name']} (score: {candidates[0][0]})")
            
            # Show top candidates
            print("📊 Top candidates:")
            for i, (score, app) in enumerate(candidates[:5]):
                print(f"   {i+1}. {app['name']} ({app['type']}) - Score: {score}")
            
            return best_app
        
        print("❌ No suitable app found")
        return None
    
    def _categorize_task(self, task_description: str) -> str:
        """Categorize the task based on description"""
        task_lower = task_description.lower()
        
        # Check each category
        for category, keywords in self.task_keywords.items():
            if any(keyword in task_lower for keyword in keywords):
                return category
        
        # Default categorization based on action verbs
        if any(verb in task_lower for verb in ['set alarm', 'wake me', 'reminder']):
            return 'alarm_timer'
        elif any(verb in task_lower for verb in ['send email', 'compose', 'mail']):
            return 'email'
        elif any(verb in task_lower for verb in ['write', 'document', 'note']):
            return 'document'
        elif any(verb in task_lower for verb in ['browse', 'website', 'search']):
            return 'browser'
        elif any(verb in task_lower for verb in ['calculate', 'math', 'compute']):
            return 'calculator'
        
        return 'general'
    
    def _score_app_for_task(self, app: Dict, task_category: str, task_description: str) -> int:
        """Score an app's suitability for a task"""
        score = 0
        
        # Safety check - make sure app has a name
        if not app.get('name'):
            return 0
            
        app_name_lower = app['name'].lower()
        task_description_lower = task_description.lower()
        
        # HIGHEST PRIORITY: Exact app name matches
        specific_app_names = {
            'edge': ['edge', 'microsoft edge', 'msedge'],
            'opera': ['opera'],
            'chrome': ['chrome', 'google chrome'],
            'firefox': ['firefox', 'mozilla firefox'],
            'calculator': ['calc', 'calculator'],
            'notepad': ['notepad'],
            'word': ['word', 'microsoft word'],
            'excel': ['excel', 'microsoft excel']
        }
        
        # Check for specific app requests
        for requested_app, app_variants in specific_app_names.items():
            if any(f'open {variant}' in task_description_lower or f'launch {variant}' in task_description_lower or f'start {variant}' in task_description_lower for variant in app_variants):
                # User specifically requested this app
                for variant in app_variants:
                    if variant in app_name_lower:
                        score += 500  # VERY HIGH priority for specific requests
                        break
        
        # Special high-priority scoring for browsers
        browser_keywords = ['opera', 'chrome', 'firefox', 'browser', 'youtube', 'website', 'web', 'internet', 'go to']
        if any(keyword in task_description_lower for keyword in browser_keywords):
            # Check if this is a browser app
            known_browsers = ['opera', 'chrome', 'firefox', 'edge', 'brave', 'vivaldi']
            if any(browser in app_name_lower for browser in known_browsers):
                score += 200  # Very high priority for browsers
                
                # Extra bonus for specific browser if mentioned
                if 'opera' in task_description_lower and 'opera' in app_name_lower:
                    score += 300
                elif 'chrome' in task_description_lower and 'chrome' in app_name_lower:
                    score += 300
                elif 'firefox' in task_description_lower and 'firefox' in app_name_lower:
                    score += 300
                elif 'edge' in task_description_lower and 'edge' in app_name_lower:
                    score += 300
        
        # Enhanced browser type scoring
        if app.get('type') == 'browser':
            score += 100  # High priority for browser type apps
            
            # Check if browser keywords are in app's keywords
            if app.get('keywords'):
                for keyword in app['keywords']:
                    if keyword in task_description_lower:
                        score += 50
        
        # Category-specific scoring
        if task_category in self.task_keywords:
            category_keywords = self.task_keywords[task_category]
            
            # Exact keyword matches
            for keyword in category_keywords:
                if keyword == app_name_lower:
                    score += 50  # Exact match
                elif keyword in app_name_lower:
                    score += 20  # Contains keyword
                elif any(part in app_name_lower for part in keyword.split()):
                    score += 10  # Partial match
        
        # Direct task description matching
        task_words = task_description.split()
        for word in task_words:
            if word.lower() in app_name_lower:
                score += 15
        
        # App type preferences
        if app.get('type') == 'uri':
            score += 15  # Prefer Windows native apps
        elif app.get('type') == 'system':
            score += 10  # System apps are reliable
        elif app.get('type') == 'uwp':
            score += 5   # UWP apps are modern
        
        # Penalty for very long names (likely not the right app)
        if len(app_name_lower) > 50:
            score -= 10
        
        # Bonus for common productivity apps
        productivity_indicators = ['microsoft', 'windows', 'office']
        if any(indicator in app_name_lower for indicator in productivity_indicators):
            score += 5
        
        return max(0, score)

    def _validate_app_command(self, app_info: Dict) -> bool:
        """Validate app command before launch"""
        try:
            cmd = app_info.get('command')
            if not cmd:
                return False
            t = app_info.get('type')
            if t == 'exe':
                # Handle quoted paths and clean them
                clean_cmd = cmd.strip('"').strip("'")
                exists = os.path.exists(clean_cmd)
                if not exists:
                    print(f"Debug: Path '{clean_cmd}' does not exist")
                return exists
            if t in ('system', 'uwp', 'uri'):
                return True
            return False
        except Exception as e:
            print(f"Debug: Validation error for {app_info.get('name')}: {e}")
            return False
    
    def test_app_launch(self, app_info: Dict) -> bool:
        """Test if an app can be launched successfully"""
        try:
            cmd = app_info.get('command')
            t = app_info.get('type')
            
            # Enhanced validation and fallback launching
            if t == 'exe':
                # Try multiple approaches for exe files
                clean_cmd = cmd.strip('"').strip("'") if cmd else ""
                
                # Method 1: Direct path execution
                if clean_cmd and os.path.exists(clean_cmd):
                    subprocess.Popen([clean_cmd])
                    return True
                
                # Method 2: Try the original command as-is
                if cmd:
                    try:
                        subprocess.Popen([cmd])
                        return True
                    except Exception:
                        pass
                
                # Method 3: For Opera specifically, try common paths
                if 'opera' in app_info.get('name', '').lower():
                    opera_paths = [
                        "C:\\Program Files\\Opera\\opera.exe",
                        "C:\\Program Files (x86)\\Opera\\opera.exe",
                        f"C:\\Users\\{os.getenv('USERNAME')}\\AppData\\Local\\Programs\\Opera\\opera.exe"
                    ]
                    for opera_path in opera_paths:
                        if os.path.exists(opera_path):
                            subprocess.Popen([opera_path])
                            return True
                
                print(f"Could not launch {app_info.get('name')}: Invalid exe path '{cmd}'")
                return False
                
            elif t == 'uwp':
                subprocess.Popen(['explorer', cmd])
                return True
            elif t == 'uri':
                subprocess.Popen(['start', cmd], shell=True)
                return True
            elif t == 'system':
                subprocess.Popen([cmd])
                return True
            else:
                # Default case - try as exe
                clean_cmd = cmd.strip('"').strip("'") if cmd else ""
                if clean_cmd and os.path.exists(clean_cmd):
                    subprocess.Popen([clean_cmd])
                    return True
                elif cmd:
                    subprocess.Popen([cmd])
                    return True
                
            return False
            
        except Exception as e:
            print(f"Failed to launch {app_info.get('name', 'unknown')}: {e}")
            return False
    
    def launch_app_and_take_screenshot(self, app_info: Dict) -> Optional[str]:
        """Launch an app and take a screenshot of the result"""
        print(f"🚀 Launching {app_info['name']}...")
        
        if self.test_app_launch(app_info):
            # Wait for app to load
            time.sleep(3)
            
            # Take screenshot
            import pyautogui
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            base_dir = None
            if Config and getattr(Config, 'AUTOMATION_SCREENSHOT_PATH', None):
                base_dir = Path(getattr(Config, 'AUTOMATION_SCREENSHOT_PATH')).resolve()
            else:
                base_dir = (Path(__file__).resolve().parent.parent / 'cache' / 'screenshots').resolve()
            base_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = str(base_dir / f"app_launch_{timestamp}.png")
            
            try:
                screenshot = pyautogui.screenshot()
                screenshot.save(screenshot_path)
                print(f"📸 Screenshot saved: {screenshot_path}")
                return screenshot_path
            except Exception as e:
                print(f"Failed to take screenshot: {e}")
                return None
        
        return None

def test_dynamic_app_selection():
    """Test the dynamic app selection system"""
    print("🚀 Testing Dynamic App Selection System")
    print("=" * 60)
    
    selector = DynamicAppSelector()
    selector.discover_all_applications()
    
    # Test different task types
    test_tasks = [
        "set an alarm for 7 AM",
        "send an email",
        "write a document",
        "open calculator",
        "browse the internet",
        "edit a photo",
        "play music"
    ]
    
    print("\n🎯 Testing App Selection for Different Tasks:")
    print("-" * 50)
    
    for task in test_tasks:
        print(f"\n📋 Task: '{task}'")
        best_app = selector.find_best_app_for_task(task)
        
        if best_app:
            print(f"✅ Selected: {best_app['name']} ({best_app['type']})")
            print(f"   Command: {best_app['command']}")
        else:
            print("❌ No suitable app found")
    
    print("\n" + "=" * 60)
    print("🎉 Dynamic App Selection System Ready!")

if __name__ == "__main__":
    test_dynamic_app_selection()
