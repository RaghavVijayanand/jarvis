import requests
import json
from datetime import datetime

class WeatherSkill:
    def __init__(self):
        # Free weather APIs that don't require keys
        self.weather_sources = [
            "https://wttr.in/{city}?format=j1",  # wttr.in provides free weather data
            "https://api.open-meteo.com/v1/forecast"  # Open-Meteo free API
        ]
        
    def get_weather(self, city=""):
        """Get current weather information by web scraping"""
        try:
            # If no city specified, try to get location-based weather
            if not city:
                return self._get_weather_wttr("")
            else:
                return self._get_weather_wttr(city)
                
        except Exception as e:
            return f"Unable to fetch weather data: {e}. Please check your internet connection."
    
    def _get_weather_wttr(self, city):
        """Get weather from wttr.in service"""
        try:
            # Use wttr.in which provides JSON weather data without API key
            if city:
                url = f"https://wttr.in/{city}?format=j1"
            else:
                url = "https://wttr.in/?format=j1"  # Auto-detect location
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract current weather
                current = data['current_condition'][0]
                location = data['nearest_area'][0]
                
                temp_c = current['temp_C']
                temp_f = current['temp_F']
                condition = current['weatherDesc'][0]['value']
                humidity = current['humidity']
                wind_speed = current['windspeedKmph']
                wind_dir = current['winddir16Point']
                feels_like_c = current['FeelsLikeC']
                feels_like_f = current['FeelsLikeF']
                
                area_name = location['areaName'][0]['value']
                country = location['country'][0]['value']
                
                # Format the weather report
                weather_report = f"""Current Weather for {area_name}, {country}:
Temperature: {temp_c}°C ({temp_f}°F)
Feels like: {feels_like_c}°C ({feels_like_f}°F)
Condition: {condition}
Humidity: {humidity}%
Wind: {wind_speed} km/h {wind_dir}"""
                
                return weather_report
            else:
                return self._fallback_weather_scrape(city)
                
        except Exception as e:
            return self._fallback_weather_scrape(city)
    
    def _fallback_weather_scrape(self, city):
        """Fallback weather scraping from weather.com"""
        try:
            from bs4 import BeautifulSoup
            
            # Scrape weather.com
            if city:
                # Search for city first
                search_url = f"https://weather.com/search/enhancedlocalsearch?where={city.replace(' ', '%20')}"
            else:
                search_url = "https://weather.com"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(search_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Try to extract weather information
                temp_element = soup.find('span', {'data-testid': 'TemperatureValue'})
                condition_element = soup.find('div', {'data-testid': 'wxPhrase'})
                location_element = soup.find('h1', {'data-testid': 'CurrentConditionsLocation'})
                
                if temp_element and condition_element:
                    temperature = temp_element.text.strip()
                    condition = condition_element.text.strip()
                    location = location_element.text.strip() if location_element else (city if city else "Current Location")
                    
                    return f"Weather for {location}: {temperature}, {condition}"
                else:
                    return self._get_simple_weather(city)
            else:
                return self._get_simple_weather(city)
                
        except Exception:
            return self._get_simple_weather(city)
    
    def _get_simple_weather(self, city):
        """Simple weather using wttr.in text format"""
        try:
            if city:
                url = f"https://wttr.in/{city}?format=%l:+%C+%t+%h+%w"
            else:
                url = "https://wttr.in/?format=%l:+%C+%t+%h+%w"
            
            headers = {
                'User-Agent': 'curl/7.68.0'  # wttr.in likes curl user agent
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                weather_text = response.text.strip()
                return f"Current weather: {weather_text}"
            else:
                return "Unable to fetch weather data at the moment. Please try again later."
                
        except Exception as e:
            return f"Weather service unavailable: {e}"
    
    def get_forecast(self, city="", days=3):
        """Get weather forecast"""
        try:
            if city:
                url = f"https://wttr.in/{city}?format=j1"
            else:
                url = "https://wttr.in/?format=j1"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                location = data['nearest_area'][0]
                area_name = location['areaName'][0]['value']
                country = location['country'][0]['value']
                
                forecast_text = f"Weather forecast for {area_name}, {country}:\n\n"
                
                for i, day_data in enumerate(data['weather'][:days]):
                    date = day_data['date']
                    max_temp_c = day_data['maxtempC']
                    min_temp_c = day_data['mintempC']
                    max_temp_f = day_data['maxtempF']
                    min_temp_f = day_data['mintempF']
                    condition = day_data['hourly'][0]['weatherDesc'][0]['value']
                    
                    forecast_text += f"{date}: {min_temp_c}°C - {max_temp_c}°C ({min_temp_f}°F - {max_temp_f}°F), {condition}\n"
                
                return forecast_text.strip()
            else:
                return "Unable to fetch weather forecast at the moment."
                
        except Exception as e:
            return f"Weather forecast unavailable: {e}"
