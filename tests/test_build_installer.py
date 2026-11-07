"""build/build_installer.py: sanity checks on the parts that don't need
Windows or a real PyInstaller/Inno Setup toolchain — warm_up_laya()'s
best-effort error handling, and that the new --skip-laya-warmup flag exists
and is wired the way build/jarvis.spec expects (JARVIS_BUNDLE_LAYA defaults
to bundling Laya)."""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_PATH = Path(__file__).resolve().parent.parent / "build" / "build_installer.py"
_spec = importlib.util.spec_from_file_location("jarvis_build_installer", _PATH)
build_installer = importlib.util.module_from_spec(_spec)
sys.modules["jarvis_build_installer"] = build_installer
_spec.loader.exec_module(build_installer)


class WarmUpLayaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._old_cache = build_installer.HF_CACHE
        build_installer.HF_CACHE = self.tmp / "_hf_cache"

    def tearDown(self):
        build_installer.HF_CACHE = self._old_cache
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_cache_dir(self):
        with patch.object(build_installer, "run", side_effect=subprocess.CalledProcessError(1, "x")):
            build_installer.warm_up_laya()  # must not raise
        self.assertTrue(build_installer.HF_CACHE.is_dir())

    def test_subprocess_failure_is_caught_not_raised(self):
        with patch.object(build_installer, "run", side_effect=subprocess.CalledProcessError(1, "x")):
            build_installer.warm_up_laya()  # no exception propagates

    def test_timeout_is_caught_not_raised(self):
        with patch.object(build_installer, "run", side_effect=subprocess.TimeoutExpired("x", 1800)):
            build_installer.warm_up_laya()

    def test_oserror_is_caught_not_raised(self):
        with patch.object(build_installer, "run", side_effect=OSError("no python")):
            build_installer.warm_up_laya()

    def test_success_path_runs_with_hf_home_env(self):
        captured = {}

        def fake_run(cmd, **kw):
            captured.update(kw)
            return None

        with patch.object(build_installer, "run", side_effect=fake_run):
            build_installer.warm_up_laya()
        self.assertEqual(captured["env"]["HF_HOME"], str(build_installer.HF_CACHE))

    def test_uses_configured_laya_repo(self):
        captured = {}

        def fake_run(cmd, **kw):
            captured["code"] = cmd[-1]

        with patch.object(build_installer, "run", side_effect=fake_run):
            build_installer.warm_up_laya()
        self.assertIn("Config.LAYA_REPO", captured["code"])
        self.assertIn("Config.LAYA_MODEL", captured["code"])


class DefaultsTests(unittest.TestCase):
    def test_bundle_laya_defaults_on(self):
        # jarvis.spec and build_installer.py both read JARVIS_BUNDLE_LAYA with
        # the same default ('1') — Laya bundles unless explicitly opted out.
        spec_text = (Path(__file__).resolve().parent.parent / "build" / "jarvis.spec").read_text(encoding="utf-8")
        self.assertIn("os.getenv('JARVIS_BUNDLE_LAYA', '1')", spec_text)

    def test_spec_bundles_prewarmed_cache_when_present(self):
        spec_text = (Path(__file__).resolve().parent.parent / "build" / "jarvis.spec").read_text(encoding="utf-8")
        self.assertIn("HF_CACHE.is_dir()", spec_text)
        self.assertIn("'hf_cache'", spec_text)

    def test_skip_laya_warmup_flag_exists(self):
        import argparse
        parser = argparse.ArgumentParser()
        # Re-derive the same flags main() registers, to check the option string without running main().
        source = _PATH.read_text(encoding="utf-8")
        self.assertIn('"--skip-laya-warmup"', source)
        self.assertIn("warm_up_laya()", source)

    def test_pyaudio_is_not_a_hard_requirement(self):
        # PyAudio compiles against PortAudio and has no wheel on every Python version — a build
        # failure there must not block installing everything else in requirements.txt.
        root = Path(__file__).resolve().parent.parent
        req_text = (root / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("\nPyAudio>=", req_text)
        self.assertIn("#   PyAudio>=0.2.14", req_text)
        # It's still attempted, just as its own non-fatal step, everywhere requirements install.
        self.assertIn("PyAudio", (root / "setup.py").read_text(encoding="utf-8"))
        self.assertIn("PyAudio", (root / "build_installer.bat").read_text(encoding="utf-8"))

    def test_pyaudio_is_an_optional_pyinstaller_hidden_import(self):
        spec_text = (Path(__file__).resolve().parent.parent / "build" / "jarvis.spec").read_text(encoding="utf-8")
        # Bundled only if actually importable at build time (same pattern as winsdk), not
        # hard-coded into the unconditional hidden-imports list.
        self.assertIn("'pyaudio'", spec_text)
        unconditional_list_line = [l for l in spec_text.splitlines() if "'vosk', 'bs4'" in l]
        self.assertTrue(unconditional_list_line)
        self.assertNotIn("pyaudio", unconditional_list_line[0])


if __name__ == "__main__":
    unittest.main()
