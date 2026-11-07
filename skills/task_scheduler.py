"""
Task Scheduler Skill for JARVIS
Handles scheduled tasks, reminders, and automation routines
"""

import threading
import time
import json
import os
import re
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import schedule

class TaskScheduler:
    def __init__(self, jarvis_instance, tasks_file=None):
        """Use a stable per-user store; tests may supply a temporary store."""
        self.jarvis = jarvis_instance
        self.tasks_file = Path(tasks_file) if tasks_file else Path(
            os.getenv('APPDATA', str(Path.home()))) / 'Jarvis' / 'scheduled_tasks.json'
        self.tasks_file = self.tasks_file.absolute()
        self._schedule = schedule.Scheduler()
        self._wake = threading.Event()
        self.active_tasks = {}
        self.task_counter = 0
        self.scheduler_thread = None
        self.is_running = False
        self._timers = {}
        self._timer_lock = threading.RLock()
        self._stopped = False
        
        # Load existing tasks. A corrupt store must neither be overwritten nor switch reminders
        # off for the whole session: set it aside (content intact) and start with an empty one.
        self.storage_warning = ""
        try:
            self.load_tasks()
        except (ValueError, OSError, UnicodeDecodeError) as error:
            self.active_tasks, self._schedule = {}, schedule.Scheduler()
            self.storage_warning = self._quarantine_store(error)
        
        # Start scheduler thread
        self.start_scheduler()
    
    def schedule_task(self, task_description: str, when: str, task_type: str = "command") -> str:
        """Schedule a task for execution"""
        try:
            with self._timer_lock:
                if self._stopped:
                    return 'Scheduler is stopped; task was not scheduled.'
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
            
            with self._timer_lock:
                if self._stopped:
                    return 'Scheduler is stopped; task was not scheduled.'
                self.active_tasks[task_id] = task
                try:
                    self.save_tasks()
                    self._add_to_scheduler(task)
                except Exception:
                    self.active_tasks.pop(task_id, None)
                    try:
                        self.save_tasks()  # don't leave a task on disk that never got registered
                    except Exception:
                        pass
                    raise

            if task_type == "reminder":
                what = re.sub(r"^reminder:\s*", "", task_description)
                when_text = (schedule_time.strftime("%I:%M %p").lstrip("0") if when.startswith("once ")
                             else self._describe_schedule(when))
                if what == "Timer finished":
                    return f"Timer set for {when_text.removeprefix('in ')}. (ID: {task_id})"
                return f"Okay, I'll remind you to {what} {'at ' if when.startswith('once ') else ''}{when_text}. (ID: {task_id})"
            return f"Task scheduled: {task_description} at {when} (ID: {task_id})"
            
        except Exception as e:
            return f"Error scheduling task: {e}"
    
    def schedule_reminder(self, message: str, when: str) -> str:
        """Schedule a reminder"""
        task_description = f"reminder: {message}"
        return self.schedule_task(task_description, when, "reminder")
    
    def schedule_alarm(self, at: datetime, label: str = "") -> str:
        """One-shot alarm at an absolute time; persisted, so it survives restarts (UC 8.1)."""
        description = f"alarm: {label}" if label else "alarm"
        result = self.schedule_task(description, f"once {at.replace(microsecond=0).isoformat()}", "alarm")
        if result.startswith("Task scheduled"):
            when = at.strftime("%I:%M %p").lstrip("0")
            day = "today" if at.date() == datetime.now().date() else at.strftime("%A")
            return f"Alarm set for {when} {day}" + (f" — {label}" if label else "") + "."
        return result

    def missed_tasks(self) -> List[Dict]:
        """Tasks that came due while JARVIS was closed and haven't been reported yet.

        Recurring tasks stay scheduled; their missed occurrence is reported as a
        copy whose next_run is the time that was missed.
        """
        with self._timer_lock:
            missed = []
            for t in list(self.active_tasks.values()):
                if t.get('status') in ('missed', 'interrupted') and not t.get('reported'):
                    t['reported'] = True
                    missed.append(t)
                elif t.get('missed_at'):
                    missed.append(dict(t, next_run=t.pop('missed_at')))
            if missed:
                try:
                    self.save_tasks()
                except Exception:
                    pass
        return missed

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
        """List pending tasks (finished and cancelled ones are history, not schedule)."""
        with self._timer_lock:
            pending = [(task_id, dict(task)) for task_id, task in self.active_tasks.items()
                       if task.get('status') not in ('completed', 'cancelled', 'failed')]
        if not pending:
            return "No scheduled tasks found."

        result = "Scheduled Tasks:\n\n"
        for task_id, task in pending:
            status_icon = "⏰" if task['status'] == 'scheduled' else "✅" if task['status'] == 'completed' else "❌"
            result += f"{status_icon} {task['description']}\n"
            result += f"   ID: {task_id}\n"
            result += f"   Schedule: {task['schedule']}\n"
            result += f"   Next run: {task.get('next_run', 'Unknown')}\n"
            result += f"   Status: {task['status']}\n\n"
        
        return result.strip()
    
    def cancel_task(self, task_id: str) -> str:
        """Cancel a scheduled task"""
        with self._timer_lock:
            task = self.active_tasks.get(task_id)
            if task is None:
                return f"Task {task_id} not found."
            if task.get('status') in ('completed', 'cancelled', 'failed'):
                return f"Task {task_id} is already {task['status']}."
            task['status'] = 'cancelled'
            task.pop('missed_at', None)
            timer = self._timers.pop(task_id, None)
            if timer is not None:
                timer.cancel()
        
            # Remove recurring jobs as well as delayed timers.
            self._schedule.clear(task_id)
        
        self.save_tasks()
        return f"Task cancelled: {task['description']}"
    
    def execute_task_now(self, task_id: str) -> str:
        """Execute a scheduled task immediately"""
        if task_id not in self.active_tasks:
            return f"Task {task_id} not found."
        
        return self._execute_task_wrapper(self.active_tasks[task_id]) or 'Task is not pending.'
    
    def _parse_schedule_time(self, when: str) -> Optional[datetime]:
        """Parse various time formats into datetime"""
        when = when.lower().strip()
        now = datetime.now()
        
        try:
            # One-shot absolute time (alarms): "once 2026-09-23T07:00:00"
            if when.startswith('once '):
                at = datetime.fromisoformat(when[5:].strip())
                if at.tzinfo is not None:
                    at = at.astimezone().replace(tzinfo=None)  # store/compare local wall time
                return at
            # Handle relative times
            if when.startswith('in '):
                seconds = self._parse_delay_seconds(when)
                return now + timedelta(seconds=seconds) if seconds else None

            weekly = self._parse_weekday(when)
            interval = self._parse_interval(when)
            if weekly:
                day, clock = weekly
                if clock is None:  # legacy 'monday': same time of day, strictly in the future
                    days_ahead = (self._WEEKDAYS.index(day) - now.weekday()) % 7 or 7
                    return now + timedelta(days=days_ahead)
                target = now.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
                target += timedelta(days=(self._WEEKDAYS.index(day) - now.weekday()) % 7)
                return target if target > now else target + timedelta(days=7)
            if interval:
                return now + timedelta(**{interval[1]: interval[0]})

            # Handle specific times
            elif ":" in when:  # HH:MM format
                time_part = when.removeprefix("at ").strip()
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

        except Exception:
            pass

        return None

    _WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')

    def _parse_weekday(self, when: str):
        """'monday', 'every monday', 'every monday at 08:00' -> ('monday', (8, 0) | None)."""
        m = re.fullmatch(r'(?:every\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)'
                         r'(?:\s+at\s+(\d{1,2}):(\d{2}))?', when.lower().strip())
        if not m:
            return None
        if m.group(2) is None:
            return m.group(1), None
        hour, minute = int(m.group(2)), int(m.group(3))
        if hour > 23 or minute > 59:
            return None
        return m.group(1), (hour, minute)

    @staticmethod
    def _parse_interval(when: str):
        """'every 2 hours' -> (2, 'hours'); minutes, hours and days are supported."""
        m = re.fullmatch(r'every\s+(\d+)\s+(minute|hour|day)s?', when.lower().strip())
        if not m or int(m.group(1)) < 1:
            return None
        return int(m.group(1)), m.group(2) + 's'

    @staticmethod
    def _describe_schedule(when: str) -> str:
        """Human wording for a stored recurring schedule."""
        low = when.lower().strip()
        clock = re.fullmatch(r'(?:(?:every\s+)?(\w*day)\s+)?(?:at\s+)?(\d{1,2}):(\d{2})', low)
        if clock:
            text = datetime(2000, 1, 1, int(clock.group(2)) % 24, int(clock.group(3)) % 60).strftime('%I:%M %p').lstrip('0')
            day = clock.group(1)
            return f"every {day.title() if day and day != 'day' else 'day'} at {text}"
        return low
    def _add_to_scheduler(self, task: Dict):
        """Register the saved absolute deadline, never restart a relative delay."""
        with self._timer_lock:
            if self._stopped or task.get('status') != 'scheduled':
                return
            when = task['schedule'].lower().strip()
            task_id = task['id']
            deadline = datetime.fromisoformat(task['next_run'])
            self._schedule.clear(task_id)
            previous = self._timers.pop(task_id, None)
            if previous is not None:
                previous.cancel()
            job = None
            weekly = None if when.startswith(('in ', 'once ')) else self._parse_weekday(when)
            interval = None if when.startswith(('in ', 'once ')) else self._parse_interval(when)
            if when in ('daily', 'every day'):
                job = self._schedule.every().day
            elif when in ('weekly', 'every week'):
                job = self._schedule.every().week
            elif when in ('hourly', 'every hour'):
                job = self._schedule.every().hour
            elif weekly:
                job = getattr(self._schedule.every(), weekly[0])
                if weekly[1]:
                    job = job.at('%02d:%02d' % weekly[1])
            elif interval:
                job = getattr(self._schedule.every(interval[0]), interval[1])
            elif ':' in when and not when.startswith(('once ', 'in ')):
                hour, minute = map(int, when.removeprefix('at ').strip().split(':'))
                job = self._schedule.every().day.at(f'{hour:02d}:{minute:02d}')
            if job is not None:
                job.do(self._execute_task_wrapper, task).tag(task_id)
                job.next_run = deadline
            else:
                # Aware arithmetic: a naive wall-clock difference is an hour off
                # when a DST transition falls between now and the deadline.
                delay = max(0, (deadline.astimezone() - datetime.now().astimezone()).total_seconds())
                timer = threading.Timer(delay, self._execute_task_wrapper, args=[task])
                timer.daemon = True
                self._timers[task_id] = timer
                timer.start()

    def _parse_delay_seconds(self, when: str) -> Optional[int]:
        """Sum complete duration tokens; reject ambiguous/trailing input."""
        text = when.lower().strip()
        if not text.startswith('in '):
            return None
        text = text[3:].strip()
        pattern = r'(\d+)\s*(seconds?|minutes?|hours?|days?|weeks?)\b'
        matches = list(re.finditer(pattern, text))
        remainder = re.sub(pattern, '', text)
        if not matches or re.sub(r'\band\b|[,\s]', '', remainder):
            return None
        units = dict(second=1, minute=60, hour=3600, day=86400, week=604800)
        seconds = sum(int(m[1]) * units[m[2].rstrip('s')] for m in matches)
        return seconds if seconds > 0 else None
    
    def _execute_task_wrapper(self, task: Dict):
        """Persist admission before effects; interrupted work is not auto-replayed."""
        with self._timer_lock:
            if self._stopped or task.get('status') != 'scheduled':
                return
            timer = self._timers.pop(task['id'], None)
            if timer is not None:
                timer.cancel()
            task['status'] = 'running'
            try:
                self.save_tasks()
            except Exception:
                task['status'] = 'failed'
                # A failed task's recurring job would otherwise stay due and be
                # re-offered by the loop every second.
                self._schedule.clear(task['id'])
                raise
        try:
            result = self._execute_task(task)
            failed = isinstance(result, str) and result.startswith(('Task execution failed:', 'Backup failed:'))
        except Exception as error:
            result = f'Task execution failed: {error}'
            failed = True
        with self._timer_lock:
            task['last_run'] = datetime.now().isoformat()
            task['last_result'] = result
            if task['status'] != 'cancelled':
                jobs = self._schedule.get_jobs(task['id'])
                recurring = not task['schedule'].lower().strip().startswith(('in ', 'once '))
                if jobs:
                    jobs[0].last_run = datetime.now()
                    jobs[0]._schedule_next_run()
                    task['next_run'] = jobs[0].next_run.isoformat()
                    task['status'] = 'scheduled'
                elif recurring:
                    task['next_run'] = self._parse_schedule_time(task['schedule']).isoformat()
                    task['status'] = 'scheduled'
                else:
                    task['status'] = 'failed' if failed else 'completed'
                    task['next_run'] = None
            self.save_tasks()
        return result
    
    def _execute_task(self, task: Dict) -> str:
        """Execute a task based on its type"""
        task_type = task.get('type', 'command')
        description = task['description']
        
        try:
            if task_type in ("reminder", "alarm"):
                message = re.sub(r"^(reminder|alarm):\s*", "", description).strip()
                text = (f"⏰ Alarm{': ' + message if message else ''}" if task_type == "alarm"
                        else f"🔔 Reminder: {message}")
                self._notify(text)
                return f"{'Alarm' if task_type == 'alarm' else 'Reminder'} delivered: {message}"

            elif task_type == "system_check":
                status = self.jarvis.system_control.get_system_status()
                self._notify("System health check:\n" + status, speak_text="System health check completed.")
                return "System health check completed"

            elif task_type == "weather":
                weather = self.jarvis.weather_skill.get_weather()
                self._notify(weather)
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
    
    def _notify(self, text: str, speak_text: str = None) -> None:
        """Deliver to the GUI transcript/console and speak it if voice output is on (UC 8.6)."""
        notify = getattr(self.jarvis, "notify", None)
        if callable(notify):
            notify(text, speak=True, speak_text=speak_text)
            return
        print(text)
        voice = getattr(self.jarvis, "voice_engine", None)
        if voice is not None:
            voice.speak(speak_text or text)

    def _perform_backup(self) -> str:
        """Perform basic file backup"""
        """Copy JARVIS's own user data (settings, memory, schedules, history) to a dated folder."""
        try:
            import shutil
            user_dir = self.tasks_file.parent
            backup_dir = user_dir / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir.mkdir(parents=True, exist_ok=True)
            sources = [user_dir / ".env", self.tasks_file, user_dir / "memory" / "memory.json",
                       user_dir / "logs" / "conversation_history.json"]
            backed_up = 0
            for src in sources:
                if src.is_file():
                    shutil.copy2(src, backup_dir / src.name)
                    backed_up += 1
            # Keep the 10 most recent backups.
            backups = sorted((backup_dir.parent).iterdir())
            for old in backups[:-10]:
                shutil.rmtree(old, ignore_errors=True)
            return f"Backup completed: {backed_up} files backed up to {backup_dir}"
        except Exception as e:
            return f"Backup failed: {e}"

    def start_scheduler(self):
        """Start (or restart) only this instance's background worker."""
        with self._timer_lock:
            if self.is_running:
                return
            if self.scheduler_thread and self.scheduler_thread.is_alive():
                raise RuntimeError('Previous scheduler worker is still stopping.')
            restarting = self._stopped
            self._stopped = False
            self._wake.clear()
            if restarting:
                for task in self.active_tasks.values():
                    self._add_to_scheduler(task)
            self.is_running = True
            self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
            self.scheduler_thread.start()

    def stop_scheduler(self):
        """Cancel pending callbacks without affecting other scheduler instances."""
        with self._timer_lock:
            self._stopped = True
            self.is_running = False
            self._wake.set()
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            self._schedule.clear()
        if self.scheduler_thread and self.scheduler_thread is not threading.current_thread():
            self.scheduler_thread.join(timeout=2)

    def _scheduler_loop(self):
        while not self._wake.is_set():
            try:
                with self._timer_lock:
                    due = [job for job in self._schedule.jobs if job.should_run]
                for job in due:
                    if self._wake.is_set():
                        break
                    # The wrapper updates both the library job and persisted
                    # next_run together. Job.run() would reschedule a second time.
                    job.job_func()
            except Exception as error:
                print(f'Scheduler error: {error}')
            self._wake.wait(1)

    def save_tasks(self):
        """Atomic replacement; failures propagate instead of claiming success."""
        with self._timer_lock:
            path = Path(self.tasks_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                                 dir=path.parent, delete=False) as stream:
                    temporary = stream.name
                    json.dump(self.active_tasks, stream, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)

    def _quarantine_store(self, error) -> str:
        path = Path(self.tasks_file)
        backup = path.with_name(f"{path.stem}.corrupt-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
        try:
            os.replace(path, backup)
        except OSError:
            backup = None
        where = f" It was kept as {backup.name}." if backup else ""
        return f"Your saved reminders couldn't be read ({error}), so I started with an empty schedule.{where}"

    def load_tasks(self):
        """Restore deadlines; never replay overdue or interrupted actions."""
        path = Path(self.tasks_file)
        if not path.exists():
            return
        # Do not silently discard corrupt storage and overwrite it on the next save.
        # utf-8-sig: tolerate a BOM added by editing the file in Notepad.
        with path.open(encoding='utf-8-sig') as stream:
            tasks = json.load(stream)
        if not isinstance(tasks, dict):
            raise ValueError('Scheduled task storage must be an object.')
        now = datetime.now()
        for task_id, task in tasks.items():
            if not isinstance(task, dict) or task.get('id') != task_id:
                raise ValueError(f'Invalid scheduled task: {task_id}')
            match = re.fullmatch(r'task_(\d+)', task_id)
            if match:
                self.task_counter = max(self.task_counter, int(match[1]) + 1)
            recurring = not str(task.get('schedule', '')).lower().strip().startswith(('in ', 'once '))
            if task.get('status') == 'running':
                if recurring and self._parse_schedule_time(str(task.get('schedule', ''))):
                    # A recurring task keeps its schedule; the lost run is reported.
                    task['missed_at'] = task.get('next_run') or now.isoformat()
                    task['next_run'] = self._parse_schedule_time(task['schedule']).isoformat()
                    task['status'] = 'scheduled'
                else:
                    task['status'] = 'interrupted'
            elif task.get('status') == 'scheduled':
                try:
                    deadline = datetime.fromisoformat(task['next_run'])
                    if deadline.tzinfo is not None:
                        deadline = deadline.astimezone().replace(tzinfo=None)
                        task['next_run'] = deadline.isoformat()
                    upcoming = self._parse_schedule_time(task['schedule'])
                    if not upcoming:
                        raise ValueError('Unsupported schedule')
                    if deadline <= now and recurring:
                        # 'every day at 9' must not stop forever because JARVIS
                        # was closed at 9: report the miss, keep the schedule.
                        task['missed_at'] = task['next_run']
                        task['next_run'] = upcoming.isoformat()
                    elif deadline <= now:
                        task['status'] = 'missed'
                except (KeyError, TypeError, ValueError, OverflowError):
                    task['status'] = 'invalid'
        # Finished tasks are history, not state: keep a week of them, so the
        # file doesn't grow forever. Unreported misses are always kept.
        cutoff = now - timedelta(days=7)
        def _finished_long_ago(task):
            if task.get('status') not in ('completed', 'cancelled', 'failed', 'invalid', 'missed', 'interrupted'):
                return False
            if task.get('status') in ('missed', 'interrupted') and not task.get('reported'):
                return False
            try:
                stamp = datetime.fromisoformat(task.get('last_run') or task.get('next_run') or task.get('created'))
                if stamp.tzinfo is not None:
                    stamp = stamp.astimezone().replace(tzinfo=None)
                return stamp < cutoff
            except (TypeError, ValueError):
                return True
        tasks = {task_id: task for task_id, task in tasks.items() if not _finished_long_ago(task)}
        self.active_tasks = tasks
        self.save_tasks()
        for task in tasks.values():
            self._add_to_scheduler(task)
    
    # Voice command handlers
    def process_schedule_command(self, command: str) -> str:
        """Natural-language reminders, recurring tasks, listing and cancelling."""
        text = command.strip().rstrip(".!?")
        low = text.lower()
        # Speech recognition writes "5 p.m." and "in an hour".
        low = re.sub(r"\b([ap])\.\s?m\b\.?", r"\1m", low)
        low = re.sub(r"\b(in|for) (?:an?|one) (second|minute|hour|day|week)\b", r"\1 1 \2", low)
        if re.search(r"\b(list|show|what are)\b.*\b(tasks|reminders|alarms|schedule)", low):
            return self.list_scheduled_tasks()
        # "cancel task_3", or spoken "cancel task 3" / "cancel task number 3".
        m = re.search(r"\bcancel\b.*?\btask(?:_|\s+(?:number\s+|id\s+|#)?)(\d+)\b", low)
        if m:
            return self.cancel_task(f"task_{m.group(1)}")
        if re.search(r"\bcancel\b.*\b(reminder|alarm|task)s?\b", low):
            with self._timer_lock:
                pending = [t for t in self.active_tasks.values() if t.get('status') == 'scheduled']
            if len(pending) == 1:
                return self.cancel_task(pending[0]['id'])
            if not pending:
                return "There are no pending reminders or alarms."
            return "Which one? Say 'cancel task <ID>':\n" + self.list_scheduled_tasks()
        duration = r"(\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)(?:\s*(?:and\s*)?\d+\s*(?:seconds?|minutes?|hours?|days?))*)"
        norm = lambda d: re.sub(r"\bsecs?\b", "seconds", re.sub(r"\bmins?\b", "minutes", re.sub(r"\bhrs?\b", "hours", d)))
        m = (re.search(rf"remind me (?:to |about )?(.+?) in {duration}$", low) or
             re.search(rf"remind me in {duration} (?:to |about )?(.+)$", low))
        if m:
            groups = m.groups()
            message, when = (groups[0], groups[1]) if not groups[0][0].isdigit() else (groups[1], groups[0])
            return self.schedule_reminder(message.strip(), "in " + norm(when))
        m = re.search(rf"(?:set (?:a |an )?)?timer (?:for )?{duration}", low)
        if m:
            return self.schedule_reminder("Timer finished", "in " + norm(m.group(1)))
        # "remind me to take pills every day at 9": the message precedes 'every'.
        prefix = re.search(r"remind me (?:to |about )?(.+?)\s+every\b", low)
        prefix = prefix.group(1).strip() if prefix else ""
        m = re.search(r"every (day|morning|evening)(?: at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?\s*(?:to\s+)?(.*)", low)
        if m:
            hour = int(m.group(2) or (8 if m.group(1) != "evening" else 19))
            minute = int(m.group(3) or 0)
            if m.group(4) == "pm" and hour < 12:
                hour += 12
            elif m.group(4) == "am" and hour == 12:
                hour = 0
            if hour > 23 or minute > 59:
                return "That isn't a valid time of day."
            what = m.group(5).strip() or prefix or "daily briefing"
            kind = "weather" if "weather" in what else "reminder"
            return self.schedule_task(what if kind == "weather" else f"reminder: {what}", f"{hour:02d}:{minute:02d}", kind)
        m = re.search(r"every (monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                      r"(?: at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?\s*(?:to\s+)?(.*)", low)
        if m:
            hour, minute = int(m.group(2) or 8), int(m.group(3) or 0)
            if m.group(4) == "pm" and hour < 12:
                hour += 12
            elif m.group(4) == "am" and hour == 12:
                hour = 0
            if hour > 23 or minute > 59:
                return "That isn't a valid time of day."
            what = m.group(5).strip() or prefix or "weekly reminder"
            return self.schedule_task(f"reminder: {what}", f"every {m.group(1)} at {hour:02d}:{minute:02d}", "reminder")
        m = re.search(r"every (\d+) (minute|hour|day)s?\s*(?:to\s+)?(.*)", low)
        if m:
            what = m.group(3).strip() or prefix or "recurring reminder"
            return self.schedule_reminder(what, f"every {int(m.group(1))} {m.group(2)}s")
        m = re.search(r"every (minute|hour)\s*(?:to\s+)?(.*)", low)
        if m:
            return self.schedule_reminder(m.group(2).strip() or prefix or "recurring reminder", f"every 1 {m.group(1)}s")
        m = re.search(r"remind me (?:to |about )?(.+?) at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", low) or \
            re.search(r"remind me at (\d{1,2})(?::(\d{2}))?\s*(am|pm)? (?:to |about )?(.+)$", low)
        if m:
            g = m.groups()
            if g[0] and not g[0].isdigit():
                message, hour, minute, period = g
            else:
                hour, minute, period, message = g
            hour, minute = int(hour), int(minute or 0)
            if period == "pm" and hour < 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0
            if hour > 23 or minute > 59:
                return "That isn't a valid time of day."
            at = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
            if at <= datetime.now():
                at += timedelta(days=1)
            return self.schedule_task(f"reminder: {message.strip()}", f"once {at.isoformat()}", "reminder")
        if "schedule" in low and "backup" in low:
            return self.schedule_backup("weekly" if "week" in low else "daily")
        if "schedule" in low and ("system check" in low or "health" in low):
            return self.schedule_system_check("daily")
        return ("Try: 'remind me to call mom in 20 minutes', 'remind me at 5 pm to stretch', "
                "'set a timer for 10 minutes', 'every day at 8 am weather', or 'list reminders'.")
