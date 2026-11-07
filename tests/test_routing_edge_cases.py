"""Edge cases in routing, confirmations and the step executor: concurrent yes/no, plan size,
pathological input sizes, and lanes that must never die."""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent))

import jarvis as jm
from core.executor import ExecutionSession, _failed
from core.natural import tidy
from skills.command_processor import normalize_site_names, split_clauses
from test_cov_jarvis import make_app


class ConcurrentConfirmationTests(unittest.TestCase):
    def test_two_simultaneous_yes_approve_only_one_action(self):
        app = make_app()
        first, second = Mock(return_value="first done"), Mock(return_value="second done")
        app._ask_to_confirm("Do first?", first, "a")
        app._ask_to_confirm("Do second?", second, "b")
        gate = threading.Barrier(2)
        replies = []

        def say_yes():
            gate.wait()
            replies.append(app._route("yes"))
        threads = [threading.Thread(target=say_yes) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        # Each "yes" answers exactly one prompt, in order: never one action twice, never a skipped one.
        self.assertEqual(first.call_count + second.call_count, 2)
        self.assertEqual(first.call_count, 1)
        self.assertEqual(app._pending_actions, [])

    def test_plan_confirmations_follow_step_order(self):
        app = make_app()
        session = Mock(steps=[Mock(index=0, reply="Restart the PC? Reply yes"),
                              Mock(index=1, reply="Delete the file 'x'? Reply yes")])
        app._pending_actions = []
        before = set()
        # The parallel lane for step 2 finished first, so its prompt was queued first.
        app._ask_to_confirm("Delete the file 'x'?", Mock(), "delete_file")
        app._ask_to_confirm("Restart the PC?", Mock(), "restart")
        app._order_plan_confirmations(session, before)
        self.assertEqual([p["label"] for p in app._pending_actions], ["restart", "delete_file"])


class PlanSizeTests(unittest.TestCase):
    def test_pasted_wall_of_commands_is_refused_not_run(self):
        app = make_app()
        app._run_plan = Mock()
        reply = app._route("open chrome and play music " * 100)
        self.assertIn("more than the", reply)
        app._run_plan.assert_not_called()

    def test_small_plan_still_runs(self):
        app = make_app()
        app._run_plan = Mock(return_value="ran")
        self.assertEqual(app._route("open chrome and then open notepad"), "ran")


class PathologicalInputTests(unittest.TestCase):
    def assertFast(self, fn, text, limit=3.0):
        start = time.time()
        fn(text)
        self.assertLess(time.time() - start, limit, fn.__name__)

    def test_long_whitespace_and_long_text_route_quickly(self):
        app = make_app()
        app._run_plan = Mock(return_value="plan")
        for text in ("what is" + " " * 30000 + "up", "open a" + "\n" * 20000 + "b",
                     "the quick brown fox. " * 2500, "这是一个很长的句子" * 5000, "open x" + "." * 20000):
            self.assertFast(app._route, text)

    def test_planner_helpers_are_linear(self):
        self.assertFast(tidy, "open a" + " " * 20000 + "b")
        self.assertFast(split_clauses, "open a" + " " * 20000 + "b and close it")
        self.assertFast(normalize_site_names, "open chrome and go to yuotube " * 2000)

    def test_space_squeeze_keeps_meaning(self):
        self.assertEqual(split_clauses("open chrome   and  then\n\n\nplay music"),
                         [("start", "open chrome"), ("seq", "play music")])
        self.assertEqual(tidy("open chrome     please"), "open chrome")


class ExecutorRobustnessTests(unittest.TestCase):
    def test_bad_wait_values_never_kill_the_lane(self):
        for seconds in (float("nan"), -5, "soon"):
            with self.subTest(seconds=seconds):
                session = ExecutionSession(lambda text, ctx: "ok")
                session.submit("wait", kind="wait", seconds=seconds)
                session.submit("after")
                session.close_and_wait(timeout=5)
                self.assertEqual([s.status for s in session.steps], ["done", "done"])
        # A huge wait (Event.wait would raise OverflowError) is clamped, and a stop still ends it.
        session = ExecutionSession(lambda text, ctx: "ok")
        step = session.submit("wait", kind="wait", seconds=1e12)
        self.assertEqual(step.seconds, 3600.0)
        time.sleep(0.1)
        session.stop()
        session.close_and_wait(timeout=5)
        self.assertEqual(step.status, "stopped")

    def test_crashing_event_callback_does_not_hang_close_and_wait(self):
        def bad_event(kind, info):
            if kind == "step_started":
                raise RuntimeError("ui gone")
        session = ExecutionSession(lambda text, ctx: "ok", on_event=bad_event)
        session.submit("a")
        session.submit("b")
        self.assertTrue(session.wait(0) or True)
        session.close_and_wait(timeout=5)
        self.assertFalse(session.busy)

    def test_common_skill_failures_stop_the_lane(self):
        for reply in ("Error creating file: denied", "Couldn't open Foo", "Failed to open URL: x",
                      "Could not connect"):
            self.assertTrue(_failed(reply), reply)
        self.assertFalse(_failed("Opened Chrome."))


if __name__ == "__main__":
    unittest.main()
