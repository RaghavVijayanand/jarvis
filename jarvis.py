#!/usr/bin/env python3
"""
JARVIS - AI Assistant
Inspired by Tony Stark's AI from Iron Man

A sophisticated AI assistant with text-to-speech, natural language processing,
system control, and various intelligent capabilities.
"""

import threading
import time
import signal
import sys
import os
from datetime import datetime
import random

# Rich console for beautiful output
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich.live import Live
from rich import box

# Core JARVIS modules
from config import Config

# Global flag for agent availability
AGENT_AVAILABLE = False

# Attempt to import the autonomous agent orchestrator
try:
   from agent_orchestrator import AgentOrchestrator
   AGENT_AVAILABLE = True
except Exception as _:
   AGENT_AVAILABLE = False

from voice_engine import VoiceEngine
from brain import AIBrain
from openrouter_brain import OpenRouterBrain

# Multi-model AI brain
try:
    from multi_model_brain import MultiModelBrain
    MULTI_MODEL_AVAILABLE = True
except Exception as e:
    MULTI_MODEL_AVAILABLE = False
    print(f"Multi-model brain not available: {e}")

from system_control import SystemControl

# Skills
from skills.weather import WeatherSkill
from skills.web_search import WebSearchSkill
from skills.web_scraper import WebScraperSkill
from skills.utility import UtilitySkill
from skills.file_manager import FileManagerSkill
from skills.automation import AutomationSkill
from skills.app_control import ApplicationControl
from skills.command_processor import CommandProcessor
from skills.task_scheduler import TaskScheduler
from skills.system_monitor import SystemMonitor

console = Console()

class JARVIS:
    def __init__(self):
        """Initialize JARVIS AI Assistant"""
        
        # Display startup banner
        self.display_startup_banner()
        
        # Initialize core components
        console.print("[yellow]Initializing JARVIS systems...[/yellow]")
        
        self.voice_engine = VoiceEngine()
        
        # Initialize AI brains - Enhanced multi-model support
        self.use_multi_model = Config.USE_MULTI_MODEL and MULTI_MODEL_AVAILABLE
        
        if self.use_multi_model:
            try:
                self.multi_brain = MultiModelBrain()
                if self.multi_brain.available_models:
                    console.print(f"[green]🧠 Multi-model AI initialized with {len(self.multi_brain.available_models)} models[/green]")
                    console.print(f"[green]Current model: {self.multi_brain.current_model}[/green]")
                    self.brain_type = "multi_model"
                    # Compatibility alias for existing code
                    self.brain = self.multi_brain
                    self.use_advanced_brain = True
                else:
                    self.use_multi_model = False
                    console.print("[yellow]Multi-model brain has no available models, falling back[/yellow]")
            except Exception as e:
                console.print(f"[yellow]Multi-model brain failed: {e}[/yellow]")
                self.use_multi_model = False
        
        if not self.use_multi_model:
            # Fallback to original brain system
            self.brain = AIBrain()
            self.use_advanced_brain = Config.USE_OPENROUTER
            
            if self.use_advanced_brain:
                self.openrouter_brain = OpenRouterBrain()
                if not self.openrouter_brain.available:
                    console.print("[yellow]OpenRouter not available, falling back to native brain[/yellow]")
                    console.print("[dim]This could be due to network issues, API service downtime, or invalid API key[/dim]")
                    self.use_advanced_brain = False
                    self.brain_type = "native"
                else:
                    console.print("[green]Using OpenRouter with Qwen model[/green]")
                    self.brain_type = "openrouter"
            
            if not self.use_advanced_brain:
                console.print("[yellow]Using native AI brain - no external APIs required.[/yellow]")
                self.brain_type = "native"
        
        self.system_control = SystemControl()
        
        # Initialize skills
        self.weather_skill = WeatherSkill()
        self.web_skill = WebSearchSkill()
        self.utility_skill = UtilitySkill()
        self.file_skill = FileManagerSkill()
        # Initialize automation and app control skills
        try:
            self.automation_skill = AutomationSkill()
            console.print("[green]✅ Automation system initialized[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️ Automation system failed: {e}[/yellow]")
            self.automation_skill = None
        
        try:
            self.app_control = ApplicationControl()
            console.print("[green]✅ Application control initialized[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️ Application control failed: {e}[/yellow]")
            self.app_control = None
        
        # Initialize enhanced skills
        try:
            self.command_processor = CommandProcessor(self)
            console.print("[green]✅ Enhanced command processor initialized[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️ Command processor failed: {e}[/yellow]")
            self.command_processor = None
        
        try:
            self.task_scheduler = TaskScheduler(self)
            console.print("[green]✅ Task scheduler initialized[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️ Task scheduler failed: {e}[/yellow]")
            self.task_scheduler = None
        
        try:
            self.system_monitor = SystemMonitor()
            console.print("[green]✅ Advanced system monitor initialized[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️ System monitor failed: {e}[/yellow]")
            self.system_monitor = None
        # Track last created or manipulated file for rename operations
        self.last_created_file = None
        # Initialize autonomous agent orchestrator if available
        self.agent_available = AGENT_AVAILABLE
        if self.agent_available:
            try:
                # Pass multi_brain to agent if available
                multi_brain_ref = self.multi_brain if self.use_multi_model else None
                self.agent = AgentOrchestrator(self.system_control,
                                               self.weather_skill,
                                               self.web_skill,
                                               self.utility_skill,
                                               self.file_skill,
                                               multi_brain=multi_brain_ref)
            except Exception as e:
                console.print(f"[yellow]Agent initialization failed: {e}[/yellow]")
                console.print("[yellow]Falling back to basic brain mode[/yellow]")
                self.agent_available = False
        
        # System state
        self.is_running = False
        self.is_sleeping = False
        self.last_activity = time.time()
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        console.print("[green]All systems initialized successfully![/green]")
        
    def display_startup_banner(self):
        """Display JARVIS startup banner"""
        banner_text = Text()
        banner_text.append("    ▄▄▄██▀▀▀▄▄▄·  ▄▄▄  ██▒   █▓ ██▓  ██████ \n", "cyan")
        banner_text.append("      ▒██  ▐█ ▀█ ▀▄ █·▓██░   █▒▓██▒▒██    ▒ \n", "cyan")
        banner_text.append("      ░██  ▄█▀▀█ ▐▀▀▄  ▓██  █▒░▒██▒░ ▓██▄   \n", "cyan")
        banner_text.append("   ██▄██▓ ▐█ ▪▐▌▐█•█▌  ▒██ █░░░██░  ▒   ██▒\n", "cyan")
        banner_text.append("    ▓▀▀▀   ▀  ▀ .▀  ▀   ▒▀█░  ░██░▒██████▒▒\n", "cyan")
        banner_text.append("                          ░ ▐░  ░▓  ▒ ▒▓▒ ▒ ░\n", "cyan")
        banner_text.append("                          ░ ░░   ▒ ░░ ░▒  ░ ░\n", "cyan")
        banner_text.append("                            ░░   ▒ ░░  ░  ░  \n", "cyan")
        banner_text.append("                             ░   ░        ░  \n", "cyan")
        
        banner_panel = Panel(
            banner_text,
            title="[bold blue]JARVIS AI Assistant[/bold blue]",
            subtitle="[italic]Just A Rather Very Intelligent System[/italic]",
            border_style="blue",
            box=box.DOUBLE
        )
        
        console.print(banner_panel)
        console.print()
        console.print("[italic cyan]\"Sometimes you gotta run before you can walk.\"[/italic cyan] - Tony Stark")
        console.print()
        console.print("[bold green]🚀 Enhanced Features Loaded:[/bold green]")
        console.print("  • Advanced compound command processing")
        console.print("  • Task scheduling and automation")
        console.print("  • Detailed system monitoring")
        console.print("  • Smart file creation with AI content")
        console.print("  • Background web scraping")
        console.print()
        console.print("[dim]Type 'help' or 'what can you do' to see all capabilities[/dim]")
        console.print()
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        console.print(f"\n[yellow]Received signal {signum}. Shutting down JARVIS...[/yellow]")
        self.shutdown()
    
    def process_command(self, command, use_voice=True):
        """Process and execute commands"""
        if not command:
            return
        
        command = command.lower().strip()
        self.last_activity = time.time()
        
        console.print(f"[green]Processing command:[/green] {command}")
        
        # Check for exit commands
        if any(word in command for word in ["goodbye", "exit", "quit", "shutdown jarvis"]):
            response = "Goodbye. JARVIS systems shutting down."
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            self.shutdown()
            return
        
        # Sleep command
        if any(word in command for word in ["sleep", "standby", "go to sleep"]):
            self.is_sleeping = True
            response = "Entering sleep mode."
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        # Wake up command
        if any(phrase in command for phrase in ["wake up", "wake", "jarvis wake up"]):
            self.is_sleeping = False
            response = "I'm awake and ready to assist."
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        # Skip processing if sleeping
        if self.is_sleeping:
            return
        
        # System commands
        if "system status" in command or "system report" in command:
            status = self.system_control.get_system_status()
            response = "System status retrieved."
            if use_voice:
                self.voice_engine.speak(response)
            console.print(Panel(status, title="System Status", border_style="green"))
            return
        
        if "running processes" in command or "process list" in command:
            processes = self.system_control.get_running_processes()
            response = "Top processes retrieved."
            if use_voice:
                self.voice_engine.speak(response)
            console.print(Panel(processes, title="Running Processes", border_style="yellow"))
            return
        
        if "disk usage" in command or "storage" in command:
            disk_info = self.system_control.get_disk_usage()
            response = "Disk usage information retrieved."
            if use_voice:
                self.voice_engine.speak(response)
            console.print(Panel(disk_info, title="Disk Usage", border_style="blue"))
            return
        
        # Application launcher
        if command.startswith("open ") or command.startswith("launch "):
            app_name = command.replace("open ", "").replace("launch ", "")
            result = self.system_control.launch_application(app_name)
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        # Weather commands
        if "weather" in command:
            result = self.weather_skill.get_weather()
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        # Search commands
        if command.startswith("search for ") or command.startswith("look up "):
            query = command.replace("search for ", "").replace("look up ", "")
            result = self.web_skill.search_web(query, open_browser=True)
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        if command.startswith("wikipedia ") or "wiki" in command:
            query = command.replace("wikipedia ", "").replace("wiki ", "")
            result = self.web_skill.search_wikipedia(query)
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        # News
        if "news" in command or "headlines" in command:
            result = self.web_skill.get_news_headlines()
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        # Utility commands
        if "tell me a joke" in command or "joke" in command:
            joke = self.utility_skill.tell_joke()
            if use_voice:
                self.voice_engine.speak(joke)
            else:
                console.print(f"[blue]JARVIS:[/blue] {joke}")
            return
        
        if "calculate" in command or "math" in command:
            # Extract the mathematical expression
            expression = command.replace("calculate", "").replace("math", "").strip()
            if expression:
                result = self.utility_skill.calculate(expression)
                if use_voice:
                    self.voice_engine.speak(result)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {result}")
            else:
                response = "What would you like me to calculate?"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if "flip a coin" in command or "coin flip" in command:
            result = self.utility_skill.flip_coin()
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        if "roll dice" in command or "roll a die" in command:
            result = self.utility_skill.roll_dice()
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        # Time and date with timezone awareness
        if command == "time" or "what time" in command or "current time" in command or "whats the time" in command or "time is" in command:
            try:
                import pytz
                from datetime import datetime
                
                # Get local timezone
                local_tz = None
                try:
                    import time as time_module
                    local_tz = pytz.timezone(time_module.tzname[0])
                except:
                    # Fallback to system timezone
                    local_tz = pytz.timezone('Asia/Kolkata')  # IST as you mentioned
                
                # Get current time in local timezone
                now = datetime.now(local_tz)
                current_time = now.strftime("%I:%M %p")
                timezone_name = now.strftime("%Z")
                
                response = f"The current time is {current_time} {timezone_name}"
            except ImportError:
                # Fallback if pytz not available
                current_time = datetime.now().strftime("%I:%M %p")
                response = f"The current time is {current_time} (local time)"
            
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if "what date" in command or "today's date" in command or "whats the date" in command:
            try:
                import pytz
                from datetime import datetime
                
                # Get local timezone
                local_tz = None
                try:
                    import time as time_module
                    local_tz = pytz.timezone(time_module.tzname[0])
                except:
                    local_tz = pytz.timezone('Asia/Kolkata')  # IST fallback
                
                now = datetime.now(local_tz)
                current_date = now.strftime("%A, %B %d, %Y")
                response = f"Today is {current_date}"
            except ImportError:
                current_date = datetime.now().strftime("%A, %B %d, %Y")
                response = f"Today is {current_date}"
                
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        # Help and capability commands
        if "help" in command or "what can you do" in command or "capabilities" in command:
            help_text = """
🤖 JARVIS Capabilities:

📊 SYSTEM CONTROL:
• System status, RAM/CPU usage, disk info
• Launch/close applications, window management
• Take screenshots, set volume, battery info
• Detailed hardware info, system health checks
• Performance monitoring, network analysis

🗂️ FILE MANAGEMENT:
• Create, read, delete files and folders
• Generate content-rich files about topics
• Navigate directories, rename files

🌐 WEB & SEARCH:
• Google search, Wikipedia lookup
• Latest news headlines, weather updates
• Background web scraping (no browser needed)

🎯 AUTOMATION:
• Mouse/keyboard control, window automation
• Complex command sequences with "then"
• Click, type, press keys, drag & drop

⏰ SCHEDULING:
• Schedule tasks and reminders
• Recurring system checks and backups
• Time-based automation routines

🎮 APPLICATION CONTROL:
• Smart app launching and management
• Gaming app support (Steam, Epic, etc.)
• App information and process control

💬 COMPOUND COMMANDS:
• "Take screenshot then open calculator and type 2+2"
• "Create file about robotics then rename it to robots.txt"
• "Schedule reminder to check email in 10 minutes"

🧠 AI PROCESSING:
• Natural language understanding
• Autonomous task planning with LangChain
• Context-aware responses and actions

Say things like:
• "Take a screenshot then open notepad and type hello world"
• "Create a detailed file about artificial intelligence"
• "Monitor system performance for 3 minutes"
• "Schedule daily weather updates at 8 AM"
• "What's my system health status?"
"""
            if use_voice:
                self.voice_engine.speak("I've displayed my full capabilities. I can help with system control, file management, automation, scheduling, and much more!")
            console.print(Panel(help_text.strip(), title="JARVIS Capabilities", border_style="cyan"))
            return
        
        if "command examples" in command or "example commands" in command:
            examples = """
🎯 Example Commands:

BASIC OPERATIONS:
• "What's the weather?"
• "Take a screenshot"
• "System status"
• "Open calculator"

COMPOUND COMMANDS:
• "Take screenshot then open calculator and type 2+2"
• "Create file about space exploration then rename it to space.txt"
• "Launch notepad, wait 2 seconds, then type 'Hello JARVIS!'"
• "Get system health then take screenshot of the results"

FILE OPERATIONS:
• "Create a detailed file about machine learning"
• "Create folder called projects then create file inside it"
• "Read file config.py"

SCHEDULING:
• "Schedule reminder to call mom in 30 minutes"
• "Schedule daily system health check at 9 AM"
• "List all scheduled tasks"

AUTOMATION:
• "Click at 500,300 then type 'automated text'"
• "Focus window notepad then press ctrl+a"
• "Minimize all windows"

SYSTEM MONITORING:
• "Monitor performance for 5 minutes"
• "Show detailed hardware information"
• "Analyze network connections"
"""
            if use_voice:
                self.voice_engine.speak("I've shown you example commands. Try any of these to see what I can do!")
            console.print(Panel(examples.strip(), title="Command Examples", border_style="green"))
            return

        # AI Model Management Commands
        if self.use_multi_model and ("list models" in command or "available models" in command):
            models_info = self.multi_brain.list_available_models()
            if use_voice:
                self.voice_engine.speak("AI models list displayed.")
            console.print(Panel(models_info, title="Available AI Models", border_style="blue"))
            return
        
        if self.use_multi_model and command.startswith("switch model "):
            model_name = command.replace("switch model ", "").strip()
            result = self.multi_brain.switch_model(model_name)
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        if self.use_multi_model and ("current model" in command or "which model" in command):
            model_info = self.multi_brain.get_model_info()
            if "error" not in model_info:
                info_text = f"""Current AI Model: {model_info['name']}
Provider: {model_info['provider']}
Description: {model_info['description']}
Context Window: {model_info['context_window']:,} tokens
Vision Support: {'Yes' if model_info['supports_vision'] else 'No'}
Cost: ${model_info['cost_per_1k_tokens']}/1K tokens
Conversation Length: {model_info['conversation_length']} messages"""
                
                if use_voice:
                    self.voice_engine.speak(f"Currently using {model_info['name']}")
                console.print(Panel(info_text, title="Current AI Model", border_style="cyan"))
            else:
                response = "No model information available"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if self.use_multi_model and ("benchmark models" in command or "test models" in command):
            if use_voice:
                self.voice_engine.speak("Running model benchmark. This may take a moment.")
            
            test_prompt = "Explain artificial intelligence in 50 words"
            if "with" in command:
                custom_prompt = command.split("with", 1)[1].strip()
                if custom_prompt:
                    test_prompt = custom_prompt
            
            benchmark_results = self.multi_brain.benchmark_models(test_prompt)
            console.print(Panel(benchmark_results, title="Model Benchmark Results", border_style="yellow"))
            
            if use_voice:
                self.voice_engine.speak("Model benchmark completed")
            return
        
        if self.use_multi_model and ("model stats" in command or "usage stats" in command):
            stats = self.multi_brain.get_usage_stats()
            if use_voice:
                self.voice_engine.speak("Model usage statistics displayed")
            console.print(Panel(stats, title="AI Model Usage Statistics", border_style="green"))
            return
        
        if "smart model" in command or "auto model" in command:
            if self.use_multi_model:
                # Analyze command to suggest best model
                suggested_model = self._suggest_model_for_command(command)
                if suggested_model and suggested_model != self.multi_brain.current_model:
                    switch_result = self.multi_brain.switch_model(suggested_model)
                    response = f"Switched to {suggested_model} for better performance. {switch_result}"
                else:
                    response = f"Current model {self.multi_brain.current_model} is optimal for this task."
                
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            else:
                response = "Smart model selection requires multi-model brain"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return

        # Simple greetings and basic interactions
        if command in ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]:
            responses = [
                "Hello! How can I assist you today?",
                "Hi there! What would you like me to do?",
                "Good to see you! I'm ready for your commands.",
                "Hello! All systems are operational and ready to help.",
                "Hi! What can I help you with?"
            ]
            import random
            response = random.choice(responses)
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            return

        # Simple calculation commands - only explicit math keywords
        calculation_triggers = ["calculate", "compute", "math", "solve"]
        
        if any(trigger in command.lower() for trigger in calculation_triggers):
            # Extract mathematical expression
            expression = command
            for phrase in calculation_triggers:
                expression = expression.replace(phrase, "").strip()
            
            if expression:
                result = self.utility_skill.calculate(expression)
                if use_voice:
                    self.voice_engine.speak(result)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {result}")
                return
            # Extract mathematical expression
            expression = command
            for phrase in ["what is", "calculate", "compute", "math", "solve", "tell me"]:
                expression = expression.replace(phrase, "").strip()
            
            if expression:
                result = self.utility_skill.calculate(expression)
                if use_voice:
                    self.voice_engine.speak(result)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {result}")
                return

        # Clear conversation history
        if "clear history" in command or "reset conversation" in command:
            if self.use_multi_model:
                result = self.multi_brain.clear_history()
            elif self.use_advanced_brain:
                result = self.openrouter_brain.clear_history()
            else:
                result = self.brain.clear_history()
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        # Screenshot commands
        if "take screenshot" in command or "screenshot" in command:
            if self.automation_skill:
                result = self.system_control.take_screenshot()
                if use_voice:
                    self.voice_engine.speak("Screenshot captured.")
                else:
                    console.print(f"[blue]JARVIS:[/blue] {result}")
            else:
                response = "Screenshot functionality not available."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        # Mouse and automation commands
        if command.startswith("click at ") and self.automation_skill:
            try:
                coords = command.replace("click at ", "").strip()
                x, y = map(int, coords.split(","))
                result = self.automation_skill.click_at(x, y)
                if use_voice:
                    self.voice_engine.speak("Clicked at coordinates.")
                else:
                    console.print(f"[blue]JARVIS:[/blue] {result}")
            except:
                response = "Invalid coordinates. Use format: click at x,y"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if command.startswith("type ") and self.automation_skill:
            text = command.replace("type ", "").strip()
            result = self.automation_skill.type_text(text)
            if use_voice:
                self.voice_engine.speak("Text typed.")
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        if command.startswith("press ") and self.automation_skill:
            key = command.replace("press ", "").strip()
            result = self.automation_skill.press_key(key)
            if use_voice:
                self.voice_engine.speak(f"Pressed {key} key.")
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        # Window management
        if command.startswith("focus window ") and self.automation_skill:
            window_title = command.replace("focus window ", "").strip()
            result = self.automation_skill.focus_window(window_title)
            if use_voice:
                self.voice_engine.speak(f"Focused on {window_title} window.")
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        if command.startswith("close window ") and self.automation_skill:
            window_title = command.replace("close window ", "").strip()
            result = self.automation_skill.close_window(window_title)
            if use_voice:
                self.voice_engine.speak(f"Closed {window_title} window.")
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        if "list windows" in command and self.automation_skill:
            result = self.automation_skill.get_window_list()
            if use_voice:
                self.voice_engine.speak("Window list displayed.")
            console.print(Panel(result, title="Open Windows", border_style="cyan"))
            return
        
        # Enhanced application commands
        if command.startswith("launch ") or command.startswith("open "):
            app_name = command.replace("launch ", "").replace("open ", "")
            
            # First try the app control skill for better app management
            if self.app_control:
                result = self.app_control.launch_app_by_name(app_name)
            else:
                # Fallback to system control
                result = self.system_control.launch_application(app_name)
            
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        if command.startswith("close app ") and self.app_control:
            app_name = command.replace("close app ", "").strip()
            result = self.app_control.close_app_by_name(app_name)
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        if "list apps" in command and self.app_control:
            filter_text = command.replace("list apps", "").strip()
            result = self.app_control.list_installed_apps(filter_text)
            if use_voice:
                self.voice_engine.speak("Application list displayed.")
            console.print(Panel(result, title="Installed Applications", border_style="green"))
            return
        
        # Enhanced system commands
        if "set volume" in command:
            try:
                volume = int(''.join(filter(str.isdigit, command)))
                result = self.system_control.set_volume(volume)
                if use_voice:
                    self.voice_engine.speak(f"Volume set to {volume} percent.")
                else:
                    console.print(f"[blue]JARVIS:[/blue] {result}")
            except:
                response = "Please specify a volume level between 0 and 100."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if "battery" in command or "battery status" in command:
            result = self.system_control.get_battery_info()
            if use_voice:
                self.voice_engine.speak("Battery information retrieved.")
            console.print(Panel(result, title="Battery Status", border_style="yellow"))
            return
        
        if "network info" in command or "network status" in command:
            result = self.system_control.get_network_info()
            if use_voice:
                self.voice_engine.speak("Network information retrieved.")
            console.print(Panel(result, title="Network Status", border_style="blue"))
            return
        
        # RAM/Memory usage commands
        if "ram usage" in command or "memory usage" in command or "whats the ram" in command:
            status = self.system_control.get_system_status()
            if use_voice:
                self.voice_engine.speak("Memory usage information retrieved.")
            console.print(Panel(status, title="System Status (RAM Usage)", border_style="green"))
            return
        
        # CPU usage commands
        if "cpu usage" in command or "processor usage" in command:
            status = self.system_control.get_system_status()
            if use_voice:
                self.voice_engine.speak("CPU usage information retrieved.")
            console.print(Panel(status, title="System Status (CPU Usage)", border_style="red"))
            return
        
        # Quick system overview
        if "system overview" in command or "quick status" in command:
            status = self.system_control.get_system_status()
            processes = self.system_control.get_running_processes(5)  # Top 5 processes
            
            combined_info = f"{status}\n\n{processes}"
            
            if use_voice:
                self.voice_engine.speak("System overview retrieved.")
            console.print(Panel(combined_info, title="Quick System Overview", border_style="cyan"))
            return
        
        # Enhanced system monitoring commands
        if "detailed system info" in command or "hardware info" in command:
            if self.system_monitor:
                if "hardware" in command:
                    info = self.system_monitor.get_hardware_info()
                else:
                    info = self.system_monitor.get_detailed_system_info()
                if use_voice:
                    self.voice_engine.speak("Detailed system information retrieved.")
                console.print(Panel(info, title="Detailed System Information", border_style="blue"))
            else:
                response = "Advanced system monitoring not available."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if "system health" in command or "health check" in command:
            if self.system_monitor:
                health = self.system_monitor.check_system_health()
                if use_voice:
                    self.voice_engine.speak("System health check completed.")
                console.print(Panel(health, title="System Health Check", border_style="green"))
            else:
                response = "System health monitoring not available."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if "monitor performance" in command or "system performance" in command:
            if self.system_monitor:
                # Extract duration if specified
                duration = 5  # default
                if "for" in command:
                    try:
                        parts = command.split("for")[1].strip()
                        duration = int(''.join(filter(str.isdigit, parts)))
                    except:
                        pass
                
                if use_voice:
                    self.voice_engine.speak(f"Monitoring system performance for {duration} minutes")
                else:
                    console.print(f"[blue]JARVIS:[/blue] Monitoring system performance for {duration} minutes")
                
                performance = self.system_monitor.monitor_performance(duration)
                console.print(Panel(performance, title="Performance Monitoring", border_style="yellow"))
                
                if use_voice:
                    self.voice_engine.speak("Performance monitoring completed")
            else:
                response = "Performance monitoring not available."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if "network analysis" in command or "network info" in command:
            if self.system_monitor:
                network_info = self.system_monitor.get_network_analysis()
                if use_voice:
                    self.voice_engine.speak("Network analysis completed.")
                console.print(Panel(network_info, title="Network Analysis", border_style="cyan"))
            else:
                # Fallback to basic network info
                result = self.system_control.get_network_info()
                if use_voice:
                    self.voice_engine.speak("Network information retrieved.")
                console.print(Panel(result, title="Network Status", border_style="blue"))
            return
        
        # Task scheduling commands
        if ("schedule" in command or "remind" in command) and self.task_scheduler:
            result = self.task_scheduler.process_schedule_command(command)
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        if "list tasks" in command or "show tasks" in command or "scheduled tasks" in command:
            if self.task_scheduler:
                tasks = self.task_scheduler.list_scheduled_tasks()
                if use_voice:
                    self.voice_engine.speak("Scheduled tasks displayed.")
                console.print(Panel(tasks, title="Scheduled Tasks", border_style="purple"))
            else:
                response = "Task scheduler not available."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if command.startswith("run command "):
            cmd = command.replace("run command ", "").strip()
            result = self.system_control.run_command(cmd)
            if use_voice:
                self.voice_engine.speak("Command executed.")
            console.print(Panel(result, title="Command Output", border_style="red"))
            return
        
        # File management commands
        if (command.startswith("create file") or command.startswith("make file") or 
            "create a file" in command or "create a text" in command or 
            ("create" in command and ("store" in command or "save" in command))):
            
            # Handle content creation requests
            if "create a text about" in command or "create text about" in command:
                # Extract topic and filename
                parts = command.replace("create a text about", "").replace("create text about", "")
                if "store it in" in parts or "save it" in parts:
                    topic_and_location = parts.replace("store it in", "|").replace("save it", "|").replace("and", "")
                    topic_parts = topic_and_location.split("|")
                    topic = topic_parts[0].strip()
                    location = topic_parts[1].strip() if len(topic_parts) > 1 else ""
                    
                    # Generate filename from topic
                    filename = topic.replace(" ", "_").replace("for", "").replace("in", "").replace("2025", "2025").strip("_")
                    if location and "desktop" not in location.lower():
                        filename = location.strip()
                    elif not filename:
                        filename = "generated_text"
                    
                    # Add extension if not present
                    if not filename.endswith('.txt'):
                        filename += '.txt'
                    
                    # Generate content using AI
                    content_request = f"Write a detailed text about {topic}"
                    if self.use_advanced_brain:
                        content = self.openrouter_brain.process_command(content_request)
                    else:
                        content = f"# {topic.title()}\n\nThis is a placeholder text about {topic}. Please provide more specific requirements for detailed content."
                    
                    # Create file with generated content
                    result = self.file_skill.create_file(filename, content)
                    # Remember last created file for later operations
                    self.last_created_file = filename
                    if use_voice:
                        self.voice_engine.speak(f"I've created a text file about {topic} and saved it as {filename}")
                    else:
                        console.print(f"[blue]JARVIS:[/blue] I've created a text file about {topic} and saved it as {filename}")
                    console.print(f"[green]{result}[/green]")
                    return
                
            # Standard file creation
            filename = command.replace("create file", "").replace("make file", "").replace("create a file", "").replace("named", "").replace("in this folder", "").replace("here", "").strip()
            if not filename:
                filename = "untitled"
            result = self.file_skill.create_file(filename)
            # Remember last created file
            self.last_created_file = filename
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        if command.startswith("read file") or command.startswith("open file"):
            filename = command.replace("read file", "").replace("open file", "").strip()
            if filename:
                result = self.file_skill.read_file(filename)
                if use_voice:
                    self.voice_engine.speak("File contents displayed.")
                console.print(Panel(result, title="File Contents", border_style="cyan"))
            else:
                response = "Please specify a filename to read."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if command.startswith("delete file") or command.startswith("remove file"):
            filename = command.replace("delete file", "").replace("remove file", "").strip()
            if filename:
                result = self.file_skill.delete_file(filename)
                if use_voice:
                    self.voice_engine.speak(result)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {result}")
            else:
                response = "Please specify a filename to delete."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if "list files" in command or "show files" in command:
            result = self.file_skill.list_files()
            if use_voice:
                self.voice_engine.speak("File list displayed.")
            console.print(Panel(result, title="File List", border_style="green"))
            return
        
        if command.startswith("create folder") or command.startswith("make folder"):
            foldername = command.replace("create folder", "").replace("make folder", "").strip()
            if foldername:
                result = self.file_skill.create_folder(foldername)
                if use_voice:
                    self.voice_engine.speak(result)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {result}")
            else:
                response = "Please specify a folder name."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if "current directory" in command or "where am i" in command:
            result = self.file_skill.get_current_directory()
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return
        
        # Rename file or folder
        if "rename" in command and "to" in command:
            # Extract parts
            parts = command.split("to", 1)
            old_part = parts[0]
            new_name = parts[1].strip()
            # Determine old_name, handle pronouns referring to last created file
            if any(pronoun in old_part for pronoun in ["that file", "this file", "it"]) and self.last_created_file:
                old_name = self.last_created_file
            else:
                # Fallback extraction by removing 'rename' keywords
                old_name = old_part.replace("rename file", "").replace("rename", "").strip()
            if not old_name or not new_name:
                response = "Please provide both the current and new name."
            else:
                # Perform rename operation
                result = self.file_skill.rename_file(old_name, new_name)
                if result:
                    # Update last_created_file if renamed
                    if self.last_created_file == old_name:
                        self.last_created_file = new_name
                    response = f"Renamed '{old_name}' to '{new_name}'."
                else:
                    response = "Failed to rename the file or folder."
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        # Direct automation command: "take screenshot then open calculator and type 2+2"
        if ("take screenshot" in command and "calculator" in command and "2+2" in command) or \
           ("screenshot" in command and "open calculator" in command):
            if self.automation_skill:
                response = "Executing: taking screenshot, opening calculator, and typing 2+2"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                
                # Take screenshot
                screenshot_result = self.system_control.take_screenshot()
                console.print(f"[green]✅ {screenshot_result}[/green]")
                
                # Open calculator
                calc_result = self.system_control.launch_application("calculator")
                console.print(f"[green]✅ {calc_result}[/green]")
                
                # Wait for app to open
                time.sleep(2)
                
                # Type calculation
                type_result = self.automation_skill.type_text("2+2")
                console.print(f"[green]✅ {type_result}[/green]")
                
                # Press equals or enter
                enter_result = self.automation_skill.press_key("enter")
                console.print(f"[green]✅ {enter_result}[/green]")
                
                final_response = "Task completed: Screenshot taken, calculator opened, and 2+2 calculated!"
                if use_voice:
                    self.voice_engine.speak(final_response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {final_response}")
            else:
                response = "Automation not available on this system."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        # Complex automation sequences
        if "take a screenshot, then open calculator and type 2+2" in command or "take screenshot, then open calculator and type 2+2" in command:
            if self.automation_skill:
                response = "Executing sequence: screenshot, calculator, and typing 2+2"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                
                # Take screenshot
                screenshot_result = self.system_control.take_screenshot()
                console.print(f"[green]✅ {screenshot_result}[/green]")
                
                # Wait a moment
                time.sleep(1)
                
                # Open calculator
                calc_result = self.system_control.launch_application("calculator")
                console.print(f"[green]✅ {calc_result}[/green]")
                
                # Wait for calculator to open
                time.sleep(3)
                
                # Type calculation
                type_result = self.automation_skill.type_text("2+2")
                console.print(f"[green]✅ {type_result}[/green]")
                
                # Press equals
                time.sleep(0.5)
                equals_result = self.automation_skill.press_key("enter")
                console.print(f"[green]✅ {equals_result}[/green]")
                
                final_response = "Sequence completed: screenshot taken, calculator opened, and 2+2 calculated!"
                if use_voice:
                    self.voice_engine.speak(final_response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {final_response}")
            else:
                response = "Automation not available on this system."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if "demo automation" in command:
            if self.automation_skill:
                response = "Executing automation demo: taking screenshot, opening calculator, and typing 2+2"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                
                # Take screenshot
                self.system_control.take_screenshot()
                console.print("[green]✅ Screenshot taken[/green]")
                
                # Open calculator
                self.system_control.launch_application("calculator")
                console.print("[green]✅ Calculator launched[/green]")
                
                # Wait a moment for app to open
                time.sleep(2)
                
                # Type calculation
                self.automation_skill.type_text("2+2")
                console.print("[green]✅ Typed 2+2[/green]")
                
                # Press equals
                self.automation_skill.press_key("enter")
                console.print("[green]✅ Calculation executed[/green]")
                
                final_response = "Automation demo completed successfully!"
                if use_voice:
                    self.voice_engine.speak(final_response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {final_response}")
            else:
                response = "Automation not available on this system."
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        if "system report" in command or "full system report" in command:
            response = "Generating comprehensive system report..."
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            
            # Collect all system information
            status = self.system_control.get_system_status()
            processes = self.system_control.get_running_processes()
            disk_info = self.system_control.get_disk_usage()
            network_info = self.system_control.get_network_info()
            battery_info = self.system_control.get_battery_info()
            
            # Create comprehensive report
            report = f"""JARVIS SYSTEM REPORT
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
+
{status}
+
{processes}
+
{disk_info}
+
{network_info}
+
{battery_info}
"""
            
            # Save report to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"system_report_{timestamp}.txt"
            self.file_skill.create_file(filename, report)
            
            # Display summary
            console.print(Panel(report, title="System Report", border_style="green"))
            
            final_response = f"System report saved as {filename}"
            if use_voice:
                self.voice_engine.speak(final_response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {final_response}")
            return
        
        # Enhanced compound command processing
        if self.command_processor and any(keyword in command for keyword in ["then", "and then", "after", ";"]):
            try:
                # Parse the complex command
                steps = self.command_processor.parse_complex_command(command)
                
                if len(steps) > 1:
                    response = f"Executing compound command with {len(steps)} steps..."
                    if use_voice:
                        self.voice_engine.speak(response)
                    else:
                        console.print(f"[blue]JARVIS:[/blue] {response}")
                    
                    # Execute the parsed steps
                    results = self.command_processor.execute_parsed_commands(steps, use_voice)
                    
                    # Show execution summary
                    summary = "Command sequence completed:\n"
                    for i, result in enumerate(results, 1):
                        summary += f"{i}. {result}\n"
                    
                    console.print(Panel(summary.strip(), title="Compound Command Results", border_style="green"))
                    
                    if use_voice:
                        self.voice_engine.speak("All command steps completed successfully")
                    
                    return
                    
            except Exception as e:
                error_msg = f"Error processing compound command: {e}"
                console.print(f"[red]{error_msg}[/red]")
                if use_voice:
                    self.voice_engine.speak("Sorry, I had trouble processing that compound command")
                # Fall through to regular processing

         # Default: Use agent orchestrator if available, else AI brain fallback
        try:
            if self.agent_available and hasattr(self, 'agent'):
                response = self.agent.run(command)
            else:
                response = self._fallback_brain(command)
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
        except Exception as e:
            console.print(f"[yellow]Agent processing failed (likely rate limit): {e}[/yellow]")
            # Try direct fallback brain processing
            try:
                response = self._fallback_brain(command)
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
            except Exception as fallback_error:
                error_msg = "I'm sorry, I encountered an error processing that request. Please try a more specific command."
                console.print(f"[red]Processing error: {fallback_error}[/red]")
                if use_voice:
                    self.voice_engine.speak(error_msg)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {error_msg}")
    
    def _fallback_brain(self, command):
        """Fallback to brain logic based on available systems"""
        if self.use_multi_model:
            return self.multi_brain.process_command(command)
        elif self.use_advanced_brain:
            return self.openrouter_brain.process_command(command)
        else:
            return self.brain.process_command(command)
    
    def _suggest_model_for_command(self, command: str) -> str:
        """Suggest the best model for a given command"""
        command_lower = command.lower()
        
        # Check for specific task types
        if any(keyword in command_lower for keyword in ["code", "programming", "debug", "script", "function"]):
            return "deepseek-coder"
        elif any(keyword in command_lower for keyword in ["analyze", "reasoning", "logic", "complex"]):
            return "deepseek-v3"
        elif any(keyword in command_lower for keyword in ["creative", "story", "poem", "artistic"]):
            return "gpt-4o" if "gpt-4o" in self.multi_brain.available_models else "claude-3.5-sonnet"
        elif any(keyword in command_lower for keyword in ["image", "picture", "visual", "screenshot"]):
            vision_models = ["gemini-pro-vision", "gpt-4o", "claude-3.5-sonnet"]
            for model in vision_models:
                if model in self.multi_brain.available_models:
                    return model
        elif any(keyword in command_lower for keyword in ["fast", "quick", "simple"]):
            return "gemini-flash" if "gemini-flash" in self.multi_brain.available_models else "qwen-2.5-vl"
        
        # Default to current model
        return self.multi_brain.current_model
    
    def run_text_mode(self):
        """Run JARVIS in text-only mode"""
        console.print("[cyan]JARVIS Text Mode - Type your commands[/cyan]")
        console.print("[dim]Type 'exit', 'quit', or 'goodbye' to exit[/dim]")
        console.print("[dim]Type 'voice on' to enable voice responses[/dim]")
        console.print("[dim]Voice commands: 'list voices', 'change voice [number/name]', 'test voice'[/dim]")
        
        use_voice = False
        
        while self.is_running:
            try:
                command = input("\n[You]: ").strip()
                
                if not command:
                    continue
                
                # Toggle voice mode
                if command.lower() in ['voice on', 'enable voice']:
                    use_voice = True
                    console.print("[blue]JARVIS:[/blue] Voice responses enabled.")
                    continue
                elif command.lower() in ['voice off', 'disable voice']:
                    use_voice = False
                    console.print("[blue]JARVIS:[/blue] Voice responses disabled.")
                    continue
                
                # Voice control commands
                elif command.lower() in ['list voices', 'show voices', 'available voices']:
                    self.voice_engine.list_available_voices()
                    continue
                elif command.lower().startswith('change voice'):
                    # Extract voice number or name
                    parts = command.split()
                    if len(parts) > 2:
                        try:
                            voice_id = int(parts[2])
                            self.voice_engine.change_voice(voice_id)
                        except ValueError:
                            voice_name = ' '.join(parts[2:])
                            self.voice_engine.change_voice(voice_name)
                    else:
                        console.print("[blue]JARVIS:[/blue] Please specify a voice number or name. Use 'list voices' to see options.")
                    continue
                elif command.lower() in ['test voice', 'voice test']:
                    self.voice_engine.test_current_voice()
                    continue
                
                if command.lower() in ['exit', 'quit', 'goodbye']:
                    console.print("[blue]JARVIS:[/blue] Goodbye!")
                    break
                
                # Process command
                self.process_command(command, use_voice=use_voice)
                
            except KeyboardInterrupt:
                console.print("\n[yellow]Text mode interrupted by user[/yellow]")
                break
            except Exception as e:
                console.print(f"[red]Text mode error: {e}[/red]")
    
    def start(self, mode="text"):
        """Start JARVIS in specified mode"""
        self.is_running = True
        
        # Welcome message
        welcome_msg = self.brain.get_personality_response("startup")
        
        if mode == "voice":
            # Check if voice recognition is available
            if self.voice_engine.sr_available:
                console.print("[green]🎤 Starting JARVIS in full voice mode...[/green]")
                self.run_voice_mode()
            else:
                # Fallback to text mode with voice responses
                console.print("[yellow]⚠️ Voice recognition not available. Using text input with voice responses.[/yellow]")
                self.voice_engine.speak(welcome_msg)
                self.run_text_mode_with_voice()
        elif mode == "text":
            console.print(f"[blue]JARVIS:[/blue] {welcome_msg}")
            self.run_text_mode()
        else:
            console.print("[red]Invalid mode. Use 'voice' or 'text'[/red]")
    
    def run_text_mode_with_voice(self):
        """Run text mode but with voice responses enabled by default"""
        console.print("[cyan]JARVIS Voice Mode - Type your commands, JARVIS will speak responses[/cyan]")
        console.print("[dim]Type 'exit', 'quit', or 'goodbye' to exit[/dim]")
        console.print("[dim]Type 'voice off' to disable voice responses[/dim]")
        
        use_voice = True
        
        while self.is_running:
            try:
                command = input("\n[You]: ").strip()
                
                if not command:
                    continue
                
                # Toggle voice mode
                if command.lower() in ['voice off', 'disable voice']:
                    use_voice = False
                    console.print("[blue]JARVIS:[/blue] Voice responses disabled.")
                    continue
                elif command.lower() in ['voice on', 'enable voice']:
                    use_voice = True
                    self.voice_engine.speak("Voice responses enabled.")
                    continue
                
                if command.lower() in ['exit', 'quit', 'goodbye']:
                    if use_voice:
                        self.voice_engine.speak("Goodbye!")
                    else:
                        console.print("[blue]JARVIS:[/blue] Goodbye!")
                    break
                
                # Process command
                self.process_command(command, use_voice=use_voice)
                
            except KeyboardInterrupt:
                console.print("\n[yellow]Voice mode interrupted by user[/yellow]")
                break
            except Exception as e:
                console.print(f"[red]Voice mode error: {e}[/red]")
    
    def run_voice_mode(self):
        """Run JARVIS in full voice mode with wake word detection"""
        if not self.voice_engine.sr_available:
            console.print("[red]❌ Voice recognition not available. Falling back to text mode with voice responses.[/red]")
            self.run_text_mode_with_voice()
            return
            
        console.print("[cyan]🎤 JARVIS Voice Mode - Say 'JARVIS' to wake me up[/cyan]")
        console.print("[dim]Press Ctrl+C to exit voice mode[/dim]")
        
        # Greet user in voice mode
        greeting = self.get_time_greeting()
        welcome_msg = random.choice(self.brain.responses["greeting"])
        
        console.print(f"[blue]JARVIS:[/blue] {welcome_msg}")
        self.voice_engine.speak(welcome_msg)
        
        console.print("[yellow]🔄 Listening for wake word...[/yellow]")
        
        while self.is_running:
            try:
                # Listen for wake word
                if self.voice_engine.listen_for_wake_word():
                    # Wake word detected, get command
                    self.voice_engine.speak("Yes?")
                    
                    command = self.voice_engine.listen_for_command(timeout=10, phrase_timeout=3)
                    
                    if command:
                        # Check for exit commands
                        if any(word in command for word in ["goodbye", "exit", "quit", "shutdown"]):
                            self.voice_engine.speak("Goodbye!")
                            break
                        
                        # Process the command with voice response
                        self.process_command(command, use_voice=True)
                    else:
                        self.voice_engine.speak("I didn't catch that. Please try again.")
                    
                    console.print("[yellow]🔄 Listening for wake word...[/yellow]")
                
            except KeyboardInterrupt:
                console.print("\n[yellow]Voice mode interrupted by user[/yellow]")
                break
            except Exception as e:
                console.print(f"[red]Voice mode error: {e}[/red]")
                time.sleep(1)  # Brief pause before retrying
    
    def get_time_greeting(self):
        """Get appropriate greeting based on time of day"""
        hour = datetime.now().hour
        
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "evening"
    
    def shutdown(self):
        """Gracefully shutdown JARVIS"""
        console.print("[yellow]Initiating JARVIS shutdown sequence...[/yellow]")
        
        self.is_running = False
        
        console.print("[green]JARVIS systems offline. Goodbye![/green]")
        sys.exit(0)

def main():
    """Main entry point"""
    try:
        # Create JARVIS instance
        jarvis = JARVIS()
        
        # Check command line arguments
        if len(sys.argv) > 1:
            mode = sys.argv[1].lower()
            if mode in ["text", "voice"]:
                jarvis.start(mode)
            else:
                console.print("[red]Usage: python jarvis.py [voice|text][/red]")
                console.print("[yellow]Defaulting to text mode...[/yellow]")
                jarvis.start("text")
        else:
            # Default to text mode
            jarvis.start("text")
            
    except KeyboardInterrupt:
        console.print("\n[yellow]JARVIS startup interrupted[/yellow]")
    except Exception as e:
        console.print(f"[red]Failed to start JARVIS: {e}[/red]")
        console.print("[yellow]Please check that all dependencies are installed[/yellow]")

if __name__ == "__main__":
    main()
