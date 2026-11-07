"""Offline scheduler regression tests; no JARVIS, timers, or file writes."""
import unittest
from unittest.mock import Mock, patch

from skills.task_scheduler import TaskScheduler


class TaskSchedulerCancellationTests(unittest.TestCase):
    def setUp(self):
        # Exercise the real constructor without loading user data or starting threads.
        with patch.object(TaskScheduler, 'load_tasks'), patch.object(TaskScheduler, 'start_scheduler'):
            self.scheduler = TaskScheduler(Mock())
        self.scheduler.save_tasks = Mock()
        self.scheduler._execute_task = Mock(return_value='done')
        self.timer_patch = patch('skills.task_scheduler.threading.Timer')
        self.timer_factory = self.timer_patch.start()
        self.addCleanup(self.timer_patch.stop)
        self.schedule = self.scheduler._schedule
        self.clear_patch = patch.object(self.schedule, 'clear', wraps=self.schedule.clear)
        self.clear_patch.start()
        self.addCleanup(self.clear_patch.stop)

    def add_delayed_task(self):
        self.scheduler.schedule_task('test reminder', 'in 5 minutes', 'reminder')
        return self.scheduler.active_tasks['task_0'], self.timer_factory.return_value

    def test_delayed_timer_is_retained_and_started(self):
        task, timer = self.add_delayed_task()
        self.timer_factory.assert_called_once()
        delay, callback = self.timer_factory.call_args.args
        self.assertGreater(delay, 295)
        self.assertLessEqual(delay, 300)
        self.assertEqual(callback, self.scheduler._execute_task_wrapper)
        self.assertEqual(self.timer_factory.call_args.kwargs, {'args': [task]})
        self.assertIs(self.scheduler._timers['task_0'], timer)
        self.assertTrue(timer.daemon)
        timer.start.assert_called_once_with()

    def test_cancel_stops_timer_and_skips_already_queued_callback(self):
        task, timer = self.add_delayed_task()
        self.schedule.clear.reset_mock()
        response = self.scheduler.cancel_task('task_0')
        self.assertIn('Task cancelled', response)
        timer.cancel.assert_called_once_with()
        self.schedule.clear.assert_called_once_with('task_0')
        self.assertEqual(task['status'], 'cancelled')
        self.assertNotIn('task_0', self.scheduler._timers)
        self.scheduler.save_tasks.reset_mock()
        # Simulate a callback that was queued just before Timer.cancel().
        self.scheduler._execute_task_wrapper(task)
        self.scheduler._execute_task.assert_not_called()
        self.scheduler.save_tasks.assert_not_called()

    def test_stop_cancels_all_timers_and_skips_queued_callbacks(self):
        first = Mock()
        second = Mock()
        self.timer_factory.side_effect = [first, second]
        self.scheduler.schedule_task('first', 'in 5 minutes')
        self.scheduler.schedule_task('second', 'in 10 minutes')
        self.scheduler.stop_scheduler()
        first.cancel.assert_called_once_with()
        second.cancel.assert_called_once_with()
        self.assertFalse(self.scheduler.is_running)
        self.assertEqual(self.scheduler._timers, {})
        for task in self.scheduler.active_tasks.values():
            self.scheduler._execute_task_wrapper(task)
        self.scheduler._execute_task.assert_not_called()

    def test_pending_task_still_executes_and_releases_timer(self):
        task, timer = self.add_delayed_task()
        self.scheduler.save_tasks.reset_mock()
        self.scheduler._execute_task_wrapper(task)
        self.scheduler._execute_task.assert_called_once_with(task)
        self.assertEqual(task['last_result'], 'done')
        self.assertIn('last_run', task)
        self.assertNotIn('task_0', self.scheduler._timers)
        self.assertEqual(self.scheduler.save_tasks.call_count, 2)
        self.assertEqual(task['status'], 'completed')

    def test_cancel_recurring_task_without_timer(self):
        self.scheduler.schedule_task('daily reminder', 'daily', 'reminder')
        task = self.scheduler.active_tasks['task_0']
        self.assertEqual(len(self.schedule.jobs), 1)
        self.schedule.clear.reset_mock()
        self.scheduler.cancel_task('task_0')
        self.assertEqual(self.schedule.jobs, [])
        self.schedule.clear.assert_called_once_with('task_0')
        self.scheduler._execute_task_wrapper(task)
        self.scheduler._execute_task.assert_not_called()
        self.timer_factory.assert_not_called()

    def test_unknown_task_cancellation_is_harmless(self):
        self.assertEqual(self.scheduler.cancel_task('missing'), 'Task missing not found.')
        self.scheduler.save_tasks.assert_not_called()
        self.schedule.clear.assert_not_called()

    def test_stopped_scheduler_does_not_start_new_delayed_timer(self):
        self.scheduler.stop_scheduler()
        self.scheduler.schedule_task('late request', 'in 5 minutes')
        self.timer_factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
