"""End to end with a real HTTP round trip: JARVIS → brain → local fake OpenAI server → tools → skills.

No internet: the "provider" is a tiny HTTP server on 127.0.0.1 that speaks the
OpenAI chat-completions protocol, asks for a tool, then answers with the tool result.
"""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch


class FakeProvider(BaseHTTPRequestHandler):
    requests_seen = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeProvider.requests_seen.append(body)
        last = body["messages"][-1]
        if last["role"] == "tool":
            reply = {"choices": [{"message": {"content": f"Done: {last['content']}"}}]}
        else:
            tool_names = {t["function"]["name"] for t in body.get("tools", [])}
            assert "calculate" in tool_names, tool_names
            reply = {"choices": [{"message": {"content": None, "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "calculate", "arguments": json.dumps({"expression": "17*23"})}}]}}]}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeProvider)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_llm_tool_call_through_real_jarvis(self):
        from core.config import Config
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = f"http://127.0.0.1:{self.server.server_port}"
        with patch.object(Config, "OPENROUTER_API_KEY", "local-test"), \
                patch.object(Config, "OPENROUTER_BASE_URL", base), \
                patch.object(Config, "GEMINI_API_KEY", ""), \
                patch.object(Config, "DECISION_ENGINE", "rules"), \
                patch.object(Config, "LOGS_DIR", Path(temp.name)), \
                patch.object(Config, "CACHE_DIR", Path(temp.name)), \
                patch.object(Config, "OLLAMA_URL", "http://127.0.0.1:9"), \
                patch("jarvis.console"), \
                patch("jarvis.VoiceEngine"), \
                patch("jarvis.TaskScheduler"), \
                patch("jarvis.ScreenAutomationSkill"), \
                patch("jarvis.AutomationSkill"), \
                patch("jarvis.ApplicationControl"), \
                patch("core.brain.MultiModelBrain.refresh_catalog_async"), \
                patch("core.memory.Config.MEMORY_DIR", Path(temp.name)):
            import jarvis
            app = jarvis.JARVIS(show_banner=False)
            app.brain.available_models = {"fake": {"provider": "openrouter", "model_id": "fake/model",
                                                   "supports_tools": True, "context_window": 8192}}
            app.brain.current_model = "fake"
            reply = app.process_command("work out seventeen times twenty three for my budget", use_voice=False)
            app.shutdown()
        self.assertIn("17*23 = 391", reply)
        first = FakeProvider.requests_seen[0]
        self.assertEqual(first["model"], "fake/model")
        self.assertIn("tools", first)
        self.assertEqual(FakeProvider.requests_seen[1]["messages"][-1]["role"], "tool")


if __name__ == "__main__":
    unittest.main()
