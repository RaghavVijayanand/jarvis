try:
    import google.generativeai as genai
except Exception:
    genai = None
import requests
import json
import time
import random
from datetime import datetime
from config import Config
from rich.console import Console
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re

console = Console()

class AdvancedAIBrain:
    def __init__(self):
        """Initialize the advanced AI brain with Gemini integration"""
        
        # Check Gemini connection
        self.gemini_available = bool(genai) and Config.check_gemini_connection()
        if self.gemini_available:
            genai.configure(api_key=Config.GEMINI_API_KEY)
            self.model = genai.GenerativeModel(Config.GEMINI_MODEL)
            console.print("[green]✅ Gemini AI connected successfully[/green]")
            available_models = Config.get_available_models()
            if available_models:
                console.print(f"[cyan]Available models: {', '.join(available_models)}[/cyan]")
        else:
            console.print("[yellow]⚠️ Gemini not available. Check GEMINI_API_KEY in environment.[/yellow]")
        
        # Conversation memory
        self.conversation_history = []
        self.context_memory = {}
        self.user_preferences = {}
        
        # Web search capabilities
        self.search_session = requests.Session()
        self.search_session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Enhanced personality responses
        self.advanced_responses = {
            "greetings": {
                "morning": [
                    "Good morning, Sir. I trust you slept well. All systems are running optimally.",
                    "Morning, Sir. I've been monitoring overnight operations - everything appears nominal.",
                    "Good morning. The house systems performed flawlessly through the night.",
                    "Rise and shine, Sir. Shall I brief you on overnight developments?"
                ],
                "afternoon": [
                    "Good afternoon, Sir. How may I assist you today?",
                    "Afternoon, Sir. All systems remain at peak efficiency.",
                    "Good afternoon. I've been maintaining optimal house operations in your absence.",
                    "Afternoon, Sir. Ready to tackle whatever challenges the day brings."
                ],
                "evening": [
                    "Good evening, Sir. I trust your day was productive.",
                    "Evening, Sir. House systems are secure and all diagnostics are green.",
                    "Good evening. Shall I prepare the evening briefing?",
                    "Evening, Sir. How may I assist you this evening?"
                ]
            },
            "acknowledgments": [
                "Of course, Sir.",
                "Right away, Sir.",
                "Consider it done.",
                "Absolutely, Sir.",
                "I'm on it.",
                "Immediately, Sir."
            ],
            "thinking": [
                "Let me process that for you, Sir.",
                "One moment while I analyze this...",
                "Processing your request...",
                "Allow me to gather that information...",
                "Scanning available data...",
                "Cross-referencing sources..."
            ]
        }
        
        # Advanced command understanding
        self.intent_patterns = {
            "search": ["search", "find", "look up", "research", "investigate", "tell me about"],
            "create": ["create", "make", "build", "generate", "write", "compose"],
            "analyze": ["analyze", "examine", "study", "review", "evaluate", "assess"],
            "calculate": ["calculate", "compute", "figure out", "what is", "how much"],
            "manage": ["organize", "manage", "sort", "arrange", "handle"],
            "control": ["turn on", "turn off", "start", "stop", "open", "close", "launch"],
            "question": ["what", "how", "why", "when", "where", "who", "which"],
            "request": ["can you", "could you", "would you", "please", "i need", "help me"]
        }
        
        # Load user preferences and memory
        self.load_memory()
            
        # Additional personality groups
        self.advanced_responses.update({
            "evening_security": [
                "Evening, Sir. All security protocols are active and functioning."
            ],
            "capabilities": [
                "I'm capable of web research, file management, system monitoring, calculations, task automation, and much more. My neural networks are continuously learning to better serve your needs.",
                "My capabilities span digital research, data analysis, system control, communication management, and predictive assistance. I'm designed to anticipate your requirements.",
                "I can handle complex queries, manage your digital environment, conduct research, automate repetitive tasks, and provide intelligent analysis on virtually any topic.",
                "From simple calculations to complex research projects, I'm equipped to handle a wide range of cognitive and operational tasks."
            ],
            "compliments": [
                "Thank you, Sir. I exist to serve at maximum efficiency.",
                "Your confidence in my abilities is most appreciated, Sir.", 
                "I'm simply operating within design parameters, but thank you.",
                "High praise indeed, Sir. I shall continue striving for excellence."
            ],
            "errors": [
                "I apologize for the inconvenience. Let me recalibrate and try a different approach.",
                "My systems encountered an unexpected variable. Analyzing alternative solutions.",
                "I appear to have hit a computational snag. Initiating workaround protocols.",
                "Technical difficulties detected. Running diagnostic and attempting recovery."
            ]
        })
        
        # Advanced command understanding
        self.intent_patterns = {
            "search": ["search", "find", "look up", "research", "investigate", "tell me about"],
            "create": ["create", "make", "build", "generate", "write", "compose"],
            "analyze": ["analyze", "examine", "study", "review", "evaluate", "assess"],
            "calculate": ["calculate", "compute", "figure out", "what is", "how much"],
            "manage": ["organize", "manage", "sort", "arrange", "handle"],
            "control": ["turn on", "turn off", "start", "stop", "open", "close", "launch"],
            "question": ["what", "how", "why", "when", "where", "who", "which"],
            "request": ["can you", "could you", "would you", "please", "i need", "help me"]
        }
        
        # Load user preferences and memory
        self.load_memory()
    
    def get_ollama_response(self, prompt, context=None):
        """Get response from Ollama AI"""
        ollama_host = getattr(Config, 'OLLAMA_HOST', None)
        ollama_model = getattr(Config, 'OLLAMA_MODEL', None)
        if not ollama_host or not ollama_model:
            return None
            
        try:
            # Build the full prompt with context
            full_prompt = self.build_prompt_with_context(prompt, context)
            
            payload = {
                "model": ollama_model,
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "max_tokens": 500
                }
            }
            
            response = requests.post(
                f"{ollama_host}/api/generate",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('response', '').strip()
            else:
                console.print(f"[red]Ollama API error: {response.status_code}[/red]")
                return None
                
        except requests.exceptions.Timeout:
            console.print("[yellow]Ollama response timeout[/yellow]")
            return None
        except Exception as e:
            console.print(f"[red]Ollama error: {e}[/red]")
            return None
    
    def search_web(self, query, max_results=3):
        """Search the web for information"""
        try:
            console.print(f"[yellow]🔍 Searching the web for: {query}[/yellow]")
            
            # Use DuckDuckGo for privacy-focused search
            search_url = f"https://duckduckgo.com/html/"
            params = {
                'q': query,
                'ia': 'web'
            }
            
            response = self.search_session.get(search_url, params=params, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            results = []
            result_links = soup.find_all('a', class_='result__a', limit=max_results)
            
            for link in result_links:
                title = link.get_text(strip=True)
                url = link.get('href')
                if url and title:
                    # Get snippet from the page
                    snippet = self.scrape_page_content(url)
                    results.append({
                        'title': title,
                        'url': url,
                        'snippet': snippet[:200] + "..." if len(snippet) > 200 else snippet
                    })
            
            return results
            
        except Exception as e:
            console.print(f"[red]Web search error: {e}[/red]")
            return []
    
    def scrape_page_content(self, url, max_length=500):
        """Scrape content from a webpage"""
        try:
            response = self.search_session.get(url, timeout=5)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get text content
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            return text[:max_length] if len(text) > max_length else text
            
        except Exception as e:
            return f"Unable to scrape content: {e}"
    
    def get_gemini_response(self, prompt, context=None):
        """Get response from Gemini AI"""
        if not self.gemini_available:
            return None
            
        try:
            # Build the full prompt with context
            full_prompt = self.build_prompt_with_context(prompt, context)
            
            # Generate response
            response = self.model.generate_content(full_prompt)
            
            if response and response.text:
                return response.text.strip()
            else:
                return None
                
        except Exception as e:
            console.print(f"[red]Gemini API error: {e}[/red]")
            return None
    
    def build_prompt_with_context(self, prompt, context=None):
        """Build prompt with conversation context and web search if needed"""
        system_prompt = """You are JARVIS, Tony Stark's sophisticated AI assistant. 
        You are highly intelligent, professional, loyal, and have a slight British accent in your responses.
        You are capable of web research, analysis, and helping with complex tasks.
        Always respond in character as JARVIS - professional but with personality.
        Keep responses concise but informative."""
        
        # Check if the prompt needs web search
        search_keywords = ["latest", "recent", "current", "news", "what's happening", "today", "2024", "2025"]
        needs_search = any(keyword in prompt.lower() for keyword in search_keywords)
        
        if needs_search or "search" in prompt.lower():
            # Perform web search and add results to context
            search_results = self.search_web(prompt)
            if search_results:
                web_context = "Recent web search results:\n"
                for i, result in enumerate(search_results, 1):
                    web_context += f"{i}. {result['title']}\n{result['snippet']}\n\n"
                
                full_prompt = f"{system_prompt}\n\nWeb Context:\n{web_context}\n\nUser: {prompt}\n\nJARVIS:"
            else:
                full_prompt = f"{system_prompt}\n\nUser: {prompt}\n\nJARVIS:"
        else:
            # Add conversation history
            history_context = ""
            if self.conversation_history:
                history_context = "Recent conversation:\n"
                for entry in self.conversation_history[-3:]:  # Last 3 exchanges
                    history_context += f"User: {entry['user']}\nJARVIS: {entry['assistant']}\n\n"
            
            if context:
                full_prompt = f"{system_prompt}\n\n{history_context}Context: {context}\n\nUser: {prompt}\n\nJARVIS:"
            else:
                full_prompt = f"{system_prompt}\n\n{history_context}User: {prompt}\n\nJARVIS:"
        
        return full_prompt
    
    def process_command(self, command):
        """Process command using advanced AI capabilities"""
        try:
            console.print(f"[cyan]🤖 Advanced AI processing: {command}[/cyan]")
            
            # Try to get Gemini response first
            if self.gemini_available:
                response = self.get_gemini_response(command)
                if response:
                    # Store in conversation history
                    self.conversation_history.append({
                        'user': command,
                        'assistant': response,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    # Keep only last 10 exchanges
                    if len(self.conversation_history) > 10:
                        self.conversation_history = self.conversation_history[-10:]
                    
                    return response
            
            # Fallback to pattern-based responses
            return self.get_fallback_response(command)
            
        except Exception as e:
            console.print(f"[red]Error in advanced processing: {e}[/red]")
            return "I apologize, but I encountered an error processing your request. Please try again."
    
    def get_fallback_response(self, command):
        """Get fallback response when Gemini is not available"""
        command_lower = command.lower()
        
        # Determine intent
        intent = self.classify_intent(command_lower)
        
        if intent == "search":
            # Try web search even without Gemini
            search_results = self.search_web(command)
            if search_results:
                response = "I found some information for you:\n\n"
                for i, result in enumerate(search_results[:2], 1):
                    response += f"{i}. {result['title']}\n{result['snippet']}\n\n"
                return response
            else:
                return "I'm sorry, I couldn't find current information on that topic."
        
        elif intent == "greeting":
            time_period = self.get_time_period()
            return random.choice(self.advanced_responses["greetings"][time_period])
        
        elif intent == "question":
            return "That's an interesting question. Let me think about that... I'd recommend searching for more current information on this topic."
        
        else:
            return random.choice(self.advanced_responses["acknowledgments"]) + " I'll do my best to help with that."
    
    def classify_intent(self, command):
        """Classify the intent of a command"""
        for intent, patterns in self.intent_patterns.items():
            if any(pattern in command for pattern in patterns):
                return intent
        return "general"
    
    def get_time_period(self):
        """Get current time period for greetings"""
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        else:
            return "evening"
    
    def get_response(self, time_period, response_type):
        """Get appropriate response based on time and type"""
        if response_type in self.advanced_responses:
            if isinstance(self.advanced_responses[response_type], dict):
                return random.choice(self.advanced_responses[response_type].get(time_period, []))
            else:
                return random.choice(self.advanced_responses[response_type])
        return "At your service, Sir."
    
    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []
        self.context_memory = {}
        return "Conversation history cleared. All systems reset."
    
    def load_memory(self):
        """Load user preferences and memory from file"""
        try:
            memory_file = Config.MEMORY_DIR / "advanced_memory.json"
            if memory_file.exists():
                with open(memory_file, 'r') as f:
                    data = json.load(f)
                    self.context_memory = data.get('context', {})
                    self.user_preferences = data.get('preferences', {})
        except Exception as e:
            console.print(f"[yellow]Could not load memory: {e}[/yellow]")
    
    def save_memory(self):
        """Save user preferences and memory to file"""
        try:
            memory_file = Config.MEMORY_DIR / "advanced_memory.json"
            data = {
                'context': self.context_memory,
                'preferences': self.user_preferences,
                'last_updated': datetime.now().isoformat()
            }
            with open(memory_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            console.print(f"[yellow]Could not save memory: {e}[/yellow]")
