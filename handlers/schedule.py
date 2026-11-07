"""Alarms, reminders, timers and recurring tasks."""
import re
import threading
from datetime import datetime, timedelta

from core.tools import params
from handlers.base import Handler


_WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
             "fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45, "half an": 30, "half a": 30}
_NUM = r"(\d+|half an|half a|forty five|an|a|one|two|three|four|five|ten|fifteen|twenty|thirty)"


def parse_alarm_time(text, now=None):
    """'7 am', '6:45 pm', '22:15', 'noon', 'tomorrow at 7', 'in 20 minutes', '10' → datetime or None.

    Clock times resolve to their next occurrence ('tomorrow' forces the next day).
    """
    now = now or datetime.now()
    text = (text or "").lower()
    # Relative: "in 5 minutes", "in an hour", "in 1 hour and 30 minutes", "in half an hour".
    rel = re.search(rf"\bin\s+{_NUM}\s*(minute|min|hour|hr)s?\b"
                    rf"(?:\s*(?:and\s+)?{_NUM}\s*(minute|min)s?\b)?", text)
    if rel:
        total = 0
        for amount, unit in ((rel.group(1), rel.group(2)), (rel.group(3), rel.group(4))):
            if not amount:
                continue
            value = int(amount) if amount.isdigit() else _WORD_NUM[amount]
            if amount.startswith("half"):
                total += 30 if unit.startswith("h") else 0
            else:
                total += value if unit.startswith("m") else value * 60
        return now + timedelta(minutes=total) if total > 0 else None
    tomorrow = re.search(r"\btomorrow\b", text) is not None
    if re.search(r"\b(?:noon|midday)\b", text):
        hour, minute = 12, 0
    elif re.search(r"\bmidnight\b", text):
        hour, minute = 0, 0
    else:
        m = re.search(r"(?:for|at)?\s*\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?(?!\s*(?:minutes?|hours?|%|\d))",
                      text)
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        period = (m.group(3) or "").replace(".", "")
        if minute > 59 or hour > 23 or (period and not 1 <= hour <= 12):
            return None      # "25:00", "13 pm", "0 am"
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if tomorrow:
        target += timedelta(days=1)
    elif target <= now:
        target += timedelta(days=1)
    return target


class ScheduleHandler(Handler):
    intents = {"SCHEDULE"}

    def handle(self, text, intent):
        low = text.lower()
        is_alarm = re.search(r"\b(alarms?|wake me)\b", low)
        removal = re.search(r"\b(delete|remove|clear|turn off|switch off|disable|stop)\b", low)
        if is_alarm and not removal and not re.search(r"\b(list|show|cancel|what are)\b", low):
            return self.set_alarm(low)
        scheduler = getattr(self.app, "task_scheduler", None)
        if scheduler is None:
            return "The scheduler isn't available."
        if is_alarm and removal:
            # "delete my alarm" must never set a new one; the scheduler understands "cancel".
            text = re.sub(r"\b(delete|remove|clear|turn off|switch off|disable|stop)\b", "cancel", low, count=1)
        return scheduler.process_schedule_command(text)

    def set_alarm(self, text):
        """Persistent alarm via the scheduler; in-memory timer if the scheduler is unavailable."""
        low = text.lower()
        target = parse_alarm_time(low, datetime.now())
        if target is None:
            return "I couldn't find a time in that. Try 'set an alarm for 7 am' or 'alarm in 20 minutes'."
        label = ""
        lm = re.search(r"\b(?:to|called|labelled|labeled)\s+([a-z][a-z ]+)$", low)
        if lm and not re.search(r"\d", lm.group(1)):
            label = lm.group(1).strip()
        scheduler = getattr(self.app, "task_scheduler", None)
        if scheduler is not None:
            return scheduler.schedule_alarm(target, label)
        seconds = max(0, (target - datetime.now()).total_seconds())
        time_str = target.strftime("%I:%M %p").lstrip("0")

        def ring():
            threading.Event().wait(seconds)
            self.app.notify(f"⏰ Alarm! It's {time_str}.", speak=True)

        threading.Thread(target=ring, daemon=True, name="JarvisAlarm").start()
        return f"Alarm set for {time_str}. (JARVIS must stay open for it to ring.)"

    def register_tools(self, t):
        scheduler = getattr(self.app, "task_scheduler", None)
        if not scheduler:
            return
        t.add("set_reminder", "Remind the user later.",
              lambda message, when: scheduler.process_schedule_command(f"remind me to {message} {when}"),
              params(["message", "when"], message=("string", "What to remind about"),
                     when=("string", "'in 20 minutes' or 'at 5 pm'")))
        t.add("set_alarm", "Set an alarm.", lambda time: self.set_alarm(f"alarm for {time}"),
              params(["time"], time=("string", "e.g. '7 am' or 'in 30 minutes'")))
        t.add("list_reminders", "List scheduled reminders, alarms and tasks.", scheduler.list_scheduled_tasks)
