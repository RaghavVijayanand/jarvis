"""Persistence tests use temporary storage and never execute system actions."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from skills.task_scheduler import TaskScheduler


class SchedulerPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tasks.json'
        timer_patch = patch('skills.task_scheduler.threading.Timer')
        self.timer = timer_patch.start()
        self.addCleanup(timer_patch.stop)
        self.timer.side_effect = lambda *a, **k: Mock()

    def make_scheduler(self, path=None):
        with patch.object(TaskScheduler, 'start_scheduler'):
            scheduler = TaskScheduler(Mock(), tasks_file=path or self.path)
        scheduler._execute_task = Mock(return_value='done')
        self.addCleanup(scheduler.stop_scheduler)
        return scheduler

    def test_restart_preserves_deadline_and_increments_ids(self):
        first = self.make_scheduler()
        first.schedule_reminder('hello', 'in 1 hour')
        task = first.active_tasks['task_0']
        task['next_run'] = (datetime.now() + timedelta(minutes=10)).isoformat()
        first.save_tasks()
        first.stop_scheduler()
        restored = self.make_scheduler()
        self.assertEqual(restored.active_tasks['task_0']['next_run'], task['next_run'])
        self.assertGreater(self.timer.call_args.args[0], 595)
        self.assertLessEqual(self.timer.call_args.args[0], 600)
        restored.schedule_reminder('second', 'in 2 hours')
        self.assertEqual(set(restored.active_tasks), {'task_0', 'task_1'})

    def test_completed_task_is_not_replayed(self):
        first = self.make_scheduler()
        first.schedule_reminder('hello', 'in 1 hour')
        task = first.active_tasks['task_0']
        first._execute_task_wrapper(task)
        first._execute_task_wrapper(task)
        first._execute_task.assert_called_once()
        self.timer.reset_mock()
        restored = self.make_scheduler()
        self.assertEqual(restored.active_tasks['task_0']['status'], 'completed')
        self.timer.assert_not_called()

    def test_overdue_and_interrupted_tasks_require_user_rescheduling(self):
        first = self.make_scheduler()
        first.schedule_reminder('late', 'in 1 hour')
        first.schedule_reminder('interrupted', 'in 2 hours')
        first.active_tasks['task_0']['next_run'] = (datetime.now() - timedelta(seconds=1)).isoformat()
        first.active_tasks['task_1']['status'] = 'running'
        first.save_tasks()
        first.stop_scheduler()
        self.timer.reset_mock()
        restored = self.make_scheduler()
        self.assertEqual(restored.active_tasks['task_0']['status'], 'missed')
        self.assertEqual(restored.active_tasks['task_1']['status'], 'interrupted')
        self.timer.assert_not_called()

    def test_scheduler_instances_do_not_clear_each_others_jobs(self):
        first = self.make_scheduler()
        second = self.make_scheduler(Path(self.temp.name) / 'other.json')
        first.schedule_reminder('one', 'daily')
        second.schedule_reminder('two', 'daily')
        first.cancel_task('task_0')
        first.stop_scheduler()
        self.assertEqual(len(second._schedule.jobs), 1)

    def test_recurring_deadline_matches_job_and_survives_restart(self):
        first = self.make_scheduler()
        first.schedule_reminder('daily', 'daily')
        task = first.active_tasks['task_0']
        self.assertEqual(task['next_run'], first._schedule.jobs[0].next_run.isoformat())
        first._execute_task_wrapper(task)
        self.assertEqual(task['status'], 'scheduled')
        self.assertEqual(task['next_run'], first._schedule.jobs[0].next_run.isoformat())
        first.stop_scheduler()
        restored = self.make_scheduler()
        self.assertEqual(restored._schedule.jobs[0].next_run.isoformat(), task['next_run'])

    def test_compound_duration_and_invalid_input(self):
        scheduler = self.make_scheduler()
        self.assertEqual(scheduler._parse_delay_seconds('in 1 hour 30 minutes'), 5400)
        self.assertEqual(scheduler._parse_delay_seconds('in 1 day and 2 seconds'), 86402)
        for value in ['in -2 hours', 'in 0 seconds', 'in 1.5 hours', 'in 5 minutes junk']:
            with self.subTest(value=value):
                self.assertIsNone(scheduler._parse_delay_seconds(value))
                self.assertIn('Unable to parse', scheduler.schedule_reminder('test', value))

    def test_atomic_write_failure_preserves_previous_file(self):
        scheduler = self.make_scheduler()
        scheduler.schedule_reminder('first', 'in 1 hour')
        before = self.path.read_bytes()
        with patch('skills.task_scheduler.os.replace', side_effect=PermissionError('read only')):
            response = scheduler.schedule_reminder('second', 'in 2 hours')
        self.assertIn('Error scheduling', response)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(scheduler.active_tasks), 1)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_corrupt_store_is_not_silently_overwritten(self):
        self.path.write_text('{broken', encoding='utf-8')
        scheduler = self.make_scheduler()            # reminders keep working this session
        self.assertEqual(scheduler.active_tasks, {})
        self.assertIn("couldn't be read", scheduler.storage_warning)
        kept = list(self.path.parent.glob('*.corrupt-*'))
        self.assertEqual([p.read_text() for p in kept], ['{broken'])
        scheduler.schedule_reminder('new', 'in 2 hours')     # a save must not touch the kept copy
        self.assertEqual(kept[0].read_text(), '{broken')

    def test_default_path_is_per_user_and_not_cwd(self):
        with patch.dict(os.environ, {'APPDATA': self.temp.name}), \
             patch.object(TaskScheduler, 'load_tasks'), \
             patch.object(TaskScheduler, 'start_scheduler'):
            scheduler = TaskScheduler(Mock())
        self.assertEqual(scheduler.tasks_file, Path(self.temp.name) / 'Jarvis' / 'scheduled_tasks.json')


class SchedulerThreadTests(unittest.TestCase):
    def test_real_timer_persists_completion_and_worker_stops(self):
        import threading
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.json'
            scheduler = TaskScheduler(Mock(), tasks_file=path)
            finished = threading.Event()
            scheduler._execute_task = Mock(side_effect=lambda task: finished.set() or 'done')
            try:
                self.assertIn('remind you', scheduler.schedule_reminder('test', 'in 1 second'))
                timer = scheduler._timers['task_0']
                self.assertTrue(finished.wait(5))
                timer.join(timeout=5)
                self.assertFalse(timer.is_alive())
                self.assertEqual(json.loads(path.read_text())['task_0']['status'], 'completed')
            finally:
                scheduler.stop_scheduler()
            self.assertFalse(scheduler.scheduler_thread.is_alive())

    def test_recurring_execution_during_stop_remains_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(TaskScheduler, 'start_scheduler'):
                scheduler = TaskScheduler(Mock(), tasks_file=Path(directory) / 'tasks.json')
            scheduler.schedule_reminder('daily', 'daily')
            scheduler._execute_task = Mock(side_effect=lambda task: scheduler.stop_scheduler() or 'done')
            scheduler._execute_task_wrapper(scheduler.active_tasks['task_0'])
            self.assertEqual(scheduler.active_tasks['task_0']['status'], 'scheduled')
            self.assertGreater(datetime.fromisoformat(scheduler.active_tasks['task_0']['next_run']), datetime.now())

    def test_cancel_during_execution_is_not_undone_by_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(TaskScheduler, 'start_scheduler'):
                scheduler = TaskScheduler(Mock(), tasks_file=Path(directory) / 'tasks.json')
            self.addCleanup(scheduler.stop_scheduler)
            scheduler.schedule_reminder('daily', 'daily')
            scheduler._execute_task = Mock(side_effect=lambda task: scheduler.cancel_task(task['id']))
            scheduler._execute_task_wrapper(scheduler.active_tasks['task_0'])
            self.assertEqual(scheduler.active_tasks['task_0']['status'], 'cancelled')
            self.assertEqual(scheduler._schedule.jobs, [])



if __name__ == '__main__':
    unittest.main()


class AlarmPersistenceTests(unittest.TestCase):
    """UC 8.1: alarms survive restarts; missed ones are reported once."""

    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tasks.json'

    def make(self):
        from skills.task_scheduler import TaskScheduler
        scheduler = TaskScheduler(Mock(), tasks_file=self.path)
        self.addCleanup(scheduler.stop_scheduler)
        return scheduler

    def test_alarm_is_one_shot_and_restored_after_restart(self):
        from datetime import datetime, timedelta
        first = self.make()
        at = datetime.now() + timedelta(hours=3)
        self.assertIn('Alarm set', first.schedule_alarm(at, 'gym'))
        first.stop_scheduler()
        second = self.make()
        task = next(iter(second.active_tasks.values()))
        self.assertEqual(task['status'], 'scheduled')
        self.assertEqual(task['type'], 'alarm')
        self.assertIn(task['id'], second._timers)       # one-shot timer, not a daily job
        self.assertEqual(second._schedule.get_jobs(task['id']), [])

    def test_missed_alarm_reported_once(self):
        from datetime import datetime, timedelta
        first = self.make()
        first.schedule_alarm(datetime.now() + timedelta(hours=1), 'late')
        first.stop_scheduler()
        data = json.loads(self.path.read_text(encoding='utf-8'))
        for task in data.values():
            task['next_run'] = (datetime.now() - timedelta(minutes=5)).isoformat()
            task['schedule'] = 'once ' + task['next_run']
        self.path.write_text(json.dumps(data), encoding='utf-8')
        second = self.make()
        self.assertEqual(len(second.missed_tasks()), 1)
        self.assertEqual(second.missed_tasks(), [])

    def test_alarm_notifies_through_jarvis(self):
        from datetime import datetime, timedelta
        scheduler = self.make()
        scheduler.schedule_alarm(datetime.now() + timedelta(hours=1), 'standup')
        task = next(iter(scheduler.active_tasks.values()))
        scheduler._execute_task_wrapper(task)
        scheduler.jarvis.notify.assert_called_once()
        self.assertIn('standup', scheduler.jarvis.notify.call_args.args[0])
        self.assertEqual(task['status'], 'completed')

    def test_natural_reminder_phrases(self):
        scheduler = self.make()
        self.assertIn('remind you to call mom in 20 minutes',
                      scheduler.process_schedule_command('remind me to call mom in 20 minutes'))
        self.assertIn('at ', scheduler.process_schedule_command('remind me at 5 pm to stretch'))
        self.assertIn('Timer set for 10 minutes', scheduler.process_schedule_command('set a timer for 10 mins'))
