"""Information: time, math, weather, web search, system status, fun utilities."""
import re
from datetime import datetime

from core.tools import params
from handlers.base import Handler


class InfoHandler(Handler):
    intents = {"TIME", "MATH", "WEATHER", "SEARCH", "SYSTEM", "UTILITY"}

    def handle(self, text, intent):
        return {"TIME": self.time, "MATH": self.math, "WEATHER": self.weather, "SEARCH": self.search,
                "SYSTEM": self.system, "UTILITY": self.utility}[intent](text)

    # ── handlers ─────────────────────────────────────────────────────────────
    @staticmethod
    def time(text):
        low = text.lower()
        now = datetime.now().astimezone()
        if re.search(r"\b(date|day|today)\b", low) and not re.search(r"\btime\b", low):
            return f"Today is {now.strftime('%A, %B %d, %Y')}."
        return f"It's {now.strftime('%I:%M %p').lstrip('0')} on {now.strftime('%A, %B %d')}."

    def math(self, text):
        result = self.app.utility_skill.calculate(text)
        if result and not result.startswith("Could not calculate"):
            return result
        return None  # conversions and word problems → language model

    def weather(self, text):
        return self.app.weather_skill.get_weather(text)

    def search(self, text):
        app = self.app
        low = text.lower()
        if re.search(r"\b(news|headlines)\b", low):
            return app.web_skill.get_news_headlines()
        if re.search(r"\b(wikipedia|wiki)\b", low):
            query = re.sub(r"\b(search|look up|on|in|wikipedia|wiki|for)\b", " ", low)
            return app.web_skill.search_wikipedia(re.sub(r"\s+", " ", query).strip())
        query = re.sub(r"^(?:please\s+)?(?:search(?: the web)?(?: for)?|google|look up|lookup|find out|"
                       r"find information (?:about|on))\s+", "", text, flags=re.I).strip()
        return app.web_skill.search_web(query or text, open_browser=False, llm_brain=getattr(app, "brain", None))

    def system(self, text):
        low = text.lower()
        monitor, control = self.app.system_monitor, self.app.system_control
        if "battery" in low:
            return control.get_battery_info()
        if re.search(r"\b(?:my |the )?ip(?: address)?\b", low):
            return control.get_network_info()  # the analysis view has no addresses
        if re.search(r"\b(network|wifi|internet)\b", low):
            return monitor.get_network_analysis() if monitor else control.get_network_info()
        if re.search(r"process", low):
            return control.get_running_processes()
        if re.search(r"\b(disk|storage|space)\b", low):
            return control.get_disk_usage()
        if re.search(r"\bhealth\b", low) and monitor:
            return monitor.check_system_health()
        if re.search(r"\bhardware\b", low) and monitor:
            return monitor.get_hardware_info()
        if re.search(r"\b(cpu|processor)\b", low) and not re.search(r"status|report|info", low):
            if monitor:
                info = monitor.get_cpu_info()
                return f"CPU usage is {info.get('usage', '?')}% across {info.get('cores', '?')} cores."
            return control.get_cpu_usage()
        if re.search(r"\b(ram|memory)\b", low) and not re.search(r"status|report|info", low):
            if monitor:
                m = monitor.get_memory_info()
                return (f"Memory: {m.get('used_gb', 0):.1f} GB of {m.get('total_gb', 0):.1f} GB used "
                        f"({m.get('percentage', 0)}%).")
            return control.get_memory_usage()
        return monitor.get_system_info() if monitor else control.get_system_status()

    def utility(self, text):
        low = text.lower()
        u = self.app.utility_skill
        if "joke" in low:
            return u.tell_joke()
        if re.search(r"coin", low):
            return u.flip_coin()
        m = re.search(r"roll (?:a |the )?(\d+)?\s*(?:d(\d+)|di(?:e|ce))", low)
        if m or "dice" in low or re.search(r"\broll\b", low):
            count = int(m.group(1)) if m and m.group(1) else (2 if "dice" in low and "two" in low else 1)
            sides = int(m.group(2)) if m and m.group(2) else 6
            return u.roll_dice(sides=sides, count=count)
        m = re.search(r"random number(?: between| from)? (\d+) (?:and|to) (\d+)", low)
        if m:
            return u.get_random_number(int(m.group(1)), int(m.group(2)))
        if "random number" in low:
            return u.get_random_number()
        if "password" in low:
            m = re.search(r"(\d{1,3})", low)
            return u.generate_password(length=int(m.group(1)) if m else 16)
        return None

    # ── tools ────────────────────────────────────────────────────────────────
    def register_tools(self, t):
        app = self.app
        if app.weather_skill:
            # The tool is called as func(location=...), but get_weather() takes a
            # free-text query and would treat a bare "London" as "no city".
            t.add("get_weather", "Current weather and forecast for a city.",
                  lambda location="": app.weather_skill.get_weather(
                      f"weather in {str(location).strip()}" if str(location or "").strip() else ""),
                  params(["location"], location=("string", "City, e.g. 'London' or 'Pune, India'")))
        t.add("web_search", "Search the web for current information, news or facts; returns a summary.",
              lambda query: app.web_skill.search_web(query, llm_brain=None),
              params(["query"], query=("string", "Search query")))
        t.add("get_system_status", "CPU, memory, disk usage and uptime.",
              (app.system_monitor.get_system_info if app.system_monitor else app.system_control.get_system_status))
        t.add("get_battery", "Battery level and charging state.", app.system_control.get_battery_info)
        t.add("calculate", "Evaluate a math expression exactly.", app.utility_skill.calculate,
              params(["expression"], expression=("string", "e.g. '15% of 240' or 'sqrt(2)*3'")))
        t.add("get_time", "Current local date and time.", lambda: self.time("time"))
