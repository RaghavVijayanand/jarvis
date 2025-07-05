"""
Multi-Model AI Brain for JARVIS
Supports DeepSeek V3, Gemini, OpenRouter models, and more
"""

import os
import json
import requests
import google.generativeai as genai
from typing import Dict, List, Optional, Any
from datetime import datetime
import time
from config import Config

class MultiModelBrain:
    def __init__(self):
        """Initialize multi-model AI brain"""
        self.available_models = {}
        self.current_model = None
        self.conversation_history = []
        
        # Model configurations
        self.model_configs = {
            "qwen-2.5": {
                "provider": "openrouter",
                "model_id": "qwen/qwen-2.5-72b-instruct",
                "context_window": 32000,
                "supports_vision": False,
                "cost_per_1k_tokens": 0.4,
                "description": "Qwen 2.5 - Fast and capable general purpose model"
            },
            "deepseek-coder": {
                "provider": "openrouter", 
                "model_id": "deepseek/deepseek-coder",
                "context_window": 16000,
                "supports_vision": False,
                "cost_per_1k_tokens": 0.14,
                "description": "DeepSeek Coder - Specialized for programming"
            },
            "claude-3.5-sonnet": {
                "provider": "openrouter",
                "model_id": "anthropic/claude-3.5-sonnet",
                "context_window": 200000,
                "supports_vision": True,
                "cost_per_1k_tokens": 3.0,
                "description": "Claude 3.5 Sonnet - Excellent reasoning and analysis"
            },
            "gpt-4o-mini": {
                "provider": "openrouter",
                "model_id": "openai/gpt-4o-mini",
                "context_window": 128000,
                "supports_vision": True,
                "cost_per_1k_tokens": 5.0,
                "description": "GPT-4o - OpenAI's flagship multimodal model"
            },
            "llama-3.3-70b": {
                "provider": "openrouter",
                "model_id": "meta-llama/llama-3.3-70b-instruct",
                "context_window": 128000,
                "supports_vision": False,
                "cost_per_1k_tokens": 0.59,
                "description": "Llama 3.3 70B - High performance open model"
            },
            "qwen-2.5-vl": {
                "provider": "openrouter",
                "model_id": "qwen/qwen2.5-vl-32b-instruct:free",
                "context_window": 32000,
                "supports_vision": True,
                "cost_per_1k_tokens": 0.0,
                "description": "Qwen 2.5 VL - Free vision-language model"
            },
            "gemini-pro": {
                "provider": "gemini",
                "model_id": "gemini-pro",
                "context_window": 30720,
                "supports_vision": False,
                "cost_per_1k_tokens": 0.5,
                "description": "Gemini Pro - Google's advanced language model"
            },
            "gemini-pro-vision": {
                "provider": "gemini",
                "model_id": "gemini-pro-vision", 
                "context_window": 30720,
                "supports_vision": True,
                "cost_per_1k_tokens": 0.5,
                "description": "Gemini Pro Vision - Google's multimodal model"
            },
            "gemini-flash": {
                "provider": "gemini",
                "model_id": "gemini-1.5-flash",
                "context_window": 1000000,
                "supports_vision": True,
                "cost_per_1k_tokens": 0.075,
                "description": "Gemini Flash - Fast and efficient model"
            }
        }
        
        # Initialize available providers
        self._initialize_providers()
        
        # Set default model
        self._set_default_model()
    
    def _initialize_providers(self):
        """Initialize all available AI providers"""
        
        # Initialize OpenRouter
        if Config.OPENROUTER_API_KEY:
            try:
                self._test_openrouter_connection()
                openrouter_models = [k for k, v in self.model_configs.items() if v["provider"] == "openrouter"]
                for model in openrouter_models:
                    self.available_models[model] = self.model_configs[model]
                print("✅ OpenRouter models available")
            except Exception as e:
                print(f"❌ OpenRouter unavailable: {e}")
        
        # Initialize Gemini
        if Config.GEMINI_API_KEY:
            try:
                genai.configure(api_key=Config.GEMINI_API_KEY)
                self._test_gemini_connection()
                gemini_models = [k for k, v in self.model_configs.items() if v["provider"] == "gemini"]
                for model in gemini_models:
                    self.available_models[model] = self.model_configs[model]
                print("✅ Gemini models available")
            except Exception as e:
                print(f"❌ Gemini unavailable: {e}")
        
        # Add local/offline models if available
        self._check_local_models()
    
    def _test_openrouter_connection(self):
        """Test OpenRouter API connection"""
        headers = {
            "Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=10
        )
        
        if response.status_code != 200:
            raise Exception(f"OpenRouter API error: {response.status_code}")
    
    def _test_gemini_connection(self):
        """Test Gemini API connection"""
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content("Hello", request_options={"timeout": 10})
        if not response.text:
            raise Exception("Gemini API test failed")
    
    def _check_local_models(self):
        """Check for available local models (Ollama, etc.)"""
        try:
            # Check for Ollama
            response = requests.get("http://localhost:11434/api/tags", timeout=5)
            if response.status_code == 200:
                ollama_models = response.json().get("models", [])
                for model in ollama_models:
                    model_name = f"ollama-{model['name']}"
                    self.available_models[model_name] = {
                        "provider": "ollama",
                        "model_id": model['name'],
                        "context_window": 8192,
                        "supports_vision": False,
                        "cost_per_1k_tokens": 0.0,
                        "description": f"Local Ollama model: {model['name']}"
                    }
                print("✅ Ollama models available")
        except:
            pass
    
    def _set_default_model(self):
        """Set the default model based on availability and preferences"""
        # Priority order for default model
        preferred_models = [
            "qwen-2.5",  # Updated to our corrected model name
            "claude-3.5-sonnet", 
            "gpt-4o-mini",
            "deepseek-coder",
            "gemini-pro",
            "llama-3.3-70b",
            "mistral-large"
        ]
        
        for model in preferred_models:
            if model in self.available_models:
                self.current_model = model
                print(f"🤖 Default model set to: {model}")
                return
        
        # Fallback to any available model
        if self.available_models:
            self.current_model = list(self.available_models.keys())[0]
            print(f"🤖 Fallback model set to: {self.current_model}")
        else:
            print("❌ No AI models available")
    
    def list_available_models(self) -> str:
        """List all available models with details"""
        if not self.available_models:
            return "No AI models available. Please check your API keys and connections."
        
        result = "🤖 Available AI Models:\n\n"
        
        # Group by provider
        providers = {}
        for model_name, config in self.available_models.items():
            provider = config["provider"]
            if provider not in providers:
                providers[provider] = []
            providers[provider].append((model_name, config))
        
        for provider, models in providers.items():
            result += f"🔹 {provider.upper()} Models:\n"
            for model_name, config in models:
                current_marker = " (CURRENT)" if model_name == self.current_model else ""
                result += f"  • {model_name}{current_marker}\n"
                result += f"    {config['description']}\n"
                result += f"    Context: {config['context_window']:,} tokens | "
                result += f"Vision: {'Yes' if config['supports_vision'] else 'No'} | "
                result += f"Cost: ${config['cost_per_1k_tokens']}/1K tokens\n\n"
        
        result += f"Current model: {self.current_model}\n"
        result += "Use 'switch model [model-name]' to change models"
        
        return result
    
    def switch_model(self, model_name: str) -> str:
        """Switch to a different AI model"""
        if model_name not in self.available_models:
            available = ", ".join(self.available_models.keys())
            return f"Model '{model_name}' not available. Available models: {available}"
        
        old_model = self.current_model
        self.current_model = model_name
        
        # Clear conversation history when switching models
        self.conversation_history = []
        
        return f"Switched from {old_model} to {model_name}. Conversation history cleared."
    
    def process_command(self, command: str, use_context: bool = True) -> str:
        """Process command using the current AI model"""
        if not self.current_model:
            return "No AI model available. Please check your configuration."
        
        try:
            config = self.available_models[self.current_model]
            provider = config["provider"]
            
            # Add to conversation history
            if use_context:
                self.conversation_history.append({"role": "user", "content": command})
                
                # Trim history if too long
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]
            
            # Route to appropriate provider
            if provider == "openrouter":
                response = self._process_openrouter(command, config, use_context)
            elif provider == "gemini":
                response = self._process_gemini(command, config, use_context)
            elif provider == "ollama":
                response = self._process_ollama(command, config, use_context)
            else:
                response = "Unsupported provider"
            
            # Add response to history
            if use_context and response:
                self.conversation_history.append({"role": "assistant", "content": response})
            
            return response
            
        except Exception as e:
            return f"Error processing command with {self.current_model}: {e}"
    
    def _process_openrouter(self, command: str, config: Dict, use_context: bool) -> str:
        """Process command using OpenRouter"""
        headers = {
            "Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Prepare messages
        messages = []
        
        if use_context and len(self.conversation_history) > 1:
            # Add conversation history
            for msg in self.conversation_history[:-1]:  # Exclude the current message
                messages.append(msg)
        
        # Add current message
        messages.append({"role": "user", "content": command})
        
        data = {
            "model": config["model_id"],
            "messages": messages,
            "max_tokens": 1000,
            "temperature": 0.7,
            "top_p": 0.9
        }
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            error_info = response.text
            if response.status_code == 429:
                return "Rate limit exceeded. Try switching to a different model or wait a moment."
            return f"OpenRouter error ({response.status_code}): {error_info}"
    
    def _process_gemini(self, command: str, config: Dict, use_context: bool) -> str:
        """Process command using Gemini"""
        model = genai.GenerativeModel(config["model_id"])
        
        # Prepare conversation history for Gemini
        if use_context and self.conversation_history:
            # Create chat with history
            chat = model.start_chat(history=[])
            
            # Add conversation history
            for msg in self.conversation_history[:-1]:  # Exclude current message
                if msg["role"] == "user":
                    chat.send_message(msg["content"])
            
            response = chat.send_message(command)
        else:
            # Single message
            response = model.generate_content(command)
        
        return response.text
    
    def _process_ollama(self, command: str, config: Dict, use_context: bool) -> str:
        """Process command using local Ollama"""
        data = {
            "model": config["model_id"],
            "prompt": command,
            "stream": False
        }
        
        response = requests.post(
            "http://localhost:11434/api/generate",
            json=data,
            timeout=60
        )
        
        if response.status_code == 200:
            return response.json().get("response", "No response")
        else:
            return f"Ollama error: {response.status_code}"
    
    def get_model_info(self) -> Dict:
        """Get information about the current model"""
        if not self.current_model:
            return {"error": "No model selected"}
        
        config = self.available_models[self.current_model]
        return {
            "name": self.current_model,
            "provider": config["provider"],
            "model_id": config["model_id"],
            "context_window": config["context_window"],
            "supports_vision": config["supports_vision"],
            "cost_per_1k_tokens": config["cost_per_1k_tokens"],
            "description": config["description"],
            "conversation_length": len(self.conversation_history)
        }
    
    def get_personality_response(self, context: str) -> str:
        """Get personality-based response for different contexts"""
        personality_responses = {
            "startup": [
                "JARVIS online. All systems operational. Good evening, Sir.",
                "Systems initialized. I am at your service.",
                "JARVIS ready. How may I assist you today?",
                "All systems green. Standing by for instructions.",
                "JARVIS AI Assistant activated. What can I do for you?"
            ],
            "greeting": [
                "Good to see you, Sir.",
                "How can I help you today?",
                "What would you like me to do?",
                "Ready for your next instruction.",
                "At your service, as always."
            ],
            "goodbye": [
                "Until next time, Sir.",
                "JARVIS signing off.",
                "Systems powering down. Goodbye.",
                "It's been a pleasure serving you.",
                "See you soon."
            ],
            "error": [
                "I apologize, but I encountered an issue.",
                "Something went wrong. Let me try a different approach.",
                "My systems are having difficulty with that request.",
                "I'm experiencing some technical difficulties."
            ],
            "success": [
                "Task completed successfully.",
                "Done, Sir.",
                "Mission accomplished.",
                "Task executed as requested.",
                "Operation completed successfully."
            ]
        }
        
        import random
        
        if context in personality_responses:
            return random.choice(personality_responses[context])
        else:
            return random.choice(personality_responses["greeting"])
    
    def clear_history(self) -> str:
        """Clear conversation history"""
        self.conversation_history = []
        return f"Conversation history cleared for {self.current_model}"
    
    def get_usage_stats(self) -> str:
        """Get usage statistics"""
        total_messages = len(self.conversation_history)
        user_messages = sum(1 for msg in self.conversation_history if msg["role"] == "user")
        assistant_messages = total_messages - user_messages
        
        return f"""📊 Usage Statistics:
Current Model: {self.current_model}
Total Messages: {total_messages}
User Messages: {user_messages}
Assistant Messages: {assistant_messages}
Available Models: {len(self.available_models)}
"""
    
    def benchmark_models(self, test_prompt: str = "Explain quantum computing in simple terms") -> str:
        """Benchmark available models with a test prompt"""
        if not self.available_models:
            return "No models available for benchmarking"
        
        results = []
        original_model = self.current_model
        
        for model_name in self.available_models.keys():
            try:
                self.current_model = model_name
                start_time = time.time()
                response = self.process_command(test_prompt, use_context=False)
                end_time = time.time()
                
                response_time = end_time - start_time
                word_count = len(response.split())
                
                results.append({
                    "model": model_name,
                    "response_time": response_time,
                    "word_count": word_count,
                    "words_per_second": word_count / response_time if response_time > 0 else 0,
                    "response_preview": response[:100] + "..." if len(response) > 100 else response
                })
                
            except Exception as e:
                results.append({
                    "model": model_name,
                    "error": str(e),
                    "response_time": 0,
                    "word_count": 0,
                    "words_per_second": 0
                })
        
        # Restore original model
        self.current_model = original_model
        
        # Format results
        result_text = f"🏃‍♂️ Model Benchmark Results (Prompt: '{test_prompt}'):\n\n"
        
        # Sort by response time
        results.sort(key=lambda x: x.get("response_time", float('inf')))
        
        for i, result in enumerate(results, 1):
            if "error" in result:
                result_text += f"{i}. {result['model']} - ERROR: {result['error']}\n"
            else:
                result_text += f"{i}. {result['model']}\n"
                result_text += f"   Time: {result['response_time']:.2f}s | "
                result_text += f"Words: {result['word_count']} | "
                result_text += f"Speed: {result['words_per_second']:.1f} w/s\n"
                result_text += f"   Preview: {result['response_preview']}\n\n"
        
        return result_text
