from langchain.agents import initialize_agent, Tool, AgentType
from langchain_core.language_models.llms import LLM
from typing import Optional, List, Mapping, Any
import requests
from config import Config

class OpenRouterLLM(LLM):
    """Custom LangChain LLM wrapper for Multi-Model Brain"""
    
    def __init__(self, multi_brain=None):
        super().__init__()
        self._multi_brain = multi_brain
    
    @property
    def _llm_type(self) -> str:
        return "multi_model"
    
    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        """Call the Multi-Model Brain"""
        try:
            if self._multi_brain:
                return self._multi_brain.process_command(prompt, use_context=False)
            else:
                # Fallback to direct OpenRouter call with a working model
                headers = {
                    "Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                }
                
                data = {
                    "model": "qwen/qwen-2.5-72b-instruct",  # Use working model
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0
                }
                
                response = requests.post(
                    f"{Config.OPENROUTER_BASE_URL}/chat/completions",
                    headers=headers,
                    json=data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result["choices"][0]["message"]["content"]
                else:
                    return f"Error: {response.status_code} - {response.text}"
                    
        except Exception as e:
            return f"Error calling AI model: {e}"
    
    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        """Get the identifying parameters."""
        return {"model": "multi_model_brain"}

from skills.weather import WeatherSkill
from skills.web_search import WebSearchSkill
from skills.utility import UtilitySkill
from skills.file_manager import FileManagerSkill
from skills.automation import AutomationSkill
from skills.app_control import ApplicationControl
from system_control import SystemControl

class AgentOrchestrator:
    """
    An autonomous agent that uses LLM planning to invoke JARVIS skills/tools.
    """
    def __init__(self, system_control: SystemControl,
                 weather_skill: WeatherSkill,
                 web_skill: WebSearchSkill,
                 utility_skill: UtilitySkill,
                 file_skill: FileManagerSkill,
                 multi_brain=None):
        # Initialize language model with Multi-Model Brain
        self.llm = OpenRouterLLM(multi_brain=multi_brain)
        self._multi_brain = multi_brain

        # Bind provided tool instances
        self.system_control = system_control
        self.weather_skill = weather_skill
        self.web_skill = web_skill
        self.utility_skill = utility_skill
        self.file_skill = file_skill
        
        # Initialize new advanced skills
        self.automation_skill = AutomationSkill()
        self.app_control = ApplicationControl()

        # Define tools for the agent
        tools = [
            # System Control Tools
            Tool(
                name="get_system_status",
                func=lambda _: self.system_control.get_system_status(),
                description="Get comprehensive system status including CPU, memory, disk, network info."
            ),
            Tool(
                name="get_running_processes",
                func=lambda limit="10": self.system_control.get_running_processes(int(limit) if limit.isdigit() else 10),
                description="List currently running processes sorted by CPU usage."
            ),
            Tool(
                name="get_disk_usage",
                func=lambda _: self.system_control.get_disk_usage(),
                description="Get disk usage information for all drives."
            ),
            Tool(
                name="kill_process",
                func=self.system_control.kill_process,
                description="Kill a process by name. Use with caution."
            ),
            Tool(
                name="get_network_info",
                func=lambda _: self.system_control.get_network_info(),
                description="Get network interface information and IP addresses."
            ),
            Tool(
                name="set_volume",
                func=self.system_control.set_volume,
                description="Set system volume (0-100). Windows only."
            ),
            Tool(
                name="take_screenshot",
                func=lambda filename="": self.system_control.take_screenshot(filename if filename else None),
                description="Take a full screenshot and save it."
            ),
            Tool(
                name="get_battery_info",
                func=lambda _: self.system_control.get_battery_info(),
                description="Get battery information for laptops."
            ),
            Tool(
                name="run_command",
                func=self.system_control.run_command,
                description="Run a system command and return output. Use carefully."
            ),
            
            # Time and Date Tools
            Tool(
                name="get_current_time",
                func=lambda _: self._get_local_time(),
                description="Get the current local time with timezone information."
            ),
            Tool(
                name="get_current_date",
                func=lambda _: self._get_local_date(),
                description="Get the current local date."
            ),
            
            # Application Control Tools
            Tool(
                name="list_installed_apps",
                func=self.app_control.list_installed_apps,
                description="List installed applications, optionally filtered by name."
            ),
            Tool(
                name="launch_app",
                func=self.app_control.launch_app_by_name,
                description="Launch an application by name."
            ),
            Tool(
                name="close_app",
                func=self.app_control.close_app_by_name,
                description="Close an application by name."
            ),
            Tool(
                name="get_app_info",
                func=self.app_control.get_app_info,
                description="Get detailed information about an installed application."
            ),
            
            # Automation Tools
            Tool(
                name="move_mouse",
                func=lambda coords: self.automation_skill.move_mouse(*map(int, coords.split(','))),
                description="Move mouse to specific coordinates. Format: 'x,y'"
            ),
            Tool(
                name="click_at",
                func=lambda coords: self.automation_skill.click_at(*map(int, coords.split(','))),
                description="Click at specific coordinates. Format: 'x,y'"
            ),
            Tool(
                name="type_text",
                func=self.automation_skill.type_text,
                description="Type text on the keyboard."
            ),
            Tool(
                name="press_key",
                func=self.automation_skill.press_key,
                description="Press a specific key (e.g., 'enter', 'tab', 'ctrl')."
            ),
            Tool(
                name="hotkey",
                func=lambda keys: self.automation_skill.hotkey(*keys.split('+')),
                description="Press multiple keys simultaneously. Format: 'ctrl+c' or 'alt+tab'"
            ),
            Tool(
                name="get_mouse_position",
                func=self.automation_skill.get_mouse_position,
                description="Get current mouse position."
            ),
            Tool(
                name="get_window_list",
                func=self.automation_skill.get_window_list,
                description="Get list of all open windows."
            ),
            Tool(
                name="focus_window",
                func=self.automation_skill.focus_window,
                description="Focus on a specific window by title."
            ),
            Tool(
                name="minimize_window",
                func=self.automation_skill.minimize_window,
                description="Minimize a specific window by title."
            ),
            Tool(
                name="maximize_window",
                func=self.automation_skill.maximize_window,
                description="Maximize a specific window by title."
            ),
            Tool(
                name="close_window",
                func=self.automation_skill.close_window,
                description="Close a specific window by title."
            ),
            
            # Weather Tool
            Tool(
                name="get_weather",
                func=self.weather_skill.get_weather,
                description="Get current weather information."
            ),
            
            # Web Search Tools
            Tool(
                name="search_web",
                func=lambda q: self.web_skill.search_web(q, open_browser=False),
                description="Search the web for a query and return results."
            ),
            Tool(
                name="search_wikipedia",
                func=self.web_skill.search_wikipedia,
                description="Search Wikipedia for a topic."
            ),
            Tool(
                name="get_news",
                func=self.web_skill.get_news_headlines,
                description="Get latest news headlines."
            ),
            
            # Utility Tools
            Tool(
                name="tell_joke",
                func=self.utility_skill.tell_joke,
                description="Tell a random joke."
            ),
            Tool(
                name="calculate",
                func=self.utility_skill.calculate,
                description="Calculate a mathematical expression."
            ),
            Tool(
                name="convert_units",
                func=lambda query: self.utility_skill.convert_units_with_llm(query, self._multi_brain),
                description="Convert between units using natural language. Examples: '2 tablespoons butter in grams', '5 km to miles', '100 fahrenheit to celsius'"
            ),
            Tool(
                name="convert_cooking_measurement",
                func=self.utility_skill.convert_cooking_measurement,
                description="Convert cooking measurements like tablespoons, teaspoons, cups to grams. Works with natural language queries."
            ),
            Tool(
                name="generate_password",
                func=self.utility_skill.generate_password,
                description="Generate a secure password."
            ),
            Tool(
                name="flip_coin",
                func=self.utility_skill.flip_coin,
                description="Flip a coin."
            ),
            Tool(
                name="roll_dice",
                func=self.utility_skill.roll_dice,
                description="Roll a dice."
            ),
            
            # File Management Tools
            Tool(
                name="create_file",
                func=self.file_skill.create_file_at_location,
                description="Create a file with filename, content, and location (like 'desktop')."
            ),
            Tool(
                name="read_file",
                func=self.file_skill.read_file,
                description="Read the contents of a file."
            ),
            Tool(
                name="delete_file",
                func=self.file_skill.delete_file,
                description="Delete a specified file."
            ),
            Tool(
                name="list_files",
                func=self.file_skill.list_files,
                description="List files in current directory."
            ),
            Tool(
                name="create_folder",
                func=self.file_skill.create_folder,
                description="Create a new folder."
            ),
            Tool(
                name="rename_file",
                func=self.file_skill.rename_file,
                description="Rename a file or folder."
            )
        ]

        # Initialize the agent with zero-shot react style
        self.agent = initialize_agent(
            tools,
            self.llm,
            agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
            verbose=False,  # Reduce verbose output
            max_iterations=5,  # Reduce iterations to prevent loops
            handle_parsing_errors=True,
            early_stopping_method="generate",  # Stop early if reasonable
            agent_kwargs={
                "prefix": """You are JARVIS, an advanced AI assistant. Provide direct, helpful responses.
For simple questions, give direct answers without using tools.
For complex tasks requiring tools, use them efficiently.
Always provide a final answer to the user's question.""",
                "format_instructions": """To use a tool, use the following format:

Thought: Do I need to use a tool? Let me think about this step by step.
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

If you cannot use tools or get an error, provide a direct response to help the user."""
            }
        )

    def _get_local_time(self) -> str:
        """Get current local time with timezone"""
        try:
            import pytz
            from datetime import datetime
            import time
            
            # Try to get local timezone
            try:
                local_tz = pytz.timezone(time.tzname[0])
            except:
                # Fallback to IST if timezone detection fails
                local_tz = pytz.timezone('Asia/Kolkata')
            
            now = datetime.now(local_tz)
            time_str = now.strftime("%I:%M %p")
            timezone_name = now.strftime("%Z")
            
            return f"The current time is {time_str} {timezone_name}"
        except ImportError:
            from datetime import datetime
            time_str = datetime.now().strftime("%I:%M %p")
            return f"The current time is {time_str} (local time)"
    
    def _get_local_date(self) -> str:
        """Get current local date"""
        try:
            import pytz
            from datetime import datetime
            import time
            
            # Try to get local timezone
            try:
                local_tz = pytz.timezone(time.tzname[0])
            except:
                # Fallback to IST
                local_tz = pytz.timezone('Asia/Kolkata')
            
            now = datetime.now(local_tz)
            return f"Today is {now.strftime('%A, %B %d, %Y')}"
        except ImportError:
            from datetime import datetime
            return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}"
    
    def run(self, query: str) -> str:
        """Run the agent on a query and return the response."""
        try:
            # First check if this is a unit conversion query and use LLM
            conversion_keywords = ['tablespoon', 'teaspoon', 'cup', 'gram', 'ounce', 'pound', 'celsius', 'fahrenheit', 'meter', 'feet', 'inch', 'mile', 'kilometer']
            if any(keyword in query.lower() for keyword in conversion_keywords) and any(num_word in query for num_word in ['0','1','2','3','4','5','6','7','8','9']):
                llm_result = self.utility_skill.convert_units_with_llm(query, self._multi_brain)
                if llm_result and "Error" not in llm_result:
                    return llm_result
            
            # Otherwise, use the agent
            result = self.agent.run(query)
            return result
        except Exception as e:
            error_msg = str(e).lower()
            # Check for parsing errors and provide helpful responses
            if "parsing" in error_msg or "format" in error_msg:
                # Try LLM conversion as fallback
                llm_result = self.utility_skill.convert_units_with_llm(query, self._multi_brain)
                if llm_result and "Error" not in llm_result:
                    return llm_result
                # Try cooking conversion as final fallback
                cooking_result = self.utility_skill.convert_cooking_measurement(query)
                if cooking_result:
                    return cooking_result
                return f"I understand you want help with: {query}. Let me provide a direct response instead of using complex tools."
            elif "timeout" in error_msg:
                return "The request took too long to process. Please try a simpler version of your request."
            else:
                # Try LLM conversion as fallback for any error
                llm_result = self.utility_skill.convert_units_with_llm(query, self._multi_brain)
                if llm_result and "Error" not in llm_result:
                    return llm_result
                cooking_result = self.utility_skill.convert_cooking_measurement(query)
                if cooking_result:
                    return cooking_result
                return f"I encountered an issue processing your request: {query}. Please try rephrasing your question."
