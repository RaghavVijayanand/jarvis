"""Tool registry, model tool-calling loops, and JARVIS routing/confirmation flows."""
import json
import unittest
from unittest.mock import Mock, patch

from core.tools import ToolRegistry, params
from tests.test_audit_regressions import BrainTestCase, bare_jarvis, ok_response


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.registry = ToolRegistry()
        self.registry.add("echo", "Echo text", lambda text, upper=False: text.upper() if upper else text,
                          params(["text"], text=("string", "t"), upper=("boolean", "u")))
        self.registry.add("nuke", "Dangerous", lambda: self.calls.append("nuked") or "nuked",
                          confirm=True, confirm_text="Really nuke?")

    def test_schema_shape(self):
        schema = self.registry.schemas()[0]
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["parameters"]["required"], ["text"])

    def test_json_string_and_dict_arguments(self):
        self.assertEqual(self.registry.execute("echo", json.dumps({"text": "hi", "upper": True})), "HI")
        self.assertEqual(self.registry.execute("echo", {"text": "café 日本"}), "café 日本")

    def test_unknown_keys_dropped_missing_required_reported(self):
        self.assertEqual(self.registry.execute("echo", {"text": "a", "evil": 1}), "a")
        self.assertIn("missing required", self.registry.execute("echo", {}))
        self.assertIn("unknown tool", self.registry.execute("rm_rf", {}))

    def test_confirmation_required_and_declined_by_default(self):
        self.assertIn("declined", self.registry.execute("nuke", {}))
        self.assertEqual(self.calls, [])
        asked = []
        self.registry.set_confirm(lambda q: asked.append(q) or True)
        self.assertEqual(self.registry.execute("nuke", {}), "nuked")
        self.assertEqual(asked, ["Really nuke?"])

    def test_tool_exceptions_become_observations(self):
        self.registry.add("boom", "fails", lambda: 1 / 0)
        self.assertIn("Error while running boom", self.registry.execute("boom", {}))


class ToolLoopTests(BrainTestCase):
    def setUp(self):
        super().setUp()
        self.registry = ToolRegistry()
        self.opened = []
        self.registry.add("open_app_or_website", "open", lambda target: self.opened.append(target) or f"Opened {target}.",
                          params(["target"], target=("string", "t")))
        self.brain.tool_registry = self.registry

    def test_openrouter_tool_call_then_answer(self):
        self.use("or", provider="openrouter", model_id="m", supports_tools=True)
        first = ok_response({"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "open_app_or_website", "arguments": '{"target": "spotify"}'}}]}}]})
        final = ok_response({"choices": [{"message": {"content": "Spotify is open."}}]})
        with patch("requests.post", side_effect=[first, final]) as post:
            reply = self.brain.process_command("put some music on")
        self.assertEqual(reply, "Spotify is open.")
        self.assertEqual(self.opened, ["spotify"])
        second_body = post.call_args_list[1].kwargs["json"]
        self.assertEqual(second_body["messages"][-1]["role"], "tool")
        self.assertEqual(second_body["messages"][-1]["content"], "Opened spotify.")
        self.assertIn("tools", post.call_args_list[0].kwargs["json"])

    def test_ollama_tool_call_with_dict_arguments(self):
        self.use("ollama:qwen", provider="ollama", model_id="qwen", supports_tools=True, context_window=8192)
        first = ok_response({"message": {"content": "", "tool_calls": [
            {"function": {"name": "open_app_or_website", "arguments": {"target": "notepad"}}}]}})
        final = ok_response({"message": {"content": "Notepad is open."}})
        with patch("requests.post", side_effect=[first, final]):
            self.assertEqual(self.brain.process_command("open notepad for me"), "Notepad is open.")
        self.assertEqual(self.opened, ["notepad"])

    def test_models_without_tool_support_get_no_tools(self):
        self.use("or", provider="openrouter", model_id="m", supports_tools=False)
        with patch("requests.post", return_value=ok_response({"choices": [{"message": {"content": "hi"}}]})) as post:
            self.brain.process_command("hello")
        self.assertNotIn("tools", post.call_args.kwargs["json"])

    def test_internal_requests_never_get_tools(self):
        self.use("or", provider="openrouter", model_id="m", supports_tools=True)
        with patch("requests.post", return_value=ok_response({"choices": [{"message": {"content": "sum"}}]})) as post:
            self.brain.process_command("summarize", use_context=False)
        self.assertNotIn("tools", post.call_args.kwargs["json"])


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.app, self.module = bare_jarvis()
        patcher = patch.object(self.module, "console")
        patcher.start()
        self.addCleanup(patcher.stop)
        from core.decision import DecisionEngine
        from skills.command_processor import CommandProcessor
        self.app.decision = DecisionEngine(engine="rules")
        self.app.command_processor = CommandProcessor(self.app)
        self.app.brain = None
        self.app.windows = Mock()
        self.app.app_control = Mock()
        self.app.screen_automation = None
        self.app.system_control = Mock()
        self.app.file_skill = None

    def test_power_action_needs_yes(self):
        self.app.windows.shutdown.return_value = "Shutting down in 30 seconds."
        prompt = self.app.process_command("shut down the computer", use_voice=False)
        self.assertIn("Reply yes", prompt)
        self.app.windows.shutdown.assert_not_called()
        self.assertIn("Shutting down", self.app.process_command("yes", use_voice=False))
        self.app.windows.shutdown.assert_called_once_with(restart=False)

    def test_no_cancels_and_unrelated_turn_drops_pending(self):
        self.app.process_command("restart the pc", use_voice=False)
        self.assertIn("Cancelled", self.app.process_command("no", use_voice=False))
        self.app.process_command("restart the pc", use_voice=False)
        self.app.windows.lock.return_value = "Locked the PC."
        self.assertEqual(self.app.process_command("lock my pc", use_voice=False), "Locked the PC.")
        self.app.process_command("yes", use_voice=False)
        self.app.windows.shutdown.assert_not_called()

    def test_pending_confirmation_expires(self):
        self.app.process_command("restart the pc", use_voice=False)
        self.app._pending_actions[0]["created"] -= 500
        self.app.process_command("yes", use_voice=False)
        self.app.windows.shutdown.assert_not_called()

    def test_close_app_needs_yes(self):
        self.app.app_control.close_app_by_name.return_value = "Closed chrome."
        self.assertIn("Reply yes", self.app.process_command("close chrome", use_voice=False))
        self.app.app_control.close_app_by_name.assert_not_called()
        self.assertEqual(self.app.process_command("yes", use_voice=False), "Closed chrome.")

    def test_file_delete_needs_yes(self):
        self.app.file_skill = Mock()
        self.app.file_skill.route_command.return_value = None
        self.app.file_skill.delete_file.return_value = "File 'a.txt' deleted"
        self.assertIn("Delete the file 'a.txt'", self.app.process_command("delete file a.txt", use_voice=False))
        self.app.file_skill.delete_file.assert_not_called()
        self.assertIn("deleted", self.app.process_command("yes", use_voice=False))

    def test_multi_step_runs_in_order_and_uses_named_browser(self):
        self.app.app_control.launch_app_by_name.side_effect = lambda text, browser=None: f"{text}|{browser}"
        self.app.windows.set_volume.return_value = "Volume set to 40%."
        with patch("skills.command_processor.time.sleep"):
            reply = self.app.process_command(
                "open chrome, go to youtube and play michael jackson, then set the volume to 40", use_voice=False)
        calls = [c.args[0] for c in self.app.app_control.launch_app_by_name.call_args_list]
        self.assertEqual(calls, ["open chrome", "go to youtube and play michael jackson"])
        self.assertEqual(self.app.app_control.launch_app_by_name.call_args_list[1].kwargs["browser"], "chrome")
        self.app.windows.set_volume.assert_called_once_with(40)
        self.assertIn("Ran 3 steps", reply)

    def test_unhandled_request_goes_to_brain(self):
        self.app.brain = Mock(current_model="m")
        self.app.brain.process_command.return_value = "Black holes are…"
        self.assertEqual(self.app.process_command("explain black holes", use_voice=False), "Black holes are…")
        self.app.brain.process_command.assert_called_once_with("explain black holes", use_context=True)

    def test_skill_answers_are_recorded_for_context(self):
        self.app.brain = Mock(current_model="m")
        self.app.windows.lock.return_value = "Locked the PC."
        self.app.process_command("lock my pc", use_voice=False)
        self.app.brain.record_exchange.assert_called_once_with("lock my pc", "Locked the PC.")

    def test_help_and_offline_fallback(self):
        self.assertIn("Here's what I can do", self.app.process_command("help", use_voice=False))
        self.assertIn("without an AI model", self.app.process_command("explain gravity", use_voice=False))

    def test_memory_commands(self):
        from core.memory import MemoryManager
        memory = MemoryManager.__new__(MemoryManager)
        memory.memory = {"user_name": None, "facts": [], "preferences": {}}
        memory._save = Mock()
        memory.fact_detector = None
        self.app.brain = Mock(current_model=None, memory=memory)
        self.assertIn("Noted", self.app.process_command("remember that I like green tea", use_voice=False))
        self.assertIn("green tea", self.app.process_command("what do you know about me", use_voice=False))
        self.assertIn("Forgotten", self.app.process_command("forget green tea", use_voice=False))
        self.assertEqual(memory.list_facts(), [])


if __name__ == "__main__":
    unittest.main()
