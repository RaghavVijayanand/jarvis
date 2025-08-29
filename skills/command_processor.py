"""
Enhanced Command Processing Skill for JARVIS
Handles complex compound commands and natural language parsing
"""

import re
import time
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta

class CommandProcessor:
    def __init__(self, jarvis_instance):
        """Initialize with reference to main JARVIS instance"""
        self.jarvis = jarvis_instance
        
        # Command patterns for complex parsing
        self.sequence_patterns = [
            r"(.*?)\s*(?:then|and then|after that|next)\s*(.*)",
            r"(.*?)\s*(?:,\s*then|,\s*and then)\s*(.*)",
            r"(.*?)\s*(?:;\s*then|;\s*and)\s*(.*)",
        ]
        
        # Time delay patterns
        self.delay_patterns = [
            r"wait\s+(\d+)\s+seconds?",
            r"pause\s+for\s+(\d+)\s+seconds?",
            r"after\s+(\d+)\s+seconds?",
            r"in\s+(\d+)\s+seconds?",
        ]
        
        # Conditional patterns
        self.conditional_patterns = [
            r"if\s+(.*?)\s+then\s+(.*)",
            r"when\s+(.*?)\s+(?:then\s+)?(.*)",
            r"once\s+(.*?)\s+(?:then\s+)?(.*)",
        ]
        
        # File operation context
        self.file_context = {}
        
    def parse_complex_command(self, command: str) -> List[Dict]:
        """Parse complex commands into executable steps"""
        steps = []
        
        # Check for conditional commands
        conditional_match = self._match_pattern(command, self.conditional_patterns)
        if conditional_match:
            condition, action = conditional_match
            steps.append({
                'type': 'conditional',
                'condition': condition.strip(),
                'action': action.strip(),
                'raw_command': command
            })
            return steps
        
        # Check for sequence commands
        sequence_match = self._match_pattern(command, self.sequence_patterns)
        if sequence_match:
            first_part, second_part = sequence_match
            
            # Parse first part
            first_steps = self._parse_single_command(first_part.strip())
            steps.extend(first_steps)
            
            # Check for delays in second part
            delay_match = self._match_pattern(second_part, self.delay_patterns)
            if delay_match:
                delay_seconds = int(delay_match[0])
                steps.append({
                    'type': 'delay',
                    'seconds': delay_seconds,
                    'raw_command': f"wait {delay_seconds} seconds"
                })
                # Remove delay from second part
                second_part = re.sub(r'wait\s+\d+\s+seconds?', '', second_part).strip()
                second_part = re.sub(r'pause\s+for\s+\d+\s+seconds?', '', second_part).strip()
            
            # Parse second part if there's anything left
            if second_part:
                second_steps = self._parse_single_command(second_part)
                steps.extend(second_steps)
            
            return steps
        
        # Single command
        steps.extend(self._parse_single_command(command))
        return steps
    
    def _match_pattern(self, text: str, patterns: List[str]) -> Optional[Tuple]:
        """Match text against multiple patterns"""
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.groups()
        return None
    
    def _parse_single_command(self, command: str) -> List[Dict]:
        """Parse a single command into actionable steps"""
        command = command.strip()
        
        # File creation with content
        if self._is_file_creation_with_content(command):
            return self._parse_file_creation_command(command)
        
        # Application automation sequences
        if self._is_app_automation_sequence(command):
            return self._parse_app_automation_sequence(command)
        
        # System automation sequences
        if self._is_system_automation_sequence(command):
            return self._parse_system_automation_sequence(command)
        
        # Default single command
        return [{
            'type': 'simple',
            'command': command,
            'raw_command': command
        }]
    
    def _is_file_creation_with_content(self, command: str) -> bool:
        """Check if command is about creating files with specific content"""
        file_keywords = ['create', 'make', 'write', 'generate']
        content_keywords = ['about', 'containing', 'with content', 'text about']
        
        has_file_keyword = any(keyword in command.lower() for keyword in file_keywords)
        has_content_keyword = any(keyword in command.lower() for keyword in content_keywords)
        
        return has_file_keyword and has_content_keyword
    
    def _parse_file_creation_command(self, command: str) -> List[Dict]:
        """Parse file creation commands with content generation.
        Robustly extracts filename, optional location, and topic.
        """
        steps = []

        text = command.strip()
        lower = text.lower()

        # Extract a topic: prefer "write about X" then generic "about X"
        topic = None
        m_topic = re.search(r"write\s+about\s+(.+)", lower, re.IGNORECASE)
        if m_topic:
            topic = m_topic.group(1).strip()
        elif " about " in lower:
            topic = lower.split(" about ", 1)[1].strip()

        # Trim trailing phrases from topic (e.g., "and save as ...", locations, filename specs)
        if topic:
            topic = re.split(
                r"\b(?:and\s+save(?:\s+it)?\s+as|save\s+as|named|called|name\s+it|call\s+it|in\s+this\s+folder|on\s+this\s+folder|in\s+folder|on\s+folder|on\s+desktop|in\s+desktop|here|with\s+name|file\s+name|filename)\b",
                topic,
                1,
                flags=re.IGNORECASE,
            )[0].strip(" .,;")

        # Extract filename via multiple patterns with non-greedy + lookahead to stop at conjunctions/locations
        filename = None
        filename_patterns = [
            r"(?:named|called|name\s+it|call\s+it)\s+([\w\-. ]+?)(?=\s+(?:on|in|and|with|write|save)\b|$)",
            r"save\s+(?:it\s+)?as\s+([\w\-. ]+?)(?=\s+(?:on|in|and|with|write)\b|$)",
            r"create\s+(?:a\s+)?file\s+([\w\-. ]+?)(?=\s+(?:on|in|and|with|write|called|named)\b|$)",
        ]
        for pat in filename_patterns:
            m = re.search(pat, lower, re.IGNORECASE)
            if m:
                filename = m.group(1).strip().strip('\"\'')
                break

        # Clean filename of location or extra chatter and ensure extension
        if filename:
            filename = re.split(r"\b(?:in|on)\s+(?:this|the)\s+folder\b", filename, 1, flags=re.IGNORECASE)[0]
            filename = re.split(r"\b(?:on|in)\s+desktop\b", filename, 1, flags=re.IGNORECASE)[0]
            filename = re.split(r"\band\s+write\b", filename, 1, flags=re.IGNORECASE)[0]
            filename = filename.replace(" here", "").replace(" in here", "").strip()

        # Ensure txt extension by default
        if filename and not filename.lower().endswith((".txt", ".md", ".log", ".csv")):
            if "." not in filename:
                filename += ".txt"

        # Fallback filename from topic
        if not filename and topic:
            safe = re.sub(r"[^a-z0-9_\-]+", "_", topic.lower()).strip("_")
            filename = (safe[:30] or "untitled") + ".txt"

        # Detect location keywords
        location = None
        if any(kw in lower for kw in ["on desktop", "to desktop", "onto desktop", "in desktop"]):
            location = "desktop"

        if topic and filename:
            steps.append(
                {
                    "type": "file_creation_with_content",
                    "topic": topic,
                    "filename": filename,
                    "location": location,
                    "raw_command": command,
                }
            )

        return steps
    
    def _is_app_automation_sequence(self, command: str) -> bool:
        """Check if command involves app automation"""
        app_keywords = ['open', 'launch', 'start']
        automation_keywords = ['type', 'click', 'press', 'calculate', 'enter']
        
        has_app = any(keyword in command.lower() for keyword in app_keywords)
        has_automation = any(keyword in command.lower() for keyword in automation_keywords)
        
        return has_app and has_automation
    
    def _parse_app_automation_sequence(self, command: str) -> List[Dict]:
        """Parse application automation sequences"""
        steps = []
        
        # Common patterns
        if "calculator" in command.lower() and any(calc in command.lower() for calc in ["2+2", "calculate", "type"]):
            steps.extend([
                {'type': 'simple', 'command': 'launch calculator', 'raw_command': 'launch calculator'},
                {'type': 'delay', 'seconds': 2, 'raw_command': 'wait for app to load'},
                {'type': 'simple', 'command': 'type 2+2', 'raw_command': 'type 2+2'},
                {'type': 'simple', 'command': 'press enter', 'raw_command': 'press enter'}
            ])
        
        elif "notepad" in command.lower() and "type" in command.lower():
            # Extract text to type
            type_match = re.search(r'type\s+"([^"]+)"', command)
            if not type_match:
                type_match = re.search(r'type\s+(.+?)(?:\s+in|\s+into|$)', command)
            
            text_to_type = type_match.group(1) if type_match else "Hello, JARVIS!"
            
            steps.extend([
                {'type': 'simple', 'command': 'launch notepad', 'raw_command': 'launch notepad'},
                {'type': 'delay', 'seconds': 2, 'raw_command': 'wait for app to load'},
                {'type': 'simple', 'command': f'type {text_to_type}', 'raw_command': f'type {text_to_type}'}
            ])
        
        return steps
    
    def _is_system_automation_sequence(self, command: str) -> bool:
        """Check if command involves system automation"""
        system_keywords = ['screenshot', 'volume', 'brightness']
        automation_keywords = ['then', 'and', 'after']
        
        has_system = any(keyword in command.lower() for keyword in system_keywords)
        has_sequence = any(keyword in command.lower() for keyword in automation_keywords)
        
        return has_system and has_sequence
    
    def _parse_system_automation_sequence(self, command: str) -> List[Dict]:
        """Parse system automation sequences"""
        steps = []
        
        if "screenshot" in command.lower():
            steps.append({'type': 'simple', 'command': 'take screenshot', 'raw_command': 'take screenshot'})
        
        if "volume" in command.lower():
            volume_match = re.search(r'volume\s+(?:to\s+)?(\d+)', command)
            if volume_match:
                volume = volume_match.group(1)
                steps.append({'type': 'simple', 'command': f'set volume {volume}', 'raw_command': f'set volume {volume}'})
        
        return steps
    
    def execute_parsed_commands(self, steps: List[Dict], use_voice: bool = True) -> List[str]:
        """Execute a list of parsed command steps"""
        results = []
        
        for i, step in enumerate(steps):
            try:
                if step['type'] == 'delay':
                    self._execute_delay(step, use_voice)
                    results.append(f"Waited {step['seconds']} seconds")
                
                elif step['type'] == 'conditional':
                    result = self._execute_conditional(step, use_voice)
                    results.append(result)
                
                elif step['type'] == 'file_creation_with_content':
                    result = self._execute_file_creation_with_content(step, use_voice)
                    results.append(result)
                
                elif step['type'] == 'simple':
                    # Use existing JARVIS command processing
                    self.jarvis.process_command(step['command'], use_voice=False)
                    results.append(f"Executed: {step['command']}")
                
                # Small delay between commands for stability
                if i < len(steps) - 1:
                    time.sleep(0.5)
                    
            except Exception as e:
                error_msg = f"Error executing step '{step.get('raw_command', step)}': {e}"
                results.append(error_msg)
                continue
        
        return results
    
    def _execute_delay(self, step: Dict, use_voice: bool):
        """Execute a delay step"""
        seconds = step['seconds']
        if use_voice:
            self.jarvis.voice_engine.speak(f"Waiting {seconds} seconds")
        time.sleep(seconds)
    
    def _execute_conditional(self, step: Dict, use_voice: bool) -> str:
        """Execute a conditional step (simplified implementation)"""
        condition = step['condition']
        action = step['action']
        
        # Simple condition checking (can be expanded)
        if "file exists" in condition.lower():
            filename = condition.lower().replace("file exists", "").replace("if", "").strip()
            if self.jarvis.file_skill.file_exists(filename):
                self.jarvis.process_command(action, use_voice=False)
                return f"Condition met, executed: {action}"
            else:
                return f"Condition not met: {condition}"
        
        # Default: execute action anyway
        self.jarvis.process_command(action, use_voice=False)
        return f"Executed conditional action: {action}"
    
    def _execute_file_creation_with_content(self, step: Dict, use_voice: bool) -> str:
        """Execute file creation with AI-generated content"""
        topic = step['topic']
        filename = step['filename']
        location = step.get('location')

        # Generate content using available brain (prefer multi-model, then OpenRouter, then native)
        content_request = (
            f"Write a clear, well-structured article about {topic}. Include a short intro, 3-5 bullet points, and a concise conclusion."
        )

        try:
            if getattr(self.jarvis, 'use_multi_model', False) and getattr(self.jarvis, 'multi_brain', None):
                content = self.jarvis.multi_brain.process_command(content_request)
            elif getattr(self.jarvis, 'use_advanced_brain', False) and getattr(self.jarvis, 'openrouter_brain', None):
                content = self.jarvis.openrouter_brain.process_command(content_request)
            else:
                raise RuntimeError("advanced brain unavailable")
        except Exception:
            content = (
                f"# {topic.title()}\n\n"
                f"Created by JARVIS on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"Key points about {topic}:\n"
                f"- Overview paragraph explaining the topic in simple terms.\n"
                f"- 3–5 bullet points with important facts.\n"
                f"- Short conclusion summarizing why it matters.\n"
            )

        # Create the file in the right place
        if location == 'desktop':
            result = self.jarvis.file_skill.create_file_at_location(filename, content, location='desktop')
        else:
            result = self.jarvis.file_skill.create_file(filename, content)

        # Update last created file reference
        self.jarvis.last_created_file = filename

        return result
    
    def get_command_suggestions(self, partial_command: str) -> List[str]:
        """Get command suggestions based on partial input"""
        suggestions = []
        
        # Common compound command patterns
        compound_patterns = [
            "take screenshot then open calculator and type 2+2",
            "create a file about robotics and save it as robotics_info.txt",
            "open notepad then type 'Hello World' and save the file",
            "get system status then take screenshot",
            "search for weather then take screenshot of results",
            "create folder called 'projects' then create file inside it",
            "launch calculator, wait 2 seconds, then type 5*5",
            "if file exists data.txt then read it, otherwise create it"
        ]
        
        # Filter suggestions based on partial command
        partial_lower = partial_command.lower()
        for pattern in compound_patterns:
            if any(word in pattern.lower() for word in partial_lower.split() if len(word) > 2):
                suggestions.append(pattern)
        
        return suggestions[:5]  # Return top 5 suggestions
