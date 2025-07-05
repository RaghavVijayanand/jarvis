# JARVIS Multi-Model AI System

## 🧠 Overview

JARVIS now supports multiple AI models from different providers, giving you access to the best AI capabilities for different tasks. The system intelligently selects models based on your needs and provides seamless switching between providers.

## 🤖 Supported Models

### OpenRouter Models (via API)
- **DeepSeek V3** - Advanced reasoning and complex problem solving
- **DeepSeek Coder** - Specialized for programming and code analysis
- **Claude 3.5 Sonnet** - Excellent for analysis and reasoning
- **GPT-4o** - OpenAI's flagship multimodal model
- **Llama 3.3 70B** - High-performance open-source model
- **Qwen 2.5 VL** - Free vision-language model

### Google Gemini Models (via API)
- **Gemini Pro** - Google's advanced language model
- **Gemini Pro Vision** - Multimodal with image understanding
- **Gemini Flash** - Fast and efficient with huge context

### Local Models (if available)
- **Ollama** - Any locally installed Ollama models
- Automatic detection and integration

## 🚀 Key Features

### 1. Intelligent Model Selection
- **Auto-switching** based on task type
- **Smart recommendations** for optimal performance
- **Context-aware** model selection

### 2. Multi-Provider Support
- **OpenRouter** integration for cutting-edge models
- **Google Gemini** for reliable performance
- **Local models** for privacy and offline use
- **Graceful fallbacks** when providers are unavailable

### 3. Advanced Capabilities
- **Vision support** with compatible models
- **Large context windows** (up to 1M tokens with Gemini)
- **Cost optimization** and usage tracking
- **Performance benchmarking**

## 🎯 Commands

### Model Management
```
list models              # Show all available AI models
switch model deepseek-v3  # Change to specific model
current model            # Show current model info
smart model              # Auto-select best model for task
```

### Performance & Analytics
```
benchmark models         # Test all models with same prompt
benchmark models with "explain quantum computing"  # Custom test
model stats             # Usage statistics
usage stats             # Detailed usage information
```

### Conversation Management
```
clear history           # Clear conversation history
reset conversation      # Same as clear history
```

## 🎮 Usage Examples

### Basic Model Switching
```
You: list models
JARVIS: [Shows all available models with details]

You: switch model deepseek-v3
JARVIS: Switched from qwen-2.5-vl to deepseek-v3. Conversation history cleared.

You: current model
JARVIS: Currently using deepseek-v3 - Advanced reasoning and coding
```

### Smart Model Selection
```
You: smart model help me debug this Python code
JARVIS: Switched to deepseek-coder for better performance.

You: smart model write a creative story
JARVIS: Switched to gpt-4o for better performance.

You: smart model analyze this image
JARVIS: Switched to gemini-pro-vision for better performance.
```

### Performance Benchmarking
```
You: benchmark models
JARVIS: [Tests all models with standard prompt and shows speed/quality results]

You: benchmark models with "solve this math problem: 2x + 5 = 15"
JARVIS: [Tests all models with custom prompt]
```

## ⚙️ Configuration

### API Keys Setup
1. **OpenRouter** (for DeepSeek, Claude, GPT-4o, etc.)
   - Already configured in JARVIS
   - Uses existing API key

2. **Google Gemini** (optional)
   ```batch
   # Get API key from: https://makersuite.google.com/app/apikey
   set GEMINI_API_KEY=your_api_key_here
   ```

3. **Local Ollama** (optional)
   ```bash
   # Install Ollama from: https://ollama.ai
   ollama run llama2  # Install any model
   ```

### Model Preferences
The system automatically prefers models based on task:
- **Coding**: DeepSeek Coder
- **Reasoning**: DeepSeek V3
- **Analysis**: Claude 3.5 Sonnet
- **Creative**: GPT-4o
- **Vision**: Gemini Pro Vision
- **Fast**: Gemini Flash
- **Free**: Qwen 2.5 VL

## 📊 Model Comparison

| Model | Provider | Context | Vision | Cost | Best For |
|-------|----------|---------|--------|------|----------|
| DeepSeek V3 | OpenRouter | 64K | ❌ | $0.14 | Reasoning, Analysis |
| DeepSeek Coder | OpenRouter | 16K | ❌ | $0.14 | Programming |
| Claude 3.5 Sonnet | OpenRouter | 200K | ✅ | $3.00 | Analysis, Writing |
| GPT-4o | OpenRouter | 128K | ✅ | $5.00 | Creative, General |
| Llama 3.3 70B | OpenRouter | 128K | ❌ | $0.59 | Open Source |
| Qwen 2.5 VL | OpenRouter | 32K | ✅ | FREE | Vision, Budget |
| Gemini Pro | Google | 30K | ❌ | $0.50 | Reliable |
| Gemini Flash | Google | 1M | ✅ | $0.075 | Fast, Long Context |

## 🔄 Migration from Single Model

Your existing JARVIS configuration remains unchanged. The multi-model system:
- **Preserves** all existing functionality
- **Enhances** AI capabilities with model choice
- **Falls back** gracefully to single model if needed
- **Maintains** conversation history per model

## 🛠️ Installation

1. **Install dependencies**:
   ```bash
   pip install google-generativeai
   ```

2. **Run setup script**:
   ```batch
   setup_multimodel.bat
   ```

3. **Set Gemini API key** (optional):
   ```batch
   set GEMINI_API_KEY=your_key_here
   ```

4. **Start JARVIS**:
   ```bash
   python jarvis.py
   ```

## 🎯 Tips & Best Practices

### Choosing the Right Model
- **DeepSeek V3**: Complex reasoning, analysis, research
- **DeepSeek Coder**: Programming, debugging, code review
- **Claude 3.5 Sonnet**: Writing, analysis, detailed explanations
- **GPT-4o**: Creative tasks, general conversation
- **Gemini Flash**: Quick questions, large documents
- **Qwen 2.5 VL**: Image analysis, free tier usage

### Performance Optimization
- Use `smart model` for automatic selection
- Switch to faster models for simple tasks
- Use vision models only when needed
- Monitor costs with `model stats`

### Troubleshooting
- If a model fails, JARVIS automatically falls back
- Check `list models` to see what's available
- Use `current model` to verify active model
- Clear history if switching contexts

## 🚨 Important Notes

- **Conversation history** is cleared when switching models
- **Different models** may have different response styles
- **Rate limits** vary by provider and model
- **Costs** are shown per 1K tokens for reference
- **Vision features** require compatible models

Enjoy your enhanced AI-powered JARVIS experience! 🤖✨
