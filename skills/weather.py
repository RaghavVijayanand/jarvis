import requests
from datetime import datetime
import re
from urllib.parse import quote

_NO_SUCH_PLACE = object()     # geocoding answered: no place by that name (not a network failure)


class WeatherSkill:
    def __init__(self):
        self.location_cache = None
        
    def get_weather(self, query=""):
        """Get current weather information by web scraping with auto location detection"""
        try:
            # Extract city from query if provided
            city = self._extract_city_from_query(query)
            
            # If no city specified, auto-detect location
            if not city:
                city = self._get_auto_location()
            
            if not city:
                return "I couldn't determine your location. Specify a city or set one in Settings."
            # Get weather using web scraping
            return self._get_weather_from_web(city)
                
        except Exception as e:
            return f"Unable to fetch weather data: {e}. Please try specifying a city name."
    
    _NOT_CITY = {"weather", "temperature", "forecast", "today", "tomorrow", "now", "current", "like",
                 "outside", "here", "right", "this", "week", "weekend", "the", "what", "whats", "what's",
                 "is", "it", "how", "hows", "how's", "tell", "me", "about", "going", "to", "be", "will",
                 "rain", "sunny", "hot", "cold", "please", "jarvis", "a", "for", "in", "at", "of", "my",
                 "there", "morning", "evening", "tonight", "check", "get", "show", "give", "report",
                 "moment", "next", "later", "on", "day", "days", "monday", "tuesday", "wednesday",
                 "thursday", "friday", "saturday", "sunday"}

    def _extract_city_from_query(self, query):
        """Extract a city from 'weather in London', 'Paris weather', 'forecast for New York tomorrow'."""
        text = re.sub(r"[?!.]", " ", (query or "")).strip()
        m = re.search(r"\b(?:in|for|at|of)\s+([A-Za-z][A-Za-z .'-]*?(?:,\s*[A-Za-z][A-Za-z .'-]*)?)"
                      r"(?=\s+(?:today|tomorrow|now|right now|this|tonight|like|please|next|on|for|at|later|"
                      r"over|during|in the)\b|\s*$)", text, re.I)
        candidate = m.group(1) if m else ""
        if not candidate:
            m = re.search(r"^\s*([A-Za-z][A-Za-z .'-]*?)\s+(?:weather|forecast|temperature)\b", text, re.I)
            candidate = m.group(1) if m else ""
        words = [w for w in re.split(r"\s+", candidate.strip()) if w]
        if not words or all(w.lower().strip(",") in self._NOT_CITY for w in words):
            return ""
        while words and words[0].lower() in self._NOT_CITY:
            words.pop(0)
        while words and words[-1].lower().strip(",") in self._NOT_CITY:
            words.pop()
        return " ".join(w if w.isupper() and len(w) <= 3 else w.capitalize() for w in words).strip(" ,")

    def _get_auto_location(self):
        """Auto-detect location using system information and IP geolocation"""
        try:
            # First check if user has set a preferred location
            from core.config import get_location_preference
            preferred_location = get_location_preference()
            if preferred_location and preferred_location.split(',')[0].strip():
                # Keep "City, Region/Country": the qualifier picks the right Springfield.
                self.location_cache = preferred_location
                return preferred_location
        except Exception:
            pass
        
        try:
            # Try to get location from IP geolocation (free service)
            # ip-api's free tier is HTTP-only (HTTPS needs a paid key).
            response = requests.get('http://ip-api.com/json/', timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    city = data.get('city', '')
                    country = data.get('country', '')
                    if city:
                        self.location_cache = f"{city}, {country}" if country else city
                        return self.location_cache      # London, Canada is not London, UK
        except Exception:
            pass
        
        # A timezone is not a city. Never substitute a guessed/default city
        # when detection fails, and do not reuse a cleared preference cache.
        self.location_cache = None
        return ""
    
    def _get_weather_from_web(self, city):
        """Fetch weather: Open-Meteo first (keyless JSON), then wttr.in."""
        try:
            result = self._get_weather_open_meteo(city)
            if result is _NO_SUCH_PLACE:
                # wttr.in would guess *some* location and report it as if it were this one.
                return f"I couldn't find a place called '{city}'. Check the spelling or add the country."
            if result:
                return result
        except Exception:
            pass

        try:
            result = self._get_weather_wttr(city)
            if result:
                return result
        except Exception:
            pass

        return f"Weather information unavailable for {city}. Please check your internet connection or try a different city name."

    _WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
            51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
            65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain", 71: "light snow", 73: "snow",
            75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers", 82: "violent showers",
            85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail",
            99: "severe thunderstorm with hail"}

    @staticmethod
    def _pick_place(results, qualifier):
        """Prefer the geocoding hit whose country/region matches 'City, <qualifier>'."""
        q = (qualifier or "").strip().lower()
        if q:
            for place in results:
                fields = (place.get("country"), place.get("country_code"), place.get("admin1"))
                if any(f and (f.lower() == q or f.lower().startswith(q)) for f in fields):
                    return place
        return results[0]

    def _get_weather_open_meteo(self, city):
        name, _, qualifier = city.partition(",")
        geo_resp = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                                params={"name": name.strip(), "count": 10 if qualifier else 1,
                                        "language": "en", "format": "json"},
                                timeout=6)
        geo_resp.raise_for_status()
        results = [r for r in (geo_resp.json().get("results") or [])
                   if isinstance(r, dict) and r.get("latitude") is not None and r.get("longitude") is not None]
        if not results:
            return _NO_SUCH_PLACE
        place = self._pick_place(results, qualifier)
        resp = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "timezone": "auto", "forecast_days": 2}, timeout=6)
        resp.raise_for_status()  # 400 -> {"error": true, "reason": ...}
        data = resp.json()
        cur, daily = data.get("current") or {}, data.get("daily") or {}
        if cur.get("temperature_2m") is None:
            return None  # never report "None°C"
        name = ", ".join(x for x in (place.get("name"), place.get("admin1"), place.get("country")) if x)
        desc = self._WMO.get(cur.get("weather_code"), "unknown conditions")
        lines = [f"Weather in {name}: {desc}, {cur.get('temperature_2m')}°C "
                 f"(feels like {cur.get('apparent_temperature')}°C).",
                 f"Humidity {cur.get('relative_humidity_2m')}%, wind {cur.get('wind_speed_10m')} km/h."]

        def day(key, i):
            values = daily.get(key) or []
            return values[i] if i < len(values) else None

        if day("temperature_2m_max", 0) is not None:
            rain = day("precipitation_probability_max", 0)
            lines.append(f"Today: {day('temperature_2m_min', 0)}–{day('temperature_2m_max', 0)}°C"
                         + (f", {rain}% chance of rain." if rain is not None else "."))
            if day("temperature_2m_max", 1) is not None:
                tdesc = self._WMO.get(day("weather_code", 1), "")
                lines.append(f"Tomorrow: {tdesc + ', ' if tdesc else ''}"
                             f"{day('temperature_2m_min', 1)}–{day('temperature_2m_max', 1)}°C.")
        return "\n".join(lines)

    def _get_weather_wttr(self, city):
        """Get weather from wttr.in service"""
        try:
            url = f"https://wttr.in/{quote(city)}?format=j1"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract current weather
                current = data['current_condition'][0]
                location_info = data.get('nearest_area', [{}])[0]
                
                temp_c = current['temp_C']
                temp_f = current['temp_F']
                condition = current['weatherDesc'][0]['value']
                humidity = current['humidity']
                wind_speed = current['windspeedKmph']
                wind_dir = current['winddir16Point']
                
                location_name = location_info.get('areaName', [{'value': city}])[0]['value']
                country = location_info.get('country', [{'value': ''}])[0]['value']
                
                weather_report = f"""🌤️ Weather for {location_name}, {country}

🌡️ Temperature: {temp_c}°C ({temp_f}°F)
☁️ Condition: {condition}
💧 Humidity: {humidity}%
🌬️ Wind: {wind_speed} km/h {wind_dir}

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
                
                return weather_report
            else:
                return None
                
        except Exception as e:
            return None
