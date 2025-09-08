"""
Multi-Model AI Brain for JARVIS (safe mode)
Supports Gemini and OpenRouter model wiring (stubbed by default).

This file intentionally avoids system-control or destructive operations.
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
from config import Config


class MultiModelBrain:
    def __init__(self):
        """Initialize multi-model AI brain"""
        self.available_models: Dict[str, Dict[str, Any]] = {}
        self.current_model: Optional[str] = None
        self.conversation_history: List[Dict[str, Any]] = []

        # Safe model configurations with expanded options
        self.model_configs: Dict[str, Dict[str, Any]] = {
            # Gemini Models
            "gemini-1.5-flash": {
                "provider": "gemini",
                "context_window": 32768,
                "supports_vision": True,
                "description": "Google Gemini 1.5 Flash - Fast and efficient",
            },
            "gemini-1.5-pro": {
                "provider": "gemini",
                "context_window": 128000,
                "supports_vision": True,
                "description": "Google Gemini 1.5 Pro - Advanced reasoning",
            },
            "gemini-2.0-flash": {
                "provider": "gemini",
                "context_window": 32768,
                "supports_vision": True,
                "description": "Google Gemini 2.0 Flash - Latest generation",
            },
            
            # OpenRouter Models - Popular options
            "deepseek-v3": {
                "provider": "openrouter",
                "model_id": "deepseek/deepseek-v3",
                "context_window": 128000,
                "supports_vision": False,
                "description": "DeepSeek V3 - Excellent for coding and reasoning",
            },
            "claude-3.5-sonnet": {
                "provider": "openrouter",
                "model_id": "anthropic/claude-3.5-sonnet",
                "context_window": 200000,
                "supports_vision": True,
                "description": "Claude 3.5 Sonnet - Best for analysis and writing",
            },
            "gpt-4o": {
                "provider": "openrouter",
                "model_id": "openai/gpt-4o",
                "context_window": 128000,
                "supports_vision": True,
                "description": "GPT-4o - OpenAI's latest multimodal model",
            },
            "gpt-4o-mini": {
                "provider": "openrouter",
                "model_id": "openai/gpt-4o-mini",
                "context_window": 128000,
                "supports_vision": True,
                "description": "GPT-4o Mini - Fast and cost-effective",
            },
            "qwen-2.5-vl": {
                "provider": "openrouter",
                "model_id": "qwen/qwen-2.5-vl-7b-instruct",
                "context_window": 32768,
                "supports_vision": True,
                "description": "Qwen 2.5 VL - Vision and language model (free)",
            },
            "llama-3.2-90b": {
                "provider": "openrouter",
                "model_id": "meta-llama/llama-3.2-90b-instruct",
                "context_window": 128000,
                "supports_vision": True,
                "description": "Llama 3.2 90B - Meta's flagship model",
            },
            "mistral-large": {
                "provider": "openrouter",
                "model_id": "mistralai/mistral-large",
                "context_window": 128000,
                "supports_vision": False,
                "description": "Mistral Large - European AI excellence",
            },
            "openrouter-auto": {
                "provider": "openrouter",
                "model_id": "openrouter/auto",
                "context_window": 128000,
                "supports_vision": False,
                "description": "OpenRouter Auto - Smart model selection",
            },
        }

        # Initialize providers and select a default
        self._initialize_providers()
        self._set_default_model()

    def _initialize_providers(self):
        """Initialize all available providers based on configuration and environment keys."""
        self.available_models = {}

        # OpenRouter-backed models
        if getattr(Config, "OPENROUTER_API_KEY", ""):
            for name, cfg in self.model_configs.items():
                if cfg.get("provider") == "openrouter":
                    self.available_models[name] = cfg
        else:
            # Add some free OpenRouter models even without API key
            free_models = ["qwen-2.5-vl"]
            for name, cfg in self.model_configs.items():
                if cfg.get("provider") == "openrouter" and name.split("-")[0] in ["qwen", "openrouter"]:
                    self.available_models[name] = cfg.copy()
                    self.available_models[name]["description"] += " (requires API key)"

        # Gemini-backed models
        if getattr(Config, "GEMINI_API_KEY", ""):
            for name, cfg in self.model_configs.items():
                if cfg.get("provider") == "gemini":
                    self.available_models[name] = cfg

        # Local/offline models can be added here (e.g., Ollama) if desired
        self._check_local_models()
        
        # Always ensure at least one demo model is available
        if not self.available_models:
            self.available_models["demo-model"] = {
                "provider": "demo",
                "context_window": 4096,
                "supports_vision": False,
                "description": "Demo model - Add API keys for real models",
            }

    def _test_openrouter_connection(self):
        """Return True if OpenRouter API key appears configured."""
        return bool(getattr(Config, "OPENROUTER_API_KEY", ""))

    def _test_gemini_connection(self):
        """Return True if Gemini API key appears configured."""
        return bool(getattr(Config, "GEMINI_API_KEY", ""))

    def _check_local_models(self):
        """Placeholder to register local models (e.g., via Ollama)."""
        return

    def _set_default_model(self):
        """Pick a reasonable default model if available."""
        if self.current_model and self.current_model in self.available_models:
            return
            
        # Prefer reliable models in order
        preferred_models = ["qwen-2.5-vl", "gpt-4o-mini", "claude-3.5-sonnet", "openrouter-auto"]
        
        for model in preferred_models:
            if model in self.available_models:
                self.current_model = model
                return
                
        # Fallback to first available model
        self.current_model = next(iter(self.available_models.keys()), None)

    def list_available_models(self) -> str:
        if not self.available_models:
            return "No models available. Open Settings to add API keys."
        lines = [
            f"- {name} ({cfg['provider']}, ctx={cfg['context_window']})"
            for name, cfg in self.available_models.items()
        ]
        return "Available models:\n" + "\n".join(lines)

    def switch_model(self, model_name: str) -> str:
        if model_name not in self.available_models:
            return f"Model '{model_name}' is not available."
        self.current_model = model_name
        return f"Switched to '{model_name}'."

    def process_command(self, command: str, use_context: bool = True, skills=None) -> str:
        """Route to provider-specific processing with intelligent skill routing."""
        if not self.current_model:
            return "No model selected. Add API keys in Settings, then choose a model."

        # Initialize skill routing
        self.last_skill_request = None
        
        # Check if we should route to a skill first
        if skills:
            skill_response = self._route_to_skill(command.lower(), skills)
            if skill_response:
                return skill_response

        cfg = self.available_models[self.current_model]
        provider = cfg.get("provider")
        self.conversation_history.append(
            {"role": "user", "content": command, "ts": datetime.utcnow().isoformat()}
        )

        try:
            if provider == "openrouter":
                reply = self._process_openrouter(command, cfg, use_context)
            elif provider == "gemini":
                reply = self._process_gemini(command, cfg, use_context)
            elif provider == "ollama":
                reply = self._process_ollama(command, cfg, use_context)
            elif provider == "demo":
                reply = self._process_demo(command, cfg, use_context)
            else:
                reply = "Provider not supported."
        except Exception as e:
            reply = f"Error: {e}"

        self.conversation_history.append(
            {"role": "assistant", "content": reply, "ts": datetime.utcnow().isoformat()}
        )
        return reply
    
    def _route_to_skill(self, command, skills):
        """Use LLM to intelligently route commands to appropriate skills"""
        if not skills:
            return None
            
        # Use LLM to determine the best skill for this command
        routing_prompt = f"""
You are JARVIS, an intelligent assistant. Analyze this user command and determine which skill should handle it.

Available skills: {', '.join(skills.keys())}

Command: "{command}"

Based on the command, respond with ONLY one of these options:
- weather (for weather, temperature, forecast queries)
- system_monitor (for system status, CPU, memory, performance)
- file_manager (for file operations, create, delete, move files)
- web_search (for web searches, looking up information)
- utility_math (for mathematical calculations, arithmetic)
- utility_joke (for jokes, humor, funny content)
- screen_automation (for clicking, automation, screen control)
- app_control (for opening/launching applications)
- automation (for complex tasks, scheduling, automation)

If the command doesn't match any specific skill, respond with "general" for general conversation.

Skill:"""

        try:
            # Use the current model to determine routing
            cfg = self.available_models[self.current_model]
            provider = cfg.get("provider")
            
            if provider == "openrouter":
                routing_response = self._process_openrouter(routing_prompt, cfg, use_context=False)
            elif provider == "gemini":
                routing_response = self._process_gemini(routing_prompt, cfg, use_context=False)
            else:
                # Fallback to basic keyword detection
                return self._fallback_keyword_routing(command, skills)
            
            # Extract the skill from response
            routing_response = routing_response.strip().lower()
            
            # Map responses to skill names
            skill_mapping = {
                'weather': 'weather',
                'system_monitor': 'system_monitor', 
                'file_manager': 'file_manager',
                'web_search': 'web_search',
                'utility_math': 'utility_math',
                'utility_joke': 'utility_joke',
                'screen_automation': 'screen_automation',
                'app_control': 'app_control',
                'automation': 'automation'
            }
            
            for key, skill_name in skill_mapping.items():
                if key in routing_response and skill_name in skills:
                    self.last_skill_request = skill_name
                    return f"Routing to {skill_name}..."
                    
            # If no specific skill matched, check for general conversation
            if 'general' in routing_response:
                return None
                
        except Exception as e:
            # Fallback to keyword routing if LLM fails
            return self._fallback_keyword_routing(command, skills)
        
        return None
    
    def _fallback_keyword_routing(self, command, skills):
        """Fallback keyword-based routing when LLM fails"""
        command_lower = command.lower()
        
        # Weather requests
        if any(word in command_lower for word in ['weather', 'temperature', 'forecast', 'rain', 'sunny', 'cloudy']) and 'weather' in skills:
            self.last_skill_request = 'weather'
            return "Let me get the weather information for you..."
        
        # System monitoring
        elif any(word in command_lower for word in ['cpu', 'memory', 'system', 'performance', 'usage', 'ram', 'disk']) and 'system_monitor' in skills:
            self.last_skill_request = 'system_monitor'
            return "Checking system performance..."
        
        # File operations
        elif any(word in command_lower for word in ['file', 'folder', 'directory', 'create', 'delete', 'move', 'copy']) and 'file_manager' in skills:
            self.last_skill_request = 'file_manager'
            return "Processing file operation..."
        
        # Web search
        elif any(word in command_lower for word in ['search', 'google', 'find online', 'look up', 'web']) and 'web_search' in skills:
            self.last_skill_request = 'web_search'
            return "Searching the web..."
        
        # Calculator/math
        elif (any(word in command_lower for word in ['calculate', 'math', 'compute', 'solve']) or 
              any(op in command_lower for op in ['+', '-', '*', '/', '=', '%']) or
              (any(char.isdigit() for char in command) and any(word in command_lower for word in ['what', 'how much', 'plus', 'minus', 'times', 'divided']))) and 'utility' in skills:
            self.last_skill_request = 'utility_math'
            return "Calculating..."
        
        # Jokes
        elif any(word in command_lower for word in ['joke', 'funny', 'humor', 'laugh']) and 'utility' in skills:
            self.last_skill_request = 'utility_joke'
            return "Let me tell you a joke..."
        
        # Screen automation / clicking
        elif any(word in command_lower for word in ['click', 'automate', 'screen', 'find and click', 'press', 'tap', 'mouse', 'move mouse']) and 'screen_automation' in skills:
            self.last_skill_request = 'screen_automation'
            return "Preparing screen automation..."
        
        # General automation
        elif any(word in command_lower for word in ['schedule', 'remind', 'automate', 'task', 'automation']) and 'automation' in skills:
            self.last_skill_request = 'automation'
            return "Setting up automation..."
        
        return None

    def _process_openrouter(self, command: str, config: Dict, use_context: bool) -> str:
        # Basic OpenRouter integration
        try:
            import requests
            
            api_key = getattr(Config, "OPENROUTER_API_KEY", "")
            if not api_key:
                return "OpenRouter API key not configured. Set OPENROUTER_API_KEY in Settings."
            
            # Get model ID from config or use fallback
            api_model = config.get("model_id", "openrouter/auto")
            
            # Fallback mapping for backward compatibility
            if not api_model or api_model == self.current_model:
                model_mapping = {
                    "deepseek-v3": "deepseek/deepseek-v3",
                    "claude-3.5-sonnet": "anthropic/claude-3.5-sonnet",
                    "gpt-4o": "openai/gpt-4o",
                    "gpt-4o-mini": "openai/gpt-4o-mini",
                    "qwen-2.5-vl": "qwen/qwen-2.5-vl-7b-instruct",
                    "llama-3.2-90b": "meta-llama/llama-3.2-90b-instruct",
                    "mistral-large": "mistralai/mistral-large",
                    "openrouter-auto": "openrouter/auto",
                }
                api_model = model_mapping.get(self.current_model, "openrouter/auto")
            
            # Prepare messages
            messages = [{"role": "user", "content": command}]
            
            # Add context if requested
            if use_context and len(self.conversation_history) > 1:
                context_messages = []
                for msg in self.conversation_history[-6:]:  # Last 6 messages
                    if msg["role"] in ["user", "assistant"]:
                        context_messages.append({
                            "role": msg["role"],
                            "content": msg["content"]
                        })
                messages = context_messages + [{"role": "user", "content": command}]
            
            # API request
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/RaghavVijayanand/jarvis",
                    "X-Title": "JARVIS AI Assistant"
                },
                json={
                    "model": api_model,
                    "messages": messages,
                    "max_tokens": 1000,
                    "temperature": 0.7,
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            else:
                return f"OpenRouter API error: {response.status_code} - {response.text[:200]}"
                
        except ImportError:
            return "Requests library not available for OpenRouter integration."
        except Exception as e:
            return f"OpenRouter error: {str(e)}"

    def _process_gemini(self, command: str, config: Dict, use_context: bool) -> str:
        # Basic Gemini integration
        try:
            import google.generativeai as genai
            api_key = getattr(Config, "GEMINI_API_KEY", "")
            if not api_key:
                return "Gemini API key not configured. Set GEMINI_API_KEY in Settings."
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(getattr(Config, "GEMINI_MODEL", "gemini-1.5-flash"))
            
            # Add context if requested
            prompt = command
            if use_context and len(self.conversation_history) > 1:
                recent_context = self.conversation_history[-3:]  # Last 3 exchanges
                context_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_context])
                prompt = f"Context:\n{context_str}\n\nNew message: {command}"
            
            response = model.generate_content(prompt)
            return response.text if response.text else "No response generated."
            
        except ImportError:
            return "Google Generative AI library not available. Install with: pip install google-generativeai"
        except Exception as e:
            return f"Gemini error: {str(e)}"

    def _process_demo(self, command: str, config: Dict, use_context: bool) -> str:
        # Demo model with some basic responses
        responses = [
            f"Demo response to: {command[:50]}{'...' if len(command) > 50 else ''}",
            "This is a demo model. Add API keys in Settings for real AI models.",
            f"You asked: '{command}'. This is a simulated response.",
            "Configure OpenRouter or Gemini API keys to access real AI models.",
        ]
        import random
        return random.choice(responses)

    def _process_ollama(self, command: str, config: Dict, use_context: bool) -> str:
        # Placeholder: integrate local LLM runtime here
        return "(stub) Local model runtime not configured."

    def get_model_info(self) -> Dict:
        if not self.current_model:
            return {"active": None}
        cfg = self.available_models[self.current_model]
        return {
            "active": self.current_model,
            "provider": cfg.get("provider"),
            "context_window": cfg.get("context_window"),
            "supports_vision": cfg.get("supports_vision"),
            "description": cfg.get("description"),
        }

    def get_personality_response(self, context: str) -> str:
        return f"Hi! You said: {context}"

    def clear_history(self) -> str:
        self.conversation_history.clear()
        return "Conversation history cleared."

    def get_usage_stats(self) -> str:
        users = sum(1 for m in self.conversation_history if m["role"] == "user")
        replies = sum(1 for m in self.conversation_history if m["role"] == "assistant")
        return f"Turns: {users} user, {replies} assistant."

    def benchmark_models(self, test_prompt: str = "Explain quantum computing in simple terms") -> str:
        if not self.available_models:
            return "No models to benchmark."
        return "Benchmark placeholder. Enable providers to run real tests."
