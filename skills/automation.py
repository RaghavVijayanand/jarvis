"""Legacy automation skill.

Mouse/keyboard/window/macro helpers that used to live here had no callers:
screen automation is handled by skills.screen_automation and window/typing
actions by skills.windows_control. Only the screen-size probe used by the
GUI Skills tab remains.
"""
import pyautogui


class AutomationSkill:
    def __init__(self):
        # Moving the mouse to a screen corner aborts automation (fail-safe).
        # Do not touch pyautogui.PAUSE here: it is process-global and used to
        # override screen_automation's 0.15 s with 0.5 s for every action.
        pyautogui.FAILSAFE = True

    def get_screen_size(self):
        """Get screen resolution"""
        try:
            size = pyautogui.size()
            return f"Screen size: {size.width} x {size.height}"
        except Exception as e:
            return f"Error getting screen size: {e}"
