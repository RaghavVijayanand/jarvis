#!/usr/bin/env python3
"""
Task Orchestrator - Complex Multi-Step Automation
Handles sophisticated workflows like "set an alarm", "send an email", etc.
"""

import time
import re
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from skills.screen_automation import ScreenAutomationSkill
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from system_control import SystemControl

class TaskOrchestrator:
    """Orchestrates complex multi-step automation tasks"""
    
    def __init__(self):
        self.screen_automation = ScreenAutomationSkill()
        self.system_control = SystemControl()
        self.task_definitions = self._load_task_definitions()
        
    def _load_task_definitions(self) -> Dict:
        """Load predefined task workflows"""
        return {
            "set_alarm": {
                "description": "Set an alarm in Windows Clock app",
                "app": "ms-clock:",
                "fallback_app": "alarm",
                "steps": [
                    {"action": "open_app", "target": "ms-clock:", "fallback": "alarm"},
                    {"action": "wait", "duration": 2},
                    {"action": "click", "target": "Alarms", "alternatives": ["Alarm", "Set alarm"]},
                    {"action": "wait", "duration": 1},
                    {"action": "click", "target": "Add alarm", "alternatives": ["New alarm", "+", "Add"]},
                    {"action": "wait", "duration": 1},
                    {"action": "set_time", "extract_from_command": True},
                    {"action": "click", "target": "Save", "alternatives": ["OK", "Done", "Set"]}
                ]
            },
            "send_email": {
                "description": "Send an email using default mail app",
                "app": "mailto:",
                "fallback_app": "mail",
                "steps": [
                    {"action": "open_app", "target": "mailto:", "fallback": "mail"},
                    {"action": "wait", "duration": 3},
                    {"action": "click", "target": "New", "alternatives": ["Compose", "New email", "Write"]},
                    {"action": "wait", "duration": 2},
                    {"action": "type_text", "extract_from_command": "recipient"},
                    {"action": "press_key", "target": "tab"},
                    {"action": "type_text", "extract_from_command": "subject"},
                    {"action": "press_key", "target": "tab"},
                    {"action": "type_text", "extract_from_command": "body"},
                    {"action": "key_combo", "target": "ctrl+enter"}
                ]
            },
            "set_reminder": {
                "description": "Set a reminder in Windows Calendar/Reminder app",
                "app": "outlookcal:",
                "fallback_app": "calendar",
                "steps": [
                    {"action": "open_app", "target": "outlookcal:", "fallback": "calendar"},
                    {"action": "wait", "duration": 3},
                    {"action": "click", "target": "New event", "alternatives": ["New", "Add event", "+"]},
                    {"action": "wait", "duration": 2},
                    {"action": "type_text", "extract_from_command": "title"},
                    {"action": "press_key", "target": "tab"},
                    {"action": "set_datetime", "extract_from_command": True},
                    {"action": "click", "target": "Save", "alternatives": ["OK", "Done"]}
                ]
            },
            "open_website": {
                "description": "Open a specific website",
                "app": "browser",
                "steps": [
                    {"action": "open_app", "target": "msedge", "fallback": "chrome"},
                    {"action": "wait", "duration": 3},
                    {"action": "key_combo", "target": "ctrl+l"},
                    {"action": "wait", "duration": 0.5},
                    {"action": "type_text", "extract_from_command": "url"},
                    {"action": "press_key", "target": "enter"}
                ]
            },
            "create_document": {
                "description": "Create a new document",
                "app": "winword",
                "fallback_app": "notepad",
                "steps": [
                    {"action": "open_app", "target": "winword", "fallback": "notepad"},
                    {"action": "wait", "duration": 4},
                    {"action": "click", "target": "Blank document", "alternatives": ["New", "Create"]},
                    {"action": "wait", "duration": 2},
                    {"action": "type_text", "extract_from_command": "content"}
                ]
            },
            "set_timer": {
                "description": "Set a timer in Clock app",
                "app": "ms-clock:",
                "steps": [
                    {"action": "open_app", "target": "ms-clock:"},
                    {"action": "wait", "duration": 2},
                    {"action": "click", "target": "Timer", "alternatives": ["Timers"]},
                    {"action": "wait", "duration": 1},
                    {"action": "set_timer_duration", "extract_from_command": True},
                    {"action": "click", "target": "Start", "alternatives": ["Begin", "Go"]}
                ]
            },
            "take_screenshot": {
                "description": "Take a screenshot and save it",
                "steps": [
                    {"action": "key_combo", "target": "win+shift+s"},
                    {"action": "wait", "duration": 1},
                    {"action": "drag_select", "instruction": "Select area for screenshot"}
                ]
            }
        }
    
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
                "message": f"Task type '{task_type}' not supported",
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
        
        # Reminder patterns
        if any(phrase in command_lower for phrase in [
            "set reminder", "remind me", "create reminder", "schedule reminder"
        ]):
            return "set_reminder"
        
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
            "create document", "new document", "write document", "open word"
        ]):
            return "create_document"
        
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
                recipient_match = re.search(r'to ([^,]+)', command_lower)
                if recipient_match:
                    parameters["recipient"] = recipient_match.group(1).strip()
            
            if "subject " in command_lower:
                subject_match = re.search(r'subject (.+?)(?:body|$)', command_lower)
                if subject_match:
                    parameters["subject"] = subject_match.group(1).strip()
            
            if "body " in command_lower or "message " in command_lower:
                body_match = re.search(r'(?:body|message) (.+)', command_lower)
                if body_match:
                    parameters["body"] = body_match.group(1).strip()
        
        elif task_type == "set_reminder":
            # Extract reminder details
            reminder_match = re.search(r'remind me (?:to )?(.+?)(?:at|in|on|$)', command_lower)
            if reminder_match:
                parameters["title"] = reminder_match.group(1).strip()
            
            # Extract time/date
            time_patterns = [
                r'at (\d{1,2}):(\d{2})\s*(am|pm)?',
                r'in (\d+) (minute|hour|day)s?',
                r'on (\w+day)'
            ]
            
            for pattern in time_patterns:
                match = re.search(pattern, command_lower)
                if match:
                    parameters["when"] = match.group(0)
                    break
        
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
            for i, step in enumerate(task_def["steps"]):
                print(f"🔄 Step {i+1}: {step['action']}")
                
                result = self._execute_step(step, parameters, original_command)
                steps_executed.append({
                    "step": i+1,
                    "action": step["action"],
                    "result": result
                })
                
                if not result.get("success", True):
                    return {
                        "success": False,
                        "message": f"Failed at step {i+1}: {result.get('message', 'Unknown error')}",
                        "steps_executed": steps_executed,
                        "task": task_def["description"]
                    }
            
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
                app_name = step.get("target", "")
                fallback = step.get("fallback", "")
                
                # Try primary app first
                result = self.system_control.launch_application(app_name)
                if "Error" in result and fallback:
                    result = self.system_control.launch_application(fallback)
                
                return {"success": True, "message": result}
            
            elif action == "wait":
                duration = step.get("duration", 1)
                time.sleep(duration)
                return {"success": True, "message": f"Waited {duration} seconds"}
            
            elif action == "click":
                target = step.get("target", "")
                alternatives = step.get("alternatives", [])
                
                # Try main target first
                result = self.screen_automation.find_and_click_element(target)
                
                # If failed, try alternatives
                if not result.get("success", False):
                    for alt in alternatives:
                        result = self.screen_automation.find_and_click_element(alt)
                        if result.get("success", False):
                            break
                
                return result
            
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
            
            elif action == "drag_select":
                # For screenshot selection
                import pyautogui
                return {"success": True, "message": "Screenshot tool activated"}
            
            else:
                return {"success": False, "message": f"Unknown action: {action}"}
                
        except Exception as e:
            return {"success": False, "message": f"Step execution error: {str(e)}"}

def process_complex_task(command: str) -> str:
    """Process a complex automation task"""
    orchestrator = TaskOrchestrator()
    result = orchestrator.execute_task(command)
    
    if result.get("success", False):
        return f"✅ {result['message']}"
    else:
        return f"❌ {result['message']}"
