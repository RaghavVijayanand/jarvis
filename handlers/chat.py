"""Small talk that needs no model: greetings and thanks."""
import random
import re
from datetime import datetime

from handlers.base import Handler

GREETINGS = {"hi", "hello", "hey", "hey jarvis", "hi jarvis", "hello jarvis", "good morning",
             "good afternoon", "good evening"}
THANKS = {"thanks", "thank you", "thanks jarvis", "thank you jarvis", "cheers"}


class ChatHandler(Handler):
    intents = {"GENERAL"}

    def handle(self, text, intent):
        low = re.sub(r"[!.?]+$", "", text.lower().strip())
        if low in GREETINGS:
            hour = datetime.now().hour
            part = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
            return random.choice([f"{part}. How may I assist you?", f"{part}. What can I do for you?",
                                  f"{part}. At your service."])
        if low in THANKS:
            return random.choice(["You're welcome.", "Always a pleasure.", "Happy to help."])
        return None
