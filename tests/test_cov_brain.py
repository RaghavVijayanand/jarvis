"""Coverage + regression tests for core/brain.py and core/memory.py.

No network: ``requests.get``/``requests.post`` are patched with payloads shaped
like the real OpenRouter, Gemini (OpenAI-compatible) and Ollama responses.
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests


def resp(payload=None, status=200, text=None, bad_json=False):
    r = Mock(status_code=status)
    if bad_json:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = payload
    r.text = text if text is not None else (json.dumps(payload) if payload is not None else "")
    r.raise_for_status = Mock()
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    return r


def oa_text(text):
    """OpenAI chat-completions style final answer."""
    return resp({"id": "gen-1", "object": "chat.completion",
                 "choices": [{"index": 0, "finish_reason": "stop",
                              "message": {"role": "assistant", "content": text}}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 3}})


def oa_tool(name, args, call_id="call_abc", content=None, extra=None):
    call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    if call_id is None:
        del call["id"]
    if extra:
        call.update(extra)
    return resp({"choices": [{"index": 0, "finish_reason": "tool_calls",
                              "message": {"role": "assistant", "content": content, "tool_calls": [call]}}]})


def ollama_text(text):
    return resp({"model": "llama3.2", "created_at": "2026-01-01T00:00:00Z",
                 "message": {"role": "assistant", "content": text}, "done": True})


def ollama_tool(name, args):
    return resp({"model": "llama3.2", "message": {"role": "assistant", "content": "",
                                                   "tool_calls": [{"function": {"name": name, "arguments": args}}]},
                 "done": True})


class Base(unittest.TestCase):
    def setUp(self):
        from core import brain as brain_module
        from core.config import Config
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        for attr, value in dict(LOGS_DIR=d, CACHE_DIR=d, MEMORY_DIR=d / "mem",
                                OPENROUTER_API_KEY="or-key", GEMINI_API_KEY="g-key", DEFAULT_MODEL="",
                                REQUEST_TIMEOUT=30, OLLAMA_URL="http://localhost:11434",
                                AUTOMATION_VISION_PROVIDER="auto", AUTOMATION_VISION_MODEL="").items():
            p = patch.object(Config, attr, value, create=True)
            p.start()
            self.addCleanup(p.stop)
        for name, value in (("get_location_preference", Mock(return_value="")),
                            ("save_location_preference", Mock())):
            p = patch("core.config." + name, value)
            p.start()
            self.addCleanup(p.stop)
        self.Config = Config
        self.m = brain_module
        # Ollama is not running during construction.
        with patch("requests.get", side_effect=requests.ConnectionError("refused")):
            self.brain = brain_module.MultiModelBrain()
        self.brain.memory.fact_detector = None

    def use(self, name, **cfg):
        self.brain.available_models = {name: cfg}
        self.brain.current_model = name

    def registry(self, **funcs):
        from core.tools import ToolRegistry, params
        reg = ToolRegistry()
        for name, fn in funcs.items():
            reg.add(name, f"{name} tool", fn, params(["x"], x=("string", "x")))
        self.brain.tool_registry = reg
        return reg


class ProviderSetupTests(Base):
    def test_defaults_and_listing(self):
        b = self.brain
        self.assertIn("gemini-flash", b.available_models)
        self.assertIn("openrouter-auto", b.available_models)
        self.assertEqual(b.current_model, "gemini-flash")
        self.assertIn("▶ gemini-flash", b.list_available_models())
        info = b.get_model_info()
        self.assertEqual(info["provider"], "gemini")
        self.assertIn("Switched", b.switch_model("flash-lite"))
        self.assertEqual(b.current_model, "gemini-flash-lite")
        self.assertIn("not available", b.switch_model("gemini"))   # ambiguous
        self.assertIn("not available", b.switch_model("nope"))
        b.current_model = None
        self.assertEqual(b.get_model_info(), {"active": None})
        b.available_models = {}
        self.assertIn("No models available", b.list_available_models())
        b._set_default_model()
        self.assertIsNone(b.current_model)

    def test_default_model_config_and_fallback_order(self):
        self.Config.DEFAULT_MODEL = "gemini-pro"
        self.brain.current_model = None
        self.brain._set_default_model()
        self.assertEqual(self.brain.current_model, "gemini-pro")
        self.brain.available_models = {"x": {"provider": "other"}}
        self.brain.current_model = None
        self.brain._set_default_model()
        self.assertEqual(self.brain.current_model, "x")

    def test_catalog_refresh_openrouter_and_gemini(self):
        or_models = {"data": [
            {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B", "context_length": 131072,
             "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools", "temperature"],
             "architecture": {"input_modalities": ["text"]}},
            {"id": "google/gemma-3-27b-it", "name": "Gemma 3", "context_length": None,
             "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"input_modalities": ["text", "image"]}},
            {"id": "openai/gpt-4o", "name": "GPT-4o", "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
            {"id": "openrouter/auto", "name": "Auto", "pricing": {"prompt": "-1", "completion": "-1"}},
            {"id": "weird/model", "pricing": {"prompt": None}},
            "garbage",
        ]}
        gem_models = {"object": "list", "data": [
            {"id": "models/gemini-2.5-flash", "object": "model", "owned_by": "google"},
            {"id": "models/gemini-flash-latest", "object": "model"},
            {"id": "models/text-embedding-004"}, {"id": "models/gemini-2.5-flash-preview-tts"},
            {"id": "models/gemma-3-27b-it"},
        ]}

        def fake_get(url, **kw):
            if "openrouter" in url:
                return resp(or_models)
            if "googleapis" in url:
                self.assertEqual(kw["headers"]["Authorization"], "Bearer g-key")
                return resp(gem_models)
            raise requests.ConnectionError()
        with patch("requests.get", side_effect=fake_get):
            note = self.brain.refresh_catalog()
        self.assertIn("OpenRouter: 2 free models", note)
        self.assertIn("Gemini: 2 models", note)
        cat = self.brain._catalog
        self.assertNotIn("openrouter/auto", cat["openrouter"])
        self.assertNotIn("openai/gpt-4o", cat["openrouter"])
        self.assertTrue(cat["openrouter"]["meta-llama/llama-3.3-70b-instruct:free"]["supports_tools"])
        self.assertTrue(cat["openrouter"]["google/gemma-3-27b-it"]["supports_vision"])
        self.assertEqual(cat["openrouter"]["google/gemma-3-27b-it"]["context_window"], 32768)
        self.assertIn("gemini-2.5-flash", cat["gemini"])
        am = self.brain.available_models
        self.assertIn("llama-3.3-70b-instruct (free)", am)
        self.assertIn("gemini-2.5-flash", am)
        self.assertNotIn("gemini-flash-latest", am)   # already covered by the alias
        # cached catalog reloads
        self.assertEqual(self.brain._load_catalog(), cat)

    def test_catalog_refresh_errors_and_no_keys(self):
        with patch("requests.get", return_value=resp({}, status=500)):
            note = self.brain.refresh_catalog()
        self.assertIn("OpenRouter catalog unavailable", note)
        self.assertIn("Gemini catalog unavailable", note)
        self.Config.OPENROUTER_API_KEY = self.Config.GEMINI_API_KEY = ""
        with patch("requests.get", side_effect=requests.ConnectionError()):
            self.assertEqual(self.brain.refresh_catalog(), "No cloud providers configured.")

    def test_catalog_cache_corrupt_and_unwritable(self):
        self.brain._catalog_file.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.brain._load_catalog(), {})
        self.brain._catalog_file = Path(self.tmp.name) / "file.txt" / "x.json"
        (Path(self.tmp.name) / "file.txt").write_text("x")
        self.brain._save_catalog()   # logs, does not raise

    def test_refresh_catalog_async_calls_back(self):
        done = threading.Event()
        got = []
        self.brain.refresh_catalog = Mock(return_value="ok")
        self.brain.refresh_catalog_async(lambda msg: (got.append(msg), done.set()))
        self.assertTrue(done.wait(2))
        self.assertEqual(got, ["ok"])
        done2 = threading.Event()

        def bad(msg):
            done2.set()
            raise RuntimeError("boom")
        self.brain.refresh_catalog_async(bad)
        self.assertTrue(done2.wait(2))

    def test_ollama_discovery_and_stale_removal(self):
        tags = {"models": [{"name": "llama3.2:3b"}, {"name": "qwen2.5vl:3b"}, {"name": "nomic-embed-text"},
                           {"name": ""}]}

        def fake_post(url, json=None, **kw):
            caps = {"llama3.2:3b": ["completion", "tools"], "qwen2.5vl:3b": ["completion", "vision"]}
            return resp({"capabilities": caps.get(json["model"], [])})
        self.brain.available_models["ollama:old"] = {"provider": "ollama", "model_id": "old"}
        with patch("requests.get", return_value=resp(tags)), patch("requests.post", side_effect=fake_post):
            found = self.brain._check_local_models()
        self.assertEqual(found, ["ollama:llama3.2:3b", "ollama:qwen2.5vl:3b"])
        am = self.brain.available_models
        self.assertNotIn("ollama:old", am)
        self.assertTrue(am["ollama:llama3.2:3b"]["supports_tools"])
        self.assertTrue(am["ollama:qwen2.5vl:3b"]["supports_vision"])
        self.assertIn("gemini-flash", am)
        # Not running: keep what we had; non-200: nothing.
        with patch("requests.get", side_effect=requests.ConnectionError()):
            self.assertEqual(self.brain._check_local_models(), [])
        self.assertIn("ollama:llama3.2:3b", self.brain.available_models)
        with patch("requests.get", return_value=resp({}, status=503)):
            self.assertEqual(self.brain._check_local_models(), [])
        with patch("requests.post", side_effect=requests.ConnectionError()):
            self.assertEqual(self.m.MultiModelBrain._ollama_capabilities("x"), [])
        # Ollama models survive a provider rebuild; tools-capable local is preferred when no cloud.
        self.Config.OPENROUTER_API_KEY = self.Config.GEMINI_API_KEY = ""
        with patch("requests.get", side_effect=requests.ConnectionError()):
            self.brain._initialize_providers()
        self.brain.current_model = None
        self.brain._set_default_model()
        self.assertEqual(self.brain.current_model, "ollama:llama3.2:3b")


class HistoryTests(Base):
    def test_load_filters_malformed_entries(self):
        self.brain._history_file.write_text(json.dumps([
            {"role": "user", "content": "ok"}, {"role": "assistant"}, {"role": "user", "content": None},
            "junk", {"role": "system", "content": "x"}, {"role": "assistant", "content": "fine"}]))
        self.brain._load_history()
        self.assertEqual([m["content"] for m in self.brain.conversation_history], ["ok", "fine"])
        self.use("or", provider="openrouter", model_id="m", context_window=8192)
        with patch("requests.post", return_value=oa_text("hi")) as post:
            self.assertEqual(self.brain.process_command("next"), "hi")
        self.assertEqual(len(post.call_args.kwargs["json"]["messages"]), 4)

    def test_load_non_list_and_corrupt(self):
        self.brain._history_file.write_text('{"role": "user"}')
        self.brain._load_history()
        self.assertEqual(self.brain.conversation_history, [])
        self.brain._history_file.write_text("[{bad")
        self.brain._load_history()
        self.assertEqual(self.brain.conversation_history, [])

    def test_record_exchange_and_cap(self):
        from core.brain import Reply
        self.brain.record_exchange("", "x")
        self.brain.record_exchange("q", Reply("err", is_error=True))
        self.assertEqual(self.brain.conversation_history, [])
        for i in range(60):
            self.brain.record_exchange(f"q{i}", "a" * 5000)
        self.assertEqual(len(self.brain.conversation_history), 100)
        self.assertEqual(len(self.brain.conversation_history[-1]["content"]), 4000)
        saved = json.loads(self.brain._history_file.read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 100)
        self.assertIn("Turns: 50 user, 50 assistant", self.brain.get_usage_stats())
        self.assertIn("cleared", self.brain.clear_history())

    def test_concurrent_turns_are_not_lost(self):
        def worker(n):
            for i in range(20):
                self.brain.record_exchange(f"{n}-{i}", "ok")
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        hist = self.brain.conversation_history
        self.assertEqual(len(hist), 100)
        # pairs stay adjacent
        for i in range(0, 100, 2):
            self.assertEqual((hist[i]["role"], hist[i + 1]["role"]), ("user", "assistant"))

    def test_save_failure_is_logged(self):
        self.brain._history_file = Path(self.tmp.name) / "f" / "h.json"
        (Path(self.tmp.name) / "f").write_text("file, not dir")
        self.brain._save_history()


class OpenAICompatTests(Base):
    def test_openrouter_headers_body_and_parts_content(self):
        self.use("or", provider="openrouter", model_id="meta/x:free", context_window=8192)
        r = resp({"choices": [{"message": {"content": [{"type": "text", "text": "Hel"}, {"text": "lo"}, "x"]}}]})
        with patch("requests.post", return_value=r) as post:
            self.assertEqual(self.brain.process_command("hi", use_tools=False), "Hello")
        url, kw = post.call_args.args[0], post.call_args.kwargs
        self.assertEqual(url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(kw["headers"]["Authorization"], "Bearer or-key")
        self.assertIn("HTTP-Referer", kw["headers"])
        self.assertEqual(kw["headers"]["X-Title"], "JARVIS")
        self.assertEqual(kw["json"]["model"], "meta/x:free")
        self.assertNotIn("tools", kw["json"])

    def test_tool_loop_openai_shape(self):
        reg = self.registry(echo=lambda x: f"echoed {x}")
        self.use("or", provider="openrouter", model_id="m", supports_tools=True)
        seen = []

        def post(url, json=None, **kw):
            seen.append(__import__("copy").deepcopy(json))
            return oa_tool("echo", {"x": "1"}) if len(seen) == 1 else oa_text("done")
        with patch("requests.post", side_effect=post):
            reply = self.brain.process_command("do it")
        self.assertEqual(reply, "done")
        self.assertEqual(seen[0]["tools"], reg.schemas())
        self.assertEqual(seen[0]["tool_choice"], "auto")
        msgs = seen[1]["messages"]
        self.assertEqual(msgs[-2]["role"], "assistant")
        self.assertEqual(msgs[-2]["tool_calls"][0]["id"], "call_abc")
        self.assertEqual(msgs[-1], {"role": "tool", "tool_call_id": "call_abc", "content": "echoed 1"})
        # only the user/assistant pair is stored, not tool traffic
        self.assertEqual([m["role"] for m in self.brain.conversation_history], ["user", "assistant"])

    def test_gemini_tool_call_without_id_gets_one_and_signature_is_echoed(self):
        self.registry(echo=lambda x: "ok")
        self.use("gemini-flash", provider="gemini", model_id="gemini-flash-latest", supports_tools=True)
        seen = []
        sig = {"extra_content": {"google": {"thought_signature": "abc"}}}

        def post(url, json=None, **kw):
            seen.append(__import__("copy").deepcopy(json))
            return oa_tool("echo", {"x": "1"}, call_id=None, extra=sig) if len(seen) == 1 else oa_text("fine")
        with patch("requests.post", side_effect=post):
            self.assertEqual(self.brain.process_command("go"), "fine")
        asst, tool = seen[1]["messages"][-2:]
        cid = asst["tool_calls"][0]["id"]
        self.assertTrue(cid)
        self.assertEqual(asst["tool_calls"][0]["extra_content"], sig["extra_content"])
        self.assertEqual(tool["tool_call_id"], cid)
        self.assertEqual(tool["name"], "echo")

    def test_json_in_content_is_treated_as_tool_call(self):
        calls = []
        self.registry(echo=lambda x: calls.append(x) or "ok")
        self.use("or", provider="openrouter", model_id="m", supports_tools=True)
        texts = ['```json\n{"name": "echo", "arguments": {"x": "7"}}\n```', "all set"]
        with patch("requests.post", side_effect=[oa_text(t) for t in texts]):
            self.assertEqual(self.brain.process_command("go"), "all set")
        self.assertEqual(calls, ["7"])
        # JSON that doesn't name a tool is an ordinary answer
        with patch("requests.post", return_value=oa_text('{"name": "nope", "arguments": {}}')):
            self.assertIn("nope", self.brain.process_command("go"))
        b = self.brain
        self.assertIsNone(b._content_tool_call("{bad json}"))
        self.assertIsNone(b._content_tool_call("[1]"))
        self.assertIsNone(b._content_tool_call('["a"]'.replace("[", "{").replace("]", "}")))
        self.assertIsNone(b._content_tool_call(None))
        self.assertEqual(b._content_tool_call('{"name": "echo", "parameters": "{}"}'),
                         {"name": "echo", "arguments": "{}"})

    def test_tool_loop_is_bounded_and_not_retried_elsewhere(self):
        runs = []
        self.registry(echo=lambda x: runs.append(x) or "ok")
        self.brain.available_models = {"a": dict(provider="openrouter", model_id="a", supports_tools=True),
                                       "b": dict(provider="openrouter", model_id="b", supports_tools=True)}
        self.brain.current_model = "a"
        bodies = []

        def post(url, json=None, **kw):
            bodies.append(dict(tool_choice=json.get("tool_choice"), model=json["model"]))
            return oa_tool("echo", {"x": "1"})
        with patch("requests.post", side_effect=post):
            reply = self.brain.process_command("loop")
        self.assertTrue(reply.is_error)
        self.assertEqual(len(bodies), self.m.MAX_TOOL_ROUNDS + 1)
        self.assertEqual(bodies[-1]["tool_choice"], "none")
        self.assertEqual({b["model"] for b in bodies}, {"a"})   # no failover re-running tools
        self.assertEqual(len(runs), self.m.MAX_TOOL_ROUNDS)

    def test_failure_after_tool_ran_is_not_retried(self):
        self.registry(echo=lambda x: "ok")
        self.brain.available_models = {"a": dict(provider="openrouter", model_id="a", supports_tools=True),
                                       "b": dict(provider="openrouter", model_id="b", supports_tools=True)}
        self.brain.current_model = "a"
        with patch("requests.post", side_effect=[oa_tool("echo", {"x": "1"}), resp({}, status=500)]) as post:
            reply = self.brain.process_command("go")
        self.assertTrue(reply.is_error)
        self.assertEqual(post.call_count, 2)

    def test_error_shapes(self):
        self.use("or", provider="openrouter", model_id="m")
        cases = [
            (resp({"error": {"message": "Upstream down", "code": 502}}), "Upstream down"),
            (resp({"error": "plain"}), "plain"),
            (resp({"choices": []}), "no answer"),
            (resp({"choices": [{"message": {"content": "  "}}]}), "empty answer"),
            (resp({"choices": [{"error": {"message": "provider crashed"}, "finish_reason": "error"}]}),
             "provider crashed"),
            (resp(bad_json=True, text="<html>"), "unreadable"),
            (resp("str"), "unreadable"),
        ]
        for r, expected in cases:
            with self.subTest(expected=expected), patch("requests.post", return_value=r):
                reply = self.brain.process_command("x")
                self.assertTrue(reply.is_error)
                self.assertIn(expected, reply)
        self.assertEqual(self.brain.conversation_history, [])
        self.assertTrue(self.brain.last_error)

    def test_gemini_list_wrapped_payloads(self):
        self.use("g", provider="gemini", model_id="gemini-flash-latest")
        with patch("requests.post", return_value=resp([{"choices": [{"message": {"content": "listy"}}]}])):
            self.assertEqual(self.brain.process_command("x"), "listy")
        bad_key = resp([{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                   "status": "INVALID_ARGUMENT"}}], status=400)
        self.brain.available_models["g2"] = dict(provider="gemini", model_id="gemini-pro-latest")
        self.brain.available_models["or"] = dict(provider="openrouter", model_id="m")
        with patch("requests.post", side_effect=[bad_key, oa_text("from openrouter")]) as post:
            reply = self.brain.process_command("x")
        # Bad Gemini key: skip the other Gemini model, fail over to OpenRouter.
        self.assertEqual(reply.model, "or")
        self.assertIn("invalid API key", reply)
        self.assertEqual(post.call_args.kwargs["json"]["model"], "m")

    def test_http_statuses_and_hints(self):
        self.use("or", provider="openrouter", model_id="m")
        for status, words, hint in [(401, "invalid API key", "API key in Settings"),
                                    (402, "out of credits", "out of credits"),
                                    (429, "rate limited", "rate-limited"),
                                    (503, "service unavailable", "try again shortly"),
                                    (400, "bad request", "connection"),
                                    (418, "error", "connection")]:
            with self.subTest(status=status), patch("requests.post",
                                                    return_value=resp({"error": {"message": "m"}}, status=status)):
                reply = self.brain.process_command("x")
                self.assertTrue(reply.is_error)
                self.assertIn(words, reply)
                self.assertIn(hint, reply)
        r = resp(bad_json=True, status=502, text="Bad Gateway html")
        with patch("requests.post", return_value=r):
            self.assertIn("Bad Gateway html", self.brain.process_command("x"))

    def test_timeout_and_network_errors(self):
        self.use("or", provider="openrouter", model_id="m")
        with patch("requests.post", side_effect=requests.ReadTimeout()):
            self.assertIn("timed out after 30s", self.brain.process_command("x"))
        with patch("requests.post", side_effect=requests.ConnectionError()):
            self.assertIn("network error: ConnectionError", self.brain.process_command("x"))

    def test_missing_key_and_unknown_provider_and_no_model(self):
        self.Config.OPENROUTER_API_KEY = ""
        self.use("or", provider="openrouter", model_id="m")
        self.assertIn("API key not configured", self.brain.process_command("x"))
        self.use("z", provider="mystery")
        self.assertIn("Unsupported provider", self.brain.process_command("x"))
        self.brain.current_model = None
        self.assertTrue(self.brain.process_command("x").is_error)

    def test_failover_message_names_original_model(self):
        self.brain.available_models = {"a": dict(provider="openrouter", model_id="a"),
                                       "openrouter-auto": dict(provider="openrouter", model_id="auto"),
                                       "b": dict(provider="gemini", model_id="b")}
        self.brain.current_model = "a"
        with patch("requests.post", side_effect=[resp({}, status=429), oa_text("from b")]):
            reply = self.brain.process_command("x")
        self.assertIn("Answered by b because a failed", reply)
        self.assertEqual(self.brain.conversation_history[-1]["content"], "from b")

    def test_memory_extraction_failure_does_not_break_chat(self):
        self.use("or", provider="openrouter", model_id="m")
        self.brain.memory.extract_from_message = Mock(side_effect=RuntimeError("x"))
        with patch("requests.post", return_value=oa_text("ok")):
            self.assertEqual(self.brain.process_command("x"), "ok")


class VisionTests(Base):
    def setUp(self):
        super().setUp()
        self.png = Path(self.tmp.name) / "shot.png"
        self.png.write_bytes(b"\x89PNG fake")
        self.jpg = Path(self.tmp.name) / "shot.JPG"
        self.jpg.write_bytes(b"\xff\xd8 fake")

    def test_user_message_shapes(self):
        um = self.m.MultiModelBrain._user_message
        self.assertEqual(um("gemini", "t", None), {"role": "user", "content": "t"})
        o = um("ollama", "t", str(self.png))
        self.assertEqual(o["images"], ["iVBORyBmYWtl"])
        g = um("gemini", "t", str(self.jpg))
        self.assertTrue(g["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,/9gg"))
        self.assertTrue(um("gemini", "t", str(self.png))["content"][1]["image_url"]["url"]
                        .startswith("data:image/png;base64,"))
        gif = Path(self.tmp.name) / "a.gif"
        gif.write_bytes(b"GIF89a")
        self.assertIn("data:image/gif;", um("openrouter", "t", str(gif))["content"][1]["image_url"]["url"])
        odd = Path(self.tmp.name) / "a.bin"
        odd.write_bytes(b"x")
        self.assertIn("data:image/png;", um("openrouter", "t", str(odd))["content"][1]["image_url"]["url"])

    def test_vision_models_and_ask_vision(self):
        b = self.brain
        b.available_models = {"t": dict(provider="openrouter", model_id="t"),
                              "v1": dict(provider="gemini", model_id="v1", supports_vision=True),
                              "v2": dict(provider="ollama", model_id="v2", supports_vision=True)}
        b.current_model = "t"
        self.assertEqual(b.vision_models(), ["v1", "v2"])
        self.Config.AUTOMATION_VISION_PROVIDER = "ollama"
        self.assertEqual(b.vision_models(), ["v2"])
        self.Config.AUTOMATION_VISION_MODEL = "v1"
        self.assertEqual(b.vision_models(), ["v1", "v2"])
        self.Config.AUTOMATION_VISION_PROVIDER, self.Config.AUTOMATION_VISION_MODEL = "auto", ""
        with patch("requests.post", side_effect=[resp({}, status=500), ollama_text("a button")]) as post:
            self.assertEqual(b.ask_vision("what?", str(self.png)), "a button")
        self.assertEqual(post.call_args.kwargs["json"]["messages"][-1]["images"], ["iVBORyBmYWtl"])
        with patch("requests.post", return_value=resp({}, status=500)):
            with self.assertRaises(self.m.ProviderError):
                b.ask_vision("what?", str(self.png))
        b.available_models = {}
        with self.assertRaises(self.m.ProviderError):
            b.ask_vision("x", str(self.png))

    def test_ask_text_no_history_no_tools_falls_back_across_models(self):
        b = self.brain
        b.available_models = {"broken": dict(provider="openrouter", model_id="m1"),
                              "good": dict(provider="ollama", model_id="m2")}
        b.current_model = "broken"
        b.conversation_history = [{"role": "user", "content": "earlier unrelated turn"}]
        self.registry(some_tool=lambda x: x)         # a registered tool must NOT be offered here
        with patch("requests.post", side_effect=[resp({}, status=500), ollama_text("import bpy\n")]) as post:
            self.assertEqual(b.ask_text("write some code"), "import bpy")
        last_call = post.call_args_list[-1]
        sent = last_call.kwargs["json"]["messages"]
        self.assertEqual([m["role"] for m in sent], ["system", "user"])   # no history, one user turn
        self.assertNotIn("tools", last_call.kwargs["json"])

    def test_ask_text_uses_a_custom_system_prompt(self):
        self.use("g", provider="gemini", model_id="m")
        with patch("requests.post", return_value=oa_text("ok")) as post:
            self.brain.ask_text("do it", system_prompt="You write terse Python.")
        self.assertEqual(post.call_args.kwargs["json"]["messages"][0],
                         {"role": "system", "content": "You write terse Python."})

    def test_ask_text_raises_when_nothing_is_available(self):
        self.brain.available_models = {}
        with self.assertRaises(self.m.ProviderError):
            self.brain.ask_text("x")

    def test_missing_image_is_an_error_reply_not_a_crash(self):
        self.use("g", provider="gemini", model_id="m", supports_vision=True)
        self.brain.available_models["g2"] = dict(provider="gemini", model_id="m2", supports_vision=True)
        with patch("requests.post") as post:
            reply = self.brain.process_command("look", image_path=str(Path(self.tmp.name) / "missing.png"))
        self.assertTrue(reply.is_error)
        self.assertIn("could not read image", reply)
        post.assert_not_called()

    def test_vision_process_command_openai_shape(self):
        self.use("g", provider="gemini", model_id="m", supports_vision=True)
        with patch("requests.post", return_value=oa_text("I see a cat")) as post:
            self.assertEqual(self.brain.process_command("look", image_path=str(self.png)), "I see a cat")
        user = post.call_args.kwargs["json"]["messages"][-1]
        self.assertEqual(user["content"][0], {"type": "text", "text": "look"})
        self.assertEqual(self.brain.conversation_history[0]["content"], "look")


class PlanStepsTests(Base):
    """MultiModelBrain.plan_steps: the LLM-driven multi-step-planning fallback."""

    def test_parses_numbered_list(self):
        with patch.object(self.brain, "ask_text", return_value="1. open chrome\n2. go to youtube\n3. play jazz"):
            self.assertEqual(self.brain.plan_steps("open chrome then go to youtube and play jazz"),
                             ["open chrome", "go to youtube", "play jazz"])

    def test_parses_list_with_parens(self):
        with patch.object(self.brain, "ask_text", return_value="1) do this\n2) do that"):
            self.assertEqual(self.brain.plan_steps("do this and that"), ["do this", "do that"])

    def test_single_step_response(self):
        with patch.object(self.brain, "ask_text", return_value="1. open chrome"):
            self.assertEqual(self.brain.plan_steps("open chrome"), ["open chrome"])

    def test_ignores_non_numbered_lines(self):
        with patch.object(self.brain, "ask_text", return_value="Here you go:\n1. step one\n2. step two\nDone."):
            self.assertEqual(self.brain.plan_steps("x"), ["step one", "step two"])

    def test_unparseable_response_falls_back_to_original(self):
        with patch.object(self.brain, "ask_text", return_value="I can't help with that."):
            self.assertEqual(self.brain.plan_steps("do the thing"), ["do the thing"])

    def test_empty_response_falls_back_to_original(self):
        with patch.object(self.brain, "ask_text", return_value=""):
            self.assertEqual(self.brain.plan_steps("do the thing"), ["do the thing"])

    def test_ask_text_error_falls_back_to_original(self):
        with patch.object(self.brain, "ask_text", side_effect=self.m.ProviderError("no model")):
            self.assertEqual(self.brain.plan_steps("do the thing"), ["do the thing"])

    def test_uses_plan_system_prompt(self):
        with patch.object(self.brain, "ask_text", return_value="1. x") as ask:
            self.brain.plan_steps("do the thing")
        self.assertEqual(ask.call_args.kwargs["system_prompt"], self.m._PLAN_SYSTEM_PROMPT)


class OllamaTests(Base):
    def test_tool_loop_dict_arguments(self):
        got = []
        self.registry(echo=lambda x: got.append(x) or "echo ok")
        self.use("ollama:l", provider="ollama", model_id="llama3.2", supports_tools=True, context_window=4096)
        seen = []

        def post(url, json=None, **kw):
            seen.append(__import__("copy").deepcopy(json))
            return ollama_tool("echo", {"x": "5"}) if len(seen) == 1 else ollama_text("done")
        with patch("requests.post", side_effect=post):
            self.assertEqual(self.brain.process_command("go"), "done")
        self.assertEqual(got, ["5"])
        self.assertEqual(seen[0]["options"]["num_ctx"], 4096)
        self.assertFalse(seen[0]["stream"])
        self.assertIn("tools", seen[0])
        self.assertEqual(seen[1]["messages"][-1], {"role": "tool", "content": "echo ok", "tool_name": "echo"})

    def test_json_content_tool_call_and_bounded_loop(self):
        got = []
        self.registry(echo=lambda x: got.append(x) or "ok")
        self.use("ollama:l", provider="ollama", model_id="llama3.2", supports_tools=True)
        with patch("requests.post", side_effect=[ollama_text('{"name": "echo", "parameters": "{\\"x\\": \\"9\\"}"}'),
                                                 ollama_text("fin")]):
            self.assertEqual(self.brain.process_command("go"), "fin")
        self.assertEqual(got, ["9"])
        seen = []

        def post(url, json=None, **kw):
            seen.append("tools" in json)
            return ollama_tool("echo", {"x": "1"})
        with patch("requests.post", side_effect=post):
            reply = self.brain.process_command("loop")
        self.assertTrue(reply.is_error)
        self.assertEqual(len(seen), self.m.MAX_TOOL_ROUNDS + 1)
        self.assertFalse(seen[-1])

    def test_errors(self):
        self.use("ollama:l", provider="ollama", model_id="llama3.2")
        cases = [
            (resp({"error": "model 'llama3.2' not found"}, status=404), "not found"),
            (resp(bad_json=True, status=500, text="boom"), "boom"),
            (resp(["x"], status=500, text="listy"), "listy"),
            (resp(bad_json=True), "unreadable"),
            (resp([1]), "unreadable"),
            (resp({"error": "out of memory"}), "out of memory"),
            (ollama_text("   "), "empty answer"),
        ]
        for r, expected in cases:
            with self.subTest(expected=expected), patch("requests.post", return_value=r):
                self.assertIn(expected, self.brain.process_command("x"))
        with patch("requests.post", side_effect=requests.ReadTimeout()):
            self.assertIn("timed out", self.brain.process_command("x"))
        with patch("requests.post", side_effect=requests.ConnectionError()):
            self.assertIn("not reachable", self.brain.process_command("x"))
        self.use("ollama:none", provider="ollama", model_id="")
        self.assertIn("model ID not set", self.brain.process_command("x"))

    def test_as_dict(self):
        f = self.m._as_dict
        self.assertEqual(f({"a": 1}), {"a": 1})
        self.assertEqual(f('{"a": 1}'), {"a": 1})
        self.assertEqual(f("[1]"), {})
        self.assertEqual(f("{bad"), {})
        self.assertEqual(f(""), {})


class MiscBrainTests(Base):
    def test_prompts_and_personality(self):
        self.brain.memory.memory["user_name"] = "Raghav"
        p = self.brain._get_system_prompt(with_tools=True)
        self.assertIn("Raghav", p)
        self.assertIn("tools", p)
        self.assertNotIn("provided tools", self.brain._get_system_prompt())
        self.assertIn("JARVIS online", self.brain.get_personality_response("startup"))
        self.assertIn("How may I help", self.brain.get_personality_response("other"))

    def test_benchmark(self):
        self.brain.available_models = {"a": dict(provider="ollama", model_id="a"),
                                       "b": dict(provider="ollama", model_id="b")}
        with patch("requests.post", side_effect=[ollama_text("fast"), resp({}, status=500)]):
            report = self.brain.benchmark_models(models=["a", "b", "zzz"])
        self.assertIn("ok, 4 chars", report)
        self.assertIn("failed", report)
        self.brain.available_models = {}
        self.assertEqual(self.brain.benchmark_models(), "No models to benchmark.")

    def test_reply_object(self):
        r = self.m.Reply("x", is_error=True, model="m")
        self.assertEqual((str(r), r.is_error, r.model), ("x", True, "m"))


class MemoryTests(Base):
    def setUp(self):
        super().setUp()
        from core.memory import MemoryManager
        self.MM = MemoryManager
        self.mem = MemoryManager()

    def test_persistence_unicode_and_dedupe(self):
        self.assertTrue(self.mem.remember_fact('"My café is Zoë\'s."'))
        self.assertFalse(self.mem.remember_fact("my CAFÉ is zoë's"))
        self.assertFalse(self.mem.remember_fact(""))
        self.assertFalse(self.mem.remember_fact("x" * 501))
        self.mem.set_user_name("  José ")
        self.mem.set_preference("tea", "green")
        again = self.MM()
        self.assertEqual(again.list_facts(), ["My café is Zoë's"])
        self.assertEqual(again.memory["user_name"], "José")
        self.assertIn("Zoë", self.mem.memory_file.read_text(encoding="utf-8"))
        s = again.summary()
        self.assertIn("Name: José", s)
        self.assertIn("tea: green", s)
        self.assertIn("1. My café", s)
        ctx = again.get_context_string()
        self.assertIn("The user's name is José.", ctx)
        self.assertIn("tea=green", ctx)

    def test_location_goes_to_settings(self):
        from core import config
        self.mem.set_preference("location", "Chennai")
        config.save_location_preference.assert_called_once_with("Chennai")
        config.get_location_preference.return_value = "Chennai"
        self.assertIn("Location: Chennai", self.mem.summary())
        self.assertIn("User location: Chennai.", self.mem.get_context_string())

    def test_empty_summary_and_cap(self):
        self.assertIn("anything stored", self.mem.summary())
        for i in range(self.MM.MAX_FACTS + 5):
            self.mem.remember_fact(f"fact {i}")
        self.assertEqual(len(self.mem.list_facts()), self.MM.MAX_FACTS)
        self.assertEqual(self.mem.list_facts()[0], "fact 5")

    def test_forget_variants(self):
        for f in ("likes tea", "likes coffee", "owns a cat"):
            self.mem.remember_fact(f)
        self.assertEqual(self.mem.forget(""), 0)          # never wipes everything
        self.assertEqual(self.mem.forget("   "), 0)
        self.assertEqual(len(self.mem.list_facts()), 3)
        self.assertEqual(self.mem.forget("2"), 1)
        self.assertEqual(self.mem.forget(9), 0)
        self.assertEqual(self.mem.forget("LIKES"), 1)
        self.assertEqual(self.mem.list_facts(), ["owns a cat"])
        self.assertEqual(self.mem.forget("name"), 0)
        self.mem.set_user_name("Ann")
        self.assertEqual(self.mem.forget("my name"), 1)
        self.assertIsNone(self.mem.memory["user_name"])
        self.mem.forget_all()
        self.assertEqual(self.MM().memory, {"user_name": None, "facts": [], "preferences": {}})

    def test_corrupt_and_malformed_files(self):
        self.mem.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.mem.memory_file.write_text("{oops", encoding="utf-8")
        m = self.MM()
        self.assertEqual(m.memory["facts"], [])
        self.assertTrue(self.mem.memory_file.with_suffix(".corrupt.json").exists())
        self.mem.memory_file.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(self.MM().memory["facts"], [])
        self.mem.memory_file.write_text(json.dumps({"facts": ["str", {"fact": 3}, {"fact": "ok"}, {"fact": " "}],
                                                    "preferences": [], "user_name": 7}), encoding="utf-8")
        m = self.MM()
        self.assertEqual(m.list_facts(), ["ok"])
        self.assertEqual(m.memory["preferences"], {})
        self.assertIsNone(m.memory["user_name"])
        self.assertTrue(m.remember_fact("new"))
        m.get_context_string()
        # Corrupt file whose backup can't be written
        self.mem.memory_file.write_text("{oops", encoding="utf-8")
        with patch.object(Path, "replace", side_effect=OSError("locked")):
            self.assertEqual(self.MM().memory["facts"], [])

    def test_save_failure_does_not_raise(self):
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            self.assertTrue(self.mem.remember_fact("still in memory"))
        self.assertEqual(self.mem.list_facts(), ["still in memory"])

    def test_concurrent_writes(self):
        def worker(n):
            for i in range(15):
                self.mem.remember_fact(f"t{n} f{i}")
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(self.mem.list_facts()), 60)
        self.assertEqual(len(self.MM().list_facts()), 60)

    def test_name_detection(self):
        cases = {
            "my name is Raghav": "Raghav",
            "Call me Tony Stark": "Tony Stark",
            "I’m José García": "José García",
            "I am Raghav and I code": "Raghav",
            "I'm Ann Busy": "Ann",
        }
        for text, name in cases.items():
            with self.subTest(text=text):
                self.mem.memory["user_name"] = None
                self.assertTrue(self.mem.extract_from_message(text))
                self.assertEqual(self.mem.memory["user_name"], name)
        for text in ("I'm Indian", "I am Vegan", "I'm OK", "I'm going home", "I am A", "I'm Sorry",
                     "i'm fine", "I am 30"):
            with self.subTest(text=text):
                self.mem.memory["user_name"] = None
                self.mem.extract_from_message(text)
                self.assertIsNone(self.mem.memory["user_name"])

    def test_explicit_remember_rules(self):
        stored = {
            "remember that my wifi is Falcon": "my wifi is Falcon",
            "Jarvis, please remember my locker is 42": "my locker is 42",
            "can you remember that my car is red?": "my car is red",
            "OK, don’t forget that I hate mornings": "I hate mornings",
        }
        for text, fact in stored.items():
            with self.subTest(text=text):
                self.mem.forget_all()
                self.assertTrue(self.mem.extract_from_message(text))
                self.assertEqual(self.mem.list_facts(), [fact])
        for text in ("do you remember my birthday?", "what do you remember about me", "remember to buy milk",
                     "I can't remember where I parked", "remember me?", "remember this"):
            with self.subTest(text=text):
                self.mem.forget_all()
                self.mem.extract_from_message(text)
                self.assertEqual(self.mem.list_facts(), [])
        self.assertFalse(self.mem.extract_from_message(""))
        self.assertFalse(self.mem.extract_from_message("x" * 401))

    def test_location_and_fact_detector(self):
        from core import config
        self.assertTrue(self.mem.extract_from_message("I live in São Paulo"))
        config.save_location_preference.assert_called_with("São Paulo")
        config.save_location_preference.reset_mock()
        for text in ("I'm from work", "I live in fear", "I moved to the kitchen", "i'm from the future"):
            self.mem.extract_from_message(text)
        config.save_location_preference.assert_not_called()          # not places: keep the saved one
        self.mem.extract_from_message("i moved to pune")                 # voice text is lower-case
        config.save_location_preference.assert_called_with("pune")
        self.mem.fact_detector = Mock(return_value=0.9)
        self.assertTrue(self.mem.extract_from_message("I'm allergic to peanuts"))
        self.assertIn("I'm allergic to peanuts", self.mem.list_facts())
        self.mem.fact_detector = Mock(return_value=0.1)
        self.assertFalse(self.mem.extract_from_message("I think it may rain"))
        self.mem.fact_detector = Mock(side_effect=RuntimeError("model down"))
        self.assertFalse(self.mem.extract_from_message("I prefer tea"))
        self.mem.fact_detector = Mock(return_value=None)
        self.assertFalse(self.mem.extract_from_message("my dog is old"))
        self.mem.fact_detector.reset_mock()
        self.mem.extract_from_message("the weather is nice")
        self.mem.fact_detector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
