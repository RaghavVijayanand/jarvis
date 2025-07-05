import pyautogui
import time
import json
import os
from pathlib import Path
import subprocess
import win32gui
import win32con
import win32api
import psutil

class AutomationSkill:
    def __init__(self):
        # Disable pyautogui fail-safe for automation
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.5
        
    def move_mouse(self, x, y):
        """Move mouse to specific coordinates"""
        try:
            pyautogui.moveTo(x, y)
            return f"Mouse moved to ({x}, {y})"
        except Exception as e:
            return f"Error moving mouse: {e}"
    
    def click_at(self, x, y, button='left'):
        """Click at specific coordinates"""
        try:
            pyautogui.click(x, y, button=button)
            return f"Clicked {button} button at ({x}, {y})"
        except Exception as e:
            return f"Error clicking: {e}"
    
    def type_text(self, text, interval=0.05):
        """Type text with specified interval between characters"""
        try:
            pyautogui.typewrite(text, interval=interval)
            return f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}"
        except Exception as e:
            return f"Error typing text: {e}"
    
    def press_key(self, key):
        """Press a specific key"""
        try:
            pyautogui.press(key)
            return f"Pressed key: {key}"
        except Exception as e:
            return f"Error pressing key: {e}"
    
    def hotkey(self, *keys):
        """Press multiple keys simultaneously (hotkey)"""
        try:
            pyautogui.hotkey(*keys)
            return f"Pressed hotkey: {'+'.join(keys)}"
        except Exception as e:
            return f"Error pressing hotkey: {e}"
    
    def scroll(self, clicks, direction='up'):
        """Scroll up or down"""
        try:
            scroll_amount = clicks if direction == 'up' else -clicks
            pyautogui.scroll(scroll_amount)
            return f"Scrolled {direction} {clicks} clicks"
        except Exception as e:
            return f"Error scrolling: {e}"
    
    def take_screenshot_region(self, x, y, width, height, filename=None):
        """Take screenshot of specific region"""
        try:
            if not filename:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"region_screenshot_{timestamp}.png"
            
            screenshot = pyautogui.screenshot(region=(x, y, width, height))
            filepath = Path.cwd() / filename
            screenshot.save(filepath)
            
            return f"Region screenshot saved as {filepath}"
        except Exception as e:
            return f"Error taking region screenshot: {e}"
    
    def find_image_on_screen(self, image_path, confidence=0.8):
        """Find an image on screen and return its location"""
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if location:
                center = pyautogui.center(location)
                return f"Image found at center: ({center.x}, {center.y})"
            else:
                return "Image not found on screen"
        except Exception as e:
            return f"Error finding image: {e}"
    
    def click_image(self, image_path, confidence=0.8):
        """Find and click on an image"""
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if location:
                center = pyautogui.center(location)
                pyautogui.click(center)
                return f"Clicked on image at ({center.x}, {center.y})"
            else:
                return "Image not found, cannot click"
        except Exception as e:
            return f"Error clicking image: {e}"
    
    def get_screen_size(self):
        """Get screen resolution"""
        try:
            size = pyautogui.size()
            return f"Screen size: {size.width} x {size.height}"
        except Exception as e:
            return f"Error getting screen size: {e}"
    
    def get_mouse_position(self):
        """Get current mouse position"""
        try:
            pos = pyautogui.position()
            return f"Mouse position: ({pos.x}, {pos.y})"
        except Exception as e:
            return f"Error getting mouse position: {e}"
    
    def drag_and_drop(self, start_x, start_y, end_x, end_y, duration=1):
        """Drag from one point to another"""
        try:
            pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration, absolute=False)
            return f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"
        except Exception as e:
            return f"Error dragging: {e}"
    
    def get_window_list(self):
        """Get list of all open windows"""
        try:
            windows = []
            
            def enum_windows_callback(hwnd, windows):
                if win32gui.IsWindowVisible(hwnd):
                    window_title = win32gui.GetWindowText(hwnd)
                    if window_title:
                        windows.append({
                            'hwnd': hwnd,
                            'title': window_title,
                            'rect': win32gui.GetWindowRect(hwnd)
                        })
                return True
            
            win32gui.EnumWindows(enum_windows_callback, windows)
            
            result = "Open Windows:\n"
            for i, window in enumerate(windows[:20]):  # Limit to 20 windows
                result += f"{i+1}. {window['title']}\n"
            
            return result
        except Exception as e:
            return f"Error getting window list: {e}"
    
    def focus_window(self, window_title):
        """Focus on a specific window by title"""
        try:
            def find_window_callback(hwnd, title_to_find):
                if title_to_find.lower() in win32gui.GetWindowText(hwnd).lower():
                    win32gui.SetForegroundWindow(hwnd)
                    return False  # Stop enumeration
                return True
            
            win32gui.EnumWindows(find_window_callback, window_title)
            return f"Focused on window containing: {window_title}"
        except Exception as e:
            return f"Error focusing window: {e}"
    
    def minimize_window(self, window_title):
        """Minimize a specific window"""
        try:
            def minimize_callback(hwnd, title_to_find):
                if title_to_find.lower() in win32gui.GetWindowText(hwnd).lower():
                    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                    return False
                return True
            
            win32gui.EnumWindows(minimize_callback, window_title)
            return f"Minimized window containing: {window_title}"
        except Exception as e:
            return f"Error minimizing window: {e}"
    
    def maximize_window(self, window_title):
        """Maximize a specific window"""
        try:
            def maximize_callback(hwnd, title_to_find):
                if title_to_find.lower() in win32gui.GetWindowText(hwnd).lower():
                    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                    return False
                return True
            
            win32gui.EnumWindows(maximize_callback, window_title)
            return f"Maximized window containing: {window_title}"
        except Exception as e:
            return f"Error maximizing window: {e}"
    
    def close_window(self, window_title):
        """Close a specific window"""
        try:
            def close_callback(hwnd, title_to_find):
                if title_to_find.lower() in win32gui.GetWindowText(hwnd).lower():
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    return False
                return True
            
            win32gui.EnumWindows(close_callback, window_title)
            return f"Closed window containing: {window_title}"
        except Exception as e:
            return f"Error closing window: {e}"
    
    def wait_for_image(self, image_path, timeout=10, confidence=0.8):
        """Wait for an image to appear on screen"""
        try:
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    location = pyautogui.locateOnScreen(image_path, confidence=confidence)
                    if location:
                        center = pyautogui.center(location)
                        return f"Image appeared at ({center.x}, {center.y}) after {time.time() - start_time:.1f} seconds"
                except:
                    pass
                time.sleep(0.5)
            
            return f"Image not found after {timeout} seconds"
        except Exception as e:
            return f"Error waiting for image: {e}"
    
    def record_macro(self, duration=10):
        """Record mouse and keyboard actions for specified duration"""
        try:
            import pynput
            from pynput import mouse, keyboard
            
            events = []
            start_time = time.time()
            
            def on_mouse_click(x, y, button, pressed):
                if time.time() - start_time < duration:
                    events.append({
                        'type': 'mouse_click',
                        'x': x, 'y': y,
                        'button': str(button),
                        'pressed': pressed,
                        'time': time.time() - start_time
                    })
            
            def on_key_press(key):
                if time.time() - start_time < duration:
                    events.append({
                        'type': 'key_press',
                        'key': str(key),
                        'time': time.time() - start_time
                    })
            
            mouse_listener = mouse.Listener(on_click=on_mouse_click)
            keyboard_listener = keyboard.Listener(on_press=on_key_press)
            
            mouse_listener.start()
            keyboard_listener.start()
            
            time.sleep(duration)
            
            mouse_listener.stop()
            keyboard_listener.stop()
            
            # Save macro to file
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"macro_{timestamp}.json"
            with open(filename, 'w') as f:
                json.dump(events, f, indent=2)
            
            return f"Recorded {len(events)} events in {duration} seconds. Saved as {filename}"
            
        except ImportError:
            return "Macro recording requires pynput library: pip install pynput"
        except Exception as e:
            return f"Error recording macro: {e}"
    
    def play_macro(self, filename):
        """Play back a recorded macro"""
        try:
            if not os.path.exists(filename):
                return f"Macro file {filename} not found"
            
            with open(filename, 'r') as f:
                events = json.load(f)
            
            start_time = time.time()
            for event in events:
                # Wait for the correct time
                while time.time() - start_time < event['time']:
                    time.sleep(0.01)
                
                if event['type'] == 'mouse_click' and event['pressed']:
                    pyautogui.click(event['x'], event['y'])
                elif event['type'] == 'key_press':
                    key = event['key'].replace("'", "")
                    if key.startswith('Key.'):
                        key = key[4:]  # Remove 'Key.' prefix
                    pyautogui.press(key)
            
            return f"Played back macro with {len(events)} events"
            
        except Exception as e:
            return f"Error playing macro: {e}"
