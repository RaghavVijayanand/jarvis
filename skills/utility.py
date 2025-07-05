import random
import math
import re
from datetime import datetime, timedelta

class UtilitySkill:
    def __init__(self):
        self.jokes = [
            "Why don't scientists trust atoms? Because they make up everything!",
            "I told my wife she was drawing her eyebrows too high. She looked surprised.",
            "Why don't eggs tell jokes? They'd crack each other up!",
            "What do you call a fake noodle? An impasta!",
            "Why did the scarecrow win an award? He was outstanding in his field!",
            "What do you call a bear with no teeth? A gummy bear!",
            "Why don't skeletons fight each other? They don't have the guts!",
            "What's the best thing about Switzerland? I don't know, but the flag is a big plus!",
            "How do you organize a space party? You planet!",
            "Why did the math book look so sad? Because it had too many problems!"
        ]
        
        # Initialize conversation context for maintaining continuity
        self.conversation_context = {
            "last_command": None,
            "pending_action": None,
            "expected_response": None,
            "context_data": {}
        }
    
    def tell_joke(self):
        """Tell a random joke"""
        return random.choice(self.jokes)
    
    def calculate(self, expression):
        """Perform mathematical calculations"""
        try:
            # Clean the expression
            expression = expression.replace("^", "**")  # Handle exponents
            expression = re.sub(r'[^0-9+\-*/().\s]', '', expression)  # Remove non-math characters
            
            # Basic safety check
            if any(word in expression.lower() for word in ["import", "exec", "eval", "__"]):
                return "Invalid mathematical expression."
            
            # Evaluate the expression
            result = eval(expression)
            return f"{expression} = {result}"
            
        except ZeroDivisionError:
            return "Error: Division by zero"
        except Exception as e:
            return f"Could not calculate '{expression}'. Please check your syntax."
    
    def convert_units(self, value, from_unit, to_unit):
        """Convert between common units"""
        try:
            value = float(value)
            
            # Temperature conversions
            if from_unit.lower() == "celsius" and to_unit.lower() == "fahrenheit":
                result = (value * 9/5) + 32
                return f"{value}°C = {result:.2f}°F"
            elif from_unit.lower() == "fahrenheit" and to_unit.lower() == "celsius":
                result = (value - 32) * 5/9
                return f"{value}°F = {result:.2f}°C"
            
            # Length conversions (to meters first, then to target)
            length_to_meters = {
                "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001,
                "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01,
                "m": 1, "meter": 1, "meters": 1,
                "km": 1000, "kilometer": 1000, "kilometers": 1000,
                "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
                "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
                "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
                "mi": 1609.34, "mile": 1609.34, "miles": 1609.34
            }
            
            if from_unit.lower() in length_to_meters and to_unit.lower() in length_to_meters:
                meters = value * length_to_meters[from_unit.lower()]
                result = meters / length_to_meters[to_unit.lower()]
                return f"{value} {from_unit} = {result:.4f} {to_unit}"
            
            # Weight conversions (to grams first, then to target)
            weight_to_grams = {
                "mg": 0.001, "milligram": 0.001, "milligrams": 0.001,
                "g": 1, "gram": 1, "grams": 1,
                "kg": 1000, "kilogram": 1000, "kilograms": 1000,
                "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
                "lb": 453.592, "pound": 453.592, "pounds": 453.592
            }
            
            if from_unit.lower() in weight_to_grams and to_unit.lower() in weight_to_grams:
                grams = value * weight_to_grams[from_unit.lower()]
                result = grams / weight_to_grams[to_unit.lower()]
                return f"{value} {from_unit} = {result:.4f} {to_unit}"
            
            return f"Unit conversion from {from_unit} to {to_unit} is not supported yet."
            
        except ValueError:
            return "Invalid numeric value for conversion."
        except Exception as e:
            return f"Error in unit conversion: {e}"
    
    def generate_password(self, length=12, include_symbols=True):
        """Generate a secure password"""
        import string
        
        try:
            length = int(length)
            if length < 4:
                length = 8
            elif length > 50:
                length = 50
            
            chars = string.ascii_letters + string.digits
            if include_symbols:
                chars += "!@#$%^&*"
            
            password = ''.join(random.choice(chars) for _ in range(length))
            return f"Generated password: {password}"
            
        except Exception as e:
            return f"Error generating password: {e}"
    
    def flip_coin(self):
        """Flip a coin"""
        result = random.choice(["Heads", "Tails"])
        return f"Coin flip result: {result}"
    
    def roll_dice(self, sides=6, count=1):
        """Roll dice"""
        try:
            sides = int(sides)
            count = int(count)
            
            if sides < 2:
                sides = 6
            if count < 1 or count > 10:
                count = 1
            
            results = [random.randint(1, sides) for _ in range(count)]
            
            if count == 1:
                return f"Rolled a {sides}-sided die: {results[0]}"
            else:
                total = sum(results)
                return f"Rolled {count} {sides}-sided dice: {results} (Total: {total})"
                
        except Exception as e:
            return f"Error rolling dice: {e}"
    
    def get_random_number(self, min_val=1, max_val=100):
        """Generate a random number within range"""
        try:
            min_val = int(min_val)
            max_val = int(max_val)
            
            if min_val > max_val:
                min_val, max_val = max_val, min_val
            
            result = random.randint(min_val, max_val)
            return f"Random number between {min_val} and {max_val}: {result}"
            
        except Exception as e:
            return f"Error generating random number: {e}"
    
    def count_words(self, text):
        """Count words in text"""
        if not text.strip():
            return "No text provided to count."
        
        words = len(text.split())
        chars = len(text)
        chars_no_spaces = len(text.replace(" ", ""))
        
        return f"Text analysis: {words} words, {chars} characters, {chars_no_spaces} characters (no spaces)"
    
    def get_current_time(self):
        """Get current local time with timezone information"""
        try:
            import pytz
            import time as time_module
            
            # Try to get local timezone
            try:
                local_tz = pytz.timezone(time_module.tzname[0])
            except:
                # Fallback to system default or UTC
                try:
                    import tzlocal
                    local_tz = tzlocal.get_localzone()
                except:
                    local_tz = pytz.UTC
            
            now = datetime.now(local_tz)
            time_str = now.strftime("%I:%M:%S %p")
            timezone_name = now.strftime("%Z")
            date_str = now.strftime("%A, %B %d, %Y")
            
            return f"The current time is {time_str} {timezone_name} on {date_str}"
        except ImportError:
            # Fallback without timezone info
            now = datetime.now()
            time_str = now.strftime("%I:%M:%S %p")
            date_str = now.strftime("%A, %B %d, %Y")
            return f"The current time is {time_str} (local time) on {date_str}"
    
    def get_current_date(self):
        """Get current date"""
        try:
            import pytz
            import time as time_module
            
            # Try to get local timezone
            try:
                local_tz = pytz.timezone(time_module.tzname[0])
            except:
                try:
                    import tzlocal
                    local_tz = tzlocal.get_localzone()
                except:
                    local_tz = pytz.UTC
            
            now = datetime.now(local_tz)
            date_str = now.strftime("%A, %B %d, %Y")
            
            return f"Today is {date_str}"
        except ImportError:
            now = datetime.now()
            date_str = now.strftime("%A, %B %d, %Y")
            return f"Today is {date_str}"
    
    def timer_reminder(self, minutes):
        """Set a simple timer reminder"""
        try:
            minutes = float(minutes)
            if minutes <= 0:
                return "Timer duration must be positive."
            
            end_time = datetime.now() + timedelta(minutes=minutes)
            return f"Timer set for {minutes} minutes. Will complete at {end_time.strftime('%I:%M %p')}."
            
        except Exception as e:
            return f"Error setting timer: {e}"
    
    def set_context(self, command, pending_action=None, expected_response=None, context_data=None):
        """Set conversation context for maintaining continuity"""
        self.conversation_context = {
            "last_command": command,
            "pending_action": pending_action,
            "expected_response": expected_response,
            "context_data": context_data or {}
        }

    def get_context(self):
        """Get current conversation context"""
        return self.conversation_context

    def clear_context(self):
        """Clear conversation context"""
        self.conversation_context = {
            "last_command": None,
            "pending_action": None,
            "expected_response": None,
            "context_data": {}
        }

    def analyze_command_intent(self, command):
        """Analyze command to understand user intent and provide context-aware responses"""
        command_lower = command.lower().strip()

        # Handle location response for weather
        if (self.conversation_context.get("pending_action") == "weather" and
            self.conversation_context.get("expected_response") == "location"):
            city = self._extract_city_name(command_lower)
            if city:
                return {"intent": "weather_location_provided", "city": city, "action": "get_weather_for_city"}

        # Setting default location
        if any(phrase in command_lower for phrase in [
            "my location as default", "use my location", "current location",
            "default location", "my city", "local weather"
        ]):
            return {"intent": "set_default_location", "action": "request_location_specification"}

        # Weather commands
        if "weather" in command_lower:
            city = self._extract_city_name(command_lower)
            if city:
                return {"intent": "weather_with_location", "city": city, "action": "get_weather_for_city"}
            else:
                return {"intent": "weather_without_location", "action": "request_location"}

        # Possible city name
        if self._looks_like_city_name(command_lower):
            return {"intent": "possible_city_name", "city": command_lower, "action": "confirm_city_intent"}

        return {"intent": "general_command", "action": "process_normally"}

    def provide_contextual_response(self, intent_analysis):
        """Provide contextual response based on intent analysis"""
        intent = intent_analysis.get("intent")

        if intent == "weather_location_provided":
            city = intent_analysis.get("city")
            self.clear_context()
            return f"Getting weather information for {city}..."

        elif intent == "set_default_location":
            self.set_context(
                command="location_setup",
                pending_action="weather",
                expected_response="location",
                context_data={"setup_type": "default"}
            )
            return "I'd be happy to use your location as default. Could you please tell me the name of your city?"

        elif intent == "weather_without_location":
            self.set_context(
                command="weather_request",
                pending_action="weather",
                expected_response="location"
            )
            return "I'd be happy to get the weather for you. Could you please specify the city name?"

        elif intent == "possible_city_name":
            if self.conversation_context.get("pending_action") == "weather":
                city = intent_analysis.get("city")
                self.clear_context()
                return f"Getting weather information for {city}..."
            else:
                return None

        return None

    def _extract_city_name(self, command):
        """Extract city name from command"""
        weather_words = ["weather", "forecast", "temperature", "climate", "for", "in", "at", "the"]
        words = command.split()
        city_words = [word for word in words if word not in weather_words]
        return " ".join(city_words).strip() if city_words else None

    def _looks_like_city_name(self, command):
        """Simple heuristic to check if command looks like a city name"""
        words = command.split()
        if len(words) > 3:
            return False
        command_indicators = [
            "calculate", "compute", "tell", "show", "open", "close", "run",
            "start", "stop", "help", "what", "how", "when", "where", "why"
        ]
        return not any(indicator in command for indicator in command_indicators)
