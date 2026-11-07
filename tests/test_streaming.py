"""Live-voice pipeline: clause tracking, act-while-speaking, parallel lanes, confirmations."""
import threading
import time
import unittest
from unittest.mock import Mock, patch

from core.streaming import ClauseTracker, StreamingSession
from skills.command_processor import CommandProcessor, split_clauses
from tests.test_audit_regressions import bare_jarvis

SENTENCE = ("open chrome and go to the youtube and play a video called rick roll and move to the next video "
            "simultaneously open the alarm set the alarm for 10 am after which open settings and change the "
            "screen resolution to 720p")


class SplitterTests(unittest.TestCase):
    def test_users_sentence_becomes_two_lanes(self):
        plan = CommandProcessor().plan(SENTENCE)
        lanes = {lane: [s.text for s in steps] for lane, steps in plan.lanes.items()}
        self.assertEqual(lanes[0], ["open chrome", "go to the youtube and play a video called rick roll",
                                    "move to the next video"])
        self.assertEqual(lanes[1], ["open the alarm", "set the alarm for 10 am", "open settings",
                                    "change the screen resolution to 720p"])

    def test_connectors(self):
        self.assertEqual(split_clauses("search for cats and dogs"), [("start", "search for cats and dogs")])
        self.assertEqual([c for _, c in split_clauses("open notepad then type hello and press enter")],
                         ["open notepad", "type hello", "press enter"])
        self.assertEqual([l for l, _ in split_clauses("pause the music meanwhile open spotify")], ["start", "par"])
        self.assertEqual(split_clauses("and then open settings"), [("seq", "open settings")])
        self.assertEqual(split_clauses("open chrome and"), [("start", "open chrome")])

    def test_questions_are_not_chopped(self):
        self.assertEqual(len(split_clauses("how do I open a file and read it")), 1)
        self.assertEqual(len(split_clauses("what is the difference between python and java")), 1)
        self.assertEqual([c for _, c in split_clauses("what is the weather and open chrome")],
                         ["what is the weather", "open chrome"])


def pause(seconds):
    threading.Event().wait(seconds)   # unaffected by the patched time.sleep


def feed_words(words):
    """Yield cumulative partial transcripts the way Vosk does."""
    for i in range(1, len(words) + 1):
        yield " ".join(words[:i])


class ClauseTrackerTests(unittest.TestCase):
    def test_clause_closes_one_word_after_connector_and_verb(self):
        tracker = ClauseTracker()
        closed_at = {}
        words = "open chrome and go to youtube and play jazz".split()
        for partial in feed_words(words):
            for link, clause in tracker.update(partial):
                closed_at[clause] = partial
        # "open chrome" is released once "and go to" is heard — long before the sentence ends.
        self.assertEqual(closed_at["open chrome"], "open chrome and go to")
        self.assertNotIn("go to youtube", closed_at)       # stays open: "and play jazz" joins it
        self.assertEqual(tracker.update(" ".join(words), final=True),
                         [("seq", "go to youtube and play jazz")])

    def test_revised_words_are_not_released_early(self):
        tracker = ClauseTracker()
        self.assertEqual(tracker.update("open crow and go"), [])
        self.assertEqual(tracker.update("open chrome and go"), [])      # prefix changed → restart count
        self.assertEqual(tracker.update("open chrome and go to"), [("start", "open chrome")])


class FakeJarvis:
    """Just enough JARVIS for StreamingSession: real routing and executor, mocked skills."""

    def __init__(self):
        from core.decision import DecisionEngine
        self.app, module = bare_jarvis()
        self.console = patch.object(module, "console")
        self.console.start()
        app = self.app
        app.decision = DecisionEngine(engine="rules")
        app.command_processor = CommandProcessor(app)
        app.brain = None
        app.file_skill = None
        app.screen_automation = None
        app.task_scheduler = Mock()
        app.task_scheduler.schedule_alarm.side_effect = lambda at, label="": f"Alarm set for {at:%I:%M %p}."
        app.system_control = Mock()
        self.log = []
        lock = threading.Lock()

        def rec(name, reply):
            def fn(*a, **k):
                with lock:
                    self.log.append((time.time(), name, a))
                return reply
            return fn
        app.app_control = Mock()
        app.app_control.launch_app_by_name.side_effect = lambda text, browser=None: rec(
            "launch", f"Opened {text}" + (" watch?v=abc" if "play" in text else ""))(text, browser)
        app.windows = Mock()
        app.windows.media.side_effect = rec("media", "Skipped to the next track.")
        app.windows.wait_for_playback.return_value = True
        app.windows.parse_resolution = __import__("skills.windows_control", fromlist=["x"]).WindowsControl.parse_resolution
        app.windows.set_resolution.side_effect = rec("resolution", "Resolution changed from 1920×1080 to 1280×720.")
        app.windows.open_settings.side_effect = rec("settings", "Opened settings.")
        app.voice_engine = Mock(is_speaking=False)

    def stop(self):
        self.console.stop()


class StreamingSessionTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeJarvis()
        self.addCleanup(self.fake.stop)
        self.events = []
        self.session = StreamingSession(self.fake.app, on_event=lambda k, i: self.events.append((k, i)), beep=False)
        real_sleep = time.sleep
        patcher = patch("time.sleep", side_effect=lambda sec: real_sleep(min(sec, 0.01)))  # skip settle delays
        patcher.start()
        self.addCleanup(patcher.stop)

    def speak(self, text, pause_after=None):
        words = text.split()
        for partial in feed_words(words):
            self.session.partial(partial)
            if pause_after and partial.endswith(pause_after):
                return partial
        return text

    def test_actions_start_while_user_is_still_talking(self):
        words = SENTENCE.split()
        cut = words.index("rick")                       # user is mid-way through "rick roll"
        for partial in feed_words(words[:cut]):
            self.session.partial(partial)
        pause(0.3)
        launched = [a[0] for _, name, a in self.fake.log if name == "launch"]
        self.assertIn("open chrome", launched)          # Chrome already opening
        for partial in list(feed_words(words))[cut:]:
            self.session.partial(partial)
        self.session.segment(SENTENCE)
        summary = self.session.end_utterance()
        names = [name for _, name, _ in self.fake.log]
        self.assertIn("media", names)
        self.assertIn("settings", names)
        self.assertEqual(self.fake.app.task_scheduler.schedule_alarm.call_args.args[0].hour, 10)
        # YouTube step went to the browser opened earlier in the same lane.
        # (Lanes run in parallel, so find the call by content, not position.)
        calls = self.fake.app.app_control.launch_app_by_name.call_args_list
        yt = next(c for c in calls if "youtube" in c.args[0])
        self.assertEqual(yt.args[0], "go to the youtube and play a video called rick roll")
        self.assertEqual(yt.kwargs["browser"], "chrome")
        # Resolution is destructive → waits for a spoken yes.
        self.fake.app.windows.set_resolution.assert_not_called()
        self.assertIn("Say yes to confirm", summary)
        self.session.segment("yes")
        pause(0.3)
        self.fake.app.windows.set_resolution.assert_called_once_with(1280, 720)
        kinds = [k for k, _ in self.events]
        self.assertIn("dispatched", kinds)
        self.assertIn("utterance_done", kinds)

    def test_lanes_really_run_in_parallel(self):
        gate = threading.Event()
        order = []

        def slow_launch(text, browser=None):
            order.append(("start", text))
            if text == "open chrome":
                gate.wait(2)
            order.append(("end", text))
            return f"Opened {text}"
        self.fake.app.app_control.launch_app_by_name.side_effect = slow_launch
        self.speak("open chrome simultaneously open notepad")
        self.session.segment("open chrome simultaneously open notepad")
        pause(0.3)
        self.assertIn(("end", "open notepad"), order)   # lane 2 finished while lane 1 is still busy
        self.assertNotIn(("end", "open chrome"), order)
        gate.set()
        self.session.end_utterance()
        self.assertIn(("end", "open chrome"), order)

    def test_questions_wait_for_the_end(self):
        self.fake.app.brain = Mock(current_model="m")
        self.fake.app.brain.process_command.return_value = "Cats and dogs are pets."
        self.speak("tell me about cats and dogs")
        self.fake.app.brain.process_command.assert_not_called()
        self.session.segment("tell me about cats and dogs")
        summary = self.session.end_utterance()
        self.fake.app.brain.process_command.assert_called_once_with("tell me about cats and dogs", use_context=True)
        self.assertEqual(summary, "Cats and dogs are pets.")

    def test_pause_mode_waits_for_segment(self):
        self.session.act_mode = "pause"
        self.speak("open chrome and go to github.com")
        self.assertEqual(self.fake.log, [])
        self.session.segment("open chrome and go to github.com")
        self.session.end_utterance()
        self.assertEqual(len([n for _, n, _ in self.fake.log if n == "launch"]), 2)

    def test_wake_word_required_when_configured(self):
        self.session.require_wake_word = True
        self.session.segment("open chrome")
        self.assertIsNone(self.session.end_utterance())
        self.session.segment("jarvis open chrome")
        self.session.end_utterance()
        self.assertEqual(self.fake.app.app_control.launch_app_by_name.call_args.args[0], "open chrome")

    def test_ask_yes_no_is_answered_by_next_segment(self):
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("a", self.session.ask_yes_no("Close Chrome?", 3)))
        t.start()
        pause(0.2)
        self.session.segment("yes")
        t.join(2)
        self.assertTrue(result["a"])


class TypedCompoundTests(unittest.TestCase):
    def test_typed_sentence_runs_both_lanes(self):
        fake = FakeJarvis()
        self.addCleanup(fake.stop)
        real_sleep = time.sleep
        with patch("time.sleep", side_effect=lambda sec: real_sleep(min(sec, 0.01))):
            reply = fake.app.process_command(
                "open chrome, go to youtube and play rick roll simultaneously set an alarm for 10 am", use_voice=False)
        self.assertIn("2 parallel lanes", reply)
        fake.app.task_scheduler.schedule_alarm.assert_called_once()
        launched = [c.args[0] for c in fake.app.app_control.launch_app_by_name.call_args_list]
        self.assertEqual(launched, ["open chrome", "go to youtube and play rick roll"])


class ResolutionTests(unittest.TestCase):
    def test_parse(self):
        from skills.windows_control import WindowsControl as W
        self.assertEqual(W.parse_resolution("change the screen resolution to 720p"), (1280, 720))
        self.assertEqual(W.parse_resolution("1920 by 1080"), (1920, 1080))
        self.assertEqual(W.parse_resolution("full hd"), (1920, 1080))
        self.assertIsNone(W.parse_resolution("change the resolution"))

    def test_resolution_needs_yes_and_auto_reverts(self):
        fake = FakeJarvis()
        self.addCleanup(fake.stop)
        app = fake.app
        app.notify = Mock()
        prompt = app.process_command("change the screen resolution to 720p", use_voice=False)
        self.assertIn("1280×720", prompt)
        with patch("handlers.control.threading.Timer") as timer:
            reply = app.process_command("yes", use_voice=False)
        self.assertIn("keep resolution", reply)
        timer.assert_called_once()
        self.assertIn("Keeping", app.process_command("keep resolution", use_voice=False))
        timer.return_value.cancel.assert_called_once_with()


class QueryCleanupTests(unittest.TestCase):
    def test_clean_query(self):
        from skills.app_control import ApplicationControl as A
        self.assertEqual(A.clean_query("a video called rick roll"), "rick roll")
        self.assertEqual(A.clean_query("some songs by arijit"), "songs by arijit")
        self.assertEqual(A.clean_query("the song despacito on youtube"), "despacito")


if __name__ == "__main__":
    unittest.main()


class ListenerLoopTests(unittest.TestCase):
    """StreamingListener with fake PyAudio/Vosk: partials, finals, self-muting, end of utterance."""

    def test_loop_feeds_session_and_detects_end(self):
        import json
        import sys
        import types
        script = [(False, "open"), (False, "open chrome"), (False, "open chrome and go"),
                  (True, "open chrome and go to github"), (False, ""), (False, "")]
        state = {"i": 0}

        class Rec:
            def __init__(self, *a):
                pass

            def SetWords(self, _):
                pass

            def Reset(self):
                state["reset"] = state.get("reset", 0) + 1

            def AcceptWaveform(self, data):
                i = min(state["i"], len(script) - 1)
                state["i"] += 1
                self.current = script[i]
                return self.current[0]

            def Result(self):
                return json.dumps({"text": self.current[1]})

            def PartialResult(self):
                return json.dumps({"partial": self.current[1]})

        vosk = types.SimpleNamespace(SetLogLevel=lambda *_: None, Model=lambda *_: object(), KaldiRecognizer=Rec)
        stream = Mock()
        stream.read.side_effect = lambda *a, **k: (pause(0.02), b"\0" * 4000)[1]
        pyaudio = types.SimpleNamespace(paInt16=8, PyAudio=lambda: Mock(open=Mock(return_value=stream)))
        session = Mock()
        voice = Mock(is_speaking=False)
        from core.streaming import StreamingListener
        listener = StreamingListener(session, voice, end_silence=0.1, model_path="/nowhere")
        with patch.dict(sys.modules, {"vosk": vosk, "pyaudio": pyaudio}):
            t = threading.Thread(target=listener.run)
            t.start()
            pause(0.6)
            voice.is_speaking = True           # JARVIS talking: audio is ignored and the recognizer reset
            pause(0.1)
            listener.stop()
            t.join(2)
        partials = [c.args[0] for c in session.partial.call_args_list]
        self.assertEqual(partials, ["open", "open chrome", "open chrome and go"])
        session.segment.assert_called_once_with("open chrome and go to github")
        pause(0.2)
        session.end_utterance.assert_called_once_with()
        self.assertGreaterEqual(state.get("reset", 0), 1)
