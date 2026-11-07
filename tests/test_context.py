"""JARVIS keeps conversational context like a chat model: follow-ups reach the model with history."""
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from core.brain import MultiModelBrain
from tests.test_cov_jarvis import QuietCase, make_app


def turn(role, content, minutes_ago=1):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {"role": role, "content": content, "ts": ts}


class FakeBrain:
    """Just enough of MultiModelBrain: a list history, tool support, a reply."""

    def __init__(self, tools=True):
        self.current_model = "gemini"
        self.available_models = {"gemini": {"supports_tools": tools}}
        self.conversation_history = []
        self.process_command = Mock(side_effect=self._answer)

    def _answer(self, command, use_context=True):
        self.conversation_history += [turn("user", command, 0), turn("assistant", "ok, did it", 0)]
        return "ok, did it"

    def record_exchange(self, user_text, reply):
        self.conversation_history += [turn("user", user_text, 0), turn("assistant", reply, 0)]


class FollowUpTests(QuietCase):
    def make(self, tools=True, history=True, minutes_ago=1):
        brain = FakeBrain(tools)
        if history:
            brain.conversation_history = [turn("user", "open notepad", minutes_ago),
                                          turn("assistant", "Opened Notepad.", minutes_ago)]
        return make_app(brain=brain)

    def test_follow_ups_detected(self):
        app = self.make()
        for text in ("close that", "play it again", "make it shorter", "rename it to notes.txt",
                     "and also open spotify", "what about tomorrow"):
            self.assertTrue(app._is_follow_up(text), text)

    def test_standalone_commands_stay_on_the_fast_path(self):
        app = self.make()
        for text in ("open chrome", "what time is it", "is it going to rain", "set volume to 40",
                     "what's the weather this weekend"):
            self.assertFalse(app._is_follow_up(text), text)

    def test_media_it_stays_on_the_fast_path(self):
        app = self.make()
        for text in ("pause it", "turn it up a bit", "resume it", "skip this song", "next one", "mute it", "stop it"):
            self.assertFalse(app._is_follow_up(text), text)

    def test_media_rules_understand_it(self):
        from core.decision import rule_decision
        for text in ("pause it", "resume it", "skip this song", "next one", "stop it", "stop the music"):
            self.assertEqual(rule_decision(text).intent, "media", text)

    def test_needs_a_recent_conversation_and_a_tool_model(self):
        self.assertFalse(self.make(history=False)._is_follow_up("close that"))
        self.assertFalse(self.make(minutes_ago=90)._is_follow_up("close that"))
        self.assertFalse(self.make(tools=False)._is_follow_up("close that"))
        self.assertFalse(make_app()._is_follow_up("close that"))                # no model at all

    def test_follow_up_goes_to_the_model_not_the_rules(self):
        app = self.make()
        with patch.object(app, "_handle_classified_command") as rules:
            self.assertEqual(app.process_command("make it shorter", use_voice=False), "ok, did it")
        app.brain.process_command.assert_called_once_with("make it shorter", use_context=True)
        rules.assert_not_called()
        self.assertEqual(len(app.brain.conversation_history), 4)               # recorded once, not twice

    def test_everyday_references_are_resolved_without_the_model(self):
        app = self.make()
        app._last_app = "Notepad"
        self.assertEqual(app._resolve_reference("close that"), "close Notepad")
        self.assertEqual(app._resolve_reference("go back to it"), "switch to Notepad")
        self.assertEqual(app._resolve_reference("minimize this window"), "minimize Notepad")
        app._last_intent = "WEATHER"
        self.assertEqual(app._resolve_reference("what about mumbai?"), "weather in mumbai")
        app._last_intent = "GENERAL"
        self.assertEqual(app._resolve_reference("what about mumbai?"), "what about mumbai?")
        app._last_app = None
        with patch.object(app, "_foreground_title", return_value="JARVIS"):
            self.assertEqual(app._resolve_reference("close that"), "close that")   # nothing to point at

    def test_closing_forgets_the_app(self):
        app = self.make()
        app._remember_app("Opened Notepad.")
        app._remember_app("Closed Notepad.")
        self.assertIsNone(app._last_app)

    def test_every_turn_is_recorded(self):
        app = self.make(history=False)
        app.app_control.launch_app_by_name.return_value = "Opened Notepad."
        app.process_command("notepad", use_voice=False)
        self.assertEqual([m["content"] for m in app.brain.conversation_history], ["notepad", "Opened Notepad."])
        self.assertEqual(app._last_app, "Notepad")


class LocalModelTests(QuietCase):
    def registry(self):
        from core.tools import CORE_TOOLS, ToolRegistry
        reg = ToolRegistry()
        for name in CORE_TOOLS + ("install_software", "connect_wifi", "flush_dns", "send_email"):
            reg.add(name, f"Does {name.replace('_', ' ')}.", lambda **kw: "ok")
        return reg

    def test_relevant_tools_are_core_plus_matches(self):
        reg = self.registry()
        names = reg.relevant("could you connect to the office wifi")
        self.assertIn("connect_wifi", names)
        self.assertIn("open_app_or_website", names)
        self.assertNotIn("install_software", names)
        self.assertLessEqual(len(reg.relevant("x", limit=10)), 10)

    def test_ollama_request(self):
        brain = MultiModelBrain.__new__(MultiModelBrain)
        brain.tool_registry = self.registry()
        sent = {}

        def post(url, json=None, timeout=None):
            sent.update(json)
            return Mock(status_code=200, json=lambda: {"message": {"content": "Hello."}})
        with patch("requests.post", post):
            reply = brain._chat_ollama({"model_id": "qwen3:4b-instruct", "context_window": 16384,
                                        "supports_thinking": True},
                                       [{"role": "system", "content": "s"},
                                        {"role": "user", "content": "connect to wifi"}], True, 100, 0.5)
        self.assertEqual(reply, "Hello.")
        self.assertIs(sent["think"], False)
        self.assertEqual(sent["keep_alive"], "30m")
        self.assertEqual(sent["options"]["num_ctx"], 16384)
        names = [t["function"]["name"] for t in sent["tools"]]
        self.assertIn("connect_wifi", names)
        self.assertNotIn("install_software", names)

    def test_claimed_action_without_a_tool_gets_one_nudge(self):
        brain = MultiModelBrain.__new__(MultiModelBrain)
        brain.tool_registry = self.registry()
        replies = iter([{"message": {"content": "The volume has been increased."}},
                        {"message": {"content": "", "tool_calls": [
                            {"function": {"name": "change_volume", "arguments": {}}}]}},
                        {"message": {"content": "Turned it up."}}])
        sent = []

        def post(url, json=None, timeout=None):
            sent.append([m["content"] for m in json["messages"]])
            return Mock(status_code=200, json=lambda r=next(replies): r)
        with patch("requests.post", post):
            reply = brain._chat_ollama({"model_id": "m"}, [{"role": "user", "content": "turn it up"}], True, 100, 0.5)
        self.assertEqual(reply, "Turned it up.")
        self.assertIn("no tool was called", sent[1][-1])

    def test_switches_to_the_local_default_once_ollama_is_up(self):
        from core.config import Config
        brain = MultiModelBrain.__new__(MultiModelBrain)
        brain.available_models = {"gemini-flash": {}}
        brain.current_model = "gemini-flash"                   # Ollama wasn't running at start-up
        with patch.object(Config, "DEFAULT_MODEL", "ollama:qwen3:4b-instruct"):
            self.assertFalse(brain.prefer_default_model())
            brain.available_models["ollama:qwen3:4b-instruct"] = {}
            self.assertTrue(brain.prefer_default_model())
            self.assertEqual(brain.current_model, "ollama:qwen3:4b-instruct")
            brain.switch_model("gemini-flash")                  # the user chose; leave it alone
            self.assertFalse(brain.prefer_default_model())
            self.assertEqual(brain.current_model, "gemini-flash")

    def test_local_only_registers_no_cloud_models(self):
        from core.config import Config
        brain = MultiModelBrain.__new__(MultiModelBrain)
        brain._catalog = {}
        brain.available_models = {"ollama:qwen3:4b-instruct": {"provider": "ollama"}}
        with patch.object(Config, "GEMINI_API_KEY", "key"), patch.object(Config, "OPENROUTER_API_KEY", "key"), \
                patch.object(brain, "_check_local_models", return_value=[]):
            with patch.object(Config, "LOCAL_ONLY", True):
                brain._initialize_providers()
                self.assertEqual({c["provider"] for c in brain.available_models.values()}, {"ollama"})
            brain._initialize_providers()
            self.assertIn("gemini", {c["provider"] for c in brain.available_models.values()})

    def test_honest_chat_is_not_nudged(self):
        brain = MultiModelBrain.__new__(MultiModelBrain)
        brain.tool_registry = self.registry()
        calls = []

        def post(url, json=None, timeout=None):
            calls.append(1)
            return Mock(status_code=200, json=lambda: {"message": {"content": "I'm well, thanks for asking."}})
        with patch("requests.post", post):
            brain._chat_ollama({"model_id": "m"}, [{"role": "user", "content": "how are you"}], True, 100, 0.5)
        self.assertEqual(len(calls), 1)


class DesktopContextTests(QuietCase):
    def test_desktop_line(self):
        app = make_app()
        app._last_app = "Notepad"
        with patch.object(app, "_foreground_title", return_value="Untitled - Notepad"):
            self.assertEqual(app._desktop_context(), "the window in front is 'Untitled - Notepad'; "
                                                     "the app JARVIS opened most recently is Notepad.")
        with patch.object(app, "_foreground_title", return_value="JARVIS"):
            self.assertEqual(app._desktop_context(), "the app JARVIS opened most recently is Notepad.")

    def test_system_prompt_carries_it(self):
        brain = MultiModelBrain.__new__(MultiModelBrain)
        brain.memory = Mock()
        brain.memory.get_context_string.return_value = ""
        brain.context_provider = lambda: "the window in front is 'Untitled - Notepad'."
        prompt = brain._get_system_prompt(with_tools=True)
        self.assertIn("Desktop right now: the window in front is 'Untitled - Notepad'.", prompt)
        self.assertIn("'it', 'that', 'there'", prompt)
        brain.context_provider = Mock(side_effect=RuntimeError("no win32"))
        self.assertNotIn("Desktop right now", brain._get_system_prompt(with_tools=True))

    def test_history_window_is_longer(self):
        brain = MultiModelBrain.__new__(MultiModelBrain)
        brain._history_lock = threading.RLock()
        brain.conversation_history = [turn("user" if i % 2 == 0 else "assistant", f"m{i}") for i in range(40)]
        self.assertEqual(len(brain._history_window(10 ** 6)), 30)
