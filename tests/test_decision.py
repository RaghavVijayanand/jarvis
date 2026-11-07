"""Decision engine: deterministic rules and Laya integration (with a fake Laya agent)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.decision import DecisionEngine, INTENTS, _prepare_hf_cache_env, rule_decision


class RuleTests(unittest.TestCase):
    CASES = {
        "what time is it": "time", "whats the date today": "time", "whats 12*7": "math",
        "15% of 200": "math", "what is 5 plus 3": "math", "weather in London": "weather",
        "will it rain tomorrow": "weather", "open chrome": "open", "close spotify": "open",
        "go to github.com": "open", "play despacito": "open", "search for python news": "search",
        "who is the president of france": "search", "latest headlines": "search",
        "pause": "media", "next track": "media", "volume 40": "media", "mute": "media",
        "cpu usage": "system", "battery status": "system", "lock my pc": "control",
        "restart the computer": "control", "show desktop": "control", "open bluetooth settings": "control",
        "empty the recycle bin": "control", "delete everything in the recycle bin": "control",
        "clear my recycle bin": "control", "clean out the recycle bin": "control",
        "install VLC": "software", "uninstall notepad++": "software", "update all apps": "software",
        "is python installed": "software",
        "make a chair model in blender": "appscript", "model a car in Blender": "appscript",
        "list wifi networks": "network", "connect to wifi HomeNet": "network",
        "forget the wifi HomeNet": "network", "forget that I like tea": "memory",
        "ping google.com": "network", "flush the dns": "network",
        "what is using my cpu": "service", "top processes by memory": "service",
        "list services": "service", "start the spooler service": "service",
        "is the spooler service running": "service",
        "list power plans": "power", "what is the active power plan": "power",
        "switch the power plan to balanced": "power", "list startup apps": "power",
        "enable OneDrive at startup": "power", "disable Spotify from startup": "power",
        "clipboard history": "productivity", "clear clipboard history": "productivity",
        "what does my screen say": "productivity", "read the pdf report.pdf": "productivity",
        "read the word document notes.docx": "productivity",
        "defender status": "security", "bitlocker status": "security",
        "check for windows updates": "security", "install windows updates": "security",
        "list monitors": "layout", "save the current layout as gaming": "layout",
        "restore layout gaming": "layout", "snap chrome to left-half": "layout",
        "list my recent emails": "email", "what is on my calendar": "email",
        "upcoming events": "email",
        "tell me when setup.exe appears": "watch", "notify me if cpu stays above 90": "watch",
        "list watchers": "watch",
        "index folder C:\\Docs": "fileindex", "remove folder C:\\Docs from the index": "fileindex",
        "clear the file index": "fileindex", "file index status": "fileindex",
        "search my files for Q3 budget": "fileindex", "find the document about the Q3 budget": "fileindex",
        "start the dashboard": "dashboard", "stop the dashboard": "dashboard",
        "dashboard status": "dashboard", "is the dashboard running": "dashboard",
        "list plugins": "plugins", "plugin status": "plugins", "which plugins are installed": "plugins",
        "create file notes.txt with content hi": "file", "open notes.txt": "file", "list files": "file",
        "remind me to call mom in 5 minutes": "schedule", "set an alarm for 7 am": "schedule",
        "take a screenshot": "screen", "what's on my screen": "screen", "click the save button": "screen",
        "type hello world": "screen", "remember that I like tea": "memory",
        "what do you know about me": "memory", "tell me a joke": "fun", "flip a coin": "fun",
        "explain quantum computing": "chat", "how do I quit smoking?": "chat",
    }

    def test_rule_intents(self):
        for text, intent in self.CASES.items():
            with self.subTest(text=text):
                self.assertEqual(rule_decision(text).intent, intent)

    def test_multi_step_detection(self):
        self.assertTrue(rule_decision("open notepad and type hello").is_multi_step)
        self.assertTrue(rule_decision("open chrome, then go to youtube and play jazz").is_multi_step)
        self.assertFalse(rule_decision("go to youtube and play jazz").is_multi_step)
        self.assertFalse(rule_decision("take a screenshot and tell me what you see").is_multi_step)
        self.assertFalse(rule_decision("what is the capital of france").is_multi_step)

    def test_destructive_flag(self):
        self.assertTrue(rule_decision("delete file a.txt").is_destructive)
        self.assertTrue(rule_decision("shutdown the computer").is_destructive)
        self.assertFalse(rule_decision("open notepad").is_destructive)


class FakeLaya:
    """Mimics laya.Agent.predict's documented output shape."""

    def __init__(self, choice, confidence, multi=0.1, destructive=0.05, raise_first=None):
        self.choice, self.confidence = choice, confidence
        self.multi, self.destructive = multi, destructive
        self.raise_first = raise_first
        self.calls = []

    def predict(self, state, questions):
        self.calls.append((state, questions))
        if self.raise_first:
            exc, self.raise_first = self.raise_first, None
            raise exc
        answers = {}
        for qid, q in questions.items():
            if q["type"] == "choice":
                crit = q["criteria"]
                keys = list(crit) if isinstance(crit, (dict, list)) else []
                answers[qid] = {"type": "choice", "choice": self.choice, "confidence": self.confidence,
                                "probabilities": {k: (self.confidence if k == self.choice else 0.01) for k in keys}}
            else:
                value = {"multi_step": self.multi, "destructive": self.destructive}.get(qid, 0.9)
                answers[qid] = {"type": "noul", "noul": value, "confidence": max(value, 1 - value)}
        return {"model": "laya-rl-agent", "answers": answers, "usage": {}}


class LayaIntegrationTests(unittest.TestCase):
    def engine(self, agent, threshold=0.45):
        engine = DecisionEngine(engine="laya", threshold=threshold)
        engine._agent = agent
        return engine

    def test_confident_model_answer_is_used(self):
        agent = FakeLaya("media", 0.93, multi=0.8)
        decision = self.engine(agent).decide("could you make it a bit quieter in here")
        self.assertEqual((decision.intent, decision.source), ("media", "laya"))
        self.assertTrue(decision.is_multi_step)
        _, questions = agent.calls[0]
        self.assertEqual(set(questions["intent"]["criteria"]), set(INTENTS))
        self.assertEqual(questions["multi_step"]["type"], "noul")

    def test_precise_rule_beats_unsure_model(self):
        decision = self.engine(FakeLaya("chat", 0.6)).decide("what time is it")
        self.assertEqual((decision.intent, decision.source), ("time", "rules"))

    def test_unsure_model_without_rule_falls_back_to_chat(self):
        decision = self.engine(FakeLaya("file", 0.2)).decide("hmm tell me something interesting")
        self.assertEqual(decision.intent, "chat")

    def test_destructive_signal_from_either_source(self):
        decision = self.engine(FakeLaya("control", 0.9, destructive=0.1)).decide("restart the computer")
        self.assertTrue(decision.is_destructive)

    def test_option_budget_overflow_retries_with_labels(self):
        agent = FakeLaya("weather", 0.9, raise_first=ValueError("question 'intent' options exceed head_max_len=192"))
        engine = self.engine(agent)
        self.assertEqual(engine.decide("is it chilly out").intent, "weather")
        self.assertIsInstance(agent.calls[-1][1]["intent"]["criteria"], list)

    def test_model_error_degrades_to_rules(self):
        agent = Mock()
        agent.predict.side_effect = RuntimeError("CUDA exploded")
        self.assertEqual(self.engine(agent).decide("open spotify").intent, "open")

    def test_yes_no_helper(self):
        engine = self.engine(FakeLaya("chat", 0.9))
        self.assertAlmostEqual(engine.yes_no("I am allergic to peanuts", "Is this a personal fact?"), 0.9)
        self.assertIsNone(DecisionEngine(engine="laya").yes_no("x", "y"))

    def test_missing_package_reports_rules_only(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "laya":
                raise ImportError("no laya")
            return real_import(name, *args, **kwargs)

        engine = DecisionEngine(engine="laya")
        statuses = []
        engine.set_status_callback(statuses.append)
        builtins.__import__ = fake_import
        try:
            engine._load()
        finally:
            builtins.__import__ = real_import
        self.assertFalse(engine.laya_ready)
        self.assertIn("pip install laya", statuses[-1])

    def test_rules_engine_never_loads(self):
        engine = DecisionEngine(engine="rules")
        engine.warm_up_async()
        self.assertFalse(engine._loading)
        self.assertEqual(engine.decide("lock my pc").intent, "control")


class HFCacheEnvTests(unittest.TestCase):
    """_prepare_hf_cache_env points Hugging Face Hub's cache at a JARVIS-managed
    (or bundled, when frozen) folder — never clobbers a user-set HF_HOME."""

    def setUp(self):
        self._old_hf_home = os.environ.pop("HF_HOME", None)
        self._old_frozen = getattr(sys, "frozen", None)
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        if self._old_hf_home is not None:
            os.environ["HF_HOME"] = self._old_hf_home
        else:
            os.environ.pop("HF_HOME", None)
        if self._old_frozen is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = self._old_frozen
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_leaves_existing_hf_home_alone(self):
        os.environ["HF_HOME"] = "/already/set"
        _prepare_hf_cache_env()
        self.assertEqual(os.environ["HF_HOME"], "/already/set")

    def test_not_frozen_uses_models_dir(self):
        with patch("core.decision.Config") as cfg:
            cfg.MODELS_DIR = self.tmp / "models"
            _prepare_hf_cache_env()
        self.assertEqual(os.environ["HF_HOME"], str(self.tmp / "models" / "hf_cache"))
        self.assertTrue((self.tmp / "models" / "hf_cache").is_dir())

    def test_frozen_with_bundled_cache_uses_it(self):
        bundled = self.tmp / "hf_cache"
        bundled.mkdir()
        sys.frozen = True
        with patch("core.decision.sys.executable", str(self.tmp / "JARVIS.exe")):
            _prepare_hf_cache_env()
        self.assertEqual(os.environ["HF_HOME"], str(bundled))

    def test_frozen_without_bundled_cache_falls_back(self):
        sys.frozen = True
        with patch("core.decision.sys.executable", str(self.tmp / "nowhere" / "JARVIS.exe")):
            with patch("core.decision.Config") as cfg:
                cfg.MODELS_DIR = self.tmp / "models"
                _prepare_hf_cache_env()
        self.assertEqual(os.environ["HF_HOME"], str(self.tmp / "models" / "hf_cache"))

    def test_mkdir_failure_is_swallowed(self):
        with patch("core.decision.Config") as cfg:
            cfg.MODELS_DIR = self.tmp / "models"
            with patch("pathlib.Path.mkdir", side_effect=OSError("no space")):
                _prepare_hf_cache_env()  # must not raise
        self.assertNotIn("HF_HOME", os.environ)


if __name__ == "__main__":
    unittest.main()
