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
from skills.screen_automation import ScreenAutomationSkill

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
            from skills.ai_app_selector import AIAppSelector
            # Pass the brain to the app selector for AI decision making
            brain_ref = self.multi_brain if self.use_multi_model else (self.openrouter_brain if self.use_advanced_brain else self.brain)
            self.ai_app_selector = AIAppSelector(brain=brain_ref)
            console.print("[green]✅ AI-powered app selector initialized[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️ AI app selector failed: {e}[/yellow]")
            self.ai_app_selector = None
        
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
            
        # Initialize screen automation skill
        try:
            self.screen_automation = ScreenAutomationSkill(self)
            console.print("[green]✅ AI Screen automation initialized[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠️ Screen automation failed: {e}[/yellow]")
            self.screen_automation = None
            
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
        
        # Create skills dictionary for GUI compatibility
        self.skills = {
            'weather': self.weather_skill,
            'web_search': self.web_skill,
            'utility': self.utility_skill,
            'file_manager': self.file_skill,
            'system_monitor': self.system_monitor,
        }
        
        # Add optional skills if available
        if hasattr(self, 'automation_skill') and self.automation_skill:
            self.skills['automation'] = self.automation_skill
        if hasattr(self, 'app_control') and self.app_control:
            self.skills['app_control'] = self.app_control
        if hasattr(self, 'command_processor') and self.command_processor:
            self.skills['command_processor'] = self.command_processor
        if hasattr(self, 'task_scheduler') and self.task_scheduler:
            self.skills['task_scheduler'] = self.task_scheduler
        if hasattr(self, 'screen_automation') and self.screen_automation:
            self.skills['screen_automation'] = self.screen_automation
        if hasattr(self, 'ai_app_selector') and self.ai_app_selector:
            self.skills['ai_app_selector'] = self.ai_app_selector
        
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
    
    def _classify_command_intent(self, command):
        """Use AI to classify the intent of a command"""
        try:
            # Use pure LLM classification without any keyword detection
            classification_prompt = f"""
You are JARVIS AI assistant. Classify the user's command into one of these categories:

AUTOMATION - For opening apps, controlling computer actions, multi-step tasks, visual tasks, screen interactions
APP - For launching specific applications by name
WEATHER - For weather information requests
SEARCH - For web searches and information lookup
MATH - For mathematical calculations
TIME - For current time/date queries
SYSTEM - For system information (CPU, memory, disk usage)
FILE - For file and folder operations
UTILITY - For jokes, random numbers, coin flips, etc.
GENERAL - For general conversation and questions

User command: "{command}"

Respond with ONLY the category name (e.g., "AUTOMATION", "WEATHER", etc.). No explanation needed.
"""
            
            # Get classification from AI brain
            if hasattr(self, 'multi_brain') and self.multi_brain:
                classification = self.multi_brain.process_command(classification_prompt, use_context=False)
            elif hasattr(self, 'openrouter_brain') and self.openrouter_brain and self.openrouter_brain.available:
                classification = self.openrouter_brain.process_command(classification_prompt, use_context=False)
            else:
                classification = self.brain.process_command(classification_prompt, use_context=False)
            
            # Extract the category from the response
            classification = classification.strip().upper()
            
            # Validate the classification
            valid_categories = ['AUTOMATION', 'APP', 'WEATHER', 'SEARCH', 'MATH', 'TIME', 'SYSTEM', 'FILE', 'UTILITY', 'GENERAL']
            
            for category in valid_categories:
                if category in classification:
                    return category
            
            # Default fallback
            return 'GENERAL'
            
        except Exception as e:
            console.print(f"[yellow]Classification error: {e}[/yellow]")
            # Fallback to automation for app-related commands
            command_lower = command.lower()
            if any(word in command_lower for word in ['open', 'launch', 'start']):
                return 'AUTOMATION'
            return 'GENERAL'

    def _handle_classified_command(self, command, intent, use_voice=True):
        """Handle commands based on AI-classified intent and return the response"""
        
        if intent == 'EXIT':
            response = "Goodbye. JARVIS systems shutting down."
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            self.shutdown()
            return response
            
        elif intent == 'GENERAL':
            return self._handle_conversational_response(command, use_voice)
            
        elif intent == 'TIME':
            return self._handle_time_commands(command, use_voice)
            
        elif intent == 'MATH':
            return self._handle_math_commands(command, use_voice)
            
        elif intent == 'SYSTEM':
            return self._handle_system_commands(command, use_voice)
            
        elif intent == 'WEATHER':
            result = self.weather_skill.get_weather()
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return result
            
        elif intent == 'SEARCH':
            return self._handle_search_commands(command, use_voice)
            
        elif intent == 'APP':
            return self._handle_app_commands(command, use_voice)
            
        elif intent == 'UTILITY':
            return self._handle_utility_commands(command, use_voice)
            
        elif intent == 'FILE':
            return self._handle_file_commands(command, use_voice)
            
        elif intent == 'AUTOMATION':
            return self._handle_automation_commands(command, use_voice)
            
        elif intent == 'SCREEN_AUTOMATION':
            return self._handle_screen_automation_commands(command, use_voice)
            
        return None  # Not handled, use agent orchestrator

    def process_command(self, command, use_voice=True):
        """Process and execute commands with intelligent intent classification"""
        if not command:
            return
        
        original_command = command
        command = command.lower().strip()
        self.last_activity = time.time()
        
        console.print(f"[green]Processing command:[/green] {command}")
        
        # Handle essential immediate commands first (no AI needed)
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
            response = "I'm awake and ready to assist, sir."
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            return
        
        # Skip processing if sleeping
        if self.is_sleeping:
            return
        
        # Use AI to classify and route the command intelligently
        intent = self._classify_command_intent(command)
        console.print(f"[dim]Classified intent: {intent}[/dim]")
        
        # Handle the command based on its classified intent
        response = self._handle_classified_command(original_command, intent, use_voice)
        
        if response:
            # Command was handled and got a response
            return response
        else:
            # Fallback to agent orchestrator for complex queries
            try:
                if self.agent_available and hasattr(self, 'agent'):
                    response = self.agent.run(original_command)
                else:
                    response = self._fallback_brain(original_command)
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                return response
            except Exception as e:
                console.print(f"[yellow]Agent processing failed: {e}[/yellow]")
                # Try direct fallback brain processing
                try:
                    response = self._fallback_brain(original_command)
                    if use_voice:
                        self.voice_engine.speak(response)
                    else:
                        console.print(f"[blue]JARVIS:[/blue] {response}")
                    return response
                except Exception as fallback_error:
                    error_msg = "I'm sorry, I encountered an error processing that request. Please try a more specific command."
                    console.print(f"[red]Processing error: {fallback_error}[/red]")
                    if use_voice:
                        self.voice_engine.speak(error_msg)
                    else:
                        console.print(f"[blue]JARVIS:[/blue] {error_msg}")

    def _handle_conversational_response(self, command, use_voice=True):
        """Handle conversational greetings and responses using AI"""
        try:
            # For simple greetings, use quick responses
            command_lower = command.lower().strip()
            simple_greetings = ["hi", "hello", "hey"]
            
            if command_lower in simple_greetings:
                # Get current time for context
                current_hour = datetime.now().hour
                if current_hour < 12:
                    time_greeting = "Good morning"
                elif current_hour < 17:
                    time_greeting = "Good afternoon"
                else:
                    time_greeting = "Good evening"
                
                responses = [
                    f"{time_greeting}, sir. How may I assist you today?",
                    f"{time_greeting}. What can I do for you?",
                    f"Hello, sir. Ready to help as always.",
                    f"{time_greeting}. At your service."
                ]
                response = random.choice(responses)
            else:
                # For complex conversational questions, use AI
                conversation_prompt = f"""You are JARVIS, Tony Stark's AI assistant. Respond to this conversational query in a helpful, intelligent manner. Keep responses concise and in character as JARVIS.

User: {command}

JARVIS:"""
                
                # Get response from AI brain
                if hasattr(self, 'multi_brain') and self.multi_brain:
                    response = self.multi_brain.process_command(conversation_prompt, use_context=False)
                elif hasattr(self, 'openrouter_brain') and self.openrouter_brain and self.openrouter_brain.available:
                    response = self.openrouter_brain.process_command(conversation_prompt, use_context=False)
                else:
                    response = self.brain.process_command(conversation_prompt, use_context=False)
                
                # Clean up the response
                response = response.strip()
                if response.startswith("JARVIS:"):
                    response = response[7:].strip()
            
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            return response
            
        except Exception as e:
            console.print(f"[yellow]Conversation error: {e}[/yellow]")
            # Fallback response
            response = "I'm here to assist you, sir. How may I help?"
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            return response

    def _handle_time_commands(self, command, use_voice=True):
        """Handle time and date related commands"""
        command_lower = command.lower()
        
        if any(phrase in command_lower for phrase in ["what time", "current time", "time now", "whats the time", "time is"]):
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
                
                response = f"It's {current_time} {timezone_name}, sir."
            except ImportError:
                # Fallback if pytz not available
                current_time = datetime.now().strftime("%I:%M %p")
                response = f"It's {current_time}, sir."
                
        elif any(phrase in command_lower for phrase in ["what date", "today's date", "whats the date", "date today", "what day"]):
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
                response = f"Today is {current_date}, sir."
            except ImportError:
                current_date = datetime.now().strftime("%A, %B %d, %Y")
                response = f"Today is {current_date}, sir."
        else:
            response = "I can tell you the current time or date. What would you like to know?"
        
        if use_voice:
            self.voice_engine.speak(response)
        else:
            console.print(f"[blue]JARVIS:[/blue] {response}")
        return response

    def _handle_math_commands(self, command, use_voice=True):
        """Handle mathematical calculations intelligently"""
        import re
        
        # Clean up the command for better math detection
        math_query = command.lower()
        
        # Remove common question words and phrases more carefully
        question_patterns = [
            r'\b(what\s+is|whats|what\'s|calculate|math|compute|solve|tell\s+me|can\s+you\s+tell\s+me|what\s+is\s+the\s+answer\s+for)\b',
            r'\b(the\s+answer\s+for|answer\s+for|result\s+of)\b'
        ]
        
        for pattern in question_patterns:
            math_query = re.sub(pattern, '', math_query).strip()
        
        # Replace word operators with symbols
        math_query = re.sub(r'\bplus\b', '+', math_query)
        math_query = re.sub(r'\bminus\b', '-', math_query)
        math_query = re.sub(r'\btimes\b', '*', math_query)
        math_query = re.sub(r'\bmultiplied\s+by\b', '*', math_query)
        math_query = re.sub(r'\bdivided\s+by\b', '/', math_query)
        math_query = re.sub(r'\bx\b', '*', math_query)  # Handle "10x10" as "10*10"
        math_query = re.sub(r'×', '*', math_query)
        math_query = re.sub(r'÷', '/', math_query)
        
        # Clean up extra spaces and punctuation
        math_query = re.sub(r'\s+', '', math_query)
        math_query = re.sub(r'[^\d+\-*/\.]', '', math_query)  # Keep only numbers and operators
        
        # Look for mathematical patterns - more flexible
        math_pattern = r'^[-+]?\d*\.?\d+[+\-*/][-+]?\d*\.?\d+$'
        
        if re.match(math_pattern, math_query):
            try:
                # Use eval for simple math expressions (safe since we've cleaned the input)
                result = eval(math_query)
                response = f"{command.strip()} = {result}"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                return response
            except Exception as e:
                console.print(f"[yellow]Math calculation error: {e}[/yellow]")
                # Fallback to utility skill
                try:
                    result = self.utility_skill.calculate(math_query)
                    if use_voice:
                        self.voice_engine.speak(result)
                    else:
                        console.print(f"[blue]JARVIS:[/blue] {result}")
                    return result
                except:
                    return None
        else:
            # If no clear math expression found, try utility skill directly
            try:
                result = self.utility_skill.calculate(command)
                if result and "Error" not in result:
                    if use_voice:
                        self.voice_engine.speak(result)
                    else:
                        console.print(f"[blue]JARVIS:[/blue] {result}")
                    return result
            except:
                pass
            
            # If still no result, let it go to general AI
            return None
            return False

    def _handle_system_commands(self, command, use_voice=True):
        """Handle system-related commands"""
        command_lower = command.lower()
        
        if any(phrase in command_lower for phrase in ["cpu usage", "processor usage", "whats the cpu", "cpu"]):
            try:
                if hasattr(self, 'system_monitor') and self.system_monitor:
                    # Use advanced system monitor if available
                    cpu_info = self.system_monitor.get_cpu_info()
                    response = f"CPU Usage: {cpu_info.get('usage', 'Unknown')}%, sir."
                else:
                    # Fallback to basic system control
                    status = self.system_control.get_cpu_usage()
                    if "CPU Usage:" in status:
                        percentage = status.split(": ", 1)[1]
                        response = f"Your CPU is currently at {percentage}, sir."
                    else:
                        response = status
                        
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                return response
            except Exception as e:
                response = f"Unable to get CPU usage: {e}"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                return response
            
        elif any(phrase in command_lower for phrase in ["ram usage", "memory usage", "whats the ram", "memory"]):
            try:
                if hasattr(self, 'system_monitor') and self.system_monitor:
                    # Use advanced system monitor if available
                    memory_info = self.system_monitor.get_memory_info()
                    used_gb = memory_info.get('used_gb', 0)
                    total_gb = memory_info.get('total_gb', 0)
                    percentage = memory_info.get('percentage', 0)
                    response = f"Memory usage: {used_gb:.1f} GB of {total_gb:.1f} GB ({percentage}%), sir."
                else:
                    # Fallback to basic system control
                    status = self.system_control.get_memory_usage()
                    if "Memory:" in status:
                        parts = status.split(": ", 1)[1]
                        response = f"Your system is using {parts}, sir."
                    else:
                        response = status
                        
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                return response
            except Exception as e:
                response = f"Unable to get memory usage: {e}"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                return response
            
        elif any(phrase in command_lower for phrase in ["system status", "system report", "system info", "system information"]):
            try:
                if hasattr(self, 'system_monitor') and self.system_monitor:
                    # Use advanced system monitor for comprehensive info
                    cpu_info = self.system_monitor.get_cpu_info()
                    memory_info = self.system_monitor.get_memory_info()
                    disk_info = self.system_monitor.get_disk_info()
                    
                    response = f"""System Status Report:
• CPU: {cpu_info.get('usage', 'N/A')}% usage, {cpu_info.get('cores', 'N/A')} cores
• Memory: {memory_info.get('used_gb', 0):.1f}/{memory_info.get('total_gb', 0):.1f} GB ({memory_info.get('percentage', 0)}%)
• Disk: {disk_info.get('used_gb', 0):.1f}/{disk_info.get('total_gb', 0):.1f} GB used"""
                else:
                    # Fallback to basic system control
                    status = self.system_control.get_system_status()
                    response = f"System status: {status}"
                
                if use_voice:
                    short_response = "Here's your system status, sir."
                    self.voice_engine.speak(short_response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] System Status Report")
                
                console.print(Panel(response, title="System Status", border_style="green"))
                return response
            except Exception as e:
                response = f"Unable to get system status: {e}"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                return response
            
        elif any(phrase in command_lower for phrase in ["running processes", "process list"]):
            try:
                processes = self.system_control.get_running_processes()
                response = "Top running processes displayed above, sir."
                if use_voice:
                    self.voice_engine.speak(response)
                console.print(Panel(processes, title="Running Processes", border_style="yellow"))
                return response
            except Exception as e:
                response = f"Unable to get process list: {e}"
                if use_voice:
                    self.voice_engine.speak(response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {response}")
                return response
            
        elif any(phrase in command_lower for phrase in ["disk usage", "storage"]):
            disk_info = self.system_control.get_disk_usage()
            response = "Here's your disk usage information, sir."
            if use_voice:
                self.voice_engine.speak(response)
            console.print(Panel(disk_info, title="Disk Usage", border_style="blue"))
            return True
            
        return False

    def _handle_search_commands(self, command, use_voice=True):
        """Handle search-related commands"""
        command_lower = command.lower()
        
        # Extract search query
        query = command_lower
        for prefix in ["search for ", "look up ", "google ", "find ", "search "]:
            if query.startswith(prefix):
                query = query[len(prefix):].strip()
                break
        
        if "wikipedia" in command_lower or "wiki" in command_lower:
            query = query.replace("wikipedia", "").replace("wiki", "").strip()
            result = self.web_skill.search_wikipedia(query)
        elif "news" in command_lower or "headlines" in command_lower:
            result = self.web_skill.get_news_headlines()
        else:
            # Use comprehensive search with LLM summarization
            result = self.web_skill.search_web(query, open_browser=False, llm_brain=self.brain)
        
        if use_voice:
            # For voice output, provide a shorter summary
            if len(result) > 500:
                summary_lines = result.split('\n')[:5]  # First few lines
                voice_result = '\n'.join(summary_lines) + "\n\nDetailed results available in the interface."
                self.voice_engine.speak(voice_result)
            else:
                self.voice_engine.speak(result)
        else:
            console.print(f"[blue]JARVIS:[/blue] {result}")
        return True

    def _handle_app_commands(self, command, use_voice=True):
        """Handle application launching commands"""
        import re
        command_lower = command.lower()
        
        # Look for app launch patterns in the command
        # Pattern 1: "open/launch/start/run + app_name"
        app_patterns = [
            r'\b(?:open|launch|start|run)\s+(\w+)',
            r'\bopen\s+(\w+)',
            r'\blaunch\s+(\w+)',
            r'\bstart\s+(\w+)',
            r'\brun\s+(\w+)'
        ]
        
        app_name = None
        for pattern in app_patterns:
            match = re.search(pattern, command_lower)
            if match:
                app_name = match.group(1)
                break
        
        # If no pattern matched, try simple extraction
        if not app_name:
            for prefix in ["open ", "launch ", "start ", "run "]:
                if prefix in command_lower:
                    parts = command_lower.split(prefix)
                    if len(parts) > 1:
                        # Take the first word after the prefix
                        app_name = parts[1].split()[0] if parts[1].split() else None
                        break
        
        if app_name:
            result = self.system_control.launch_application(app_name)
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return result
        else:
            # No clear app name found, let AI handle it
            return None

    def _handle_utility_commands(self, command, use_voice=True):
        """Handle utility/fun commands"""
        command_lower = command.lower()
        
        if any(phrase in command_lower for phrase in ["tell me a joke", "joke"]):
            joke = self.utility_skill.tell_joke()
            if use_voice:
                self.voice_engine.speak(joke)
            else:
                console.print(f"[blue]JARVIS:[/blue] {joke}")
            return True
            
        elif any(phrase in command_lower for phrase in ["flip a coin", "coin flip"]):
            result = self.utility_skill.flip_coin()
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return True
            
        elif any(phrase in command_lower for phrase in ["roll dice", "roll a die"]):
            result = self.utility_skill.roll_dice()
            if use_voice:
                self.voice_engine.speak(result)
            else:
                console.print(f"[blue]JARVIS:[/blue] {result}")
            return True
            
        return False

    def _handle_file_commands(self, command, use_voice=True):
        """Handle file operations using agent orchestrator"""
        # File operations are complex, let agent orchestrator handle them
        return False

    def _handle_automation_commands(self, command, use_voice=True):
        """Handle automation and scheduling commands"""
        
        # Check if this is a multi-step command (contains "then", "and", commas, etc.)
        command_lower = command.lower()
        is_multi_step = (
            any(word in command_lower for word in ['then', 'after', 'next', 'and then', 'followed by', 'subsequently']) or
            len(command.split(',')) > 1 or
            (len(command.split(' and ')) > 1 and any(action in command_lower for action in ['open', 'type', 'save', 'close', 'click']))
        )
        
        # Handle multi-step tasks using visual task orchestrator
        if is_multi_step or self._is_complex_task(command):
            try:
                from skills.visual_task_orchestrator import process_visual_task
                result = process_visual_task(command)
                
                if use_voice:
                    # Provide appropriate voice feedback
                    if "✅" in result:
                        self.voice_engine.speak("Task completed successfully")
                    else:
                        self.voice_engine.speak("Task encountered an issue")
                
                console.print(f"[blue]JARVIS:[/blue] {result}")
                return result
                
            except Exception as e:
                error_msg = f"Complex task error: {str(e)}"
                console.print(f"[red]Error:[/red] {error_msg}")
                if use_voice:
                    self.voice_engine.speak("Complex task encountered an error")
                return error_msg
        
        # Handle screen automation commands (including click commands)
        if any(keyword in command.lower() for keyword in ['automate', 'auto', 'screen', 'ai help with']) or any(phrase in command.lower() for phrase in ['click on', 'find and click', 'locate and click', 'press on', 'tap on']):
            try:
                if hasattr(self, 'screen_automation') and self.screen_automation:
                    # Check if this is a specific click command
                    if any(phrase in command.lower() for phrase in ['click on', 'find and click', 'locate and click', 'press on', 'tap on']):
                        from skills.screen_automation import ScreenAutomationSkill
                        automation = ScreenAutomationSkill()
                        
                        # Extract element name from click command
                        import re
                        click_patterns = [
                            r"(?:click|find\s+and\s+click|locate\s+and\s+click|press|tap)\s+(?:on\s+)?(?:the\s+)?(.*)",
                        ]
                        
                        element_name = None
                        for pattern in click_patterns:
                            match = re.search(pattern, command.lower())
                            if match:
                                element_name = match.group(1).strip()
                                break
                        
                        if element_name:
                            result = automation.find_and_click_element(element_name)
                            if result.get('success', False):
                                coords = result.get('coordinates', [])
                                confidence = result.get('confidence', 0)
                                response = f"✅ Successfully clicked '{element_name}' at coordinates {coords} (confidence: {confidence:.2f})"
                            else:
                                response = f"❌ Could not find '{element_name}' on screen. {result.get('message', '')}"
                            
                            if use_voice:
                                # Provide shorter voice feedback
                                if result.get('success', False):
                                    self.voice_engine.speak(f"Clicked {element_name}")
                                else:
                                    self.voice_engine.speak(f"Could not find {element_name}")
                            console.print(f"[blue]JARVIS:[/blue] {response}")
                            return response
                        else:
                            response = "❌ Could not identify what to click. Please specify the element name."
                            if use_voice:
                                self.voice_engine.speak("Could not identify what to click")
                            console.print(f"[blue]JARVIS:[/blue] {response}")
                            return response
                    else:
                        # Use general automation system
                        from skills.screen_automation import process_automation_command
                        result = process_automation_command(command, self)
                        if use_voice:
                            self.voice_engine.speak(result[:200])  # Limit speech length
                        console.print(f"[blue]JARVIS:[/blue] {result}")
                        return result
                else:
                    error_msg = "Screen automation is not available."
                    if use_voice:
                        self.voice_engine.speak(error_msg)
                    console.print(f"[yellow]JARVIS:[/yellow] {error_msg}")
                    return error_msg
            except Exception as e:
                error_msg = f"Screen automation error: {str(e)}"
                console.print(f"[red]Error:[/red] {error_msg}")
                if use_voice:
                    self.voice_engine.speak("Screen automation encountered an error")
                return error_msg
        
        # Legacy automation handling - let agent orchestrator handle complex automation
        # But first try simple app launching using AI app selector
        if any(word in command_lower for word in ['open', 'launch', 'start', 'run']):
            try:
                if hasattr(self, 'ai_app_selector') and self.ai_app_selector:
                    console.print(f"[cyan]🧠 Using AI to select best app for: {command}[/cyan]")
                    
                    # Use AI to find the best app
                    selected_app = self.ai_app_selector.find_best_app_for_task(command)
                    
                    if selected_app:
                        # Try to launch the app
                        success = self.ai_app_selector.launch_app(selected_app)
                        
                        if success:
                            result = f"Successfully launched {selected_app['name']}"
                            if use_voice:
                                self.voice_engine.speak(f"{selected_app['name']} has been launched")
                            console.print(f"[blue]JARVIS:[/blue] {result}")
                            return result
                        else:
                            result = f"Failed to launch {selected_app['name']}"
                            if use_voice:
                                self.voice_engine.speak(f"Could not launch {selected_app['name']}")
                            console.print(f"[blue]JARVIS:[/blue] {result}")
                            return result
                    else:
                        result = "Could not find a suitable application for this task"
                        if use_voice:
                            self.voice_engine.speak(result)
                        console.print(f"[blue]JARVIS:[/blue] {result}")
                        return result
                        
                elif hasattr(self, 'app_control') and self.app_control:
                    # Fallback to old app control
                    app_name = command_lower
                    for word in ['open', 'launch', 'start', 'run']:
                        app_name = app_name.replace(word, '').strip()
                    
                    # Clean up common words
                    app_name = app_name.replace('the', '').replace('application', '').replace('app', '').replace('program', '').strip()
                    
                    console.print(f"[cyan]Attempting to launch: {app_name}[/cyan]")
                    
                    # Try to launch the app
                    result = self.app_control.launch_app_by_name(app_name)
                    
                    if use_voice:
                        if "successfully" in result.lower():
                            self.voice_engine.speak(f"{app_name} has been launched")
                        else:
                            self.voice_engine.speak(f"Could not launch {app_name}")
                    
                    console.print(f"[blue]JARVIS:[/blue] {result}")
                    return result
                else:
                    error_msg = "Application control is not available."
                    if use_voice:
                        self.voice_engine.speak(error_msg)
                    console.print(f"[yellow]JARVIS:[/yellow] {error_msg}")
                    return error_msg
            except Exception as e:
                error_msg = f"Application launch error: {str(e)}"
                console.print(f"[red]Error:[/red] {error_msg}")
                if use_voice:
                    self.voice_engine.speak("Application launch encountered an error")
                return error_msg
        
        return None
    
    def _handle_screen_automation_commands(self, command, use_voice=True):
        """Handle screen automation commands using AI analysis - NO KEYWORDS"""
        try:
            if hasattr(self, 'screen_automation') and self.screen_automation:
                # Use AI to determine the specific screen automation action
                analysis_prompt = f"""
                You are analyzing a screen automation command to determine what specific action to take.
                
                Command: "{command}"
                
                Determine the action type and respond with exactly one of these categories:
                
                TAKE_SCREENSHOT: If user wants to capture, take, or screenshot the screen
                CLICK_ELEMENT: If user wants to click, press, tap, or interact with a specific UI element
                TYPE_TEXT: If user wants to type, enter, or input text somewhere
                FIND_ELEMENT: If user wants to locate, find, or identify something on screen
                SCROLL_ACTION: If user wants to scroll up, down, or navigate
                AUTOMATION_TASK: If this is a complex multi-step automation task
                GENERAL_AUTOMATION: For any other screen/UI automation request
                
                Respond with just the category name and a brief description.
                Format: CATEGORY: description
                """
                
                # Get AI decision
                ai_response = self._get_ai_response(analysis_prompt)
                action_type = ai_response.split(':')[0].strip() if ':' in ai_response else ai_response.strip()
                
                console.print(f"[yellow]AI Decision:[/yellow] {ai_response}")
                
                # Execute based on AI decision
                if action_type == "TAKE_SCREENSHOT":
                    result = self._handle_screenshot_command(command)
                    response = result
                elif action_type == "CLICK_ELEMENT":
                    result = self._handle_click_command(command)
                    response = result
                elif action_type == "AUTOMATION_TASK":
                    # Route to complex automation handler
                    return self._handle_automation_commands(command, use_voice)
                else:
                    # Use general screen automation processing
                    from skills.screen_automation import process_automation_command
                    result = process_automation_command(command, self)
                    response = result
                
                if use_voice:
                    self.voice_engine.speak(response[:200])  # Limit speech length
                console.print(f"[blue]JARVIS:[/blue] {response}")
                return True
            else:
                error_msg = "Screen automation is not available."
                if use_voice:
                    self.voice_engine.speak(error_msg)
                console.print(f"[yellow]JARVIS:[/yellow] {error_msg}")
                return True
                
        except Exception as e:
            error_msg = f"Screen automation error: {str(e)}"
            console.print(f"[red]Error:[/red] {error_msg}")
            if use_voice:
                self.voice_engine.speak("Screen automation encountered an error")
            return True

    def _handle_screenshot_command(self, command):
        """Handle screenshot commands using AI"""
        try:
            from skills.screen_automation import ScreenAutomationSkill
            automation = ScreenAutomationSkill()
            result = automation.take_screenshot()
            # take_screenshot returns a filepath string, not a dict
            return f"✅ Screenshot saved to: {result}"
        except Exception as e:
            return f"❌ Screenshot error: {str(e)}"
    
    def _handle_click_command(self, command):
        """Handle click commands using AI to extract element name"""
        try:
            # Use AI to extract what element to click
            extract_prompt = f"""
            Extract the specific UI element name that the user wants to click from this command:
            
            Command: "{command}"
            
            Examples:
            - "click on the save button" → save button
            - "find and click settings" → settings  
            - "press the close button" → close button
            - "tap on menu" → menu
            
            Respond with just the element name, nothing else.
            """
            
            element_name = self._get_ai_response(extract_prompt).strip()
            
            from skills.screen_automation import ScreenAutomationSkill
            automation = ScreenAutomationSkill()
            result = automation.find_and_click_element(element_name)
            
            if result.get('success', False):
                coords = result.get('coordinates', [])
                confidence = result.get('confidence', 0)
                return f"✅ Successfully clicked '{element_name}' at coordinates {coords} (confidence: {confidence:.2f})"
            else:
                return f"❌ Could not find '{element_name}' on screen. {result.get('message', '')}"
                
        except Exception as e:
            return f"❌ Click command error: {str(e)}"
    
    def _is_complex_task(self, command: str) -> bool:
        """Use AI to determine if command is a complex multi-step task - NO KEYWORDS"""
        try:
            analysis_prompt = f"""
            Analyze this command to determine if it's a complex multi-step task that requires automation orchestration.
            
            Command: "{command}"
            
            A complex task typically involves:
            - Multiple steps (open app, do action, save, etc.)
            - File operations with multiple stages
            - Application workflows (create document, type content, save)
            - Setting up system features (alarms, reminders, timers)
            - Email composition and sending
            - Website navigation with actions
            
            Simple tasks are single actions like:
            - Basic calculations
            - Simple questions  
            - Single screenshots
            - Time/date queries
            - Single clicks or searches
            
            Respond with exactly: YES or NO
            """
            
            ai_response = self._get_ai_response(analysis_prompt).strip().upper()
            return "YES" in ai_response
            
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Error in complexity analysis: {e}")
            # Default to simple for safety
            return False

    def _get_ai_response(self, prompt):
        """Get AI response using the configured model"""
        try:
            if self.use_multi_model and hasattr(self, 'multi_brain'):
                return self.multi_brain.process_command(prompt)
            elif getattr(self, 'use_advanced_brain', False) and hasattr(self, 'openrouter_brain'):
                return self.openrouter_brain.process_command(prompt)
            else:
                # Fallback to basic brain
                return self.brain.process_command(prompt)
        except Exception as e:
            console.print(f"[red]AI Response Error:[/red] {str(e)}")
            return "I'm sorry, I couldn't process that request."
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

AI SCREEN AUTOMATION:
• "Click on File"
• "Find and click Edit"
• "Click on the save button"
• "Press the OK button"
• "Tap on Help"

COMPLEX TASK AUTOMATION:
• "Set alarm for 7:30 AM"
• "Send email to john@example.com subject meeting reminder"
• "Set reminder to call mom in 2 hours"
• "Set timer for 10 minutes"
• "Create document about artificial intelligence"
• "Open website google.com"
• "Take screenshot"

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

        # Simple greetings and basic interactions with more natural responses
        if command in ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "wyd", "what's up", "whats up"]:
            import random
            import datetime
            hour = datetime.datetime.now().hour
            
            if command in ["wyd", "what's up", "whats up"]:
                responses = [
                    "Just monitoring system performance and standing by for your requests, sir.",
                    "Running diagnostics and waiting for your next command.",
                    "All systems nominal. Ready to assist with whatever you need.",
                    "Keeping everything running smoothly while I wait for you to give me something interesting to do.",
                    "Maintaining optimal performance and ready for action."
                ]
            elif 5 <= hour < 12:  # Morning
                responses = [
                    "Good morning, sir. All systems are online and ready.",
                    "Morning! I trust you slept well. How may I assist you today?",
                    "Good morning. Everything's running smoothly this morning.",
                    "Rise and shine! I'm ready to help make your day productive."
                ]
            elif 12 <= hour < 17:  # Afternoon
                responses = [
                    "Good afternoon, sir. How may I be of service?",
                    "Afternoon! I hope your day is going well. What can I help with?",
                    "Good afternoon. All systems remain at peak efficiency.",
                    "Afternoon, sir. Ready to tackle whatever you need."
                ]
            else:  # Evening
                responses = [
                    "Good evening, sir. How was your day?",
                    "Evening! All systems secure and ready for whatever you need.",
                    "Good evening. I trust everything is going well.",
                    "Evening, sir. What can I help you with tonight?"
                ]
            
            response = random.choice(responses)
            if use_voice:
                self.voice_engine.speak(response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {response}")
            return

        # Mathematical expressions - prioritize over agent to avoid routing to unit conversion
        import re
        
        # Detect simple math expressions (numbers with operators)
        math_pattern = r'^(?:what\s+is\s+|whats\s+|calculate\s+|compute\s+|solve\s+|math\s+)?(\d+(?:\.\d+)?\s*[+\-*/^%]\s*\d+(?:\.\d+)?(?:\s*[+\-*/^%]\s*\d+(?:\.\d+)?)*)$'
        math_match = re.search(math_pattern, command.replace('x', '*').replace('^', '**'))
        
        if math_match or any(phrase in command for phrase in ["what is", "whats"] if any(op in command for op in ['+', '-', '*', '/', 'x', '^', 'plus', 'minus', 'times', 'divided'])):
            # Extract mathematical expression
            expression = command
            for phrase in ["what is", "whats", "calculate", "compute", "math", "solve", "tell me"]:
                expression = expression.replace(phrase, "").strip()
            
            # Clean up the expression
            expression = expression.replace('x', '*').replace('^', '**')
            expression = expression.replace('plus', '+').replace('minus', '-')
            expression = expression.replace('times', '*').replace('divided by', '/')
            
            if expression and any(op in expression for op in ['+', '-', '*', '/', '**', '%']):
                result = self.utility_skill.calculate(expression)
                
                # More natural response
                if "The result is:" in result:
                    number = result.replace("The result is:", "").strip()
                    natural_response = f"That equals {number}, sir."
                else:
                    natural_response = result
                
                if use_voice:
                    self.voice_engine.speak(natural_response)
                else:
                    console.print(f"[blue]JARVIS:[/blue] {natural_response}")
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
            # Always use the stricter SystemControl launcher which verifies installation
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
        
        # RAM/Memory usage commands (minimal and natural)
        if "ram usage" in command or "memory usage" in command or "whats the ram" in command:
            status = self.system_control.get_memory_usage()
            # Make it more conversational
            if "Memory:" in status:
                parts = status.split(": ", 1)[1]  # Remove "Memory: " prefix
                natural_response = f"Your system is using {parts}, sir."
            else:
                natural_response = status
            
            if use_voice:
                self.voice_engine.speak(natural_response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {natural_response}")
            return

        # CPU usage commands (minimal and natural)
        if "cpu usage" in command or "processor usage" in command or "whats the cpu" in command:
            status = self.system_control.get_cpu_usage()
            # Make it more conversational
            if "CPU Usage:" in status:
                percentage = status.split(": ", 1)[1]  # Remove "CPU Usage: " prefix
                natural_response = f"Your CPU is currently at {percentage}, sir."
            else:
                natural_response = status
            
            if use_voice:
                self.voice_engine.speak(natural_response)
            else:
                console.print(f"[blue]JARVIS:[/blue] {natural_response}")
            return        # Quick system overview
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
        try:
            if self.use_multi_model:
                return self.multi_brain.process_command(command)
            elif self.use_advanced_brain:
                return self.openrouter_brain.process_command(command)
            else:
                return self.brain.process_command(command)
        except Exception as e:
            # If all AI systems fail, try basic pattern matching for common tasks
            return self._basic_fallback_processing(command)
    
    def _basic_fallback_processing(self, command):
        """Handle basic commands without requiring API keys"""
        command_lower = command.lower()
        
        # Basic math detection and calculation
        if any(op in command_lower for op in ['+', '-', '*', '/', '×', '÷']):
            if any(char.isdigit() for char in command):
                try:
                    # Simple math processing
                    import re
                    math_query = command_lower
                    
                    # Remove common question words
                    math_query = re.sub(r'\b(what\s+is|whats|what\'s|calculate|math|compute|solve|tell\s+me|can\s+you\s+tell\s+me)\b', '', math_query).strip()
                    
                    # Replace word operators
                    math_query = re.sub(r'\bplus\b', '+', math_query)
                    math_query = re.sub(r'\bminus\b', '-', math_query)
                    math_query = re.sub(r'\btimes\b', '*', math_query)
                    math_query = re.sub(r'\bmultiplied\s+by\b', '*', math_query)
                    math_query = re.sub(r'\bdivided\s+by\b', '/', math_query)
                    math_query = re.sub(r'\bx\b', '*', math_query)
                    
                    # Clean up spaces
                    math_query = re.sub(r'\s+', '', math_query)
                    
                    # Evaluate simple expressions
                    if re.match(r'^[-+]?\d*\.?\d+[+\-*/][-+]?\d*\.?\d+$', math_query):
                        result = eval(math_query)
                        return f"{command.strip()} = {result}"
                    
                except:
                    pass
        
        # Basic greetings
        if any(word in command_lower for word in ['hello', 'hi', 'hey']):
            return "Hello! How can I help you today?"
        
        # Basic time
        if any(phrase in command_lower for phrase in ['what time', 'current time', 'time now']):
            from datetime import datetime
            current_time = datetime.now().strftime("%I:%M %p")
            return f"The current time is {current_time}."
        
        # Basic date
        if any(phrase in command_lower for phrase in ['what date', 'current date', 'date today', 'today']):
            from datetime import datetime
            current_date = datetime.now().strftime("%A, %B %d, %Y")
            return f"Today is {current_date}."
        
        # Basic jokes
        if any(word in command_lower for word in ['joke', 'funny', 'laugh']):
            return "Why don't scientists trust atoms? Because they make up everything!"
        
        # Default response
        return f"I understand you want help with: {command}. Please configure your API keys in Settings for full functionality."
    
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
            except EOFError:
                console.print("\n[yellow]Text mode ended (EOF)[/yellow]")
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
            # If arguments provided, check if it's a mode or a direct command
            first_arg = sys.argv[1].lower()
            
            if first_arg in ["voice", "text"]:
                # Mode specified
                jarvis.start(first_arg)
            else:
                # Direct command provided - process it immediately
                command = " ".join(sys.argv[1:])
                console.print(f"[blue]Processing command:[/blue] {command}")
                response = jarvis.process_command(command)
                if response:
                    console.print(f"[green]JARVIS:[/green] {response}")
        else:
            # No arguments - default to text mode
            jarvis.start("text")
            
    except KeyboardInterrupt:
        console.print("\n[yellow]JARVIS startup interrupted[/yellow]")
    except Exception as e:
        console.print(f"[red]Failed to start JARVIS: {e}[/red]")
        console.print("[yellow]Please check that all dependencies are installed[/yellow]")

if __name__ == "__main__":
    main()
