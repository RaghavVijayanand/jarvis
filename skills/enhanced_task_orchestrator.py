#!/usr/bin/env python3
"""
Enhanced Task Orchestrator - Complex Multi-Step Automation
Handles sophisticated workflows like "set an alarm", "send an email", etc.
Uses smart app discovery to find the best apps for each task.
"""

import time
import re
import json
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from skills.screen_automation import ScreenAutomationSkill
from system_control import SystemControl
from skills.app_discovery import SmartAppDiscovery

class EnhancedTaskOrchestrator:
    """Orchestrates complex multi-step automation tasks with smart app discovery"""
    
    def __init__(self):
        self.screen_automation = ScreenAutomationSkill()
        self.system_control = SystemControl()
        self.app_discovery = SmartAppDiscovery()
        
        # Discover available apps
        print("🔍 Discovering available apps for task automation...")
        self.available_apps = self.app_discovery.get_app_info_for_tasks()
        
        # Show what apps we found
        print("📱 Available apps for tasks:")
        for task_type, app_info in self.available_apps.items():
            if app_info:
                print(f"  • {task_type}: {app_info['name']} ({app_info['type']})")
            else:
                print(f"  • {task_type}: No suitable app found")
        
        self.task_definitions = self._build_dynamic_task_definitions()
        
    def _build_dynamic_task_definitions(self) -> Dict:
        """Build task definitions based on discovered apps"""
        definitions = {}
        
        # Alarm/Timer tasks
        alarm_app = self.available_apps.get('alarm_timer')
        if alarm_app:
            definitions["set_alarm"] = {
                "description": f"Set an alarm using {alarm_app['name']}",
                "app_info": alarm_app,
                "steps": [
                    {"action": "open_app", "app_info": alarm_app},
                    {"action": "wait", "duration": 4},
                    {"action": "find_and_click", "targets": ["Alarms", "Alarm", "Set alarm", "Timer"], "required": False},
                    {"action": "wait", "duration": 2},
                    {"action": "find_and_click", "targets": ["Add alarm", "New alarm", "+", "Add", "New"], "required": False},
                    {"action": "wait", "duration": 2},
                    {"action": "set_time", "extract_from_command": True},
                    {"action": "find_and_click", "targets": ["Save", "OK", "Done", "Set"], "required": False}
                ]
            }
            
            definitions["set_timer"] = {
                "description": f"Set a timer using {alarm_app['name']}",
                "app_info": alarm_app,
                "steps": [
                    {"action": "open_app", "app_info": alarm_app},
                    {"action": "wait", "duration": 4},
                    {"action": "find_and_click", "targets": ["Timer", "Timers", "Stopwatch"], "required": False},
                    {"action": "wait", "duration": 2},
                    {"action": "set_timer_duration", "extract_from_command": True},
                    {"action": "find_and_click", "targets": ["Start", "Begin", "Go", "Play"], "required": False}
                ]
            }
        
        # Email tasks
        email_app = self.available_apps.get('email')
        if email_app:
            definitions["send_email"] = {
                "description": f"Send an email using {email_app['name']}",
                "app_info": email_app,
                "steps": [
                    {"action": "open_app", "app_info": email_app},
                    {"action": "wait", "duration": 5},
                    {"action": "find_and_click", "targets": ["New", "Compose", "New email", "Write", "New message"], "required": False},
                    {"action": "wait", "duration": 3},
                    {"action": "type_text", "extract_from_command": "recipient"},
                    {"action": "press_key", "target": "tab"},
                    {"action": "type_text", "extract_from_command": "subject"},
                    {"action": "press_key", "target": "tab"},
                    {"action": "type_text", "extract_from_command": "body"}
                ]
            }
        
        # Document creation tasks
        doc_app = self.available_apps.get('document')
        if doc_app:
            definitions["create_document"] = {
                "description": f"Create a new document using {doc_app['name']}",
                "app_info": doc_app,
                "steps": [
                    {"action": "open_app", "app_info": doc_app},
                    {"action": "wait", "duration": 3},
                    {"action": "type_text", "extract_from_command": "content"}
                ]
            }
        
        # Browser tasks
        browser_app = self.available_apps.get('browser')
        if browser_app:
            definitions["open_website"] = {
                "description": f"Open a website using {browser_app['name']}",
                "app_info": browser_app,
                "steps": [
                    {"action": "open_app", "app_info": browser_app},
                    {"action": "wait", "duration": 4},
                    {"action": "key_combo", "target": "ctrl+l"},
                    {"action": "wait", "duration": 1},
                    {"action": "type_text", "extract_from_command": "url"},
                    {"action": "press_key", "target": "enter"}
                ]
            }
        
        # Calculator tasks
        calc_app = self.available_apps.get('calculator')
        if calc_app:
            definitions["calculate"] = {
                "description": f"Open calculator using {calc_app['name']}",
                "app_info": calc_app,
                "steps": [
                    {"action": "open_app", "app_info": calc_app},
                    {"action": "wait", "duration": 2}
                ]
            }
        
        # Screenshot (system-level)
        definitions["take_screenshot"] = {
            "description": "Take a screenshot using Windows Snipping Tool",
            "steps": [
                {"action": "key_combo", "target": "win+shift+s"},
                {"action": "wait", "duration": 2}
            ]
        }
        
        return definitions
    
    def execute_task(self, command: str) -> Dict:
        """Execute a complex task based on natural language command"""
        # Identify the task type
        task_type = self._identify_task_type(command)
        
        if not task_type:
            return {
                "success": False,
                "message": "Could not identify task type from command",
                "command": command
            }
        
        # Extract parameters from command
        parameters = self._extract_parameters(command, task_type)
        
        # Get task definition
        task_def = self.task_definitions.get(task_type)
        if not task_def:
            return {
                "success": False,
                "message": f"Task type '{task_type}' not supported (no suitable app found)",
                "command": command
            }
        
        # Execute the task steps
        return self._execute_task_steps(task_def, parameters, command)
    
    def _identify_task_type(self, command: str) -> Optional[str]:
        """Identify the type of task from the command"""
        command_lower = command.lower()
        
        # Alarm patterns
        if any(phrase in command_lower for phrase in [
            "set alarm", "set an alarm", "alarm for", "wake me up"
        ]):
            return "set_alarm"
        
        # Email patterns
        if any(phrase in command_lower for phrase in [
            "send email", "send an email", "email", "compose email"
        ]):
            return "send_email"
        
        # Timer patterns
        if any(phrase in command_lower for phrase in [
            "set timer", "start timer", "timer for"
        ]):
            return "set_timer"
        
        # Website patterns
        if any(phrase in command_lower for phrase in [
            "open website", "go to website", "navigate to", "visit"
        ]) and any(domain in command_lower for domain in [".com", ".org", ".net", "http", "www"]):
            return "open_website"
        
        # Document patterns
        if any(phrase in command_lower for phrase in [
            "create document", "new document", "write document", "open document"
        ]):
            return "create_document"
        
        # Calculator patterns
        if any(phrase in command_lower for phrase in [
            "open calculator", "calculator", "calc"
        ]):
            return "calculate"
        
        # Screenshot patterns
        if any(phrase in command_lower for phrase in [
            "take screenshot", "screenshot", "capture screen", "snip"
        ]):
            return "take_screenshot"
        
        return None
    
    def _extract_parameters(self, command: str, task_type: str) -> Dict:
        """Extract parameters from the command for the specific task type"""
        parameters = {}
        command_lower = command.lower()
        
        if task_type == "set_alarm":
            # Extract time
            time_match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', command_lower)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                period = time_match.group(3)
                
                if period == "pm" and hour != 12:
                    hour += 12
                elif period == "am" and hour == 12:
                    hour = 0
                
                parameters["time"] = f"{hour:02d}:{minute:02d}"
            
            # Extract relative time (in X minutes/hours)
            relative_match = re.search(r'in (\d+) (minute|hour|min|hr)s?', command_lower)
            if relative_match:
                amount = int(relative_match.group(1))
                unit = relative_match.group(2)
                
                now = datetime.now()
                if unit.startswith('hour') or unit == 'hr':
                    future_time = now + timedelta(hours=amount)
                else:
                    future_time = now + timedelta(minutes=amount)
                
                parameters["time"] = future_time.strftime("%H:%M")
        
        elif task_type == "send_email":
            # Extract email components
            if "to " in command_lower:
                recipient_match = re.search(r'to ([^,\s]+@[^,\s]+)', command_lower)
                if recipient_match:
                    parameters["recipient"] = recipient_match.group(1).strip()
            
            if "subject " in command_lower:
                subject_match = re.search(r'subject (.+?)(?:\s+body|\s+message|$)', command_lower)
                if subject_match:
                    parameters["subject"] = subject_match.group(1).strip()
            
            if "body " in command_lower or "message " in command_lower:
                body_match = re.search(r'(?:body|message) (.+)', command_lower)
                if body_match:
                    parameters["body"] = body_match.group(1).strip()
        
        elif task_type == "set_timer":
            # Extract timer duration
            duration_patterns = [
                r'(\d+) minute[s]?',
                r'(\d+) min[s]?',
                r'(\d+) hour[s]?',
                r'(\d+) hr[s]?',
                r'(\d+):(\d{2})',  # MM:SS format
                r'(\d+) second[s]?'
            ]
            
            for pattern in duration_patterns:
                match = re.search(pattern, command_lower)
                if match:
                    parameters["duration"] = match.group(0)
                    break
        
        elif task_type == "open_website":
            # Extract URL
            url_patterns = [
                r'(https?://[^\s]+)',
                r'(www\.[^\s]+)',
                r'([a-zA-Z0-9-]+\.[a-zA-Z]{2,})'
            ]
            
            for pattern in url_patterns:
                match = re.search(pattern, command)
                if match:
                    url = match.group(1)
                    if not url.startswith('http'):
                        url = 'https://' + url
                    parameters["url"] = url
                    break
        
        elif task_type == "create_document":
            # Extract document content
            content_patterns = [
                r'about (.+)',
                r'with content (.+)',
                r'containing (.+)'
            ]
            
            for pattern in content_patterns:
                match = re.search(pattern, command_lower)
                if match:
                    parameters["content"] = match.group(1).strip()
                    break
        
        return parameters
    
    def _execute_task_steps(self, task_def: Dict, parameters: Dict, original_command: str) -> Dict:
        """Execute the steps for a specific task"""
        steps_executed = []
        
        try:
            print(f"\n🚀 Executing task: {task_def['description']}")
            
            for i, step in enumerate(task_def["steps"]):
                print(f"🔄 Step {i+1}: {step['action']}")
                
                result = self._execute_step(step, parameters, original_command)
                steps_executed.append({
                    "step": i+1,
                    "action": step["action"],
                    "result": result
                })
                
                # Continue even if some steps fail (for UWP apps that might have different UI)
                if not result.get("success", True) and step.get("required", False):
                    print(f"⚠️ Required step failed: {result.get('message', 'Unknown error')}")
                    # Don't stop execution for non-critical steps
                
            return {
                "success": True,
                "message": f"Successfully completed: {task_def['description']}",
                "steps_executed": steps_executed,
                "task": task_def["description"]
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error executing task: {str(e)}",
                "steps_executed": steps_executed,
                "task": task_def["description"]
            }
    
    def _execute_step(self, step: Dict, parameters: Dict, original_command: str) -> Dict:
        """Execute a single step of the task"""
        action = step["action"]
        
        try:
            if action == "open_app":
                app_info = step.get("app_info", {})
                
                if app_info.get('type') == 'uwp':
                    # UWP app
                    command = ['explorer', app_info['command']]
                elif app_info.get('type') == 'uri':
                    # URI-based app (like ms-clock:)
                    command = ['start', app_info['command']]
                elif app_info.get('type') == 'system':
                    # System command
                    command = [app_info['command']]
                else:
                    # Executable
                    command = [app_info['command']]
                
                try:
                    if app_info.get('type') == 'uri':
                        # Use shell execution for URIs
                        subprocess.run(command, shell=True)
                    else:
                        subprocess.Popen(command)
                    return {"success": True, "message": f"Opened {app_info['name']}"}
                except Exception as e:
                    return {"success": False, "message": f"Failed to open app: {str(e)}"}
            
            elif action == "wait":
                duration = step.get("duration", 1)
                time.sleep(duration)
                return {"success": True, "message": f"Waited {duration} seconds"}
            
            elif action == "find_and_click":
                targets = step.get("targets", [])
                
                # Try each target until one works
                for target in targets:
                    result = self.screen_automation.find_and_click_element(target)
                    if result.get("success", False):
                        return {"success": True, "message": f"Clicked '{target}'"}
                
                # If none worked, return info but don't fail completely
                return {"success": False, "message": f"Could not find any of: {targets}"}
            
            elif action == "type_text":
                if step.get("extract_from_command"):
                    # Extract text based on the parameter type
                    param_type = step.get("extract_from_command")
                    if param_type == True:
                        text = original_command  # Use full command
                    else:
                        text = parameters.get(param_type, "")
                else:
                    text = step.get("target", "")
                
                if text:
                    import pyautogui
                    pyautogui.typewrite(text, interval=0.05)
                    return {"success": True, "message": f"Typed: {text}"}
                else:
                    return {"success": False, "message": "No text to type"}
            
            elif action == "press_key":
                key = step.get("target", "")
                import pyautogui
                pyautogui.press(key)
                return {"success": True, "message": f"Pressed key: {key}"}
            
            elif action == "key_combo":
                combo = step.get("target", "")
                import pyautogui
                pyautogui.hotkey(*combo.split('+'))
                return {"success": True, "message": f"Pressed combo: {combo}"}
            
            elif action == "set_time":
                if parameters.get("time"):
                    time_str = parameters["time"]
                    import pyautogui
                    pyautogui.typewrite(time_str, interval=0.1)
                    return {"success": True, "message": f"Set time: {time_str}"}
                else:
                    return {"success": False, "message": "No time specified"}
            
            elif action == "set_timer_duration":
                if parameters.get("duration"):
                    duration = parameters["duration"]
                    import pyautogui
                    pyautogui.typewrite(duration, interval=0.1)
                    return {"success": True, "message": f"Set duration: {duration}"}
                else:
                    return {"success": False, "message": "No duration specified"}
            
            else:
                return {"success": False, "message": f"Unknown action: {action}"}
                
        except Exception as e:
            return {"success": False, "message": f"Step execution error: {str(e)}"}

def process_complex_task(command: str) -> str:
    """Process a complex automation task using enhanced orchestrator"""
    try:
        orchestrator = EnhancedTaskOrchestrator()
        result = orchestrator.execute_task(command)
        
        if result.get("success", False):
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"
    except Exception as e:
        return f"❌ Task orchestration error: {str(e)}"
