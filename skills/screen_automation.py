"""
AI-Powered Screen Automation Skill for JARVIS
Takes screenshots, analyzes with AI vision, and executes actions
"""

import os
import time
import json
import base64
import threading
import re
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
from pathlib import Path

import pyautogui
import pynput
from PIL import Image, ImageDraw
import requests

class ScreenAutomationSkill:
    def __init__(self, jarvis_instance=None):
        """Initialize the screen automation system"""
        self.jarvis = jarvis_instance
        self.is_running = False
        self.emergency_stop = False
        self.automation_history = []
        self.current_task = None
        
        # Configuration (prefer values from Config and environment)
        try:
            from config import Config
            vision_provider = getattr(Config, 'AUTOMATION_VISION_PROVIDER', getattr(Config, 'VISION_PROVIDER', 'openrouter'))
            vision_model = getattr(Config, 'AUTOMATION_VISION_MODEL', getattr(Config, 'VISION_MODEL', 'qwen/qwen-2.5-vl-7b-instruct'))
            openrouter_base = getattr(Config, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
            openrouter_key = os.getenv('OPENROUTER_API_KEY', getattr(Config, 'OPENROUTER_API_KEY', ''))
        except Exception:
            vision_provider = 'openrouter'
            vision_model = 'qwen/qwen-2.5-vl-7b-instruct'
            openrouter_base = 'https://openrouter.ai/api/v1'
            openrouter_key = os.getenv('OPENROUTER_API_KEY', '')

        # Determine screenshot path from Config
        try:
            from config import Config
            screenshot_path = getattr(Config, 'AUTOMATION_SCREENSHOT_PATH', str((Path(__file__).resolve().parent.parent / 'cache' / 'screenshots').resolve()))
        except Exception:
            screenshot_path = str((Path(__file__).resolve().parent.parent / 'cache' / 'screenshots').resolve())

        self.config = {
            'screenshot_path': screenshot_path,
            'max_retries': 3,
            'action_delay': 1.0,
            'confirmation_required': True,
            'safe_mode': True,
            'vision_provider': vision_provider,
            'vision_model': vision_model,
            'openrouter_api_key': openrouter_key,
            'openrouter_base_url': openrouter_base,
            'confidence_threshold': 0.7,
            'disable_coordinate_adjustment': False  # Set to True to use raw AI coordinates
        }
        
        # Ensure screenshot directory exists
        os.makedirs(self.config['screenshot_path'], exist_ok=True)
        
        # Setup PyAutoGUI safety features
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.5
        
        # Emergency stop listener
        self.setup_emergency_stop()
        
        # Action whitelist for safe mode
        self.safe_actions = {
            'click', 'scroll', 'type_text', 'read_text', 
            'take_screenshot', 'move_mouse', 'press_key'
        }
        
        # Dangerous actions that require confirmation
        self.dangerous_actions = {
            'delete_file', 'system_shutdown', 'install_software',
            'modify_registry', 'admin_command'
        }
        
    def setup_emergency_stop(self):
        """Setup emergency stop hotkey (Ctrl+Shift+ESC)"""
        def on_hotkey():
            self.emergency_stop = True
            self.is_running = False
            print("🛑 EMERGENCY STOP ACTIVATED!")
            
        try:
            self.hotkey_listener = pynput.keyboard.GlobalHotKeys({
                '<ctrl>+<shift>+<esc>': on_hotkey
            })
            self.hotkey_listener.start()
        except Exception as e:
            print(f"Warning: Could not setup emergency stop hotkey: {e}")
    
    def take_screenshot(self, region=None) -> str:
        """Take a screenshot and save it"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
            filepath = os.path.join(self.config['screenshot_path'], filename)
            
            if region:
                screenshot = pyautogui.screenshot(region=region)
            else:
                screenshot = pyautogui.screenshot()
                
            screenshot.save(filepath)
            return filepath
            
        except Exception as e:
            raise Exception(f"Failed to take screenshot: {str(e)}")
    
    def analyze_screenshot(self, image_path: str, user_goal: str) -> Dict[str, Any]:
        """Send screenshot to AI vision model for analysis"""
        try:
            # Read and encode image
            with open(image_path, 'rb') as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')
            
            # Get screen dimensions for coordinate calculation
            import pyautogui
            screen_width, screen_height = pyautogui.size()
            
            # Prepare the enhanced prompt for precise element location
            prompt = f"""
            Analyze this screenshot and help achieve the user's goal: "{user_goal}"
            
            IMPORTANT: This screenshot is from a {screen_width}x{screen_height} screen.
            
            Please provide:
            1. A description of what you see on the screen
            2. EXACT pixel coordinates for clickable elements
            3. Specific actions needed to achieve the goal
            4. Confidence level (0-1) for your recommendations
            
            When identifying clickable elements:
            - Look for buttons, icons, text fields, menu items
            - Estimate their CENTER position in pixels from top-left (0,0)
            - Be as precise as possible with coordinates
            - Consider element size when calculating center point
            
            For coordinate calculation:
            - Top-left corner is (0, 0)
            - Bottom-right corner is ({screen_width}, {screen_height})
            - Click coordinates should be the CENTER of the element
            
            Return your response as JSON with this structure:
            {{
                "description": "What you see on screen",
                "screen_info": {{
                    "resolution": "{screen_width}x{screen_height}",
                    "elements_found": ["list of clickable elements you can see"]
                }},
                "actions": [
                    {{
                        "type": "click|type|scroll|wait",
                        "coordinates": [x, y],
                        "element_description": "what element you're clicking (e.g., 'Start button', 'File menu')",
                        "text": "text to type if applicable",
                        "description": "what this action does",
                        "confidence": 0.9
                    }}
                ],
                "confidence": 0.8,
                "risks": ["any potential risks"],
                "success_indicators": ["how to know if goal achieved"]
            }}
            """
            
            # Get API response based on provider
            if self.config['vision_provider'] == 'openrouter':
                response = self._query_openrouter_vision(prompt, image_path)
            elif self.config['vision_provider'] == 'openai':
                response = self._query_openai_vision(prompt, image_data)
            elif self.config['vision_provider'] == 'anthropic':
                response = self._query_anthropic_vision(prompt, image_data)
            elif self.config['vision_provider'] == 'gemini':
                response = self._query_gemini_vision(prompt, image_path)
            else:
                raise Exception("Unsupported vision provider")
                
            return response
            
        except Exception as e:
            raise Exception(f"Failed to analyze screenshot: {str(e)}")
    
    def _query_openai_vision(self, prompt: str, image_data: str) -> Dict[str, Any]:
        """Query OpenAI GPT-4 Vision API"""
        try:
            api_key = os.getenv('OPENAI_API_KEY') or os.getenv('OPENROUTER_API_KEY')
            if not api_key:
                raise Exception("No OpenAI API key found")
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            # Use OpenRouter if available, otherwise direct OpenAI
            if os.getenv('OPENROUTER_API_KEY'):
                url = "https://openrouter.ai/api/v1/chat/completions"
                model = "openai/gpt-4o"
            else:
                url = "https://api.openai.com/v1/chat/completions"
                model = "gpt-4o"
            
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 1000
            }
            
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            # Try to parse as JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # If not JSON, wrap in basic structure
                return {
                    "description": content,
                    "actions": [],
                    "confidence": 0.5,
                    "risks": ["Unable to parse structured response"],
                    "success_indicators": []
                }
                
        except Exception as e:
            raise Exception(f"OpenAI Vision API error: {str(e)}")
    
    def _query_openrouter_vision(self, prompt: str, image_path: str) -> str:
        """Query OpenRouter Gemini Vision API"""
        try:
            import requests
            import base64
            import json
            
            # Get API key from config
            api_key = self.config.get('openrouter_api_key') or os.getenv('OPENROUTER_API_KEY', '')
            if not api_key:
                raise Exception("No OpenRouter API key found in configuration")
            
            # Read and encode the image
            with open(image_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')
            
            # Create the request payload
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://jarvis-local",
                "X-Title": "JARVIS Visual Automation"
            }
            
            payload = {
                "model": self.config.get('vision_model', 'qwen/qwen-2.5-vl-7b-instruct'),
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text", 
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 4000,
                "temperature": 0.1
            }
            
            # Make the API request
            response = requests.post(
                f"{self.config.get('openrouter_base_url', 'https://openrouter.ai/api/v1')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f"OpenRouter API error: {response.status_code} {response.text}")
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            return content
                
        except Exception as e:
            raise Exception(f"OpenRouter Vision API error: {str(e)}")
    
    def _query_anthropic_vision(self, prompt: str, image_data: str) -> Dict[str, Any]:
        """Query Anthropic Claude Vision API"""
        # Placeholder for Anthropic implementation
        raise Exception("Anthropic vision not implemented yet")
    
    def _query_gemini_vision(self, prompt: str, image_path: str) -> Dict[str, Any]:
        """Query Gemini Vision directly using Google API"""
        try:
            # Try direct Gemini API first
            gemini_key = 'AIzaSyCiiWZCWLp2bZl60HDHFGuokYifwmnSvfg'
            if gemini_key:
                return self._query_gemini_direct(prompt, image_path, gemini_key)
            else:
                # Fallback to OpenRouter
                return self._query_gemini_via_openrouter(prompt, image_path)
                
        except Exception as e:
            print(f"Gemini Vision API error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Vision analysis failed: {str(e)}",
                "elements": [],
                "recommendations": []
            }
    
    def _query_gemini_direct(self, prompt: str, image_path: str, api_key: str) -> Dict[str, Any]:
        """Query Gemini Vision API directly"""
        try:
            import requests
            import base64
            import json
            
            # Read and encode the image
            with open(image_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')
            
            # Create the request payload for Gemini API
            headers = {
                "Content-Type": "application/json",
            }
            
            # Gemini API endpoint
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": prompt
                            },
                            {
                                "inline_data": {
                                    "mime_type": "image/png",
                                    "data": image_data
                                }
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "maxOutputTokens": 2000,
                    "temperature": 0.1
                }
            }
            
            # Make the API request
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code != 200:
                raise Exception(f"Gemini API error: {response.status_code} {response.text}")
            
            result = response.json()
            
            # Handle different response structures
            try:
                if "candidates" in result and result["candidates"]:
                    candidate = result["candidates"][0]
                    if "content" in candidate:
                        if "parts" in candidate["content"]:
                            content = candidate["content"]["parts"][0]["text"]
                        elif "text" in candidate["content"]:
                            content = candidate["content"]["text"]
                        else:
                            content = str(candidate["content"])
                    elif "text" in candidate:
                        content = candidate["text"]
                    else:
                        content = str(candidate)
                else:
                    content = str(result)
            except (KeyError, IndexError, TypeError) as e:
                print(f"Debug - API Response structure: {result}")
                raise Exception(f"Unexpected API response structure: {str(e)}")
            
            # Try to parse as JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # If not JSON, try to extract JSON from the response
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    try:
                        return json.loads(json_match.group())
                    except json.JSONDecodeError:
                        pass
                
                # If still can't parse, wrap in basic structure
                return {
                    "success": True,
                    "message": content,
                    "elements": [],
                    "recommendations": [content]
                }
                
        except Exception as e:
            raise Exception(f"Direct Gemini API error: {str(e)}")
    
    def _query_gemini_via_openrouter(self, prompt: str, image_path: str) -> Dict[str, Any]:
        """Query Gemini Vision via OpenRouter (fallback)"""
        try:
            import requests
            import base64
            import json
            
            # Configure OpenRouter API from config
            api_key = self.config.get('openrouter_api_key') or os.getenv('OPENROUTER_API_KEY', '')
            if not api_key:
                raise Exception("No OpenRouter API key found in configuration")
            
            # Read and encode the image
            with open(image_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')
            
            # Create the request payload
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://jarvis-local",
                "X-Title": "JARVIS Visual Automation"
            }
            
            # Create the prompt for Gemini via OpenRouter
            full_prompt = f"""
            {prompt}
            
            Please analyze this screenshot carefully and provide a JSON response with the exact structure requested above.
            Focus on identifying clickable elements, text fields, and providing precise coordinates for actions.
            """
            
            payload = {
                "model": self.config.get('vision_model', 'qwen/qwen-2.5-vl-7b-instruct'),
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": full_prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 2000,  # Reduced to save credits
                "temperature": 0.1
            }
            
            # Make the API request
            response = requests.post(
                f"{self.config.get('openrouter_base_url', 'https://openrouter.ai/api/v1')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f"OpenRouter API error: {response.status_code} {response.text}")
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Try to parse as JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # If not JSON, try to extract JSON from the response
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    try:
                        return json.loads(json_match.group())
                    except json.JSONDecodeError:
                        pass
                
                # If still can't parse, wrap in basic structure
                return {
                    "success": True,
                    "message": content,
                    "elements": [],
                    "recommendations": [content]
                }
                
        except Exception as e:
            raise Exception(f"OpenRouter fallback error: {str(e)}")
    
    def _query_anthropic_vision(self, prompt: str, image_data: str) -> Dict[str, Any]:
        """Query Anthropic Claude Vision API"""
        # Placeholder for Anthropic implementation
        raise Exception("Anthropic vision not implemented yet")
    
    def execute_action(self, action: Dict[str, Any]) -> bool:
        """Execute a single action"""
        try:
            if self.emergency_stop:
                return False
                
            action_type = action.get('type', '').lower()
            
            # Safety checks
            if self.config['safe_mode'] and action_type not in self.safe_actions:
                if self.config['confirmation_required']:
                    if not self._confirm_action(action):
                        return False
            
            # Add to history
            self.automation_history.append({
                'timestamp': datetime.now().isoformat(),
                'action': action,
                'status': 'executing'
            })
            
            # Execute based on type
            success = False
            if action_type == 'click':
                success = self._execute_click(action)
            elif action_type == 'type':
                success = self._execute_type(action)
            elif action_type == 'scroll':
                success = self._execute_scroll(action)
            elif action_type == 'wait':
                success = self._execute_wait(action)
            elif action_type == 'press_key':
                success = self._execute_key_press(action)
            else:
                print(f"Unknown action type: {action_type}")
                return False
            
            # Update history
            self.automation_history[-1]['status'] = 'success' if success else 'failed'
            
            # Add delay between actions
            time.sleep(self.config['action_delay'])
            
            return success
            
        except Exception as e:
            print(f"Error executing action: {str(e)}")
            if self.automation_history:
                self.automation_history[-1]['status'] = 'error'
                self.automation_history[-1]['error'] = str(e)
            return False
    
    def _execute_click(self, action: Dict[str, Any]) -> bool:
        """Execute mouse click"""
        try:
            coords = action.get('coordinates', [0, 0])
            
            # Validate coordinates
            coords = self._validate_coordinates(coords)
            
            button = action.get('button', 'left')
            clicks = action.get('clicks', 1)
            
            print(f"Clicking at validated coordinates: {coords}")
            pyautogui.click(coords[0], coords[1], clicks=clicks, button=button)
            return True
        except Exception as e:
            print(f"Click failed: {str(e)}")
            return False
    
    def _execute_type(self, action: Dict[str, Any]) -> bool:
        """Execute text typing"""
        try:
            text = action.get('text', '')
            interval = action.get('interval', 0.1)
            
            pyautogui.typewrite(text, interval=interval)
            return True
        except Exception as e:
            print(f"Type failed: {str(e)}")
            return False
    
    def _execute_scroll(self, action: Dict[str, Any]) -> bool:
        """Execute scroll action"""
        try:
            clicks = action.get('clicks', 3)
            direction = action.get('direction', 'up')
            x = action.get('x', pyautogui.size()[0] // 2)
            y = action.get('y', pyautogui.size()[1] // 2)
            
            if direction == 'down':
                clicks = -clicks
                
            pyautogui.scroll(clicks, x=x, y=y)
            return True
        except Exception as e:
            print(f"Scroll failed: {str(e)}")
            return False
    
    def _execute_wait(self, action: Dict[str, Any]) -> bool:
        """Execute wait/delay"""
        try:
            duration = action.get('duration', 1.0)
            time.sleep(duration)
            return True
        except Exception as e:
            print(f"Wait failed: {str(e)}")
            return False
    
    def _execute_key_press(self, action: Dict[str, Any]) -> bool:
        """Execute key press"""
        try:
            key = action.get('key', '')
            modifier = action.get('modifier', None)
            
            if modifier:
                pyautogui.hotkey(modifier, key)
            else:
                pyautogui.press(key)
            return True
        except Exception as e:
            print(f"Key press failed: {str(e)}")
            return False
    
    def _confirm_action(self, action: Dict[str, Any]) -> bool:
        """Ask user to confirm dangerous action"""
        try:
            if self.jarvis and hasattr(self.jarvis, 'gui'):
                # Use GUI confirmation if available
                from PySide6.QtWidgets import QMessageBox
                
                msg = QMessageBox()
                msg.setWindowTitle("Confirm Automation Action")
                msg.setText(f"Action: {action.get('type', 'Unknown')}\n"
                           f"Description: {action.get('description', 'No description')}\n"
                           f"Coordinates: {action.get('coordinates', 'N/A')}\n\n"
                           f"Do you want to proceed?")
                msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                msg.setDefaultButton(QMessageBox.No)
                
                return msg.exec() == QMessageBox.Yes
            else:
                # Console confirmation
                response = input(f"Confirm action: {action.get('description', 'Unknown action')} (y/N): ")
                return response.lower() in ['y', 'yes']
                
        except Exception as e:
            print(f"Confirmation failed: {str(e)}")
            return False
    
    def automate_task(self, goal: str, max_steps: int = 10) -> Dict[str, Any]:
        """Main automation function"""
        try:
            self.is_running = True
            self.emergency_stop = False
            self.current_task = goal
            
            results = {
                'goal': goal,
                'status': 'running',
                'steps_completed': 0,
                'total_steps': 0,
                'actions_taken': [],
                'screenshots': [],
                'errors': []
            }
            
            for step in range(max_steps):
                if self.emergency_stop or not self.is_running:
                    results['status'] = 'stopped'
                    break
                
                try:
                    # Take screenshot
                    screenshot_path = self.take_screenshot()
                    results['screenshots'].append(screenshot_path)
                    
                    # Analyze with AI
                    analysis = self.analyze_screenshot(screenshot_path, goal)
                    
                    if analysis['confidence'] < self.config['confidence_threshold']:
                        results['errors'].append(f"Low confidence in step {step + 1}: {analysis['confidence']}")
                        
                    # Check if goal achieved
                    if self._check_goal_achieved(analysis, goal):
                        results['status'] = 'completed'
                        break
                    
                    # Execute actions
                    actions_executed = 0
                    for action in analysis.get('actions', []):
                        if self.emergency_stop:
                            break
                            
                        success = self.execute_action(action)
                        results['actions_taken'].append({
                            'action': action,
                            'success': success,
                            'step': step + 1
                        })
                        
                        if success:
                            actions_executed += 1
                    
                    results['steps_completed'] = step + 1
                    
                    # If no actions taken, we might be stuck
                    if actions_executed == 0:
                        results['errors'].append(f"No actions executed in step {step + 1}")
                        break
                        
                except Exception as e:
                    error_msg = f"Error in step {step + 1}: {str(e)}"
                    results['errors'].append(error_msg)
                    print(error_msg)
                    break
            
            # Final status
            if results['status'] == 'running':
                results['status'] = 'incomplete' if results['errors'] else 'max_steps_reached'
            
            results['total_steps'] = results['steps_completed']
            self.is_running = False
            self.current_task = None
            
            return results
            
        except Exception as e:
            self.is_running = False
            self.current_task = None
            return {
                'goal': goal,
                'status': 'error',
                'error': str(e),
                'steps_completed': 0,
                'total_steps': 0,
                'actions_taken': [],
                'screenshots': [],
                'errors': [str(e)]
            }
    
    def _check_goal_achieved(self, analysis: Dict[str, Any], goal: str) -> bool:
        """Check if the goal has been achieved"""
        # This is a simple implementation - could be enhanced with more sophisticated checks
        success_indicators = analysis.get('success_indicators', [])
        description = analysis.get('description', '').lower()
        goal_lower = goal.lower()
        
        # Look for success keywords in description
        success_keywords = ['completed', 'finished', 'done', 'success', 'opened', 'loaded']
        goal_keywords = goal_lower.split()
        
        # Check if any success indicators match
        for indicator in success_indicators:
            if any(keyword in indicator.lower() for keyword in goal_keywords):
                return True
        
        # Check description for success
        if any(keyword in description for keyword in success_keywords):
            if any(keyword in description for keyword in goal_keywords):
                return True
        
        return False
    
    def _adjust_coordinates_for_accuracy(self, coordinates: list, element_info: dict) -> list:
        """Adjust coordinates for better clicking accuracy"""
        try:
            x, y = coordinates[0], coordinates[1]
            element_name = element_info.get('element_name', '').lower()
            element_size = element_info.get('element_size', [0, 0])
            text_bounds = element_info.get('text_bounds', {})
            
            print(f"Raw coordinates from AI: ({x}, {y})")
            print(f"Element: {element_name}")
            print(f"Text bounds: {text_bounds}")
            
            # For menu items, use more conservative X-axis adjustment
            if any(menu_word in element_name for menu_word in ['file', 'edit', 'view', 'help', 'terminal', 'run']):
                # If we have text bounds, use them but validate they make sense
                if text_bounds and all(key in text_bounds for key in ['left', 'right', 'top', 'bottom']):
                    # Calculate center from bounds
                    bounds_center_x = (text_bounds['left'] + text_bounds['right']) // 2
                    bounds_center_y = (text_bounds['top'] + text_bounds['bottom']) // 2
                    
                    # Check if bounds seem reasonable (not too far from original)
                    x_diff = abs(bounds_center_x - x)
                    if x_diff < 100:  # If bounds are reasonable, use them
                        print(f"Using text bounds center: ({bounds_center_x}, {bounds_center_y})")
                        return [bounds_center_x, bounds_center_y]
                    else:
                        print(f"Text bounds seem off (x_diff: {x_diff}), using minimal adjustment")
                
                # Apply minimal X-axis adjustment for menu items
                # Keep Y as-is since it's correct, adjust X slightly towards center
                text_length = len(element_name)
                # Very conservative adjustment - just move a few pixels right
                adjusted_x = x + max(5, text_length)  # Small rightward adjustment
                print(f"Conservative menu adjustment: ({x}, {y}) -> ({adjusted_x}, {y})")
                return [adjusted_x, y]
            
            # For other elements, keep original coordinates
            print(f"Using original coordinates for non-menu element: ({x}, {y})")
            return coordinates
            
        except Exception as e:
            print(f"Coordinate adjustment failed: {e}")
            return coordinates
    
    def _validate_coordinates(self, coordinates: list) -> list:
        """Validate and adjust coordinates to be within screen bounds"""
        try:
            import pyautogui
            screen_width, screen_height = pyautogui.size()
            
            x, y = coordinates[0], coordinates[1]
            
            # Ensure coordinates are within screen bounds
            x = max(0, min(x, screen_width - 1))
            y = max(0, min(y, screen_height - 1))
            
            return [int(x), int(y)]
            
        except Exception as e:
            print(f"Coordinate validation failed: {e}")
            return coordinates
    
    def _find_element_on_screen(self, element_description: str, screenshot_path: str) -> dict:
        """Enhanced element detection using AI vision"""
        try:
            import pyautogui
            screen_width, screen_height = pyautogui.size()
            
            # Enhanced prompt for precise element location
            prompt = f"""
            In this {screen_width}x{screen_height} screenshot, locate the "{element_description}" with EXTREME PRECISION.
            
            CRITICAL X-AXIS ACCURACY REQUIREMENTS:
            1. Find the EXACT horizontal center of the text/element
            2. For menu items, measure the text width carefully and find the true center
            3. Do NOT guess - count pixels if needed for X-coordinate precision
            4. The X coordinate must be the EXACT middle of the visible text
            5. Y coordinate should be the vertical center of the text
            
            MEASUREMENT PROCESS:
            1. Identify the leftmost pixel of the text
            2. Identify the rightmost pixel of the text  
            3. Calculate: center_x = (left + right) / 2
            4. Verify this is the true center
            
            Look for:
            - Buttons, icons, menu items, text fields matching this description
            - Consider partial matches (e.g., "calc" could match "Calculator")
            
            Return JSON with PRECISE measurements:
            {{
                "found": true/false,
                "element_name": "actual name of element found",
                "coordinates": [precise_center_x, precise_center_y],
                "element_size": [width, height],
                "confidence": 0.9,
                "text_bounds": {{"left": exact_left_x, "top": exact_top_y, "right": exact_right_x, "bottom": exact_bottom_y}},
                "measurement_notes": "description of how coordinates were measured",
                "alternatives": [
                    {{"name": "alternative element", "coordinates": [x, y]}}
                ]
            }}
            """
            
            # Get response from vision API
            if self.config['vision_provider'] == 'openrouter':
                response = self._query_openrouter_vision(prompt, screenshot_path)
            elif self.config['vision_provider'] == 'gemini':
                response = self._query_gemini_vision(prompt, screenshot_path)
            else:
                # Read and encode image for OpenAI
                with open(screenshot_path, 'rb') as image_file:
                    image_data = base64.b64encode(image_file.read()).decode('utf-8')
                response = self._query_openai_vision(prompt, image_data)
                
            return response
            
        except Exception as e:
            return {
                "found": False,
                "error": str(e),
                "coordinates": [0, 0],
                "confidence": 0.0
            }
    
    def stop_automation(self):
        """Stop current automation"""
        self.emergency_stop = True
        self.is_running = False
        self.current_task = None
    
    def get_status(self) -> Dict[str, Any]:
        """Get current automation status"""
        return {
            'is_running': self.is_running,
            'current_task': self.current_task,
            'emergency_stop': self.emergency_stop,
            'history_count': len(self.automation_history),
            'config': self.config
        }
    
    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent automation history"""
        return self.automation_history[-limit:] if self.automation_history else []
    
    def clear_history(self):
        """Clear automation history"""
        self.automation_history.clear()
    
    def cleanup(self):
        """Cleanup resources"""
        self.stop_automation()
        if hasattr(self, 'hotkey_listener'):
            self.hotkey_listener.stop()
    
    def find_and_click_element(self, element_description: str) -> Dict[str, Any]:
        """Find a specific element on screen and click it"""
        try:
            # Take screenshot first
            screenshot_path = self.take_screenshot()
            
            # Find the element
            element_info = self._find_element_on_screen(element_description, screenshot_path)
            
            if not element_info.get('found', False):
                return {
                    'success': False,
                    'message': f"Could not find element: {element_description}",
                    'alternatives': element_info.get('alternatives', [])
                }
            
            # Adjust coordinates for better accuracy (if enabled)
            raw_coordinates = element_info['coordinates']
            
            if self.config.get('disable_coordinate_adjustment', False):
                print(f"Using raw AI coordinates (adjustment disabled): {raw_coordinates}")
                validated_coordinates = self._validate_coordinates(raw_coordinates)
            else:
                adjusted_coordinates = self._adjust_coordinates_for_accuracy(raw_coordinates, element_info)
                validated_coordinates = self._validate_coordinates(adjusted_coordinates)
            
            # Execute click on found element
            click_action = {
                'type': 'click',
                'coordinates': validated_coordinates,
                'element_description': element_info.get('element_name', element_description),
                'confidence': element_info.get('confidence', 0.0)
            }
            
            success = self.execute_action(click_action)
            
            return {
                'success': success,
                'message': f"{'Successfully clicked' if success else 'Failed to click'} {element_info.get('element_name', element_description)}",
                'coordinates': validated_coordinates,
                'confidence': element_info.get('confidence', 0.0)
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f"Error finding/clicking element: {str(e)}",
                'error': str(e)
            }

# Integration with JARVIS command processing
def process_automation_command(command: str, jarvis_instance=None) -> str:
    """Process automation-related commands"""
    automation = ScreenAutomationSkill(jarvis_instance)
    
    command_lower = command.lower()
    
    if command_lower.startswith('automate'):
        goal = command[8:].strip()  # Remove 'automate' prefix
        if not goal:
            return "Please specify what you want to automate. Example: 'automate open calculator'"
        
        try:
            result = automation.automate_task(goal)
            
            status_msg = f"Automation {result['status']}\n"
            status_msg += f"Goal: {result['goal']}\n"
            status_msg += f"Steps completed: {result['steps_completed']}\n"
            status_msg += f"Actions taken: {len(result['actions_taken'])}\n"
            
            if result['errors']:
                status_msg += f"Errors: {len(result['errors'])}\n"
                for error in result['errors'][:3]:  # Show first 3 errors
                    status_msg += f"  - {error}\n"
            
            return status_msg
            
        except Exception as e:
            return f"Automation failed: {str(e)}"
    
    elif command_lower.startswith('click on') or command_lower.startswith('find and click'):
        # Extract element description
        if command_lower.startswith('click on'):
            element = command[8:].strip()  # Remove 'click on' prefix
        else:
            element = command[13:].strip()  # Remove 'find and click' prefix
            
        if not element:
            return "Please specify what to click. Example: 'click on start button'"
        
        try:
            result = automation.find_and_click_element(element)
            
            if result['success']:
                return f"✅ {result['message']} (confidence: {result.get('confidence', 0):.1f})"
            else:
                msg = f"❌ {result['message']}"
                if result.get('alternatives'):
                    msg += f"\nAlternatives found: {', '.join([alt['name'] for alt in result['alternatives'][:3]])}"
                return msg
                
        except Exception as e:
            return f"Click operation failed: {str(e)}"
    
    elif 'stop automation' in command_lower:
        automation.stop_automation()
        return "Automation stopped"
    
    elif 'automation status' in command_lower:
        status = automation.get_status()
        return f"Running: {status['is_running']}, Task: {status['current_task'] or 'None'}"
    
    elif 'automation history' in command_lower:
        history = automation.get_history(5)
        if not history:
            return "No automation history"
        
        history_msg = "Recent automation history:\n"
        for i, entry in enumerate(history, 1):
            history_msg += f"{i}. {entry['action'].get('description', 'Unknown')} - {entry['status']}\n"
        
        return history_msg
    
    else:
        return "Unknown automation command. Try: 'automate [task]', 'stop automation', 'automation status', or 'automation history'"
