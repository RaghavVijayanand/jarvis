"""
Task Scheduler Skill for JARVIS
Handles scheduled tasks, reminders, and automation routines
"""

import threading
import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import schedule

class TaskScheduler:
    def __init__(self, jarvis_instance):
        """Initialize task scheduler with reference to JARVIS"""
        self.jarvis = jarvis_instance
        self.tasks_file = "scheduled_tasks.json"
        self.active_tasks = {}
        self.task_counter = 0
        self.scheduler_thread = None
        self.is_running = False
        
        # Load existing tasks
        self.load_tasks()
        
        # Start scheduler thread
        self.start_scheduler()
    
    def schedule_task(self, task_description: str, when: str, task_type: str = "command") -> str:
        """Schedule a task for execution"""
        try:
            task_id = f"task_{self.task_counter}"
            self.task_counter += 1
            
            # Parse the 'when' parameter
            schedule_time = self._parse_schedule_time(when)
            if not schedule_time:
                return f"Unable to parse schedule time: {when}"
            
            # Create task object
            task = {
                'id': task_id,
                'description': task_description,
                'schedule': when,
                'type': task_type,
                'created': datetime.now().isoformat(),
                'next_run': schedule_time.isoformat() if schedule_time else None,
                'status': 'scheduled'
            }
            
            self.active_tasks[task_id] = task
            self.save_tasks()
            
            # Schedule with the schedule library
            self._add_to_scheduler(task)
            
            return f"Task scheduled: {task_description} at {when} (ID: {task_id})"
            
        except Exception as e:
            return f"Error scheduling task: {e}"
    
    def schedule_reminder(self, message: str, when: str) -> str:
        """Schedule a reminder"""
        task_description = f"reminder: {message}"
        return self.schedule_task(task_description, when, "reminder")
    
    def schedule_system_check(self, when: str = "daily") -> str:
        """Schedule periodic system health checks"""
        task_description = "system health check"
        return self.schedule_task(task_description, when, "system_check")
    
    def schedule_weather_update(self, when: str = "08:00") -> str:
        """Schedule daily weather updates"""
        task_description = "daily weather update"
        return self.schedule_task(task_description, when, "weather")
    
    def schedule_backup(self, when: str = "weekly") -> str:
        """Schedule backup operations"""
        task_description = "backup important files"
        return self.schedule_task(task_description, when, "backup")
    
    def list_scheduled_tasks(self) -> str:
        """List all scheduled tasks"""
        if not self.active_tasks:
            return "No scheduled tasks found."
        
        result = "Scheduled Tasks:\n\n"
        for task_id, task in self.active_tasks.items():
            status_icon = "⏰" if task['status'] == 'scheduled' else "✅" if task['status'] == 'completed' else "❌"
            result += f"{status_icon} {task['description']}\n"
            result += f"   ID: {task_id}\n"
            result += f"   Schedule: {task['schedule']}\n"
            result += f"   Next run: {task.get('next_run', 'Unknown')}\n"
            result += f"   Status: {task['status']}\n\n"
        
        return result.strip()
    
    def cancel_task(self, task_id: str) -> str:
        """Cancel a scheduled task"""
        if task_id not in self.active_tasks:
            return f"Task {task_id} not found."
        
        task = self.active_tasks[task_id]
        task['status'] = 'cancelled'
        
        # Remove from scheduler
        schedule.clear(task_id)
        
        self.save_tasks()
        return f"Task cancelled: {task['description']}"
    
    def execute_task_now(self, task_id: str) -> str:
        """Execute a scheduled task immediately"""
        if task_id not in self.active_tasks:
            return f"Task {task_id} not found."
        
        task = self.active_tasks[task_id]
        result = self._execute_task(task)
        return f"Task executed: {task['description']}. Result: {result}"
    
    def _parse_schedule_time(self, when: str) -> Optional[datetime]:
        """Parse various time formats into datetime"""
        when = when.lower().strip()
        now = datetime.now()
        
        try:
            # Handle relative times
            if "in" in when:
                if "minute" in when:
                    minutes = int(''.join(filter(str.isdigit, when)))
                    return now + timedelta(minutes=minutes)
                elif "hour" in when:
                    hours = int(''.join(filter(str.isdigit, when)))
                    return now + timedelta(hours=hours)
                elif "day" in when:
                    days = int(''.join(filter(str.isdigit, when)))
                    return now + timedelta(days=days)
            
            # Handle specific times
            elif ":" in when:  # HH:MM format
                time_part = when.replace("at", "").strip()
                hour, minute = map(int, time_part.split(":"))
                scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # If time has passed today, schedule for tomorrow
                if scheduled_time <= now:
                    scheduled_time += timedelta(days=1)
                
                return scheduled_time
            
            # Handle recurring patterns
            elif when in ["daily", "every day"]:
                return now + timedelta(days=1)
            elif when in ["weekly", "every week"]:
                return now + timedelta(weeks=1)
            elif when in ["hourly", "every hour"]:
                return now + timedelta(hours=1)
            
            # Handle specific days
            elif "monday" in when:
                days_ahead = 0 - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                return now + timedelta(days=days_ahead)
            
            # Add more patterns as needed
            
        except Exception:
            pass
        
        return None
    
    def _add_to_scheduler(self, task: Dict):
        """Add task to the schedule library"""
        when = task['schedule'].lower()
        task_id = task['id']
        
        if "daily" in when or "every day" in when:
            schedule.every().day.do(self._execute_task_wrapper, task).tag(task_id)
        elif "weekly" in when or "every week" in when:
            schedule.every().week.do(self._execute_task_wrapper, task).tag(task_id)
        elif "hourly" in when or "every hour" in when:
            schedule.every().hour.do(self._execute_task_wrapper, task).tag(task_id)
        elif ":" in when:  # Specific time
            time_part = when.replace("at", "").strip()
            schedule.every().day.at(time_part).do(self._execute_task_wrapper, task).tag(task_id)
        elif "in" in when:
            # For one-time tasks with delays
            delay_seconds = self._parse_delay_seconds(when)
            if delay_seconds:
                threading.Timer(delay_seconds, self._execute_task_wrapper, args=[task]).start()
    
    def _parse_delay_seconds(self, when: str) -> Optional[int]:
        """Parse delay string into seconds"""
        when = when.lower()
        try:
            if "minute" in when:
                minutes = int(''.join(filter(str.isdigit, when)))
                return minutes * 60
            elif "hour" in when:
                hours = int(''.join(filter(str.isdigit, when)))
                return hours * 3600
            elif "second" in when:
                seconds = int(''.join(filter(str.isdigit, when)))
                return seconds
        except:
            pass
        return None
    
    def _execute_task_wrapper(self, task: Dict):
        """Wrapper for task execution with error handling"""
        try:
            result = self._execute_task(task)
            task['last_run'] = datetime.now().isoformat()
            task['last_result'] = result
            self.save_tasks()
        except Exception as e:
            task['last_error'] = str(e)
            self.save_tasks()
    
    def _execute_task(self, task: Dict) -> str:
        """Execute a task based on its type"""
        task_type = task.get('type', 'command')
        description = task['description']
        
        try:
            if task_type == "reminder":
                message = description.replace("reminder:", "").strip()
                self.jarvis.voice_engine.speak(f"Reminder: {message}")
                return f"Reminder delivered: {message}"
            
            elif task_type == "system_check":
                status = self.jarvis.system_control.get_system_status()
                self.jarvis.voice_engine.speak("System health check completed")
                return "System health check completed"
            
            elif task_type == "weather":
                weather = self.jarvis.weather_skill.get_weather()
                self.jarvis.voice_engine.speak("Daily weather update ready")
                return "Weather update completed"
            
            elif task_type == "backup":
                # Simple backup implementation
                backup_result = self._perform_backup()
                return backup_result
            
            elif task_type == "command":
                # Execute as JARVIS command
                self.jarvis.process_command(description, use_voice=False)
                return f"Command executed: {description}"
            
            else:
                return f"Unknown task type: {task_type}"
                
        except Exception as e:
            return f"Task execution failed: {e}"
    
    def _perform_backup(self) -> str:
        """Perform basic file backup"""
        try:
            import shutil
            from pathlib import Path
            
            # Create backup directory
            backup_dir = Path("backups") / datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # Backup important files
            important_files = ["config.py", "jarvis.py", "*.txt"]
            backed_up = 0
            
            for pattern in important_files:
                if "*" in pattern:
                    for file_path in Path(".").glob(pattern):
                        if file_path.is_file():
                            shutil.copy2(file_path, backup_dir)
                            backed_up += 1
                else:
                    file_path = Path(pattern)
                    if file_path.exists():
                        shutil.copy2(file_path, backup_dir)
                        backed_up += 1
            
            return f"Backup completed: {backed_up} files backed up to {backup_dir}"
            
        except Exception as e:
            return f"Backup failed: {e}"
    
    def start_scheduler(self):
        """Start the background scheduler thread"""
        if not self.is_running:
            self.is_running = True
            self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
            self.scheduler_thread.start()
    
    def stop_scheduler(self):
        """Stop the scheduler"""
        self.is_running = False
        schedule.clear()
    
    def _scheduler_loop(self):
        """Main scheduler loop"""
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                print(f"Scheduler error: {e}")
                time.sleep(60)  # Wait longer on error
    
    def save_tasks(self):
        """Save tasks to file"""
        try:
            with open(self.tasks_file, 'w') as f:
                json.dump(self.active_tasks, f, indent=2)
        except Exception as e:
            print(f"Error saving tasks: {e}")
    
    def load_tasks(self):
        """Load tasks from file"""
        try:
            if os.path.exists(self.tasks_file):
                with open(self.tasks_file, 'r') as f:
                    self.active_tasks = json.load(f)
                    
                # Reactivate non-completed tasks
                for task in self.active_tasks.values():
                    if task.get('status') == 'scheduled':
                        self._add_to_scheduler(task)
                        
        except Exception as e:
            print(f"Error loading tasks: {e}")
            self.active_tasks = {}
    
    # Voice command handlers
    def process_schedule_command(self, command: str) -> str:
        """Process schedule-related voice commands"""
        command = command.lower()
        
        if "schedule" in command and "reminder" in command:
            # Extract reminder details
            if "to" in command:
                parts = command.split("to", 1)
                if len(parts) > 1:
                    reminder_text = parts[1].strip()
                    when = "in 5 minutes"  # Default
                    
                    if "in" in command:
                        when_match = command.split("in", 1)[-1].strip()
                        when = f"in {when_match}"
                    
                    return self.schedule_reminder(reminder_text, when)
        
        elif "schedule" in command and "task" in command:
            # Generic task scheduling
            task_desc = command.replace("schedule task", "").replace("schedule", "").strip()
            return self.schedule_task(task_desc, "in 1 hour")
        
        elif "list" in command and ("task" in command or "schedule" in command):
            return self.list_scheduled_tasks()
        
        elif "cancel" in command and "task" in command:
            # Extract task ID if provided
            words = command.split()
            for word in words:
                if word.startswith("task_"):
                    return self.cancel_task(word)
            
            return "Please specify task ID to cancel (e.g., 'cancel task task_1')"
        
        return "I couldn't understand the schedule command. Try 'schedule reminder to check email in 10 minutes' or 'list scheduled tasks'."
