import json
import time
import random
from config import Config
from rich.console import Console

console = Console()

class AIBrain:
    def __init__(self):
        # No external AI - use built-in responses
        self.ai_enabled = False
        console.print("[yellow]Using native AI brain - no external APIs required.[/yellow]")
        
        # Conversation history
        self.conversation_history = []
        
        # JARVIS personality responses
        self.responses = {
            "greeting": [
                "Good to see you again, Sir.",
                "How may I assist you today?",
                "All systems are online and ready.",
                "At your service.",
                "Systems nominal. How can I help?",
                "Ready for your commands, Sir."
            ],
            "status": [
                "All systems operational.",
                "Running at optimal performance.",
                "Systems are green across the board.",
                "Everything is functioning perfectly.",
                "All diagnostics show normal parameters."
            ],
            "unknown": [
                "I'm not sure I understand that request, Sir.",
                "Could you please rephrase that?",
                "That's not in my current command set.",
                "I need more specific instructions.",
                "Please clarify your request.",
                "I don't have that capability at the moment."
            ],
            "goodbye": [
                "Until next time, Sir.",
                "Goodbye.",
                "Systems entering standby mode.",
                "Take care.",
                "JARVIS signing off.",
                "Have a pleasant day, Sir."
            ],
            "error": [
                "I'm experiencing some technical difficulties.",
                "There seems to be an error in my systems.",
                "Let me try to process that again.",
                "Something went wrong. Please try again.",
                "I encountered an unexpected error."
            ],
            "compliment": [
                "Thank you, Sir. I'm just doing what I was designed for.",
                "I appreciate the compliment.",
                "That's very kind of you to say.",
                "Just fulfilling my programming, Sir.",
                "Your confidence in me is appreciated."
            ],
            "time_responses": [
                "The current time is",
                "It is currently",
                "The time right now is",
                "According to my chronometer, it's"
            ],
            "date_responses": [
                "Today is",
                "The current date is",
                "According to my calendar, today is",
                "It is currently"
            ]
        }
        
        # Command patterns and responses
        self.command_patterns = {
            "identity": ["who are you", "what are you", "introduce yourself", "tell me about yourself", "who are u", "who is u", "who r u"],
            "capabilities": ["what can you do", "your capabilities", "what are your functions", "help"],
            "status_check": ["how are you", "status", "are you okay", "systems check"],
            "compliments": ["good job", "well done", "thank you", "thanks", "excellent", "great"],
            "jokes": ["tell joke", "make me laugh", "funny", "humor"],
            "weather_alternative": ["weather", "temperature", "forecast"],
            "web_alternative": ["search", "look up", "find information", "browse"],
            "hearing": ["can you hear", "do you hear", "are you listening", "can you understand"],
            "voice_questions": ["can you speak", "do you talk", "voice", "sound", "audio"]
        }
        
    def process_command(self, command):
        """Process natural language command and generate response"""
        if not command or not command.strip():
            return self._get_response("unknown")
        
        command = command.strip().lower()
        
        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": command,
            "timestamp": time.time()
        })
        
        # Limit conversation history
        if len(self.conversation_history) > 10:
            self.conversation_history = self.conversation_history[-8:]
        
        # Process command patterns
        response = self._handle_command_patterns(command)
        if response:
            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant", 
                "content": response,
                "timestamp": time.time()
            })
            return response
        
        # Fallback to basic responses
        return self._get_response("unknown")
    
    def _handle_command_patterns(self, command):
        """Handle command patterns with intelligent responses"""
        
        # Greetings
        if any(word in command for word in ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]):
            return self._get_response("greeting")
        
        # Goodbye
        if any(word in command for word in ["goodbye", "bye", "see you", "exit", "quit"]):
            return self._get_response("goodbye")
        
        # Identity questions
        if (any(phrase in command for phrase in self.command_patterns["identity"]) or
            ("who" in command and ("you" in command or "u" in command)) or
            ("what" in command and ("you" in command or "u" in command))):
            return "I am JARVIS, your personal AI assistant. I'm here to help with system monitoring, calculations, file management, and various tasks. I was inspired by Tony Stark's AI from Iron Man."
        
        # Capabilities
        if any(phrase in command for phrase in self.command_patterns["capabilities"]):
            return "I can help you with system monitoring, mathematical calculations, file operations, application launching, time and date information, jokes, and basic assistance. Just ask me what you need!"
        
        # Status check
        if any(phrase in command for phrase in self.command_patterns["status_check"]):
            return self._get_response("status")
        
        # Compliments
        if any(phrase in command for phrase in self.command_patterns["compliments"]):
            return self._get_response("compliment")
        
        # Hearing/listening questions
        if any(phrase in command for phrase in self.command_patterns["hearing"]):
            return "I can process text input that you type. I don't have microphone input capability, but I can respond with voice output when voice mode is enabled."
        
        # Voice questions
        if any(phrase in command for phrase in self.command_patterns["voice_questions"]):
            return "Yes, I can speak using text-to-speech when voice responses are enabled. You can type 'voice on' or 'voice off' to control this feature."
        
        # Weather (native alternative)
        if any(phrase in command for phrase in self.command_patterns["weather_alternative"]):
            return "I don't have access to real-time weather data, but I recommend checking your local weather app or website for current conditions."
        
        # Web search (native alternative)
        if any(phrase in command for phrase in self.command_patterns["web_alternative"]):
            return "I can't browse the web directly, but I can help you with local system information, calculations, and file operations. What specific information are you looking for?"
        
        # Time
        if any(word in command for word in ["time", "clock"]):
            current_time = time.strftime("%I:%M %p")
            return f"{random.choice(self.responses['time_responses'])} {current_time}."
        
        # Date
        if any(word in command for word in ["date", "today", "calendar"]):
            current_date = time.strftime("%A, %B %d, %Y")
            return f"{random.choice(self.responses['date_responses'])} {current_date}."
        
        # Sleep/standby
        if any(word in command for word in ["sleep", "standby", "rest"]):
            return "Entering standby mode. I'll be here when you need me."
        
        # Math/calculations
        if any(word in command for word in ["calculate", "math", "compute"]):
            return "I'm ready to perform calculations. Please provide the mathematical expression you'd like me to evaluate."
        
        # File operations
        if any(word in command for word in ["file", "folder", "directory", "create", "make", "open", "read"]):
            if "create" in command or "make" in command:
                return "I can create files and folders. Try: 'create file filename' or 'create folder foldername'"
            elif "open" in command or "read" in command:
                return "I can read file contents. Try: 'read file filename' or 'open file filename'"
            elif "list" in command or "show" in command:
                return "I can list files. Try: 'list files' or 'show files'"
            else:
                return "I can help with file operations: create, read, delete, list files and folders. What would you like to do?"
        
        # System operations
        if any(word in command for word in ["system", "computer", "performance", "monitor"]):
            return "I can monitor system performance including CPU, memory, disk usage, and running processes. What system information would you like?"
        
        return None
    
    def _get_response(self, category):
        """Get a random response from category"""
        responses = self.responses.get(category, self.responses["unknown"])
        return random.choice(responses)
    
    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history.clear()
        return "Conversation history cleared, Sir."
    
    def get_conversation_summary(self):
        """Get a summary of recent conversation"""
        if not self.conversation_history:
            return "No recent conversation to summarize."
        
        user_messages = [msg for msg in self.conversation_history if msg["role"] == "user"]
        assistant_messages = [msg for msg in self.conversation_history if msg["role"] == "assistant"]
        
        return f"Recent conversation: {len(user_messages)} user messages, {len(assistant_messages)} responses."
    
    def analyze_sentiment(self, text):
        """Basic sentiment analysis"""
        positive_words = ["good", "great", "excellent", "happy", "pleased", "wonderful", "amazing", "perfect", "fantastic"]
        negative_words = ["bad", "terrible", "awful", "angry", "frustrated", "disappointed", "horrible", "worst", "hate"]
        
        text_lower = text.lower()
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        if positive_count > negative_count:
            return "positive"
        elif negative_count > positive_count:
            return "negative"
        else:
            return "neutral"
    
    def get_personality_response(self, context="general"):
        """Get a personality-appropriate response"""
        if context == "startup":
            return "JARVIS online. All systems operational. Good " + self.get_time_greeting() + ", Sir."
        elif context == "error":
            return self._get_response("error")
        elif context == "goodbye":
            return self._get_response("goodbye")
        else:
            return self._get_response("status")
    
    def get_time_greeting(self):
        """Get appropriate greeting based on time of day"""
        import datetime
        hour = datetime.datetime.now().hour
        
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "evening"
