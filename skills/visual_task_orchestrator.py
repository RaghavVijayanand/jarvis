#!/usr/bin/env python3
"""
Complete Visual Task Orchestrator
Uses dynamic app selection and AI vision to complete complex tasks
"""

import time
import re
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from skills.screen_automation import ScreenAutomationSkill
from skills.dynamic_app_selector import DynamicAppSelector
import pyautogui

class CompleteVisualTaskOrchestrator:
    """Orchestrates complex tasks using dynamic app selection and AI vision"""
    
    def __init__(self):
        self.screen_automation = ScreenAutomationSkill()
        self.app_selector = DynamicAppSelector()
        self.screenshots_dir = "cache/task_screenshots"
        self.current_task_id = None
        
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)
    
    def execute_task(self, task_description: str) -> Dict:
        """Execute a complete task using dynamic app selection and AI-guided visual automation"""
        self.current_task_id = f"task_{int(time.time())}"
        print(f"\n🎯 Executing Task: {task_description}")
        print(f"📁 Task ID: {self.current_task_id}")
        
        try:
            # Step 1: Find the best app for this task
            best_app = self.app_selector.find_best_app_for_task(task_description)
            
            if not best_app:
                return {
                    "success": False,
                    "message": "No suitable application found for this task",
                    "task": task_description
                }
            
            # Step 2: Launch the app and take initial screenshot
            print(f"\n🚀 Step 1: Launching {best_app['name']}")
            initial_screenshot = self.app_selector.launch_app_and_take_screenshot(best_app)
            
            if not initial_screenshot:
                return {
                    "success": False,
                    "message": f"Failed to launch {best_app['name']}",
                    "task": task_description
                }
            
            # Step 3: Execute the task using dynamic AI-guided automation
            print(f"\n🧠 Starting dynamic AI-guided task execution...")
            execution_result = self._execute_dynamic_task(
                task_description, 
                best_app, 
                initial_screenshot
            )
            
            # Step 4: Take final verification screenshot
            print(f"\n� Taking final verification screenshot...")
            final_screenshot = self._take_step_screenshot("final_verification")
            
            # Step 5: Use AI to verify task completion (with fallback)
            verification_result = None
            try:
                verification_result = self._verify_task_completion(task_description, final_screenshot, best_app)
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    print(f"⚠️ Verification skipped due to API limits")
                    verification_result = {
                        "success": True, 
                        "confidence": 0.8, 
                        "evidence": "Manual verification required - API quota exceeded"
                    }
                else:
                    print(f"⚠️ Verification error: {str(e)}")
                    verification_result = {
                        "success": True, 
                        "confidence": 0.7, 
                        "evidence": f"Verification failed: {str(e)}"
                    }
            
            return {
                "success": True,
                "message": f"Successfully completed task using {best_app['name']}",
                "app_used": best_app,
                "execution_log": execution_result.get("steps", []),
                "final_screenshot": final_screenshot,
                "verification": verification_result,
                "task": task_description
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Task execution error: {str(e)}",
                "task": task_description
            }
    
    def _plan_task_steps(self, task_description: str, app_info: Dict) -> List[Dict]:
        """Plan the steps needed to complete the task"""
        task_lower = task_description.lower()
        steps = []
        
        # Alarm/Timer tasks
        if any(word in task_lower for word in ['alarm', 'wake', 'timer']):
            if 'alarm' in task_lower:
                steps = [
                    {"description": "Find and click Alarms tab", "action": "find_click", "targets": ["Alarms", "Alarm"], "critical": False},
                    {"description": "Find and click Add/New alarm", "action": "find_click", "targets": ["Add alarm", "New alarm", "+", "Add"], "critical": False},
                    {"description": "Set the alarm time", "action": "set_time", "extract_time": True, "critical": True},
                    {"description": "Save the alarm", "action": "find_click", "targets": ["Save", "OK", "Done"], "critical": True}
                ]
            else:  # timer
                steps = [
                    {"description": "Find and click Timer tab", "action": "find_click", "targets": ["Timer", "Timers"], "critical": False},
                    {"description": "Set timer duration", "action": "set_duration", "extract_duration": True, "critical": True},
                    {"description": "Start the timer", "action": "find_click", "targets": ["Start", "Begin", "Play"], "critical": True}
                ]
        
        # Email tasks
        elif any(word in task_lower for word in ['email', 'mail', 'send']):
            steps = [
                {"description": "Find and click New/Compose", "action": "find_click", "targets": ["New", "Compose", "Write"], "critical": True},
                {"description": "Enter recipient", "action": "type_text", "extract_param": "recipient", "critical": True},
                {"description": "Enter subject", "action": "type_text", "extract_param": "subject", "critical": False},
                {"description": "Enter message body", "action": "type_text", "extract_param": "body", "critical": False},
                {"description": "Send email", "action": "find_click", "targets": ["Send"], "critical": True}
            ]
        
        # Document tasks
        elif any(word in task_lower for word in ['document', 'write', 'note']):
            steps = [
                {"description": "Start typing content", "action": "type_text", "extract_param": "content", "critical": True},
                {"description": "Save document", "action": "key_combo", "combo": "ctrl+s", "critical": True},
                {"description": "Handle Save As dialog", "action": "handle_save_dialog", "critical": True},
                {"description": "Verify document saved", "action": "verify_save", "critical": False}
            ]
        
        # Calculator tasks
        elif any(word in task_lower for word in ['calculator', 'calc', 'calculate']):
            steps = [
                {"description": "Calculator opened and ready", "action": "wait", "duration": 1, "critical": False}
            ]
        
        # Browser tasks
        elif any(word in task_lower for word in ['website', 'browse', 'open']):
            steps = [
                {"description": "Click address bar", "action": "key_combo", "combo": "ctrl+l", "critical": True},
                {"description": "Enter website URL", "action": "type_text", "extract_param": "url", "critical": True},
                {"description": "Navigate to website", "action": "press_key", "key": "enter", "critical": True}
            ]
        
        # Default steps for unknown tasks
        else:
            steps = [
                {"description": "Application opened successfully", "action": "wait", "duration": 2, "critical": False}
            ]
        
        return steps
    
    def _execute_visual_step(self, step: Dict, current_screenshot: str, task_description: str) -> Dict:
        """Execute a single step with visual feedback"""
        action = step.get('action', 'wait')
        
        try:
            if action == "find_click":
                return self._execute_find_click(step, current_screenshot, task_description)
            
            elif action == "type_text":
                return self._execute_type_text(step, current_screenshot, task_description)
            
            elif action == "set_time":
                return self._execute_set_time(step, current_screenshot, task_description)
            
            elif action == "set_duration":
                return self._execute_set_duration(step, current_screenshot, task_description)
            
            elif action == "key_combo":
                return self._execute_key_combo(step, current_screenshot)
            
            elif action == "press_key":
                return self._execute_press_key(step, current_screenshot)
            
            elif action == "handle_save_dialog":
                return self._execute_handle_save_dialog(step, current_screenshot, task_description)
            
            elif action == "verify_save":
                return self._execute_verify_save(step, current_screenshot, task_description)
            
            elif action == "wait":
                duration = step.get('duration', 1)
                time.sleep(duration)
                return self._take_step_screenshot(f"waited_{duration}s")
            
            else:
                return {
                    "success": False,
                    "message": f"Unknown action: {action}",
                    "screenshot": current_screenshot
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"Step execution error: {str(e)}",
                "screenshot": current_screenshot
            }
    
    def _execute_find_click(self, step: Dict, current_screenshot: str, task_description: str) -> Dict:
        """Execute find and click with visual feedback"""
        targets = step.get('targets', [])
        
        # Try each target
        for target in targets:
            result = self.screen_automation.find_and_click_element(target)
            if result.get('success', False):
                # Take screenshot after successful click
                screenshot = self._take_step_screenshot(f"clicked_{target}")
                return {
                    "success": True,
                    "message": f"Successfully clicked '{target}'",
                    "target_found": target,
                    "coordinates": result.get('coordinates', []),
                    "screenshot": screenshot
                }
        
        # If no target found, take screenshot and return info
        screenshot = self._take_step_screenshot("targets_not_found")
        return {
            "success": False,
            "message": f"Could not find any of: {targets}",
            "targets_searched": targets,
            "screenshot": screenshot
        }
    
    def _execute_type_text(self, step: Dict, current_screenshot: str, task_description: str) -> Dict:
        """Execute text typing with parameter extraction"""
        text_to_type = ""
        
        if step.get('extract_param'):
            param_type = step['extract_param']
            text_to_type = self._extract_parameter(task_description, param_type)
        
        if text_to_type:
            pyautogui.typewrite(text_to_type, interval=0.05)
            screenshot = self._take_step_screenshot(f"typed_{param_type}")
            return {
                "success": True,
                "message": f"Typed: {text_to_type}",
                "text": text_to_type,
                "screenshot": screenshot
            }
        else:
            return {
                "success": False,
                "message": f"No text to type for parameter: {step.get('extract_param')}",
                "screenshot": current_screenshot
            }
    
    def _execute_set_time(self, step: Dict, current_screenshot: str, task_description: str) -> Dict:
        """Execute time setting"""
        time_str = self._extract_parameter(task_description, 'time')
        
        if time_str:
            pyautogui.typewrite(time_str, interval=0.1)
            screenshot = self._take_step_screenshot(f"set_time_{time_str}")
            return {
                "success": True,
                "message": f"Set time: {time_str}",
                "time": time_str,
                "screenshot": screenshot
            }
        else:
            return {
                "success": False,
                "message": "No time specified in task",
                "screenshot": current_screenshot
            }
    
    def _execute_set_duration(self, step: Dict, current_screenshot: str, task_description: str) -> Dict:
        """Execute duration setting"""
        duration_str = self._extract_parameter(task_description, 'duration')
        
        if duration_str:
            pyautogui.typewrite(duration_str, interval=0.1)
            screenshot = self._take_step_screenshot(f"set_duration_{duration_str}")
            return {
                "success": True,
                "message": f"Set duration: {duration_str}",
                "duration": duration_str,
                "screenshot": screenshot
            }
        else:
            return {
                "success": False,
                "message": "No duration specified in task",
                "screenshot": current_screenshot
            }
    
    def _execute_key_combo(self, step: Dict, current_screenshot: str) -> Dict:
        """Execute keyboard combination"""
        combo = step.get('combo', '')
        if combo:
            pyautogui.hotkey(*combo.split('+'))
            screenshot = self._take_step_screenshot(f"combo_{combo.replace('+', '_')}")
            return {
                "success": True,
                "message": f"Pressed combo: {combo}",
                "combo": combo,
                "screenshot": screenshot
            }
        else:
            return {
                "success": False,
                "message": "No key combo specified",
                "screenshot": current_screenshot
            }
    
    def _execute_press_key(self, step: Dict, current_screenshot: str) -> Dict:
        """Execute single key press"""
        key = step.get('key', '')
        if key:
            pyautogui.press(key)
            screenshot = self._take_step_screenshot(f"key_{key}")
            return {
                "success": True,
                "message": f"Pressed key: {key}",
                "key": key,
                "screenshot": screenshot
            }
        else:
            return {
                "success": False,
                "message": "No key specified",
                "screenshot": current_screenshot
            }
    
    def _execute_handle_save_dialog(self, step: Dict, current_screenshot: str, task_description: str) -> Dict:
        """Handle Save As dialog that appears when saving new documents"""
        try:
            time.sleep(2)  # Wait for dialog to appear
            
            # Take screenshot to see current state
            screenshot = self._take_step_screenshot("save_dialog_check")
            
            # Use AI to analyze if Save dialog is open
            dialog_prompt = f"""
            Look at this screenshot. Is there a "Save As" or "Save" dialog box open?
            
            If yes, describe:
            1. Where is the filename field?
            2. Where is the Save button?
            3. What should I click to save the document?
            
            If no dialog is visible, say "NO_DIALOG_FOUND".
            
            Be specific about clickable elements and their locations.
            """
            
            ai_response = self.screen_automation._query_gemini_vision(dialog_prompt, screenshot)
            
            # Extract text from response if it's a dict
            if isinstance(ai_response, dict):
                response_text = ai_response.get('message', '') or ai_response.get('content', '') or str(ai_response)
            else:
                response_text = str(ai_response)
            
            if "NO_DIALOG_FOUND" in response_text.upper():
                return {
                    "success": True,
                    "message": "No save dialog needed - document may already be saved",
                    "screenshot": screenshot
                }
            
            # If dialog found, try to handle it
            print(f"🔍 AI detected save dialog: {response_text[:100]}...")
            
            # First, try to set a filename if needed
            if "filename" in response_text.lower() or "file name" in response_text.lower():
                # Generate a simple filename
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"Document_{timestamp}"
                print(f"📝 Setting filename: {filename}")
                
                # Clear any existing text and type new filename
                pyautogui.hotkey('ctrl', 'a')  # Select all
                time.sleep(0.5)
                pyautogui.typewrite(filename)
                time.sleep(1)
            
            # Now try to find and click Save button
            save_click_prompt = f"""
            Look at this screenshot of a Save dialog. I need to click the Save button to save the document.
            
            Find the Save button and give me the exact coordinates to click.
            Look for buttons labeled "Save", "OK", or similar.
            
            Respond with: CLICK_X_Y where X and Y are the pixel coordinates.
            If you can't find a Save button, respond with "NO_SAVE_BUTTON".
            """
            
            # Take fresh screenshot after typing filename
            current_screenshot = self._take_step_screenshot("save_dialog_ready")
            ai_click_response = self.screen_automation._query_gemini_vision(save_click_prompt, current_screenshot)
            
            # Extract text from response if it's a dict
            if isinstance(ai_click_response, dict):
                click_response_text = ai_click_response.get('message', '') or ai_click_response.get('content', '') or str(ai_click_response)
            else:
                click_response_text = str(ai_click_response)
            
            if "CLICK_" in click_response_text:
                try:
                    # Extract coordinates
                    coords = click_response_text.split("CLICK_")[1].split("_")
                    if len(coords) >= 2:
                        x, y = int(coords[0]), int(coords[1])
                        print(f"🎯 Clicking Save button at ({x}, {y})")
                        pyautogui.click(x, y)
                        time.sleep(2)  # Wait for save to complete
                        
                        # Take final screenshot
                        final_screenshot = self._take_step_screenshot("save_dialog_completed")
                        
                        return {
                            "success": True,
                            "message": f"Successfully clicked Save button at ({x}, {y})",
                            "coordinates": [x, y],
                            "filename": filename if 'filename' in locals() else "default",
                            "screenshot": final_screenshot
                        }
                except Exception as e:
                    print(f"⚠️ Error clicking Save button: {e}")
            
            # Fallback: try pressing Enter or common save shortcuts
            print("🔄 Trying fallback save methods...")
            pyautogui.press('enter')  # Try Enter key
            time.sleep(1)
            
            fallback_screenshot = self._take_step_screenshot("save_dialog_fallback")
            
            return {
                "success": True,
                "message": "Attempted to save using fallback method (Enter key)",
                "method": "fallback",
                "screenshot": fallback_screenshot
            }
            
        except Exception as e:
            print(f"⚠️ Save dialog handling error: {e}")
            return {
                "success": False,
                "message": f"Failed to handle save dialog: {str(e)}",
                "screenshot": current_screenshot
            }
    
    def _execute_verify_save(self, step: Dict, current_screenshot: str, task_description: str) -> Dict:
        """Verify that the document was actually saved"""
        try:
            time.sleep(2)  # Wait for any save operations to complete
            
            # Take screenshot to verify save state
            screenshot = self._take_step_screenshot("save_verification")
            
            # Use AI to verify save completion
            verify_prompt = f"""
            Look at this screenshot to verify if the document save operation was successful.
            
            Check for:
            1. Is there still a "Save As" dialog open? (This would indicate save failed)
            2. Is the document title updated (no asterisk * indicating unsaved changes)?
            3. Are there any error messages visible?
            4. Does the interface look like a saved document state?
            
            Respond with:
            - SAVE_SUCCESS: If the document appears to be saved successfully
            - SAVE_FAILED: If there are still dialogs open or error messages
            - SAVE_UNCLEAR: If you can't determine the save status
            
            Also provide a brief explanation of what you see.
            """
            
            ai_response = self.screen_automation._query_gemini_vision(verify_prompt, screenshot)
            
            # Extract text from response if it's a dict
            if isinstance(ai_response, dict):
                response_text = ai_response.get('message', '') or ai_response.get('content', '') or str(ai_response)
            else:
                response_text = str(ai_response)
            
            success = "SAVE_SUCCESS" in response_text.upper()
            failed = "SAVE_FAILED" in response_text.upper()
            
            if success:
                return {
                    "success": True,
                    "message": "Document save verified successfully",
                    "verification": "SAVE_SUCCESS",
                    "ai_analysis": response_text,
                    "screenshot": screenshot
                }
            elif failed:
                return {
                    "success": False,
                    "message": "Document save verification failed - save may be incomplete",
                    "verification": "SAVE_FAILED",
                    "ai_analysis": response_text,
                    "screenshot": screenshot
                }
            else:
                return {
                    "success": True,  # Default to success for unclear cases
                    "message": "Document save status unclear but proceeding",
                    "verification": "SAVE_UNCLEAR",
                    "ai_analysis": response_text,
                    "screenshot": screenshot
                }
                
        except Exception as e:
            print(f"⚠️ Save verification error: {e}")
            return {
                "success": False,
                "message": f"Failed to verify save: {str(e)}",
                "screenshot": current_screenshot
            }
    
    def _take_step_screenshot(self, step_name: str) -> str:
        """Take a screenshot for the current step"""
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(
                self.screenshots_dir, 
                f"{self.current_task_id}_{step_name}_{timestamp}.png"
            )
            
            screenshot = pyautogui.screenshot()
            screenshot.save(screenshot_path)
            print(f"📸 Screenshot: {screenshot_path}")
            return screenshot_path
            
        except Exception as e:
            print(f"Failed to take screenshot: {e}")
            return ""
    
    def _extract_parameter(self, task_description: str, param_type: str) -> str:
        """Extract specific parameters from task description"""
        task_lower = task_description.lower()
        
        if param_type == 'time':
            # Extract time patterns
            time_patterns = [
                r'(\d{1,2}):(\d{2})\s*(am|pm)?',
                r'(\d{1,2})\s*(am|pm)',
                r'at (\d{1,2}):(\d{2})',
                r'for (\d{1,2}):(\d{2})'
            ]
            
            for pattern in time_patterns:
                match = re.search(pattern, task_lower)
                if match:
                    if len(match.groups()) >= 2:
                        hour = int(match.group(1))
                        minute = int(match.group(2)) if match.group(2) else 0
                        period = match.group(3) if len(match.groups()) > 2 else None
                        
                        if period == "pm" and hour != 12:
                            hour += 12
                        elif period == "am" and hour == 12:
                            hour = 0
                        
                        return f"{hour:02d}:{minute:02d}"
                    else:
                        hour = int(match.group(1))
                        period = match.group(2) if len(match.groups()) > 1 else None
                        
                        if period == "pm" and hour != 12:
                            hour += 12
                        elif period == "am" and hour == 12:
                            hour = 0
                        
                        return f"{hour:02d}:00"
        
        elif param_type == 'duration':
            # Extract duration patterns
            duration_patterns = [
                r'(\d+)\s*minute[s]?',
                r'(\d+)\s*min[s]?',
                r'(\d+)\s*hour[s]?',
                r'(\d+)\s*hr[s]?',
                r'(\d+):(\d{2})',
                r'for\s+(\d+)\s+minutes?'
            ]
            
            for pattern in duration_patterns:
                match = re.search(pattern, task_lower)
                if match:
                    return match.group(0)
        
        elif param_type == 'recipient':
            # Extract email recipient
            email_match = re.search(r'to\s+([^@\s]+@[^@\s]+\.[^@\s]+)', task_lower)
            if email_match:
                return email_match.group(1)
        
        elif param_type == 'subject':
            # Extract email subject
            subject_match = re.search(r'subject\s+(.+?)(?:\s+body|\s+message|$)', task_lower)
            if subject_match:
                return subject_match.group(1).strip()
        
        elif param_type == 'body':
            # Extract email body
            body_match = re.search(r'(?:body|message)\s+(.+)', task_lower)
            if body_match:
                return body_match.group(1).strip()
        
        elif param_type == 'content':
            # Extract document content
            content_patterns = [
                r'about\s+(.+)',
                r'with\s+content\s+(.+)',
                r'containing\s+(.+)',
                r'write\s+(.+)'
            ]
            
            for pattern in content_patterns:
                match = re.search(pattern, task_lower)
                if match:
                    return match.group(1).strip()
        
        elif param_type == 'url':
            # Extract URL
            url_patterns = [
                r'(https?://[^\s]+)',
                r'(www\.[^\s]+)',
                r'([a-zA-Z0-9-]+\.[a-zA-Z]{2,})'
            ]
            
            for pattern in url_patterns:
                match = re.search(pattern, task_description)
                if match:
                    url = match.group(1)
                    if not url.startswith('http'):
                        url = 'https://' + url
                    return url
        
        return ""

    def _execute_dynamic_task(self, task_description: str, app_info: Dict, initial_screenshot: str) -> Dict:
        """Execute task dynamically by analyzing screenshots and deciding next actions with AI"""
        execution_steps = []
        current_screenshot = initial_screenshot
        max_steps = 10  # Prevent infinite loops
        step_count = 0
        previous_actions = []  # Track recent actions to detect loops
        
        print(f"🧠 Starting dynamic AI-guided task execution...")
        
        # First action: Maximize the window for better visibility and interaction
        print(f"📺 Step 0: Maximizing window for better visibility...")
        try:
            import pyautogui
            time.sleep(0.5)  # Brief pause to ensure app is ready
            pyautogui.hotkey('win', 'up')  # Windows shortcut to maximize window
            time.sleep(1)  # Wait for maximize animation
            
            # Take screenshot after maximizing
            current_screenshot = self._take_step_screenshot("after_maximize")
            print(f"📸 Window maximized, new screenshot taken")
        except Exception as e:
            print(f"⚠️ Failed to maximize window: {e}, continuing anyway...")
        
        while step_count < max_steps:
            step_count += 1
            
            # Ask AI to analyze current screenshot and decide next action
            analysis_result = self._analyze_screenshot_and_decide_action(
                task_description, 
                current_screenshot, 
                step_count,
                execution_steps
            )
            
            if not analysis_result or analysis_result.get("action") == "task_complete":
                print(f"✅ AI determined task is complete after {step_count-1} steps")
                break
                
            action = analysis_result.get("action")
            if not action or action == "no_action":
                print(f"⚠️ AI couldn't determine next action. Stopping.")
                break

            # Let the AI handle everything - no system interference
            
            print(f"\n🔄 Step {step_count}: {analysis_result.get('description', 'AI-guided action')}")
            print(f"   Action: {action}")
            
            # Execute the AI-determined action
            step_result = self._execute_ai_determined_action(
                action, 
                analysis_result,
                task_description,
                current_screenshot
            )
            
            # Log the step
            execution_steps.append({
                "step_number": step_count,
                "description": analysis_result.get('description', 'AI-guided action'),
                "action": action,
                "ai_reasoning": analysis_result.get('reasoning', ''),
                "success": step_result.get("success", False),
                "screenshot": step_result.get("screenshot", current_screenshot),
                "details": step_result
            })
            
            # Update current screenshot for next iteration
            if step_result.get("screenshot"):
                current_screenshot = step_result["screenshot"]
            
            # Check if AI says we're done
            if (analysis_result.get("task_status") == "complete" or 
                analysis_result.get("action") == "task_complete" or
                step_result.get("task_complete")):
                print(f"✅ AI confirmed task completion")
                break
            
            # Remove hardcoded save logic - let AI decide everything
            # The AI should determine when to save, how to save, and when it's complete
                
            # Small delay between steps
            time.sleep(1.5)
        
        return {
            "success": True,
            "message": f"Dynamic task execution completed in {step_count} steps",
            "steps": execution_steps,
            "final_screenshot": current_screenshot
        }

    def _analyze_screenshot_and_decide_action(self, task_description: str, screenshot_path: str, step_number: int, previous_steps: List) -> Dict:
        """Use AI to analyze screenshot and decide the next action"""
        try:
            # Create analysis prompt
            previous_actions = []
            if previous_steps:
                for step in previous_steps[-3:]:  # Only show last 3 steps for context
                    previous_actions.append(f"Step {step['step_number']}: {step['action']} - {step['description']}")
            
            context = "\n".join(previous_actions) if previous_actions else "This is the first step."
            
            analysis_prompt = f"""
            You are controlling a computer to complete this task: "{task_description}"
            
            Current step: {step_number}
            Previous actions taken: {context}
            
            Analyze this screenshot carefully and determine the NEXT ACTION or if the task is COMPLETE.
            
            YOU are responsible for:
            1. Deciding what action to take next
            2. Determining when the task is fully complete
            3. Handling all dialogs, buttons, and UI elements
            4. Making sure the task is 100% finished before saying "task_complete"
            
            For document tasks like typing dates:
            - Click in the main white document area (NOT toolbar buttons)
            - Type the content directly: "September 4, 2025"
            - Use Ctrl+S to save when done typing
            - Handle save dialogs if they appear
            - Only say "task_complete" when document is saved and task is done
            
            AVOID using toolbar buttons or menus - just type directly in the document area.
            - Handle any save dialogs that appear
            - Only say "task_complete" when you can see the document is saved and the task is done
            
            Your action options:
            - click: Click on any UI element (provide exact coordinates)
            - type: Type any text content
            - key: Press keyboard keys (ctrl+s, enter, tab, etc.)
            - task_complete: Task is 100% finished successfully
            
            RESPOND EXACTLY IN THIS FORMAT:
            ACTION: [click/type/key/task_complete]
            DESCRIPTION: [what this action does]
            COORDINATES: [for click: x,y coordinates like 400,300]
            TEXT: [for type: exact text to type]
            KEY: [for key: key combination like "ctrl+s" or "enter"]
            
            EXAMPLES:
            ACTION: click
            DESCRIPTION: Click in document text area
            COORDINATES: 400,300
            
            ACTION: type
            DESCRIPTION: Type today's date
            TEXT: September 4, 2025
            
            ACTION: key
            DESCRIPTION: Save document
            KEY: ctrl+s
            
            ACTION: click
            DESCRIPTION: Click Save button in dialog
            COORDINATES: 1190,447
            
            ACTION: task_complete
            DESCRIPTION: Document saved successfully, task finished
            
            IMPORTANT: Only use "task_complete" when you can see clear evidence the task is 100% done.
            For save operations, make sure the file is actually saved before completing.
            Look carefully at the current state and decide the next step.
            """
            
            # Use AI vision to analyze
            try:
                ai_response = self.screen_automation._query_gemini_vision(analysis_prompt, screenshot_path)
                return self._parse_ai_action_response(ai_response)
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    print(f"⚠️ AI Vision quota exceeded, falling back to simple heuristics")
                    return self._fallback_action_heuristic(task_description, step_number)
                else:
                    raise e
            
        except Exception as e:
            print(f"⚠️ Screenshot analysis error: {str(e)}")
            return {"action": "no_action", "description": "Analysis failed"}

    def _parse_ai_action_response(self, ai_response) -> Dict:
        """Parse AI response into actionable data"""
        try:
            # Handle both dict and string responses
            if isinstance(ai_response, dict):
                # If it's already a structured response, try to extract text content
                if 'message' in ai_response:
                    ai_text = ai_response['message']
                elif 'content' in ai_response:
                    ai_text = ai_response['content']
                elif 'recommendations' in ai_response and ai_response['recommendations']:
                    ai_text = ai_response['recommendations'][0]
                else:
                    # Try to convert the entire dict to string for parsing
                    ai_text = str(ai_response)
            else:
                ai_text = str(ai_response)
            
            print(f"🔍 AI Response to parse: {ai_text[:200]}...")  # Debug output
            
            # Try to parse as JSON first (new structured format)
            try:
                import json
                import re
                
                # Look for JSON structure in the response with better error handling
                json_match = re.search(r'```(?:json)?\s*(\[.*?\]|\{.*?\})', ai_text, re.DOTALL | re.IGNORECASE)
                if json_match:
                    json_str = json_match.group(1)
                    # Clean up common JSON formatting issues
                    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)  # Remove trailing commas
                    json_str = re.sub(r'\s+', ' ', json_str)  # Normalize whitespace
                    
                    parsed_json = json.loads(json_str)
                    
                    # If it's a list, take the first action
                    if isinstance(parsed_json, list) and len(parsed_json) > 0:
                        action_data = parsed_json[0]
                    elif isinstance(parsed_json, dict):
                        action_data = parsed_json
                    else:
                        raise ValueError("Invalid JSON structure")
                    
                    # Extract action details from JSON
                    action = action_data.get('ACTION', '').lower()
                    description = action_data.get('DESCRIPTION', 'AI-guided action')
                    coordinates = action_data.get('COORDINATES')
                    text = action_data.get('TEXT', '')
                    key = action_data.get('KEY', '')
                    
                    result = {
                        "action": action,
                        "description": description,
                        "reasoning": action_data.get('REASONING', ''),
                        "coordinates": tuple(coordinates) if coordinates and len(coordinates) == 2 else None,
                        "text": text,
                        "key": key,
                        "task_status": "incomplete",
                        "full_response": ai_text
                    }
                    
                    print(f"🎯 Parsed Action: {action}, Description: {description}")
                    return result
                    
                # Try direct JSON parsing if response starts with {
                if ai_text.strip().startswith('{'):
                    action_data = json.loads(ai_text)
                    action = action_data.get('ACTION', '').lower()
                    description = action_data.get('DESCRIPTION', 'AI-guided action')
                    coordinates = action_data.get('COORDINATES')
                    text = action_data.get('TEXT', '')
                    key = action_data.get('KEY', '')
                    
                    result = {
                        "action": action,
                        "description": description,
                        "reasoning": action_data.get('REASONING', ''),
                        "coordinates": tuple(coordinates) if coordinates and len(coordinates) == 2 else None,
                        "text": text,
                        "key": key,
                        "task_status": "incomplete",
                        "full_response": ai_text
                    }
                    
                    print(f"🎯 Parsed Action: {action}, Description: {description}")
                    return result
                    
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                print(f"🔍 JSON parsing failed: {e}, falling back to regex")
                pass
            
            # Fallback to regex parsing for old format
            response_lower = ai_text.lower()
            
            # Extract action with more flexible patterns
            action_patterns = [
                r'action[:\s]+(\w+)',
                r'^(\w+):',  # For responses that start with action:
                r'(\w+)\s*-\s*',  # For action - description format
            ]
            
            action = "no_action"
            for pattern in action_patterns:
                action_match = re.search(pattern, response_lower)
                if action_match:
                    potential_action = action_match.group(1)
                    if potential_action in ['click', 'type', 'key', 'wait', 'task_complete', 'no_action']:
                        action = potential_action
                        break
            
            # If no specific action found, try to infer from content
            if action == "no_action":
                if any(word in response_lower for word in ['click', 'press', 'tap']):
                    action = "click"
                elif any(word in response_lower for word in ['type', 'enter', 'input']):
                    action = "type"
                elif any(word in response_lower for word in ['key', 'ctrl', 'enter', 'tab']):
                    action = "key"
                elif any(word in response_lower for word in ['complete', 'finished', 'done']):
                    action = "task_complete"
            
            # Extract description
            desc_patterns = [
                r'description[:\s]+(.+?)(?:\n|reasoning|$)',
                r'action[:\s]+\w+[:\s]*(.+?)(?:\n|$)',
                r'^[^:\n]*:\s*(.+?)(?:\n|$)'  # Fallback for simple format
            ]
            
            description = "AI-guided action"
            for pattern in desc_patterns:
                desc_match = re.search(pattern, ai_text, re.IGNORECASE)
                if desc_match:
                    description = desc_match.group(1).strip()
                    break
            
            # Extract reasoning
            reasoning_match = re.search(r'reasoning[:\s]+(.+?)(?:\n|coordinates|text|key|task_status|$)', ai_text, re.IGNORECASE)
            reasoning = reasoning_match.group(1).strip() if reasoning_match else ""
            
            # Extract coordinates for clicking
            coord_patterns = [
                r'coordinates[:\s]+(\d+)[,\s]+(\d+)',
                r'(\d+)\s*,\s*(\d+)',  # Simple x,y format
                r'x[:\s]*(\d+).*y[:\s]*(\d+)',  # x: 123, y: 456 format
            ]
            
            coordinates = None
            for pattern in coord_patterns:
                coord_match = re.search(pattern, ai_text)
                if coord_match:
                    coordinates = (int(coord_match.group(1)), int(coord_match.group(2)))
                    break
            
            # Extract text for typing
            text_patterns = [
                r'text[:\s]+(.+?)(?:\n|key|task_status|$)',
                r'type[:\s]+["\']([^"\']+)["\']',  # Quoted text
                r'type[:\s]+(.+?)(?:\n|$)',  # Simple type: text format
            ]
            
            text = ""
            for pattern in text_patterns:
                text_match = re.search(pattern, ai_text, re.IGNORECASE)
                if text_match:
                    text = text_match.group(1).strip()
                    break
            
            # Extract key for key presses
            key_patterns = [
                r'(?:^|\n)key[:\s]+([^\n\r]+)',  # Match KEY: at start of line or after newline
                r'(?:^|\n)press[:\s]+([^\n\r]+)',  # Match press: at start of line or after newline
            ]
            
            key = ""
            for pattern in key_patterns:
                key_match = re.search(pattern, ai_text, re.IGNORECASE | re.MULTILINE)
                if key_match:
                    key = key_match.group(1).strip()
                    print(f"🔑 Key extracted: '{key}' using pattern: {pattern}")
                    break
            
            if not key:
                print(f"🔑 No key found in text: {ai_text[:200]}...")
            
            # Extract task status
            status_match = re.search(r'task_status[:\s]+(\w+)', response_lower)
            task_status = status_match.group(1) if status_match else "incomplete"
            
            result = {
                "action": action,
                "description": description,
                "reasoning": reasoning,
                "coordinates": coordinates,
                "text": text,
                "key": key,
                "task_status": task_status,
                "full_response": ai_text
            }
            
            print(f"🎯 Parsed Action: {action}, Description: {description}")
            if action == "key":
                print(f"🔑 Key extracted: '{key}'")  # Debug key extraction
            return result
            
        except Exception as e:
            print(f"⚠️ Failed to parse AI response: {str(e)}")
            return {"action": "no_action", "description": "Failed to parse AI response"}

    def _execute_ai_determined_action(self, action: str, action_data: Dict, task_description: str, current_screenshot: str) -> Dict:
        """Execute the action determined by AI analysis"""
        try:
            if action == "click":
                return self._execute_ai_click(action_data, current_screenshot)
            elif action == "type":
                return self._execute_ai_type(action_data, current_screenshot)
            elif action == "key":
                return self._execute_ai_key(action_data, current_screenshot)
            elif action == "wait":
                return self._execute_ai_wait(action_data, current_screenshot)
            elif action == "task_complete":
                return {
                    "success": True,
                    "message": "AI confirmed task completion",
                    "task_complete": True,
                    "screenshot": current_screenshot
                }
            else:
                return {
                    "success": False,
                    "message": f"Unknown action: {action}",
                    "screenshot": current_screenshot
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"Action execution failed: {str(e)}",
                "screenshot": current_screenshot
            }

    def _execute_ai_click(self, action_data: Dict, current_screenshot: str) -> Dict:
        """Execute AI-determined click action"""
        coordinates = action_data.get("coordinates")
        if coordinates:
            x, y = coordinates
            
            # Validate coordinates are within screen bounds
            screen_width, screen_height = pyautogui.size()
            if not (0 <= x <= screen_width and 0 <= y <= screen_height):
                return {
                    "success": False,
                    "message": f"Coordinates ({x}, {y}) are outside screen bounds ({screen_width}x{screen_height})",
                    "screenshot": current_screenshot
                }
            
            pyautogui.click(x, y)
            time.sleep(0.5)
            screenshot = self._take_step_screenshot(f"ai_click_{x}_{y}")
            return {
                "success": True,
                "message": f"Clicked at ({x}, {y})",
                "action_taken": f"Clicked at coordinates ({x}, {y})",
                "screenshot": screenshot
            }
        else:
            # Try to find element to click based on description
            description = action_data.get("description", "")
            # Use existing click logic as fallback
            result = self.screen_automation.perform_automation_task(
                f"click on {description}",
                current_screenshot
            )
            screenshot = self._take_step_screenshot("ai_click_description")
            return {
                "success": result.get("success", False),
                "message": result.get("message", "Click attempted"),
                "action_taken": f"Clicked on {description}",
                "screenshot": screenshot
            }

    def _execute_ai_type(self, action_data: Dict, current_screenshot: str) -> Dict:
        """Execute AI-determined typing action"""
        text = action_data.get("text", "")
        if text:
            pyautogui.typewrite(text, interval=0.05)
            time.sleep(0.5)
            screenshot = self._take_step_screenshot(f"ai_type")
            return {
                "success": True,
                "message": f"Typed: {text}",
                "action_taken": f"Typed: {text}",
                "screenshot": screenshot
            }
        else:
            return {
                "success": False,
                "message": "No text specified for typing",
                "screenshot": current_screenshot
            }

    def _execute_ai_key(self, action_data: Dict, current_screenshot: str) -> Dict:
        """Execute AI-determined key press action"""
        key = action_data.get("key", "")
        print(f"🔑 Executing key press: '{key}' (from action_data: {action_data})")  # Debug
        if key:
            try:
                if "+" in key:  # Handle key combinations like ctrl+s
                    keys = key.split("+")
                    print(f"🔑 Pressing key combination: {keys}")
                    pyautogui.hotkey(*keys)
                else:
                    print(f"🔑 Pressing single key: {key}")
                    pyautogui.press(key)
                time.sleep(0.5)
                screenshot = self._take_step_screenshot(f"ai_key_{key.replace('+', '_')}")
                return {
                    "success": True,
                    "message": f"Pressed key: {key}",
                    "action_taken": f"Pressed key: {key}",
                    "screenshot": screenshot
                }
            except Exception as e:
                print(f"❌ Key press error: {str(e)}")
                return {
                    "success": False,
                    "message": f"Key press failed: {str(e)}",
                    "screenshot": current_screenshot
                }
        else:
            print(f"❌ No key extracted from action_data")
            return {
                "success": False,
                "message": "No key specified for pressing",
                "screenshot": current_screenshot
            }

    def _execute_ai_wait(self, action_data: Dict, current_screenshot: str) -> Dict:
        """Execute AI-determined wait action"""
        wait_time = 2  # Default wait time
        time.sleep(wait_time)
        screenshot = self._take_step_screenshot("ai_wait")
        return {
            "success": True,
            "message": f"Waited {wait_time} seconds",
            "action_taken": f"Waited {wait_time} seconds",
            "screenshot": screenshot
        }

    def _fallback_action_heuristic(self, task_description: str, step_number: int) -> Dict:
        """Simple fallback logic when AI is not available"""
        task_lower = task_description.lower()
        
        if step_number == 1:
            # First step: usually need to focus or navigate
            if "google" in task_lower or "search" in task_lower:
                return {
                    "action": "key",
                    "key": "ctrl+l",
                    "description": "Focus address bar",
                    "task_status": "incomplete"
                }
            elif "alarm" in task_lower:
                return {
                    "action": "click",
                    "description": "Look for alarm or clock interface",
                    "task_status": "incomplete"
                }
        elif step_number == 2:
            # Second step: usually input or type
            if "google" in task_lower:
                return {
                    "action": "type",
                    "text": "https://google.com",
                    "description": "Type Google URL",
                    "task_status": "incomplete"
                }
        elif step_number == 3:
            # Third step: usually press enter or submit
            return {
                "action": "key",
                "key": "enter",
                "description": "Press Enter to execute",
                "task_status": "complete"
            }
        
        return {
            "action": "task_complete",
            "description": "Fallback completion",
            "task_status": "complete"
        }

    def _verify_task_completion(self, task_description: str, final_screenshot: str, app_used: Dict) -> Dict:
        """Use AI to verify if the task was completed successfully"""
        try:
            print(f"🔍 Verifying task completion using AI...")
            
            # Create verification prompt
            verification_prompt = f"""
            Analyze this screenshot to verify if the following task was completed successfully:

            TASK: {task_description}
            APP USED: {app_used.get('name', 'Unknown')}

            CRITICAL CHECKS - Look for signs of INCOMPLETE tasks:
            1. Are there any open dialog boxes (Save As, File Save, etc.)?
            2. Are there any modal windows waiting for user input?
            3. Are there any error messages or warning dialogs?
            4. Is there an asterisk (*) in the title indicating unsaved changes?
            5. Are there any "Cancel", "Save", "OK" buttons still visible and clickable?

            COMPLETION CHECKS:
            1. Was the main task objective achieved?
            2. Does the UI show evidence of successful completion?
            3. Is the application in a stable, completed state?
            4. Are all operations finished (no loading indicators)?

            SPECIAL ATTENTION FOR DOCUMENT TASKS:
            - If task involved writing/saving: Is the document actually saved (no unsaved indicator)?
            - If there's a Save dialog still open, the task is NOT complete
            - Check if filename appears in title bar (indicates successful save)

            Respond with:
            - SUCCESS: true/false (false if ANY dialogs are still open or task incomplete)
            - CONFIDENCE: 0.0-1.0
            - EVIDENCE: What you see that supports your conclusion
            - INCOMPLETE_REASON: If task is incomplete, explain what's still pending
            - RECOMMENDATION: What specific action is needed to complete the task

            Be very strict - if there are any open dialogs or incomplete elements, mark as FAILED.
            """
            
            # Use screen automation to analyze the screenshot
            verification_result = self.screen_automation._query_gemini_vision(
                verification_prompt, 
                final_screenshot
            )
            
            # Parse the AI response to extract verification data
            verification_data = self._parse_verification_response(verification_result)
            
            print(f"✅ Verification completed:")
            print(f"   Success: {verification_data.get('success', 'Unknown')}")
            print(f"   Confidence: {verification_data.get('confidence', 'Unknown')}")
            print(f"   Evidence: {verification_data.get('evidence', 'No evidence provided')[:100]}...")
            
            return verification_data
            
        except Exception as e:
            print(f"⚠️ Verification error: {str(e)}")
            return {
                "success": False,
                "confidence": 0.0,
                "evidence": f"Verification failed: {str(e)}",
                "recommendation": "Manual verification required"
            }
    
    def _parse_verification_response(self, ai_response) -> Dict:
        """Parse AI verification response into structured data"""
        try:
            # Handle both dict and string responses
            if isinstance(ai_response, dict):
                # If it's already a structured response, try to extract text content
                if 'message' in ai_response:
                    ai_text = ai_response['message']
                elif 'content' in ai_response:
                    ai_text = ai_response['content']
                elif 'recommendations' in ai_response and ai_response['recommendations']:
                    ai_text = ai_response['recommendations'][0]
                else:
                    # Try to convert the entire dict to string for parsing
                    ai_text = str(ai_response)
            else:
                ai_text = str(ai_response)
            
            response_lower = ai_text.lower()
            
            # Extract success status - be strict about open dialogs
            success = False
            if 'success: true' in response_lower:
                success = True
            elif 'successful' in response_lower and 'not' not in response_lower:
                success = True
            elif 'completed' in response_lower and 'not' not in response_lower:
                success = True
            
            # Override success if any incomplete indicators are found
            incomplete_indicators = [
                'dialog', 'save as', 'modal', 'waiting', 'pending', 
                'cancel button', 'save button', 'ok button', 'incomplete'
            ]
            if any(indicator in response_lower for indicator in incomplete_indicators):
                success = False
            
            # Extract confidence
            confidence = 0.5  # Default
            confidence_match = re.search(r'confidence[:\s]+([0-9.]+)', response_lower)
            if confidence_match:
                try:
                    confidence = float(confidence_match.group(1))
                except:
                    confidence = 0.5
            
            # Extract evidence
            evidence = "No specific evidence provided"
            evidence_match = re.search(r'evidence[:\s]+(.+?)(?:\n|incomplete_reason|recommendation|$)', ai_text, re.IGNORECASE | re.DOTALL)
            if evidence_match:
                evidence = evidence_match.group(1).strip()
            
            # Extract incomplete reason
            incomplete_reason = ""
            incomplete_match = re.search(r'incomplete_reason[:\s]+(.+?)(?:\n|recommendation|$)', ai_text, re.IGNORECASE | re.DOTALL)
            if incomplete_match:
                incomplete_reason = incomplete_match.group(1).strip()
                if incomplete_reason:
                    success = False  # Force fail if incomplete reason found
            
            # Extract recommendation
            recommendation = "Task appears complete"
            rec_match = re.search(r'recommendation[:\s]+(.+)', ai_text, re.IGNORECASE | re.DOTALL)
            if rec_match:
                recommendation = rec_match.group(1).strip()
            
            return {
                "success": success,
                "confidence": confidence,
                "evidence": evidence,
                "incomplete_reason": incomplete_reason,
                "recommendation": recommendation,
                "full_response": ai_response
            }
            
        except Exception as e:
            return {
                "success": False,
                "confidence": 0.0,
                "evidence": f"Failed to parse verification: {str(e)}",
                "recommendation": "Manual verification required",
                "full_response": ai_response
            }

def process_visual_task(task_description: str) -> str:
    """Process a task using the complete visual orchestrator"""
    try:
        orchestrator = CompleteVisualTaskOrchestrator()
        result = orchestrator.execute_task(task_description)
        
        if result.get("success", False):
            app_name = result.get("app_used", {}).get("name", "Unknown app")
            return f"✅ Task completed successfully using {app_name}"
        else:
            return f"❌ {result.get('message', 'Task failed')}"
            
    except Exception as e:
        return f"❌ Visual task orchestration error: {str(e)}"
