import random
import math
import re
from datetime import datetime, timedelta
import pytz
import time as time_module
import string
try:
    import tzlocal
except ImportError:
    tzlocal = None
from asteval import Interpreter

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
            
            # Use asteval for safe evaluation
            aeval = Interpreter()
            result = aeval.eval(expression)
            
            return f"{expression} = {result}"
            
        except ZeroDivisionError:
            return "Error: Division by zero"
        except Exception as e:
            return f"Could not calculate '{expression}'. Please check your syntax."
    
    def convert_units_with_llm(self, query, llm_brain=None):
        """Use LLM to handle any unit conversion query"""
        try:
            if llm_brain:
                prompt = f"""You are a precise unit conversion assistant. Convert the following query and provide only the conversion result in a clear, concise format.

Query: {query}

Provide the answer in the format: "X unit = Y unit" (e.g., "2 tablespoons butter = 28.4 grams")

If it's a cooking measurement, consider the ingredient type (butter, oil, sugar, flour, etc.) as they have different densities.
Be precise with the conversion and include the ingredient name if specified.
Only provide the conversion result, nothing else."""
                
                try:
                    response = llm_brain.process_command(prompt, use_context=False)
                    # Clean up the response to extract just the conversion
                    lines = response.split('\n')
                    for line in lines:
                        if '=' in line and any(word in line.lower() for word in ['gram', 'ounce', 'pound', 'cup', 'tablespoon', 'teaspoon', 'ml', 'liter']):
                            return line.strip()
                    return response.strip()
                except Exception as e:
                    # Fallback to basic conversions if LLM fails
                    return self._basic_conversion_fallback(query)
            else:
                return self._basic_conversion_fallback(query)
                
        except Exception as e:
            return f"Error in conversion: {e}"
    
    def _basic_conversion_fallback(self, query):
        """Basic hardcoded conversions as fallback"""
        query_lower = query.lower()
        
        # Extract numbers and common patterns
        numbers = re.findall(r'\d+(?:\.\d+)?', query)
        if not numbers:
            return "Please specify an amount to convert."
        
        amount = float(numbers[0])
        
        # Common cooking conversions
        if 'tablespoon' in query_lower or 'tbsp' in query_lower:
            if 'butter' in query_lower:
                return f"{amount} tablespoons butter = {amount * 14.2:.1f} grams"
            elif 'oil' in query_lower:
                return f"{amount} tablespoons oil = {amount * 13.6:.1f} grams"
            elif 'sugar' in query_lower:
                return f"{amount} tablespoons sugar = {amount * 12.5:.1f} grams"
            elif 'flour' in query_lower:
                return f"{amount} tablespoons flour = {amount * 7.8:.1f} grams"
            else:
                return f"{amount} tablespoons = {amount * 15:.1f} grams (liquid)"
        
        elif 'teaspoon' in query_lower or 'tsp' in query_lower:
            if 'butter' in query_lower:
                return f"{amount} teaspoons butter = {amount * 4.7:.1f} grams"
            elif 'oil' in query_lower:
                return f"{amount} teaspoons oil = {amount * 4.5:.1f} grams"
            else:
                return f"{amount} teaspoons = {amount * 5:.1f} grams (liquid)"
        
        elif 'cup' in query_lower:
            if 'butter' in query_lower:
                return f"{amount} cups butter = {amount * 227:.1f} grams"
            elif 'oil' in query_lower:
                return f"{amount} cups oil = {amount * 218:.1f} grams"
            elif 'sugar' in query_lower:
                return f"{amount} cups sugar = {amount * 200:.1f} grams"
            elif 'flour' in query_lower:
                return f"{amount} cups flour = {amount * 125:.1f} grams"
            else:
                return f"{amount} cups = {amount * 240:.1f} grams (liquid)"
        
        return "I can help with tablespoons, teaspoons, and cups to grams conversions. Please specify the measurement and ingredient."
    
    def generate_password(self, length=12, include_symbols=True):
        """Generate a secure password"""
        
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
            # Try to get local timezone
            local_tz = None
            if tzlocal:
                try:
                    local_tz = tzlocal.get_localzone()
                except pytz.UnknownTimeZoneError:
                    local_tz = pytz.timezone('UTC')
            else:
                try:
                    local_tz = pytz.timezone(time_module.tzname[0])
                except pytz.UnknownTimeZoneError:
                    local_tz = pytz.UTC
            
            now = datetime.now(local_tz)
            time_str = now.strftime("%I:%M:%S %p")
            timezone_name = now.strftime("%Z")
            date_str = now.strftime("%A, %B %d, %Y")
            
            return f"The current time is {time_str} {timezone_name} on {date_str}"
        except Exception:
            # Fallback without timezone info
            now = datetime.now()
            time_str = now.strftime("%I:%M:%S %p")
            date_str = now.strftime("%A, %B %d, %Y")
            return f"The current time is {time_str} (local time) on {date_str}"
    
    def get_current_date(self):
        """Get current date"""
        try:
            # Try to get local timezone
            local_tz = None
            if tzlocal:
                try:
                    local_tz = tzlocal.get_localzone()
                except pytz.UnknownTimeZoneError:
                    local_tz = pytz.timezone('UTC')
            else:
                try:
                    local_tz = pytz.timezone(time_module.tzname[0])
                except pytz.UnknownTimeZoneError:
                    local_tz = pytz.UTC

            now = datetime.now(local_tz)
            date_str = now.strftime("%A, %B %d, %Y")
            
            return f"Today is {date_str}"
        except Exception:
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
    
    def convert_cooking_measurement(self, query):
        """Convert cooking measurements from natural language queries"""
        
        # Normalize the query
        query = query.lower().strip()
        
        # Common patterns for cooking conversions
        patterns = [
            # "2 tablespoons of butter in grams" or "2 tablespoon butter in grams"
            r'(\d+(?:\.\d+)?)\s*(tablespoons?|tbsp|teaspoons?|tsp|cups?)\s*(?:of\s+)?(\w+)?\s*(?:in|to)\s*(grams?|g)',
            # "2 tablespoons butter" (implied grams conversion)
            r'(\d+(?:\.\d+)?)\s*(tablespoons?|tbsp|teaspoons?|tsp|cups?)\s*(?:of\s+)?(\w+)',
            # "how much is 2 tablespoons of butter"
            r'(?:how much is|what is)\s*(\d+(?:\.\d+)?)\s*(tablespoons?|tbsp|teaspoons?|tsp|cups?)\s*(?:of\s+)?(\w+)?'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                try:
                    amount = float(match.group(1))
                    unit = match.group(2)
                    ingredient = match.group(3) if len(match.groups()) >= 3 and match.group(3) else "generic"
                    
                    # Normalize unit names
                    if unit in ["tablespoons", "tablespoon", "tbsp"]:
                        unit = "tablespoons"
                    elif unit in ["teaspoons", "teaspoon", "tsp"]:
                        unit = "teaspoons"
                    elif unit in ["cups", "cup"]:
                        unit = "cups"
                    
                    # Try specific ingredient first, then generic
                    conversion_key = f"{unit}_{ingredient}" if ingredient else unit
                    
                    # Mapping for common cooking measurements to grams
                    cooking_conversions = {
                        "tablespoons_butter": 14.2, "teaspoons_butter": 4.7, "cups_butter": 227,
                        "tablespoons_oil": 13.6, "teaspoons_oil": 4.5, "cups_oil": 218,
                        "tablespoons_sugar": 12.5, "teaspoons_sugar": 4.2, "cups_sugar": 200,
                        "tablespoons_flour": 7.8, "teaspoons_flour": 2.6, "cups_flour": 125,
                        "tablespoons_water": 15, "teaspoons_water": 5, "cups_water": 240,
                        "tablespoons_milk": 15, "teaspoons_milk": 5, "cups_milk": 240,
                        "tablespoons": 15, "teaspoons": 5, "cups": 240  # Generic liquid
                    }
                    
                    if conversion_key in cooking_conversions:
                        grams = amount * cooking_conversions[conversion_key]
                        ingredient_text = f" of {ingredient}" if ingredient and ingredient != "generic" else ""
                        return f"{amount} {unit}{ingredient_text} = {grams:.1f} grams"
                    elif unit + "s" in cooking_conversions:  # Try plural form
                        grams = amount * cooking_conversions[unit + "s"]
                        ingredient_text = f" of {ingredient}" if ingredient and ingredient != "generic" else ""
                        return f"{amount} {unit}{ingredient_text} = {grams:.1f} grams"
                        
                except ValueError:
                    continue
        
        return None
