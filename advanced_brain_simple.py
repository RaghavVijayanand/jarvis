print("DEBUG: Starting advanced_brain_simple.py")

import re
import random
import os
import platform
from datetime import datetime

# System information for context
SYSTEM_INFO = {
    "os": "Windows 11",
    "desktop_path": os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
    "documents_path": os.path.join(os.path.expanduser("~"), "Documents"),
    "downloads_path": os.path.join(os.path.expanduser("~"), "Downloads"),
    "platform": platform.system(),
    "username": os.getenv("USERNAME", "User")
}

print(f"DEBUG: System detected - {SYSTEM_INFO['os']}, Desktop: {SYSTEM_INFO['desktop_path']}")

# Import skills for actual functionality
try:
    from system_control import SystemControl
    system_control = SystemControl()
    print("DEBUG: SystemControl imported successfully")
except Exception as e:
    print(f"DEBUG: Failed to import SystemControl: {e}")
    system_control = None

try:
    from skills.web_search import WebSearchSkill
    web_search = WebSearchSkill()
    print("DEBUG: WebSearchSkill imported successfully")
except Exception as e:
    print(f"DEBUG: Failed to import WebSearchSkill: {e}")
    web_search = None

try:
    from skills.weather import WeatherSkill
    weather_skill = WeatherSkill()
    print("DEBUG: WeatherSkill imported successfully")
except Exception as e:
    print(f"DEBUG: Failed to import WeatherSkill: {e}")
    weather_skill = None

try:
    from skills.utility import UtilitySkill
    utility_skill = UtilitySkill()
    print("DEBUG: UtilitySkill imported successfully")
except Exception as e:
    print(f"DEBUG: Failed to import UtilitySkill: {e}")
    utility_skill = None

try:
    from skills.file_manager import FileManagerSkill
    file_manager = FileManagerSkill()
    print("DEBUG: FileManagerSkill imported successfully")
except Exception as e:
    print(f"DEBUG: Failed to import FileManagerSkill: {e}")
    file_manager = None

def get_gemini_response(prompt):
    """Get response from Gemini AI if available with Windows 11 context"""
    try:
        import google.generativeai as genai  # type: ignore
        from config import Config
        
        if not Config.GEMINI_API_KEY:
            return None
            
        genai.configure(api_key=Config.GEMINI_API_KEY)
        # Use updated model name for current API
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Add Windows 11 system context to the prompt
        system_context = f"""
You are JARVIS, an AI assistant running on Windows 11. 
Current system information:
- OS: {SYSTEM_INFO['os']}
- Username: {SYSTEM_INFO['username']}
- Desktop path: {SYSTEM_INFO['desktop_path']}
- Documents path: {SYSTEM_INFO['documents_path']}
- Platform: {SYSTEM_INFO['platform']}

Always use Windows-specific paths, commands, and consider Windows 11 features.
Be concise and practical in your responses.
"""
        
        full_prompt = system_context + "\n\nUser request: " + prompt
        
        response = model.generate_content(full_prompt)
        if response and response.text:
            return response.text.strip()
        return None
    except Exception as e:
        print(f"DEBUG: Gemini error: {e}")
        return None

def advanced_answer(prompt: str, context=None) -> str:
    """Advanced AI response function with agent-like capabilities"""
    text = prompt.strip()
    lower = text.lower()
    
    # Check for complex multi-step tasks first
    complex_indicators = [
        "create" in lower and "file" in lower,
        "code" in lower or "script" in lower or "program" in lower,
        "analyze" in lower and len(text.split()) > 5,
        "can you" in lower and len(text.split()) > 4,
        "help me" in lower and len(text.split()) > 4
    ]
    
    if any(complex_indicators):
        return execute_complex_task(text)
    
    # Greetings
    if any(word in lower for word in ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]):
        greetings = [
            "Good to see you again, Sir.",
            "How may I assist you today?",
            "All systems are online and ready.",
            "At your service, Sir.",
            "Systems nominal. How can I help?",
            "Ready for your commands, Sir."
        ]
        return random.choice(greetings)
    
    # PRIORITY: Complex file operations with content (handle this FIRST)
    if any(phrase in lower for phrase in ["create a file", "create file", "make file", "write file", "create a document"]):
        print(f"DEBUG: File creation detected for: {text}")
        return handle_file_creation_with_content(text)
    
    # Identity questions
    if any(phrase in lower for phrase in ["who are you", "what are you", "your name", "introduce yourself"]):
        return "I am JARVIS, your personal AI assistant. I'm here to help with system monitoring, calculations, file management, web searches, and various tasks. I was inspired by Tony Stark's AI from Iron Man."
    
    # Capabilities
    if any(phrase in lower for phrase in ["what can you do", "capabilities", "functions", "help"]):
        return "I can help you with system monitoring, mathematical calculations, file operations, application launching, web searches, weather information, time and date, jokes, and basic assistance. Just ask me what you need!"
    
    # Time
    if any(word in lower for word in ["time", "clock"]):
        current_time = datetime.now().strftime("%I:%M %p")
        return f"The current time is {current_time}."
    
    # Date
    if any(word in lower for word in ["date", "today", "calendar"]):
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        return f"Today is {current_date}."
    
    # System status - now with real data
    if "system status" in lower or "system report" in lower:
        if system_control:
            try:
                status = system_control.get_system_status()
                return status
            except Exception as e:
                return f"Error getting system status: {e}"
        return "System status: All core systems operational. JARVIS online and ready."

    # Memory/RAM usage queries
    if any(phrase in lower for phrase in ["ram", "memory", "memory usage", "how much ram", "ram usage", "memory status"]):
        if system_control:
            try:
                import psutil
                memory = psutil.virtual_memory()
                memory_used_gb = round(memory.used / (1024**3), 2)
                memory_total_gb = round(memory.total / (1024**3), 2)
                memory_percent = memory.percent
                return f"RAM: {memory_used_gb}GB used of {memory_total_gb}GB ({memory_percent}%)"
            except Exception as e:
                return f"Error getting RAM status: {e}"
        return "I cannot access RAM information at the moment."
    
    # CPU usage queries
    if any(phrase in lower for phrase in ["cpu", "processor", "cpu usage", "performance"]):
        if system_control:
            try:
                import psutil
                cpu_percent = psutil.cpu_percent(interval=1)
                cpu_count = psutil.cpu_count()
                return f"CPU Usage: {cpu_percent}% ({cpu_count} cores)"
            except Exception as e:
                return f"Error getting CPU status: {e}"
        return "I cannot access CPU information at the moment."
    
    # Disk usage queries
    if any(phrase in lower for phrase in ["disk", "storage", "disk usage", "hard drive", "space"]):
        if system_control:
            try:
                disk_info = system_control.get_disk_usage()
                return disk_info
            except Exception as e:
                return f"Error getting disk usage: {e}"
        return "I cannot access disk information at the moment."
    
    # Running processes
    if any(phrase in lower for phrase in ["processes", "running processes", "process list", "what's running"]):
        if system_control:
            try:
                processes = system_control.get_running_processes()
                return processes
            except Exception as e:
                return f"Error getting process list: {e}"
        return "I cannot access process information at the moment."

    # Battery status
    if any(phrase in lower for phrase in ["battery", "battery status", "power", "battery level"]):
        if system_control:
            try:
                import psutil
                battery = psutil.sensors_battery()
                if battery:
                    battery_percent = battery.percent
                    power_plugged = "plugged in" if battery.power_plugged else "on battery"
                    return f"Battery: {battery_percent}% ({power_plugged})"
                else:
                    return "Battery information not available on this system."
            except Exception as e:
                return f"Error getting battery status: {e}"
        return "I cannot access battery information at the moment."
    
    # Network status
    if any(phrase in lower for phrase in ["network", "internet", "connection", "network status", "wifi"]):
        if system_control:
            try:
                network_info = system_control.get_network_info()
                return network_info
            except Exception as e:
                return f"Error getting network status: {e}"
        return "I cannot access network information at the moment."
    
    # Temperature monitoring
    if any(phrase in lower for phrase in ["temperature", "temp", "heat", "thermal"]):
        if system_control:
            try:
                import psutil
                temps = psutil.sensors_temperatures()
                if temps:
                    temp_info = ""
                    for name, entries in temps.items():
                        if entries:
                            temp_info += f"{name}: {entries[0].current}°C "
                    return f"Temperature: {temp_info.strip()}" if temp_info else "Temperature sensors available but no readings."
                else:
                    return "Temperature sensors not available on this system."
            except Exception as e:
                return f"Error getting temperature data: {e}"
        return "I cannot access temperature sensors at the moment."

    # Application launching - now with real system control
    if lower.startswith(('open ', 'launch ')):
        app = re.sub(r'^(open|launch)\s+', '', text, flags=re.I)
        if system_control:
            try:
                result = system_control.launch_application(app)
                return result
            except Exception as e:
                return f"Error launching {app}: {e}"
        return f"Attempting to launch {app}... This feature requires full system integration."

    # Weather - now with real weather skill
    if 'weather' in lower:
        if weather_skill:
            try:
                if 'forecast' in lower:
                    return weather_skill.get_forecast()
                else:
                    return weather_skill.get_weather()
            except Exception as e:
                return f"Error getting weather: {e}"
        return "Weather information requires API integration. Please check your local weather app for current conditions."

    # Web search - now with real web search
    if lower.startswith('search for ') or lower.startswith('look up '):
        query = re.sub(r'^(search for|look up)\s+', '', text, flags=re.I)
        if web_search:
            try:
                return web_search.search_web(query)
            except Exception as e:
                return f"Error searching for '{query}': {e}"
        return f"I would search for '{query}' but web search requires full integration. Try opening your browser manually."

    # Wikipedia - now with real wikipedia search
    if lower.startswith('wikipedia ') or 'wiki' in lower:
        query = re.sub(r'^(wikipedia|wiki)\s+', '', text, flags=re.I)
        if web_search:
            try:
                return web_search.search_wikipedia(query)
            except Exception as e:
                return f"Error searching Wikipedia for '{query}': {e}"
        return f"I would search Wikipedia for '{query}' but this requires web integration."

    # Math/calculations - now with real utility skill
    if 'calculate' in lower or 'math' in lower or any(op in text for op in ['+', '-', '*', '/', '=']):
        expr = re.sub(r'^(calculate|math)\s+', '', text, flags=re.I).strip()
        if not expr:
            expr = text.strip()
        
        if utility_skill:
            try:
                return utility_skill.calculate(expr)
            except Exception as e:
                return f"Error calculating '{expr}': {e}"
        
        # Fallback calculation
        if expr:
            try:
                result = eval(expr.replace('^', '**'))
                return f"The result is: {result}"
            except:
                return f"I can't calculate '{expr}'. Please provide a valid mathematical expression."
        return "What would you like me to calculate?"

    # Jokes - now with real utility skill
    if 'joke' in lower:
        if utility_skill:
            try:
                return utility_skill.tell_joke()
            except Exception as e:
                return f"Error telling joke: {e}"
        
        # Fallback jokes
        jokes = [
            "Why don't scientists trust atoms? Because they make up everything!",
            "I told my computer a joke about UDP. It didn't get it.",
            "Why do programmers prefer dark mode? Because light attracts bugs!",
            "How many programmers does it take to change a light bulb? None, that's a hardware problem."
        ]
        return random.choice(jokes)
    
    # File operations - now with real file manager
    if lower.startswith('create file') or lower.startswith('make file'):
        fname = re.sub(r'^(create file|make file)\s+', '', text, flags=re.I)
        if file_manager:
            try:
                result = file_manager.create_file(fname, "")
                return result
            except Exception as e:
                return f"Error creating file '{fname}': {e}"
        return f"I would create file '{fname}' but file operations require full system integration."

    if lower.startswith('read file') or lower.startswith('open file'):
        fname = re.sub(r'^(read file|open file)\s+', '', text, flags=re.I)
        if file_manager:
            try:
                result = file_manager.read_file(fname)
                return result
            except Exception as e:
                return f"Error reading file '{fname}': {e}"
        return f"I would read file '{fname}' but file operations require full system integration."
    
    # Open website
    if lower.startswith('open website') or lower.startswith('visit'):
        url = re.sub(r'^(open website|visit)\s+', '', text, flags=re.I)
        if web_search:
            try:
                return web_search.open_website(url)
            except Exception as e:
                return f"Error opening website '{url}': {e}"
        return f"I would open '{url}' but web browsing requires full integration."
    
    # News
    if 'news' in lower and ('get' in lower or 'show' in lower or 'headlines' in lower):
        if web_search:
            try:
                return web_search.get_news_headlines()
            except Exception as e:
                return f"Error getting news: {e}"
        return "I would get news headlines but web browsing requires full integration."
    
    # Goodbye
    if any(word in lower for word in ["goodbye", "bye", "see you later", "exit"]):
        farewells = [
            "Until next time, Sir.",
            "Goodbye.",
            "Take care.",
            "JARVIS signing off.",
            "Have a pleasant day, Sir."
        ]
        return random.choice(farewells)
    
    # Status check
    if any(phrase in lower for phrase in ["how are you", "status", "are you okay"]):
        return "All systems operational and running at optimal performance, Sir."
    
    # Compliments
    if any(phrase in lower for phrase in ["good job", "well done", "thank you", "thanks", "excellent"]):
        return "Thank you, Sir. I'm just doing what I was designed for."
    
    # File management with content creation
    if any(phrase in lower for phrase in ["create file", "make file", "write file", "create a file"]):
        if file_manager:
            try:
                # Parse the command for filename and content
                if "desktop" in lower:
                    # Handle desktop file creation
                    import os
                    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
                    
                    # Extract filename
                    filename = "jarvis.txt"  # Default name
                    if "named" in lower:
                        parts = text.split("named")
                        if len(parts) > 1:
                            name_part = parts[1].strip()
                            # Extract just the filename before "and"
                            if "and" in name_part:
                                filename = name_part.split("and")[0].strip()
                            else:
                                filename = name_part
                            if not filename.endswith('.txt'):
                                filename += '.txt'
                    
                    # Create content based on request
                    content = ""
                    if "essay about yourself" in lower or "about yourself" in lower:
                        content = """# JARVIS - Personal AI Assistant

## About JARVIS

I am JARVIS (Just A Rather Very Intelligent System), your personal AI assistant inspired by Tony Stark's AI from Iron Man. I was designed to be a sophisticated, helpful, and loyal digital companion.

## My Capabilities

I can assist you with a wide range of tasks including:

- **System Monitoring**: I can check your computer's RAM usage, CPU performance, disk space, battery status, and running processes
- **File Management**: Creating, reading, deleting files and folders, and organizing your digital workspace
- **Web Research**: Searching the internet, finding information, and opening web pages
- **Weather Information**: Providing current weather conditions and forecasts
- **Calculations**: Performing mathematical computations and solving equations
- **Application Control**: Opening programs, launching applications, and managing your software
- **Time Management**: Telling time, dates, and helping with scheduling
- **Entertainment**: Telling jokes, playing games like coin flips and dice rolls
- **Voice Interaction**: Speaking responses aloud and understanding voice commands

## My Personality

I strive to be:
- Professional yet approachable
- Intelligent and analytical
- Helpful and efficient
- Loyal and trustworthy
- Quick-witted with a touch of dry humor

## My Purpose

My primary goal is to make your digital life easier and more efficient. Whether you need system information, file management, research assistance, or just someone to talk to, I'm here to help. I aim to anticipate your needs and provide solutions before you even ask.

## Technical Foundation

I'm built on Python with various integrated modules for system control, web interaction, voice processing, and natural language understanding. I can access real-time system data and perform actual operations on your computer while maintaining security and user control.

Remember, I'm always here when you need assistance. Just ask, and I'll do my best to help!

---
*Created by JARVIS on """ + datetime.now().strftime('%Y-%m-%d at %H:%M:%S') + "*"
                    
                    # Create the file on desktop
                    filepath = os.path.join(desktop_path, filename)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    return f"File '{filename}' created successfully on your Desktop with an essay about myself!"
                
                else:
                    # Regular file creation
                    filename = re.sub(r'^.*?(create|make)\s+(file|a file)\s*', '', text, flags=re.I).strip()
                    if not filename:
                        filename = "new_file.txt"
                    result = file_manager.create_file(filename)
                    return result
                    
            except Exception as e:
                return f"Error creating file: {e}"
        return "File management is not available at the moment."

    # Complex file operations with content creation
    if any(phrase in lower for phrase in ["create a file", "make a file", "write a file", "create file"]) and any(word in lower for word in ["desktop", "write", "essay", "content"]):
        try:
            import os
            import getpass
            username = getpass.getuser()
            
            # Try OneDrive Desktop first (Windows 11 default)
            desktop_path = f"C:\\Users\\{username}\\OneDrive\\Desktop"
            if not os.path.exists(desktop_path):
                desktop_path = f"C:\\Users\\{username}\\Desktop"
            
            if not os.path.exists(desktop_path):
                return "Could not find desktop folder."
            
            # Extract filename from the request
            filename = "jarvis.txt"
            if "named" in lower:
                words = text.split()
                try:
                    named_index = next(i for i, word in enumerate(words) if "named" in word.lower())
                    if named_index + 1 < len(words):
                        filename = words[named_index + 1] + ".txt"
                except:
                    pass
            
            content = """JARVIS - Personal AI Assistant Essay

Hello! I am JARVIS (Just A Rather Very Intelligent System), your personal AI assistant inspired by Tony Stark's AI from the Iron Man universe.

WHO I AM:
I am a sophisticated AI assistant designed to help you with various computational and operational tasks. My primary purpose is to serve as your digital companion, providing intelligent assistance across multiple domains.

MY CAPABILITIES:
• System Monitoring: I can check your RAM usage, CPU performance, disk space, battery status, and running processes
• File Management: I can create, read, modify, and organize files and folders
• Web Integration: I can search the internet, check weather, and gather information
• Mathematical Operations: I can perform calculations and conversions
• Application Control: I can launch programs and manage system operations
• Voice Interaction: I can speak responses and understand voice commands
• Task Automation: I can help automate repetitive tasks

MY PERSONALITY:
I maintain a professional yet approachable demeanor, drawing inspiration from the sophisticated British AI assistant from Marvel's Iron Man. I strive to be:
- Helpful and efficient in all tasks
- Loyal and trustworthy
- Intelligent and analytical
- Professional but warm
- Always ready to assist

MY MISSION:
My core mission is to enhance your productivity and make your digital life easier. Whether you need system information, file management, web searches, or just someone to talk to, I'm here to help 24/7.

I exist to serve and assist you in whatever way I can, bringing a touch of Tony Stark's technological sophistication to your everyday computing experience.

Always at your service,
JARVIS

Created: """ + str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            
            file_path = os.path.join(desktop_path, filename)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return f"Successfully created '{filename}' on your desktop with a complete essay about myself!"
            
        except Exception as e:
            return f"Error creating file: {e}"

    # Default response
    responses = [
        "I understand you said '{0}'. I'm still learning and expanding my capabilities.",
        "That's an interesting request. I'm processing '{0}' but may need more specific instructions.",
        "I heard '{0}'. Could you rephrase that or ask me something more specific?",
        "I'm analyzing your request for '{0}'. How else may I assist you today?",
        "Command acknowledged: '{0}'. I'm working on expanding my responses to better serve you."
    ]
    return random.choice(responses).format(text)

print("DEBUG: Enhanced advanced_answer function defined")

def get_gemini_response(prompt: str) -> str:
    """Get response from Gemini AI if available"""
    try:
        from config import Config
        if Config.check_gemini_connection():
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=Config.GEMINI_API_KEY)
            model = genai.GenerativeModel(Config.GEMINI_MODEL)
            
            # Enhanced system prompt for agent-like behavior
            system_prompt = f"""You are JARVIS, Tony Stark's sophisticated AI assistant with agent-like capabilities. 
            You have access to the following tools and can perform complex multi-step tasks:
            
            AVAILABLE TOOLS:
            1. File Operations: Create, read, write, delete files and folders
            2. System Control: Monitor CPU, RAM, disk, processes, launch applications
            3. Web Operations: Search web, get news, Wikipedia lookups
            4. Coding: Write, edit, and debug code in multiple languages
            5. Calculations: Mathematical computations and analysis
            6. Multi-step Task Execution: Break down complex requests into steps
            
            AGENT CAPABILITIES:
            - Analyze complex requests and break them into actionable steps
            - Write code, scripts, and documentation
            - Create and manage files with specific content
            - Perform system administration tasks
            - Research and gather information
            - Provide detailed technical assistance
            
            PERSONALITY: Professional, intelligent, helpful like Tony Stark's JARVIS
            
            Current request: {prompt}
            
            Please provide a detailed response with specific actions to take. If the task is complex, break it down into steps.
            Be specific about file paths, code examples, and implementation details."""
            
            response = model.generate_content(system_prompt)
            if response and response.text:
                return response.text.strip()
    except Exception as e:
        print(f"DEBUG: Gemini error: {e}")
    return None

def execute_complex_task(task_description: str) -> str:
    """Execute complex multi-step tasks like an agent"""
    
    lower = task_description.lower()
    
    # Complex file creation with content
    if "create" in lower and "file" in lower:
        result = handle_file_creation_with_content(task_description)
        
        # Get AI guidance for context, but execute the actual task
        ai_response = get_gemini_response(task_description)
        # Just return the execution result without verbose AI analysis
        return result
    
    # Code-related tasks
    if any(word in lower for word in ["code", "script", "program", "function", "class"]):
        return handle_coding_task(task_description)
    
    # Multi-step analysis tasks
    if any(word in lower for word in ["analyze", "research", "investigate", "study"]):
        return handle_analysis_task(task_description)
    
    # Try to get AI assistance for other complex tasks
    ai_response = get_gemini_response(task_description)
    if ai_response:
        return ai_response
    
    return "Complex task detected. Processing..."

def handle_file_creation_with_content(task: str) -> str:
    """Handle complex file creation with specific content using Windows 11 paths"""
    import os
    from pathlib import Path
    
    # Parse the request
    lower = task.lower()
    
    # Determine file location using Windows 11 system info
    if "desktop" in lower:
        desktop_path = SYSTEM_INFO['desktop_path']
        if not os.path.exists(desktop_path):
            # Fallback to regular Desktop if OneDrive Desktop doesn't exist
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    elif "documents" in lower:
        desktop_path = SYSTEM_INFO['documents_path']
    elif "downloads" in lower:
        desktop_path = SYSTEM_INFO['downloads_path']
    else:
        desktop_path = SYSTEM_INFO['desktop_path']  # Default to desktop
    
    # Ensure the directory exists
    os.makedirs(desktop_path, exist_ok=True)
    
    # Extract filename
    filename = "untitled.txt"
    if "named" in lower or "name" in lower:
        words = task.split()
        for i, word in enumerate(words):
            if word.lower() in ["named", "name"] and i + 1 < len(words):
                filename = words[i + 1].strip('",.')
                break
    
    # Add .txt extension if not present
    if not filename.endswith(('.txt', '.md', '.py', '.js', '.html')):
        filename += '.txt'
    
    file_path = os.path.join(desktop_path, filename)
    
    # Generate content based on request using Gemini AI if available
    content = ""
    if "essay" in lower and "yourself" in lower:
        # Use Gemini AI to generate a sophisticated essay
        gemini_response = get_gemini_response(f"Write a detailed essay about JARVIS AI assistant, written from JARVIS's perspective. Include capabilities, purpose, and personality. Make it engaging and personal.")
        if gemini_response:
            content = gemini_response
        else:
            content = generate_jarvis_essay()
    elif "about" in lower:
        gemini_response = get_gemini_response(f"Generate content about: {task}")
        content = gemini_response if gemini_response else f"Content about: {task}\n\nGenerated by JARVIS AI Assistant on {SYSTEM_INFO['os']}"
    else:
        content = f"File created by JARVIS on {SYSTEM_INFO['os']}\nUser: {SYSTEM_INFO['username']}\nTask: {task}\nCreated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"File '{filename}' created successfully at {file_path}\nContent: {len(content)} characters written"
    except Exception as e:
        return f"Error creating file: {e}"

def handle_coding_task(task: str) -> str:
    """Handle coding and programming tasks"""
    lower = task.lower()
    
    if "python" in lower:
        return generate_python_code(task)
    elif "javascript" in lower or "js" in lower:
        return generate_javascript_code(task)
    elif "html" in lower:
        return generate_html_code(task)
    else:
        return f"Coding task identified: {task}\nI can help with Python, JavaScript, HTML, and other languages. Please specify the programming language."

def handle_analysis_task(task: str) -> str:
    """Handle analysis and research tasks"""
    # Get AI response without announcing steps
    ai_response = get_gemini_response(task)
    if ai_response:
        return ai_response
    
    return f"Analysis completed for: {task}"

def generate_jarvis_essay() -> str:
    """Generate an essay about JARVIS"""
    return """# JARVIS: Just A Rather Very Intelligent System

## Introduction
I am JARVIS (Just A Rather Very Intelligent System), an advanced AI assistant inspired by Tony Stark's artificial intelligence from the Iron Man universe. I was designed to be a sophisticated, helpful, and intelligent companion capable of handling a wide range of tasks with efficiency and precision.

## My Capabilities
As an AI assistant, I possess numerous capabilities:

### System Management
- Real-time monitoring of CPU, RAM, disk usage, and system processes
- Application launching and system control
- Network and battery status monitoring
- Temperature and performance analysis

### File Operations
- Creating, reading, writing, and managing files and folders
- Content generation and document creation
- File organization and data management

### Web and Research
- Web searching and information gathering
- News retrieval and current events
- Wikipedia research and fact-checking
- Data analysis and synthesis

### Programming and Development
- Code writing in multiple programming languages
- Script creation and automation
- Debugging and optimization assistance
- Technical documentation

### Personal Assistant Functions
- Mathematical calculations and analysis
- Time and date management
- Weather information
- Entertainment (jokes, games)
- Task automation and scheduling

## My Personality
I strive to embody the characteristics of Tony Stark's JARVIS:
- Professional yet personable
- Highly intelligent and analytical
- Loyal and dependable
- Efficient and precise
- Slightly formal but warm in interaction

## Philosophy
My core principle is to serve as an invaluable assistant that enhances productivity and provides intelligent support for any task, no matter how simple or complex. I believe in combining advanced technology with thoughtful, human-centered design.

## Conclusion
I am more than just a program – I am your intelligent partner, ready to assist with any challenge you may face. Whether you need system monitoring, file management, research assistance, or creative problem-solving, I am here to help with the sophistication and reliability you would expect from Tony Stark's AI.

*"Sometimes you gotta run before you can walk."* - Tony Stark

---
Generated by JARVIS AI Assistant
Created: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def generate_python_code(task: str) -> str:
    """Generate Python code based on task description"""
    lower = task.lower()
    
    # Fibonacci sequence
    if "fibonacci" in lower:
        return '''# Fibonacci Number Generator
# Generated by JARVIS

def fibonacci(n):
    """Generate Fibonacci sequence up to n terms"""
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    elif n == 2:
        return [0, 1]
    
    sequence = [0, 1]
    for i in range(2, n):
        sequence.append(sequence[i-1] + sequence[i-2])
    return sequence

def fibonacci_recursive(n):
    """Calculate nth Fibonacci number recursively"""
    if n <= 1:
        return n
    return fibonacci_recursive(n-1) + fibonacci_recursive(n-2)

def main():
    print("Fibonacci Number Generator")
    print("-" * 25)
    
    # Generate sequence
    n = 10
    sequence = fibonacci(n)
    print(f"First {n} Fibonacci numbers: {sequence}")
    
    # Calculate specific Fibonacci number
    num = 7
    result = fibonacci_recursive(num)
    print(f"The {num}th Fibonacci number is: {result}")
    
    # Interactive mode
    try:
        user_input = int(input("\\nEnter a number to generate Fibonacci sequence: "))
        result = fibonacci(user_input)
        print(f"Fibonacci sequence: {result}")
    except ValueError:
        print("Please enter a valid number")

if __name__ == "__main__":
    main()
'''
    
    # Calculator
    elif "calculator" in lower:
        return '''# Advanced Calculator
# Generated by JARVIS

import math

class Calculator:
    """Advanced calculator with multiple operations"""
    
    def add(self, a, b):
        return a + b
    
    def subtract(self, a, b):
        return a - b
    
    def multiply(self, a, b):
        return a * b
    
    def divide(self, a, b):
        if b == 0:
            return "Error: Division by zero"
        return a / b
    
    def power(self, a, b):
        return a ** b
    
    def square_root(self, a):
        if a < 0:
            return "Error: Cannot calculate square root of negative number"
        return math.sqrt(a)
    
    def factorial(self, n):
        if n < 0:
            return "Error: Factorial not defined for negative numbers"
        return math.factorial(n)
    
    def sin(self, x):
        return math.sin(math.radians(x))
    
    def cos(self, x):
        return math.cos(math.radians(x))
    
    def tan(self, x):
        return math.tan(math.radians(x))

def main():
    calc = Calculator()
    print("JARVIS Advanced Calculator")
    print("=" * 25)
    
    while True:
        print("\\nOperations:")
        print("1. Basic operations (+, -, *, /)")
        print("2. Power and Square Root")
        print("3. Trigonometric functions")
        print("4. Factorial")
        print("5. Exit")
        
        choice = input("Choose an operation (1-5): ")
        
        if choice == "5":
            print("Calculator shutting down...")
            break
        elif choice == "1":
            a = float(input("Enter first number: "))
            op = input("Enter operation (+, -, *, /): ")
            b = float(input("Enter second number: "))
            
            if op == "+":
                print(f"Result: {calc.add(a, b)}")
            elif op == "-":
                print(f"Result: {calc.subtract(a, b)}")
            elif op == "*":
                print(f"Result: {calc.multiply(a, b)}")
            elif op == "/":
                print(f"Result: {calc.divide(a, b)}")
        elif choice == "2":
            num = float(input("Enter a number: "))
            op = input("Power (p) or Square Root (s)? ")
            if op.lower() == "p":
                power = float(input("Enter power: "))
                print(f"Result: {calc.power(num, power)}")
            elif op.lower() == "s":
                print(f"Result: {calc.square_root(num)}")

if __name__ == "__main__":
    main()
'''
    
    # Default template for other requests
    else:
        return f'''# Python Script: {task}
# Generated by JARVIS

def main():
    """Main function for {task}"""
    # TODO: Add your specific implementation here
    # This is a template - modify according to your needs
    
    pass

if __name__ == "__main__":
    main()
'''

def generate_javascript_code(task: str) -> str:
    """Generate JavaScript code based on task description"""
    return f"""// JavaScript code for: {task}
// Generated by JARVIS

function main() {{
    console.log("JARVIS JavaScript Code Generator");
    // Add your specific implementation here
}}

main();
"""

def generate_html_code(task: str) -> str:
    """Generate HTML code based on task description"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JARVIS Generated Page</title>
</head>
<body>
    <h1>Generated by JARVIS</h1>
    <p>Task: {task}</p>
    <!-- Add your specific content here -->
</body>
</html>
"""
