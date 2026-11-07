"""Screen vision, clicking, typing and key presses."""
import re

from core.tools import params
from handlers.base import Handler


class ScreenHandler(Handler):
    intents = {"SCREEN_AUTOMATION", "AUTOMATION"}

    def handle(self, text, intent):
        app = self.app
        low = text.lower().strip()
        m = re.match(r"^(?:please\s+)?(?:type|write out)\s+(?:out\s+)?[\"'“]?(.+?)[\"'”]?$", text.strip(), re.I)
        if m and not re.search(r"\b(into|in the|on screen)\b", low):
            return app.windows.type_text(m.group(1))
        sa = app.screen_automation
        m = re.match(r"^(?:please\s+)?(?:press|hit)\s+(?:the\s+)?([a-z0-9+ ]+?)(?:\s+key)?$", low)
        if m and sa:
            ok, msg = sa.execute_action({"type": "press", "keys": m.group(1).replace(" ", "+")})
            return msg.capitalize() if ok else f"Couldn't press that: {msg}"
        if sa is None:
            return "Screen automation isn't available on this system."
        from skills.screen_automation import process_automation_command
        return process_automation_command(text, app)

    def register_tools(self, t):
        sa = self.app.screen_automation
        if not sa:
            return
        t.add("take_screenshot", "Take a screenshot and return its file path.", sa.take_screenshot)
        t.add("describe_screen", "Look at the screen and answer a question about it.", sa.describe_screen,
              params(question=("string", "What to look for or describe")))
        t.add("click_on_screen", "Find a visible UI element by description and click it.",
              lambda element: sa.find_and_click_element(element)["message"],
              params(["element"], element=("string", "e.g. 'the Save button'")))
        t.add("press_keys", "Press a key or shortcut, e.g. 'enter' or 'ctrl+s'.",
              lambda keys: sa.execute_action({"type": "press", "keys": keys})[1],
              params(["keys"], keys=("string", "Keys joined by +")))
