import requests
import json
import socket
from datetime import datetime
import re

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
            
            # Get weather using web scraping
            return self._get_weather_from_web(city)
                
        except Exception as e:
            return f"Unable to fetch weather data: {e}. Please try specifying a city name."
    
    def _extract_city_from_query(self, query):
        """Extract city name from user query"""
        query = query.lower()
        
        # Remove common weather-related words
        words_to_remove = ['weather', 'temperature', 'forecast', 'in', 'for', 'at', 'today', 'now', 'current']
        words = query.split()
        city_words = [word for word in words if word not in words_to_remove]
        
        if city_words:
            return ' '.join(city_words).title()
        return ""
    
    def _get_auto_location(self):
        """Auto-detect location using system information and IP geolocation"""
        try:
            # First check if user has set a preferred location
            import os
            preferred_location = os.getenv("JARVIS_LOCATION", "").strip()
            if preferred_location:
                # Extract just the city name from "City, Country" format
                city = preferred_location.split(',')[0].strip()
                if city:
                    self.location_cache = preferred_location
                    return city
        except:
            pass
        
        try:
            # Try to get location from IP geolocation (free service)
            response = requests.get('http://ip-api.com/json/', timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    city = data.get('city', '')
                    country = data.get('country', '')
                    if city:
                        self.location_cache = f"{city}, {country}"
                        return city
        except:
            pass
        
        # Fallback: try to get timezone-based location
        try:
            import time
            import platform
            
            # Get timezone info
            if platform.system() == "Windows":
                import subprocess
                result = subprocess.run(['powershell', '-Command', 'Get-TimeZone'], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    timezone_info = result.stdout
                    # Extract timezone name and guess location
                    if 'Eastern' in timezone_info:
                        return "New York"
                    elif 'Pacific' in timezone_info:
                        return "Los Angeles"
                    elif 'Central' in timezone_info:
                        return "Chicago"
                    elif 'Mountain' in timezone_info:
                        return "Denver"
        except:
            pass
        
        # Final fallback - default to Chennai
        return "Chennai"
    
    def _get_weather_from_web(self, city):
        """Get weather by scraping weather websites"""
        try:
            # Method 1: Try wttr.in (terminal weather service)
            result = self._get_weather_wttr(city)
            if result and "Unable to fetch" not in result:
                return result
        except:
            pass
        
        try:
            # Method 2: Try Google weather scraping
            result = self._scrape_google_weather(city)
            if result and "Unable to fetch" not in result:
                return result
        except:
            pass
        
        try:
            # Method 3: Try OpenWeatherMap-like services
            result = self._get_weather_simple(city)
            if result:
                return result
        except:
            pass
        
        return f"Weather information unavailable for {city}. Please check your internet connection or try a different city name."
    
    def _get_weather_wttr(self, city):
        """Get weather from wttr.in service"""
        try:
            url = f"https://wttr.in/{city}?format=j1"
            
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
    
    def _scrape_google_weather(self, city):
        """Scrape weather from Google search results"""
        try:
            from bs4 import BeautifulSoup
            
            # Search Google for weather
            search_url = f"https://www.google.com/search?q=weather+in+{city.replace(' ', '+')}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(search_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Try to find weather information in Google's weather widget
                temp_elem = soup.find('span', {'id': 'wob_tm'})
                condition_elem = soup.find('span', {'id': 'wob_dc'})
                location_elem = soup.find('div', {'id': 'wob_loc'})
                humidity_elem = soup.find('span', {'id': 'wob_hm'})
                wind_elem = soup.find('span', {'id': 'wob_ws'})
                
                if temp_elem and condition_elem:
                    temp = temp_elem.text
                    condition = condition_elem.text
                    location = location_elem.text if location_elem else city
                    humidity = humidity_elem.text if humidity_elem else "N/A"
                    wind = wind_elem.text if wind_elem else "N/A"
                    
                    weather_report = f"""🌤️ Weather for {location}

🌡️ Temperature: {temp}°C
☁️ Condition: {condition}
💧 Humidity: {humidity}
🌬️ Wind: {wind}

Source: Google Weather
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
                    
                    return weather_report
            
            return None
            
        except Exception as e:
            return None
    
    def _get_weather_simple(self, city):
        """Simple weather from free API services"""
        try:
            # Use Open-Meteo API with geocoding
            geocode_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1"
            geo_response = requests.get(geocode_url, timeout=5)
            
            if geo_response.status_code == 200:
                geo_data = geo_response.json()
                if geo_data.get('results'):
                    location = geo_data['results'][0]
                    lat = location['latitude']
                    lon = location['longitude']
                    location_name = location['name']
                    country = location.get('country', '')
                    
                    # Get weather data
                    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m"
                    weather_response = requests.get(weather_url, timeout=5)
                    
                    if weather_response.status_code == 200:
                        weather_data = weather_response.json()
                        current = weather_data['current_weather']
                        
                        temp = current['temperature']
                        wind_speed = current['windspeed']
                        
                        # Get humidity from hourly data (first hour)
                        humidity = weather_data['hourly']['relative_humidity_2m'][0] if weather_data['hourly']['relative_humidity_2m'] else "N/A"
                        
                        weather_report = f"""🌤️ Weather for {location_name}, {country}

🌡️ Temperature: {temp}°C
🌬️ Wind Speed: {wind_speed} km/h
💧 Humidity: {humidity}%

Source: Open-Meteo
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
                        
                        return weather_report
            
            return None
            
        except Exception as e:
            return None
