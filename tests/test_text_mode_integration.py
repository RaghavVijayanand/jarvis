"""End-to-end text-mode test: real command loop, all external boundaries mocked."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import unittest

APP_ROOT = str(Path(__file__).resolve().parents[1])


class TextModeLoopTests(unittest.TestCase):
    def test_reply_reaches_console_and_exit_stops_loop(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(temp.name)
        self.addCleanup(os.chdir, old_cwd)
        environ = {k: v for k, v in os.environ.items()
                   if k not in ('OPENROUTER_API_KEY', 'GEMINI_API_KEY')}
        environ['APPDATA'] = temp.name

        def canned_brain(prompt, *args, **kwargs):
            if 'intent' in prompt.lower():
                return 'GENERAL'
            return 'Hello from fake brain.'

        with patch.dict(os.environ, environ, clear=True), \
             patch('jarvis.console') as console, \
             patch('jarvis.VoiceEngine'), \
             patch('jarvis.MultiModelBrain') as brain_cls, \
             patch('jarvis.TaskScheduler'), \
             patch('jarvis.SystemMonitor'), \
             patch('jarvis.ScreenAutomationSkill'), \
             patch('jarvis.AutomationSkill'), \
             patch('jarvis.ApplicationControl'), \
             patch('jarvis.DecisionEngine', side_effect=lambda **kw: __import__('core.decision', fromlist=['x']).DecisionEngine(engine='rules')), \
             patch('skills.system_control.subprocess') as subprocess_mod, \
             patch('skills.automation.pyautogui') as automation_gui:
            brain_cls.return_value.process_command.side_effect = canned_brain
            brain_cls.return_value.available_models = {}
            sys.path.insert(0, APP_ROOT)
            try:
                import jarvis as jarvis_module
                app = jarvis_module.JARVIS()
                app.is_running = True
                # 'exit' breaks the loop (no SystemExit by design); the trailing
                # EOFError sentinel terminates it if that ever regresses.
                with patch('builtins.input', side_effect=['hello there', 'exit', EOFError]):
                    app.run_text_mode()
            finally:
                sys.path.remove(APP_ROOT)
                sys.modules.pop('jarvis', None)

        printed = ' '.join(str(c.args[0]) for c in console.print.call_args_list if c.args)
        self.assertIn('Hello from fake brain.', printed)
        self.assertIn('Goodbye!', printed)
        self.assertEqual(subprocess_mod.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
