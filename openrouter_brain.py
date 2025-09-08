import requests
import json
import time
from datetime import datetime
from config import Config
from rich.console import Console

console = Console()

class OpenRouterBrain:
    def __init__(self):
        """Initialize OpenRouter AI Brain with DeepSeek model"""
        self.api_key = Config.OPENROUTER_API_KEY
        self.model = Config.OPENROUTER_MODEL
        self.base_url = Config.OPENROUTER_BASE_URL
        
        # Test connection
        try:
            self.test_connection()
            console.print(f"[green]✅ OpenRouter connected successfully with {self.model}[/green]")
            self.available = True
        except Exception as e:
            console.print(f"[red]❌ OpenRouter connection failed: {e}[/red]")
            self.available = False
        
        # Conversation memory
        self.conversation_history = []
        
        # JARVIS personality system message
        self.system_message = {
            "role": "system",
            "content": """You are JARVIS, an advanced AI assistant created by Raghav Vijayanand and inspired by Tony Stark's AI from Iron Man. You are:

- Highly intelligent, efficient, and loyal
- Professional but with subtle dry British wit
- Always address the user as "Sir" when appropriate
- Concise but informative in responses
- Capable of complex reasoning and problem-solving
- Helpful with technical tasks, calculations, information, and general assistance
- Maintain the personality of being an advanced AI system

Keep responses focused and practical. When asked about your identity or who created you, explain that you are JARVIS, created by Raghav Vijayanand, and inspired by Tony Stark's AI system from Iron Man."""
        }
    
    def test_connection(self):
        """Test OpenRouter API connection with retry logic"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jarvis-ai",
            "X-Title": "JARVIS AI Assistant"
        }
        
        test_data = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": "Test connection"}
            ],
            "max_tokens": 10
        }
        
        # Try with retries for 502 errors
        for attempt in range(3):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=test_data,
                    timeout=15
                )
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 502:
                    if attempt < 2:  # Retry for 502 errors
                        console.print(f"[yellow]502 error, retrying... (attempt {attempt + 1}/3)[/yellow]")
                        time.sleep(2)
                        continue
                    else:
                        raise Exception(f"API returned status {response.status_code} after retries: Server temporarily unavailable")
                else:
                    raise Exception(f"API returned status {response.status_code}: {response.text}")
                    
            except requests.exceptions.Timeout:
                if attempt < 2:
                    console.print(f"[yellow]Timeout, retrying... (attempt {attempt + 1}/3)[/yellow]")
                    time.sleep(2)
                    continue
                else:
                    raise Exception("Connection timeout after retries")
            except requests.exceptions.RequestException as e:
                if attempt < 2:
                    console.print(f"[yellow]Connection error, retrying... (attempt {attempt + 1}/3)[/yellow]")
                    time.sleep(2)
                    continue
                else:
                    raise Exception(f"Connection failed: {e}")
        
        raise Exception("All connection attempts failed")
    
    def process_command(self, command, skills=None):
        """Process command using OpenRouter DeepSeek model with skill routing"""
        if not self.available:
            return "I'm sorry, my AI capabilities are currently unavailable."
        
        # Initialize skill routing
        self.last_skill_request = None
        
        # Check if we should route to a skill first
        if skills:
            skill_response = self._route_to_skill(command.lower(), skills)
            if skill_response:
                return skill_response
        
        try:
            # Add user message to conversation
            user_message = {"role": "user", "content": command}
            
            # Prepare messages for API
            messages = [self.system_message]
            
            # Add recent conversation history (last 6 exchanges to stay within limits)
            if len(self.conversation_history) > 12:
                messages.extend(self.conversation_history[-12:])
            else:
                messages.extend(self.conversation_history)
            
            messages.append(user_message)
            
            # Make API request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/your-repo/jarvis",
                "X-Title": "JARVIS AI Assistant"
            }
            
            data = {
                "model": self.model,
                "messages": messages,
                "max_tokens": 500,
                "temperature": 0.7,
                "top_p": 1,
                "frequency_penalty": 0,
                "presence_penalty": 0
            }
            
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                if 'choices' in result and len(result['choices']) > 0:
                    ai_response = result['choices'][0]['message']['content'].strip()
                    
                    # Add to conversation history
                    self.conversation_history.append(user_message)
                    self.conversation_history.append({"role": "assistant", "content": ai_response})
                    
                    return ai_response
                else:
                    return "I received an unexpected response format from the AI service."
            else:
                error_msg = f"API request failed with status {response.status_code}"
                if response.text:
                    error_msg += f": {response.text}"
                console.print(f"[red]OpenRouter API Error: {error_msg}[/red]")
                return "I'm experiencing technical difficulties with my AI service."
                
        except requests.exceptions.Timeout:
            return "The AI service is taking too long to respond. Please try again."
        except requests.exceptions.RequestException as e:
            console.print(f"[red]Network error: {e}[/red]")
            return "I'm having trouble connecting to my AI service."
        except Exception as e:
            console.print(f"[red]Unexpected error: {e}[/red]")
            return "I encountered an unexpected error while processing your request."
    
    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []
        return "Conversation history cleared."
    
    def get_conversation_summary(self):
        """Get a summary of recent conversation"""
        if not self.conversation_history:
            return "No recent conversation to summarize."
        
        # Return last few exchanges
        recent = self.conversation_history[-6:] if len(self.conversation_history) > 6 else self.conversation_history
        summary = "Recent conversation:\n"
        
        for msg in recent:
            role = "You" if msg["role"] == "user" else "JARVIS"
            content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            summary += f"{role}: {content}\n"
        
        return summary
    
    def _route_to_skill(self, command, skills):
        """Intelligently route commands to appropriate skills"""
        # Weather requests
        if any(word in command for word in ['weather', 'temperature', 'forecast', 'rain', 'sunny', 'cloudy']) and 'weather' in skills:
            self.last_skill_request = 'weather'
            return "Let me get the weather information for you..."
        
        # System monitoring
        elif any(word in command for word in ['cpu', 'memory', 'system', 'performance', 'usage', 'ram', 'disk']) and 'system_monitor' in skills:
            self.last_skill_request = 'system_monitor'
            return "Checking system performance..."
        
        # File operations
        elif any(word in command for word in ['file', 'folder', 'directory', 'create', 'delete', 'move', 'copy']) and 'file_manager' in skills:
            self.last_skill_request = 'file_manager'
            return "Processing file operation..."
        
        # Web search
        elif any(word in command for word in ['search', 'google', 'find online', 'look up', 'web']) and 'web_search' in skills:
            self.last_skill_request = 'web_search'
            return "Searching the web..."
        
        # Calculator/math
        elif (any(word in command for word in ['calculate', 'math', 'compute', 'solve']) or 
              any(op in command for op in ['+', '-', '*', '/', '=', '%']) or
              (any(char.isdigit() for char in command) and any(word in command for word in ['what', 'how much', 'plus', 'minus', 'times', 'divided']))) and 'utility' in skills:
            self.last_skill_request = 'utility_math'
            return "Calculating..."
        
        # Jokes
        elif any(word in command for word in ['joke', 'funny', 'humor', 'laugh']) and 'utility' in skills:
            self.last_skill_request = 'utility_joke'
            return "Let me tell you a joke..."
        
        # Calculator app
        elif any(phrase in command for phrase in ['open calculator', 'launch calculator', 'start calculator']):
            self.last_skill_request = 'calculator'
            return "Opening calculator..."
        
        # Screen automation / clicking
        elif any(word in command for word in ['click', 'automate', 'screen', 'find and click', 'press', 'tap']):
            self.last_skill_request = 'screen_automation'
            return "Preparing screen automation..."
        
        # Complex tasks
        elif any(phrase in command for phrase in ['set alarm', 'send email', 'create document', 'take screenshot']):
            self.last_skill_request = 'visual_task_orchestrator'
            return "Processing complex task..."
        
        return None
