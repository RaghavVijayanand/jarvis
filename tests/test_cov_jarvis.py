"""Coverage for jarvis.py, skills/command_processor.py and handlers/{__init__,base,chat,files}.py."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import jarvis as jm
from core.decision import DecisionEngine
from core.executor import ExecutionSession
from handlers import HandlerRegistry
from handlers.base import Handler
from handlers.chat import ChatHandler
from handlers.files import FilesHandler
from skills import command_processor as cp
from skills.command_processor import CommandProcessor, Plan, Step, split_clauses


def make_app(**overrides):
    """A JARVIS without __init__: rules routing, mocked skills, no brain."""
    app = jm.JARVIS.__new__(jm.JARVIS)
    app.is_sleeping = False
    app.is_running = True
    app.voice_engine = Mock()
    app.confirm_callback = app.notify_callback = app.exit_callback = None
    app.voice_output_enabled = False
    app._voice_mode = app._console_mode = False
    app._pending_actions = []
    app._last_decision = None
    app._stop_plan = threading.Event()
    app._input_lock = threading.Lock()
    app._active_session = None
    app.stream = None
    app._live_listener = None
    app.decision = DecisionEngine(engine="rules")
    app.command_processor = CommandProcessor(app)
    app.brain = None
    app.windows = Mock()
    app.app_control = Mock()
    app.screen_automation = None
    app.system_control = Mock()
    app.file_skill = None
    app.task_scheduler = None
    for k, v in overrides.items():
        setattr(app, k, v)
    return app


class QuietCase(unittest.TestCase):
    def setUp(self):
        p = patch.object(jm, "console")
        self.console = p.start()
        self.addCleanup(p.stop)
        q = patch.object(jm, "log")
        q.start()
        self.addCleanup(q.stop)


# ── split_clauses ────────────────────────────────────────────────────────────

class SplitClauseTests(unittest.TestCase):
    ONE_ACTION = [
        "search for salt and pepper recipes", "play tom and jerry", "open the terms and conditions pdf",
        "what's the difference between python and java", "remind me to buy eggs and milk at 5pm",
        "rock and roll music", "play rock and roll music", "search for black and white movies",
        "remind me to take the trash out and lock the door", "remind me to open the window",
        "search for how to open a jar", "type I want to go to the store", "google how to set the time on a casio",
        "remind me in 10 minutes to take the pills", "search for the best way to lock my phone",
        "help me write an email", "how do I open a file and read it", "play hide and seek",
        "take a screenshot and tell me what you see", "search for pizza, burgers and fries",
    ]

    def test_normal_sentences_stay_whole(self):
        for text in self.ONE_ACTION:
            with self.subTest(text=text):
                self.assertEqual(len(split_clauses(text)), 1, split_clauses(text))

    def test_real_compounds_split(self):
        cases = {
            "open chrome and go to youtube": ["open chrome", "go to youtube"],
            "open notepad, type hello, then press ctrl+s": ["open notepad", "type hello", "press ctrl+s"],
            "remind me to stretch in 20 minutes and open chrome": ["remind me to stretch in 20 minutes",
                                                                  "open chrome"],
            "remind me to buy eggs and then open chrome": ["remind me to buy eggs", "open chrome"],
            "open the alarm set the alarm for 10 am": ["open the alarm", "set the alarm for 10 am"],
            "set a timer for 5 minutes; open notepad": ["set a timer for 5 minutes", "open notepad"],
            "what time is it and open chrome": ["what time is it", "open chrome"],
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual([c for _, c in split_clauses(text)], want)

    def test_links_and_edges(self):
        got = split_clauses("open chrome simultaneously open notepad and also open spotify")
        self.assertEqual([l for l, _ in got], ["start", "par", "par"])
        self.assertEqual(split_clauses(""), [])
        self.assertEqual(split_clauses("and then"), [])
        self.assertEqual(split_clauses("and then open chrome"), [("seq", "open chrome")])
        self.assertEqual(split_clauses("please open chrome and"), [("start", "open chrome")])
        # "go to youtube" + "play x" re-join into one browser action
        self.assertEqual(split_clauses("go to youtube, then play lofi"), [("start", "go to youtube and play lofi")])
        self.assertEqual(split_clauses("what is the weather, and open chrome")[1], ("seq", "open chrome"))

    def test_keep_whole_screenshot_question(self):
        self.assertEqual(len(split_clauses("take a screenshot and describe it")), 1)


class CommandProcessorTests(unittest.TestCase):
    def test_plan_waits_lanes_and_classify(self):
        proc = CommandProcessor()
        plan = proc.plan("open chrome, wait 2 minutes, then open notepad simultaneously open spotify",
                         classify=lambda c: "APP")
        self.assertEqual([s.kind for s in plan.steps], ["command", "wait", "command", "command"])
        self.assertEqual(plan.steps[1].seconds, 120)
        self.assertEqual([s.lane for s in plan.steps], [0, 0, 0, 1])
        self.assertEqual(plan.steps[0].intent, "APP")
        text = plan.describe()
        self.assertIn("Lane 2 (runs in parallel)", text)
        self.assertIn("wait 120 seconds", text)
        self.assertIn("[APP]", text)
        capped = proc.plan("wait 900 minutes")
        self.assertEqual(capped.steps[0].seconds, 600)

    def test_plan_classify_errors_and_single_lane(self):
        plan = CommandProcessor().plan("open a and open b", classify=Mock(side_effect=RuntimeError))
        self.assertEqual([s.intent for s in plan.steps], ["", ""])
        self.assertNotIn("Lane", plan.describe())
        self.assertEqual(set(plan.lanes), {0})

    def test_split_steps_parse_complex_and_browser(self):
        self.assertEqual(CommandProcessor.split_steps("open a and open b"), ["open a", "open b"])
        parsed = CommandProcessor().parse_complex_command("open a then wait 3 seconds")
        self.assertEqual(parsed[1], {"type": "wait", "command": "wait 3 seconds", "seconds": 3.0, "lane": 0})
        self.assertEqual(CommandProcessor.is_browser_launch(" open the google chrome browser "), "chrome")
        self.assertIsNone(CommandProcessor.is_browser_launch("open notepad"))

    def test_execute_runs_lanes_and_reports_progress(self):
        proc = CommandProcessor()
        plan = proc.plan("open chrome, then go to youtube simultaneously open notepad")
        progress, events, seen = [], [], []

        def run(text, ctx):
            seen.append((text, ctx.get("browser")))
            return f"did {text}"
        with patch.object(cp.time, "sleep"):
            out = proc.execute(plan, run, should_stop=lambda: False,
                               on_progress=lambda i, n, t: progress.append((i, n)), on_event=lambda k, i: events.append(k))
        self.assertEqual(out, ["did open chrome", "did go to youtube", "did open notepad"])
        self.assertIn(("go to youtube", "chrome"), seen)
        self.assertEqual(len(progress), 3)
        self.assertIn("step_done", events)

    def test_execute_should_stop(self):
        proc = CommandProcessor()
        plan = proc.plan("wait 5 seconds then open x")
        start = time.time()
        out = proc.execute(plan, lambda t, c: "ok", should_stop=lambda: True, settle=lambda *a: None)
        self.assertLess(time.time() - start, 4)
        self.assertEqual(out[-1], "Stopped.")


# ── handlers ─────────────────────────────────────────────────────────────────

class HandlerTests(unittest.TestCase):
    def test_base_handler(self):
        h = Handler(Mock())
        with self.assertRaises(NotImplementedError):
            h.handle("x", "Y")
        self.assertIsNone(h.register_tools(Mock()))

    def test_chat_handler(self):
        h = ChatHandler(Mock())
        for hour, part in ((9, "Good morning"), (14, "Good afternoon"), (20, "Good evening")):
            with patch("handlers.chat.datetime") as dt:
                dt.now.return_value = SimpleNamespace(hour=hour)
                self.assertTrue(h.handle("Hello!", "GENERAL").startswith(part))
        self.assertIn(h.handle("thanks jarvis.", "GENERAL"), ["You're welcome.", "Always a pleasure.", "Happy to help."])
        self.assertIsNone(h.handle("help me write an email", "GENERAL"))

    def test_files_handler_delete_needs_confirmation(self):
        app = make_app(file_skill=Mock())
        h = FilesHandler(app)
        reply = h.handle("delete the file 'a.txt'.", "FILE")
        self.assertIn("Delete the file 'a.txt'?", reply)
        app.file_skill.delete_file.assert_not_called()
        app._pending_actions[0]["run"]()
        app.file_skill.delete_file.assert_called_once_with("a.txt")
        app.file_skill.handle_file_command.return_value = "listed"
        self.assertEqual(h.handle("list files", "FILE"), "listed")
        self.assertIsNone(FilesHandler(SimpleNamespace(file_skill=None)).handle("list files", "FILE"))

    def test_files_handler_tools(self):
        fs = Mock()
        tools = Mock()
        FilesHandler(SimpleNamespace(file_skill=fs)).register_tools(tools)
        funcs = {c.args[0]: c.args[2] for c in tools.add.call_args_list}
        funcs["list_files"]()
        fs.list_files.assert_called_with(None)
        funcs["list_files"]("desktop")
        fs.list_files.assert_called_with("desktop")
        funcs["create_file"]("a.txt")
        fs.create_file.assert_called_with("a.txt", "")
        delete = [c for c in tools.add.call_args_list if c.args[0] == "delete_file"][0]
        self.assertTrue(delete.kwargs["confirm"])
        funcs["create_archive"]("a.txt, sub/b.txt", "bundle")
        fs.create_archive.assert_called_with(["a.txt", "sub/b.txt"], "bundle")
        funcs["extract_archive"]("bundle.zip")
        fs.extract_archive.assert_called_with("bundle.zip")
        funcs["search_file_contents"]("budget", "notes", "txt,md")
        fs.search_file_contents.assert_called_with("budget", "notes", ["txt", "md"])
        funcs["search_file_contents"]("budget")
        fs.search_file_contents.assert_called_with("budget", None, None)
        funcs["find_duplicate_files"]("downloads")
        fs.find_duplicate_files.assert_called_with("downloads")
        funcs["disk_usage_by_folder"]()
        fs.disk_usage_by_folder.assert_called_with(None)

    def test_registry_dispatch_and_tool_errors(self):
        app = make_app()
        reg = HandlerRegistry(app)
        self.assertIsNone(reg.dispatch("x", "NOPE"))
        self.assertIsInstance(reg["ChatHandler"], ChatHandler)
        with patch.object(ChatHandler, "handle", side_effect=RuntimeError("bad")):
            self.assertIn("Something went wrong handling that (bad)", reg.dispatch("hi", "GENERAL"))
        tools = Mock()
        with patch.object(FilesHandler, "register_tools", side_effect=RuntimeError):
            reg.register_tools(tools)          # one handler failing doesn't stop the others
        self.assertTrue(tools.add.called)


# ── JARVIS routing ───────────────────────────────────────────────────────────

class LifecycleTests(QuietCase):
    def test_exit_sleep_wake(self):
        app = make_app()
        app.shutdown = Mock()
        self.assertIn("Goodbye", app.process_command("Goodbye jarvis!", use_voice=False))
        app.shutdown.assert_called_once()
        self.assertIn("sleep mode", app.process_command("go to sleep", use_voice=True))
        app.voice_engine.speak.assert_called()
        self.assertIn("sleeping", app.process_command("open chrome", use_voice=False))
        self.assertIn("awake", app.process_command("wake up jarvis", use_voice=False))
        self.assertFalse(app.is_sleeping)
        self.assertIsNone(app.process_command("   "))

    def test_exit_survives_shutdown_error(self):
        app = make_app()
        app.shutdown = Mock(side_effect=RuntimeError)
        self.assertIn("Goodbye", app.process_command("exit", use_voice=False))

    def test_lifecycle_words_inside_sentences(self):
        app = make_app()
        app.shutdown = Mock()
        app._handle_classified_command = Mock(return_value="answer")
        for text in ("how do I exit vim", "put the pc to sleep please", "why do I wake up early"):
            app.process_command(text, use_voice=False)
        app.shutdown.assert_not_called()
        self.assertFalse(app.is_sleeping)

    def test_process_command_never_raises_and_returns_str(self):
        app = make_app()
        app._route = Mock(side_effect=RuntimeError("kaboom"))
        self.assertIn("kaboom", app.process_command("hello there", use_voice=False))
        app._route = Mock(return_value=None)
        self.assertIsInstance(app.process_command("hmm", use_voice=False), str)
        app._route = Mock(return_value=42)
        self.assertEqual(app.process_command("hmm", use_voice=False), "42")

    def test_say_speech_failures(self):
        app = make_app()
        app.voice_engine.speak.side_effect = [TypeError, None]
        app._say("hi", True)
        self.assertEqual(app.voice_engine.speak.call_args.args, ("hi",))
        app.voice_engine.speak.side_effect = RuntimeError("no audio")
        app._say("hi", True)                     # no exception
        app._say(None, True)


class ConfirmationQueueTests(QuietCase):
    def setUp(self):
        super().setUp()
        self.app = make_app()
        self.ran = []

    def queue(self, name):
        return self.app._ask_to_confirm(f"Do {name}?", lambda: self.ran.append(name) or f"did {name}")

    def test_yes_no_and_next(self):
        self.assertIn("Reply yes", self.queue("a"))
        self.queue("b")
        self.assertEqual(self.app._pending_action["prompt"], "Do a?")
        self.assertEqual(self.app.process_command("Yes, please", use_voice=False), "did a Next: Do b? Reply yes or no.")
        self.assertIn("Cancelled", self.app.process_command("no thanks", use_voice=False))
        self.assertEqual(self.ran, ["a"])
        self.assertIsNone(self.app._pending_action)

    def test_next_prompt_gets_fresh_timer(self):
        self.queue("a")
        self.queue("b")
        for p in self.app._pending_actions:
            p["created"] -= 100
        self.app.process_command("yes", use_voice=False)
        time_left = jm._CONFIRM_TTL - (time.monotonic() - self.app._pending_actions[0]["created"])
        self.assertGreater(time_left, 100)

    def test_failing_action(self):
        self.app._ask_to_confirm("Boom?", Mock(side_effect=OSError("disk")))
        self.assertEqual(self.app.process_command("do it", use_voice=False), "That failed: disk")

    def test_expired_yes_does_not_reach_brain(self):
        self.app.brain = Mock(current_model="m")
        self.queue("a")
        self.app._pending_actions[0]["created"] -= 500
        reply = self.app.process_command("yes", use_voice=False)
        self.assertIn("expired", reply)
        self.assertEqual(self.ran, [])
        self.app.brain.process_command.assert_not_called()

    def test_yes_with_nothing_pending(self):
        self.assertIn("nothing waiting", self.app.process_command("yes", use_voice=False))
        self.app.brain = Mock(current_model="m")
        self.app.brain.process_command.return_value = "Sure thing."
        self.assertEqual(self.app.process_command("yes", use_voice=False), "Sure thing.")

    def test_unrelated_request_cancels_queue(self):
        self.queue("a")
        self.app._handle_classified_command = Mock(return_value="ok")
        self.app.process_command("what time is it", use_voice=False)
        self.assertEqual(self.app._pending_actions, [])

    def test_queue_attribute_missing(self):
        del self.app._pending_actions
        self.assertIsNone(self.app._pending_action)
        self.queue("a")
        self.assertEqual(len(self.app._pending_actions), 1)
        del self.app._pending_actions
        self.app._handle_classified_command = Mock(return_value="ok")
        self.assertEqual(self.app._route("hello"), "ok")


class FileRoutingTests(QuietCase):
    def test_delete_confirm_and_route(self):
        app = make_app(file_skill=Mock())
        app.file_skill.route_command.return_value = None
        app.file_skill.delete_file.return_value = "deleted"
        self.assertIn("Delete the file 'a.txt'?", app.process_command('delete the file "a.txt".', use_voice=False))
        app.file_skill.route_command.assert_not_called()
        self.assertEqual(app.process_command("yes", use_voice=False), "deleted")
        app.file_skill.route_command.return_value = "File listing"
        self.assertEqual(app.process_command("list files", use_voice=False), "File listing")

    def test_delete_inside_plan_still_asks(self):
        app = make_app(file_skill=Mock())
        app.file_skill.route_command.return_value = None
        app.file_skill.handle_file_command.return_value = None
        app.app_control.launch_app_by_name.return_value = "Opened notepad."
        with patch.object(jm.time, "sleep"):
            reply = app.process_command("delete file a.txt and then open notepad", use_voice=False)
        self.assertIn("Ran 2 steps", reply)
        app.file_skill.delete_file.assert_not_called()
        self.assertIn("Delete the file 'a.txt'?", reply)
        app.process_command("yes", use_voice=False)
        app.file_skill.delete_file.assert_called_once_with("a.txt")


class MetaCommandTests(QuietCase):
    def test_help_and_normal_sentences(self):
        app = make_app()
        self.assertEqual(app.process_command("Help", use_voice=False), jm.HELP_TEXT)
        app.brain = Mock(current_model="m")
        app.brain.process_command.return_value = "Dear…"
        self.assertEqual(app.process_command("help me write an email", use_voice=False), "Dear…")
        self.assertEqual(app.process_command("what can you do for my resume", use_voice=False), "Dear…")

    def test_model_commands(self):
        app = make_app()
        for cmd in ("list models", "switch model x", "benchmark models", "model stats", "refresh models"):
            self.assertEqual(app._meta_command(cmd, cmd), "The AI brain is offline.")
        self.assertIsNone(app._meta_command("clear history", "clear history"))
        b = app.brain = Mock()
        b.list_available_models.return_value = "L"
        b.switch_model.return_value = "S"
        b.benchmark_models.return_value = "B"
        b.get_usage_stats.return_value = "U"
        b.clear_history.return_value = "C"
        b.refresh_catalog.return_value = "R"
        self.assertEqual(app._meta_command("", "list models"), "L")
        self.assertEqual(app._meta_command("", "change model to gemini-flash"), "S")
        b.switch_model.assert_called_with("gemini-flash")
        self.assertEqual(app._meta_command("", "use gpt4 model"), "S")
        b.switch_model.assert_called_with("gpt4")
        self.assertEqual(app._meta_command("", "benchmark"), "B")
        self.assertEqual(app._meta_command("", "usage stats"), "U")
        self.assertEqual(app._meta_command("", "clear conversation"), "C")
        self.assertEqual(app._meta_command("", "scan models"), "R")
        self.assertIn("threshold", app._meta_command("", "decision status"))

    def test_stop_meta(self):
        app = make_app()
        self.assertIsNone(app._meta_command("stop", "stop"))
        app.screen_automation = Mock(is_running=True)
        self.assertEqual(app._meta_command("stop", "stop"), "Stopped screen automation.")
        app.screen_automation.stop_automation.assert_called_once()
        app.screen_automation = None
        app._active_session = Mock(busy=True)
        app._active_session.stop.return_value = {"running": 1, "queued": 2}
        self.assertEqual(app._meta_command("abort", "abort"), "Stopped 1 running step and 2 queued steps.")
        app._active_session.stop.assert_called_once()


class ClassifiedRoutingTests(QuietCase):
    def test_brain_fallback_and_record(self):
        app = make_app()
        self.assertIn("without an AI model", app.process_command("explain black holes", use_voice=False))
        app.brain = Mock(current_model="m")
        app.brain.process_command.side_effect = RuntimeError("down")
        self.assertIn("The AI model failed: down", app.process_command("explain black holes", use_voice=False))
        app.brain.record_exchange.side_effect = RuntimeError
        self.assertTrue(app.process_command("hello", use_voice=False).startswith("Good"))
        app.brain.record_exchange.assert_called()

    def test_exit_intent_and_set_alarm(self):
        app = make_app()
        app.shutdown = Mock()
        self.assertIn("Goodbye", app._handle_classified_command("bye", "EXIT", use_voice=False))
        sched = Mock()
        sched.set_alarm.return_value = "alarm"
        app._handlers = Mock()
        app._handlers.__getitem__ = Mock(return_value=sched)
        self.assertEqual(app._set_alarm("set alarm 7"), "alarm")

    def test_handlers_property_and_tools(self):
        app = make_app()
        self.assertIs(app.handlers, app.handlers)
        app.tools = Mock()
        app._register_tools()
        self.assertTrue(app.tools.add.called)

    def test_intent_print_tolerates_odd_decision(self):
        app = make_app()
        app.decision = Mock()
        app.decision.decide.return_value = SimpleNamespace(intent="chat", source="x", confidence=None)
        app._handle_classified_command = Mock(return_value="ok")
        self.assertEqual(app._route("something"), "ok")


class PlanTests(QuietCase):
    def test_run_plan_format_and_browser_context(self):
        app = make_app()
        app.app_control.launch_app_by_name.side_effect = lambda text, browser=None: f"Opened {text}|{browser}"
        app.windows.wait_for_playback.return_value = False
        with patch.object(jm.time, "sleep") as sleep:
            reply = app.process_command("open chrome, then go to youtube and play lofi simultaneously open notepad",
                                        use_voice=False)
        self.assertTrue(reply.startswith("Ran 3 steps in 2 parallel lanes:"), reply)
        self.assertIn("[2] open notepad", reply)
        self.assertIn("go to youtube and play lofi → Opened go to youtube and play lofi|chrome", reply)
        self.assertTrue(sleep.called)

    def test_format_session_single_lane(self):
        steps = [SimpleNamespace(lane=0, index=0, text="a", reply="", status="skipped"),
                 SimpleNamespace(lane=0, index=1, text="b", reply="ok", status="done")]
        self.assertEqual(jm.JARVIS.format_session(SimpleNamespace(steps=steps)), "Ran 2 steps:\n1. a → skipped\n2. b → ok")

    def test_settle_and_media_wait(self):
        app = make_app()
        ctx = {}
        with patch.object(jm.time, "sleep") as sleep:
            app._settle("open edge", "Opened edge", ctx)
            self.assertEqual(ctx["browser"], "edge")
            app._settle("play x", "Playing: x", ctx)
            self.assertIn("media_started", ctx)
            app._settle("open notepad", "Opened notepad", {})
            self.assertEqual(sleep.call_count, 2)
            app._classify_command_intent = Mock(return_value="MEDIA")
            app.windows.wait_for_playback.return_value = False
            app._handle_classified_command = Mock(return_value=None)
            app._fallback_brain = Mock(return_value="brain")
            self.assertEqual(app._run_step("next video", ctx), "brain")
            self.assertNotIn("media_started", ctx)
            app._input_lock = None
            app._classify_command_intent = Mock(return_value="GENERAL")
            app._handle_classified_command = Mock(return_value="ok")
            self.assertEqual(app._run_step("hi", {}), "ok")

    def test_stop_current_task_and_session_reset(self):
        app = make_app()
        app._input_lock = None
        app.screen_automation = Mock()
        app.screen_automation.stop_automation.side_effect = RuntimeError
        app.stop_current_task()
        self.assertTrue(app._stop_plan.is_set())
        session = app.new_execution_session()
        self.assertIsInstance(session, ExecutionSession)
        self.assertFalse(app._stop_plan.is_set())
        self.assertIsNotNone(app._input_lock)
        app.stop_current_task()
        self.assertTrue(session.stopped.is_set())
        session.close_and_wait()


class LLMPlanFallbackTests(QuietCase):
    """_llm_plan_fallback: the LLM-driven fallback for compound requests the regex
    splitter (skills/command_processor.py) doesn't manage to split."""

    def test_no_brain_returns_none(self):
        app = make_app()
        app.brain = None
        self.assertIsNone(app._llm_plan_fallback("do this and that"))

    def test_brain_without_current_model_returns_none(self):
        app = make_app()
        app.brain = Mock(current_model=None)
        self.assertIsNone(app._llm_plan_fallback("do this and that"))

    def test_not_flagged_multi_step_returns_none(self):
        app = make_app()
        app.brain = Mock(current_model="m")
        app.decision = Mock()
        app.decision.decide.return_value = SimpleNamespace(intent="chat", is_multi_step=False)
        self.assertIsNone(app._llm_plan_fallback("just one thing"))
        app.brain.plan_steps.assert_not_called()

    def test_plan_steps_single_item_returns_none(self):
        app = make_app()
        app.brain = Mock(current_model="m")
        app.brain.plan_steps.return_value = ["do the whole thing"]
        app.decision = Mock()
        app.decision.decide.return_value = SimpleNamespace(intent="chat", is_multi_step=True)
        self.assertIsNone(app._llm_plan_fallback("do the whole thing"))

    def test_plan_steps_error_returns_none(self):
        app = make_app()
        app.brain = Mock(current_model="m")
        app.brain.plan_steps.side_effect = RuntimeError("model down")
        app.decision = Mock()
        app.decision.decide.return_value = SimpleNamespace(intent="chat", is_multi_step=True)
        self.assertIsNone(app._llm_plan_fallback("do this and that"))

    def test_multi_step_plan_builds_plan_object(self):
        app = make_app()
        app.brain = Mock(current_model="m")
        app.brain.plan_steps.return_value = ["open chrome", "  ", "go to youtube"]
        app.decision = Mock()
        app.decision.decide.return_value = SimpleNamespace(intent="chat", is_multi_step=True)
        plan = app._llm_plan_fallback("open chrome and go to youtube")
        self.assertEqual(plan.original, "open chrome and go to youtube")
        self.assertEqual([s.text for s in plan.steps], ["open chrome", "go to youtube"])
        self.assertTrue(all(s.lane == 0 for s in plan.steps))

    def test_route_uses_llm_fallback_when_regex_split_finds_nothing(self):
        app = make_app()
        app.brain = Mock(current_model="m")
        app.brain.plan_steps.return_value = ["open chrome", "go to youtube"]
        app.decision = Mock()
        app.decision.decide.return_value = SimpleNamespace(intent="chat", is_multi_step=True, source="rules",
                                                            confidence=0.9)
        app.file_skill = None
        app._run_plan = Mock(return_value="ran the plan")
        with patch.object(cp.CommandProcessor, "plan", return_value=Plan("do a compound thing")):
            result = app._route("do a compound thing")
        self.assertEqual(result, "ran the plan")
        app._run_plan.assert_called_once()
        built_plan = app._run_plan.call_args.args[0]
        self.assertEqual([s.text for s in built_plan.steps], ["open chrome", "go to youtube"])


class InteractionTests(QuietCase):
    def test_voice_sessions_mark_their_steps_as_voice(self):
        app = make_app()
        seen = []
        app._run_step = lambda text, ctx: seen.append(getattr(jm._ORIGIN, "voice", False)) or "ok"
        for voice in (True, False):
            session = app.new_execution_session(voice=voice)
            session.submit("lock my pc")
            session.close_and_wait(timeout=5)
        self.assertEqual(seen, [True, False])
        self.assertFalse(getattr(jm._ORIGIN, "voice", False))

    def test_confirm_paths(self):
        app = make_app()
        app.stream = Mock()
        app.stream.ask_yes_no.return_value = True
        app.confirm_callback = Mock(return_value=False)
        # A typed command while live voice is on still uses the dialog…
        self.assertFalse(app.confirm("ok?"))
        app.stream.ask_yes_no.assert_not_called()
        # …while a command that came from live voice is confirmed out loud.
        jm._ORIGIN.voice = True
        try:
            self.assertTrue(app.confirm("ok?"))
            app.stream.ask_yes_no.side_effect = RuntimeError
            self.assertFalse(app.confirm("ok?"))
        finally:
            jm._ORIGIN.voice = False
        app.stream = None
        app.confirm_callback = lambda q: 1
        self.assertTrue(app.confirm("ok?"))
        app.confirm_callback = Mock(side_effect=RuntimeError)
        self.assertFalse(app.confirm("ok?"))
        app.confirm_callback = None
        app._voice_mode = True
        app.voice_engine.listen_for_command.return_value = "yeah go on"
        self.assertTrue(app.confirm("ok?"))
        app.voice_engine.listen_for_command.side_effect = RuntimeError
        self.assertFalse(app.confirm("ok?"))
        app._voice_mode = False
        app._console_mode = True
        with patch.object(jm.sys, "stdin") as stdin, patch("builtins.input", return_value=" Y "):
            stdin.isatty.return_value = True
            self.assertTrue(app.confirm("ok?"))
            with patch("builtins.input", side_effect=EOFError):
                self.assertFalse(app.confirm("ok?"))
        app._console_mode = False
        self.assertFalse(app.confirm("ok?"))

    def test_notify(self):
        app = make_app()
        app.notify("hello", speak=True)
        app.voice_engine.speak.assert_called_with("hello", summarize=True)
        got = []
        app.notify_callback = got.append
        app.voice_engine.speak.reset_mock()
        app.notify("quiet", speak=True)
        app.voice_engine.speak.assert_not_called()
        app.voice_output_enabled = True
        app.voice_engine.speak.side_effect = RuntimeError
        app.notify_callback = Mock(side_effect=RuntimeError)
        app.notify("x", speak=True, speak_text="y")
        self.assertEqual(got, ["quiet"])

    def test_misc_helpers(self):
        app = make_app()
        with patch.object(jm, "datetime") as dt:
            for hour, word in ((8, "morning"), (13, "afternoon"), (22, "evening")):
                dt.now.return_value = SimpleNamespace(hour=hour)
                self.assertEqual(app.get_time_greeting(), word)
        app.display_startup_banner()
        with patch("signal.signal") as sig:
            app.install_signal_handlers()
            self.assertEqual(sig.call_count, 2)
        app.shutdown = Mock()
        with self.assertRaises(SystemExit):
            app.signal_handler(2, None)
        app.shutdown.assert_called_once()
        t = threading.Thread(target=app.install_signal_handlers)
        with patch("signal.signal") as sig:
            t.start()
            t.join()
            sig.assert_not_called()

    def test_null_voice(self):
        v = jm._NullVoice()
        self.assertIsNone(v.speak("x"))
        self.assertIsNone(v.listen_for_command(timeout=1))
        self.assertFalse(v.listen_for_wake_word())
        self.assertIsNone(v.setup_tts())
        self.assertFalse(v.sr_available)


class ShutdownTests(QuietCase):
    def test_shutdown_stops_everything(self):
        app = make_app()
        app.task_scheduler = Mock()
        listener = app._live_listener = Mock()
        cb = app.exit_callback = Mock()
        app.screen_automation = Mock()
        app.shutdown()
        self.assertFalse(app.is_running)
        app.task_scheduler.stop_scheduler.assert_called_once()
        listener.stop.assert_called_once()
        cb.assert_called_once()
        app.screen_automation.stop_automation.assert_called()
        self.assertIsNone(app._live_listener)

    def test_shutdown_tolerates_failures(self):
        app = make_app()
        app.task_scheduler = Mock()
        app.task_scheduler.stop_scheduler.side_effect = RuntimeError
        app._live_listener = Mock()
        app._live_listener.stop.side_effect = RuntimeError
        app.exit_callback = Mock(side_effect=RuntimeError)
        app.stop_current_task = Mock(side_effect=RuntimeError)
        app.shutdown()
        app.shutdown()                       # twice is harmless
        self.assertFalse(app.is_running)


class TextModeTests(QuietCase):
    def run_inputs(self, inputs):
        app = make_app()
        app.process_command = Mock(return_value="ok")
        with patch("builtins.input", side_effect=inputs):
            app.run_text_mode()
        return app

    def test_loop_commands(self):
        app = self.run_inputs(["", "voice on", "hi", "voice off", "hey", "exit"])
        self.assertEqual(app.process_command.call_args_list[0].kwargs["use_voice"], True)
        self.assertEqual(app.process_command.call_args_list[1].kwargs["use_voice"], False)
        self.assertTrue(app._console_mode)

    def test_eof_and_interrupt_and_errors(self):
        self.run_inputs([EOFError])
        self.run_inputs([KeyboardInterrupt])
        app = make_app()
        app.process_command = Mock(side_effect=[RuntimeError("x"), "ok"])
        with patch("builtins.input", side_effect=["a", "b", EOFError]):
            app.run_text_mode()
        self.assertEqual(app.process_command.call_count, 2)

    def test_loop_ends_when_shut_down(self):
        app = make_app()
        app.process_command = Mock(side_effect=lambda *a, **k: setattr(app, "is_running", False))
        with patch("builtins.input", side_effect=["bye jarvis", "never read"]):
            app.run_text_mode_with_voice()
        self.assertEqual(app.process_command.call_count, 1)


class StartTests(QuietCase):
    def test_start_modes(self):
        app = make_app()
        app.run_text_mode = Mock()
        app.run_voice_mode = Mock()
        app.run_text_mode_with_voice = Mock()
        app.task_scheduler = Mock()
        app.task_scheduler.missed_tasks.return_value = [
            {"next_run": "2026-01-01T10:00:00", "description": "reminder: stretch"}, {"type": "alarm"}]
        app.notify = Mock()
        app.start("text")
        app.run_text_mode.assert_called_once()
        self.assertIn("stretch (2026-01-01 10:00)", app.notify.call_args_list[0].args[0])
        app.voice_engine.sr_available = True
        app.start("voice")
        app.run_voice_mode.assert_called_once()
        app.voice_engine.sr_available = False
        app.brain = Mock()
        app.brain.get_personality_response.side_effect = RuntimeError
        app.task_scheduler.missed_tasks.side_effect = RuntimeError
        app.start("voice")
        app.run_text_mode_with_voice.assert_called_once()
        app.voice_engine.speak.assert_called_with("JARVIS online.")


class VoiceModeTests(QuietCase):
    def test_classic_voice_loop(self):
        app = make_app()
        app._run_live_voice_cli = Mock(return_value=False)
        v = app.voice_engine
        v.listen_for_wake_word.side_effect = [False, True, True, True, True, True]
        v.listen_for_command.side_effect = [None, "open chrome", RuntimeError("mic"), KeyboardInterrupt]
        app.process_command = Mock()
        with patch.object(jm.time, "sleep"):
            app.run_voice_mode()
        app.process_command.assert_called_once_with("open chrome", use_voice=True)
        self.assertFalse(app._voice_mode)

    def test_voice_goodbye_and_live(self):
        app = make_app()
        app._run_live_voice_cli = Mock(return_value=False)
        app.voice_engine.listen_for_wake_word.return_value = True
        app.voice_engine.listen_for_command.return_value = "Goodbye."
        app.process_command = Mock()
        app.run_voice_mode()
        app.process_command.assert_not_called()
        app._run_live_voice_cli = Mock(return_value=True)
        app.run_voice_mode()
        self.assertFalse(app._voice_mode)

    def test_start_live_voice(self):
        app = make_app()
        fake = Mock()
        with patch.dict("sys.modules", {"core.streaming": fake}), patch("core.streaming", fake, create=True):
            import core
            with patch.object(core, "streaming", fake, create=True):
                fake.vosk_available.return_value = False
                self.assertIsNone(app.start_live_voice())
                fake.vosk_available.return_value = True
                fake.ensure_model.return_value = None
                with patch.object(jm.Config, "LIVE_VOICE", True):
                    self.assertIsNone(app.start_live_voice())
                    fake.ensure_model.return_value = "/m"
                    listener = fake.StreamingListener.return_value
                    listener.run.side_effect = RuntimeError("mic gone")
                    status = []
                    got = app.start_live_voice(on_status=status.append)
                    self.assertIs(got, listener)
                    app._live_thread.join(2)
                    self.assertEqual(status, ["Live voice stopped: mic gone"])
                    self.assertIsNone(app.stream)
                    self.assertIsNone(app._live_listener)
                    missing = ModuleNotFoundError("No module named 'pyaudio'")
                    missing.name = "pyaudio"
                    listener.run.side_effect = missing
                    status.clear()
                    app.start_live_voice(on_status=status.append)
                    app._live_thread.join(2)
                    self.assertEqual(status, ["Live voice needs the 'pyaudio' package, which isn't "
                                               "installed. Install it with: pip install PyAudio  "
                                               "(if that fails to build: pip install pipwin && "
                                               "pipwin install pyaudio)"])
                    listener.run.side_effect = None
                    app.start_live_voice(on_status=Mock(side_effect=RuntimeError))
                    app._live_thread.join(2)

    def test_live_voice_cli(self):
        app = make_app()
        app.start_live_voice = Mock(return_value=None)
        self.assertFalse(app._run_live_voice_cli())
        listener = Mock()

        def fake_start(on_event, require_wake_word, on_status):
            on_event("partial", {"text": "op"})
            on_event("dispatched", {"text": "open x", "lane": 0})
            on_event("utterance_done", {"details": "d", "summary": "s"})
            on_event("other", {})
            on_status("loading")
            app._live_thread = SimpleNamespace(is_alive=lambda: False)   # listener already ended
            return listener
        app.start_live_voice = fake_start
        self.assertTrue(app._run_live_voice_cli())
        listener.stop.assert_called_once()
        app.voice_engine.speak.assert_called_with("s", summarize=True)

    def test_live_voice_cli_keyboard_interrupt(self):
        app = make_app()
        listener = Mock()
        app.start_live_voice = Mock(return_value=listener)
        app._live_thread = None
        with patch.object(jm.threading, "Event") as ev:
            ev.return_value.wait.side_effect = KeyboardInterrupt
            self.assertTrue(app._run_live_voice_cli())
        listener.stop.assert_called_once()


class InitTests(QuietCase):
    NAMES = ("setup_logging", "VoiceEngine", "DecisionEngine", "MultiModelBrain", "ApplicationControl",
             "SystemControl", "WindowsControl", "WeatherSkill", "WebSearchSkill", "UtilitySkill",
             "FileManagerSkill", "AutomationSkill", "SystemMonitor", "ScreenAutomationSkill",
             "TaskScheduler", "ToolRegistry")

    def patched(self, **side_effects):
        mocks = {}
        for name in self.NAMES:
            p = patch.object(jm, name, side_effect=side_effects.get(name)) if name in side_effects \
                else patch.object(jm, name)
            mocks[name] = p.start()
            self.addCleanup(p.stop)
        return mocks

    def test_full_startup(self):
        m = self.patched()
        m["MultiModelBrain"].return_value.available_models = ["a"]
        m["MultiModelBrain"].return_value.current_model = None
        app = jm.JARVIS()
        self.assertIs(app.brain, app.multi_brain)
        app.brain.refresh_catalog_async.assert_called_once()
        app.decision.warm_up_async.assert_called_once()
        self.assertIn("screen_automation", app.skills)
        detector = app.brain.memory.fact_detector
        detector("I like tea")
        app.decision.yes_no.assert_called()

    def test_startup_with_everything_missing(self):
        m = self.patched(VoiceEngine=RuntimeError("no audio"), MultiModelBrain=RuntimeError("no keys"),
                         ApplicationControl=RuntimeError, AutomationSkill=RuntimeError, SystemMonitor=RuntimeError,
                         ScreenAutomationSkill=RuntimeError, TaskScheduler=RuntimeError)
        rules = Mock()
        m["DecisionEngine"].side_effect = [RuntimeError("no torch"), rules]
        rules.warm_up_async.side_effect = RuntimeError
        app = jm.JARVIS(show_banner=False)
        self.assertIsNone(app.brain)
        self.assertIsInstance(app.voice_engine, jm._NullVoice)
        self.assertIs(app.decision, rules)
        self.assertEqual(m["DecisionEngine"].call_args.kwargs, {"engine": "rules"})
        for name in ("app_control", "task_scheduler", "screen_automation"):
            self.assertIsNone(getattr(app, name))
        self.assertNotIn("task_scheduler", app.skills)
        app.run_text_mode = Mock()
        app.start("voice")                     # NullVoice: no speech recognition → text mode
        app.shutdown()

    def test_brain_setup_failure_is_contained(self):
        m = self.patched()
        m["MultiModelBrain"].return_value.refresh_catalog_async.side_effect = RuntimeError
        app = jm.JARVIS(show_banner=False)
        self.assertIsNotNone(app.brain)


class MainTests(QuietCase):
    def test_main_variants(self):
        inst = Mock()
        with patch.object(jm, "JARVIS", return_value=inst):
            with patch.object(jm.sys, "argv", ["jarvis.py", "voice"]):
                jm.main()
            inst.start.assert_called_with("voice")
            with patch.object(jm.sys, "argv", ["jarvis.py", "what", "time"]):
                jm.main()
            inst.process_command.assert_called_with("what time", use_voice=False)
            with patch.object(jm.sys, "argv", ["jarvis.py"]):
                jm.main()
            inst.start.assert_called_with("text")
        with patch.object(jm, "JARVIS", side_effect=KeyboardInterrupt), patch.object(jm.sys, "argv", ["j"]):
            jm.main()
        with patch.object(jm, "JARVIS", side_effect=RuntimeError("x")), patch.object(jm.sys, "argv", ["j"]):
            jm.main()


if __name__ == "__main__":
    unittest.main()
