"""Media playback and volume."""
import re

from core.tools import params
from handlers.base import Handler


class MediaHandler(Handler):
    intents = {"MEDIA"}

    def handle(self, text, intent):
        low = text.lower().strip().rstrip(".!?")
        w = self.app.windows
        if re.search(r"what(?:'s|s| is) playing|now playing|what song", low):
            return w.now_playing()
        m = re.search(r"\b(?:volume|sound)\b.*?\b(\d{1,3})\s*%?|\b(\d{1,3})\s*(?:%|percent)?\s*volume\b", low)
        if m:
            level = int(m.group(1) or m.group(2))
            # "turn the volume up by 20" / "volume down 10" are relative; "lower the volume to 20" is absolute.
            if re.search(r"\b(?:up|down|increase|decrease|raise|lower|reduce|louder|quieter)\b", low) \
                    and not re.search(r"\bto\s+\d", low):
                down = re.search(r"\b(?:down|decrease|lower|reduce|quieter)\b", low)
                return w.change_volume(-level if down else level)
            return w.set_volume(level)
        if re.search(r"\bunmute\b", low):
            return w.mute(False)
        if re.search(r"\bmute\b", low):
            return w.mute(True)
        if re.search(r"(volume|sound|it) (up|higher)|louder|turn (it |the volume )?up|(increase|raise) (the )?volume", low):
            return w.change_volume(+10)
        if re.search(r"(volume|sound|it) (down|lower)|quieter|turn (it |the volume )?down|decrease (the )?volume|"
                     r"lower the volume", low):
            return w.change_volume(-10)
        if re.search(r"what(?:'s|s| is) the volume|current volume", low):
            return w.get_volume()
        if re.search(r"\b(next|skip)\b", low):
            return w.media("next")
        if re.search(r"\b(previous|last|back)\b", low):
            return w.media("previous")
        if re.fullmatch(r"(?:please\s+)?stop(?: it| this| that)?(?: the)?(?: music| song| video| playback)?", low):
            return w.media("stop")
        if re.search(r"\b(pause|resume|unpause|play)\b", low):
            return w.media("play_pause")
        return None

    def register_tools(self, t):
        w = self.app.windows
        t.add("set_volume", "Set the system volume to an exact level (0-100).", w.set_volume,
              params(["level"], level=("integer", "0-100")))
        t.add("change_volume", "Turn the system volume up or down by some amount ('a bit' is about 10).",
              lambda amount: w.change_volume(int(amount)), params(["amount"], amount=("integer", "Change in percent: +10 louder, -10 quieter")))
        t.add("media_control", "Control media playback.", w.media,
              params(["action"], action=("string", "Playback action", ["play_pause", "next", "previous", "stop"])))
        t.add("now_playing", "What media is currently playing.", w.now_playing)
