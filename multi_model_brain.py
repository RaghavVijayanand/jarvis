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
                "context_window": 128000,
                "supports_vision": False,
                "description": "DeepSeek V3 - Excellent for coding and reasoning",
            },
            "claude-3.5-sonnet": {
                "provider": "openrouter",
                "context_window": 200000,
                "supports_vision": True,
                "description": "Claude 3.5 Sonnet - Best for analysis and writing",
            },
            "gpt-4o": {
                "provider": "openrouter",
                "context_window": 128000,
                "supports_vision": True,
                "description": "GPT-4o - OpenAI's latest multimodal model",
            },
            "gpt-4o-mini": {
                "provider": "openrouter",
                "context_window": 128000,
                "supports_vision": True,
                "description": "GPT-4o Mini - Fast and cost-effective",
            },
            "qwen-2.5-vl": {
                "provider": "openrouter",
                "context_window": 32768,
                "supports_vision": True,
                "description": "Qwen 2.5 VL - Vision and language model (free)",
            },
            "llama-3.2-90b": {
                "provider": "openrouter",
                "context_window": 128000,
                "supports_vision": True,
                "description": "Llama 3.2 90B - Meta's flagship model",
            },
            "mistral-large": {
                "provider": "openrouter",
                "context_window": 128000,
                "supports_vision": False,
                "description": "Mistral Large - European AI excellence",
            },
            "openrouter-auto": {
                "provider": "openrouter",
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

    def process_command(self, command: str, use_context: bool = True) -> str:
        """Route to provider-specific processing. This is a safe stub by default."""
        if not self.current_model:
            return "No model selected. Add API keys in Settings, then choose a model."

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

    def _process_openrouter(self, command: str, config: Dict, use_context: bool) -> str:
        # Basic OpenRouter integration
        try:
            import requests
            
            api_key = getattr(Config, "OPENROUTER_API_KEY", "")
            if not api_key:
                return "OpenRouter API key not configured. Set OPENROUTER_API_KEY in Settings."
            
            # Map model names to OpenRouter API names
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
            
            current_model_name = self.current_model
            api_model = model_mapping.get(current_model_name, "openrouter/auto")
            
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
