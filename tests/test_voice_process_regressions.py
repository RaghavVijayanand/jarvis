"""Offline voice-duration and exact process-selection regressions."""
import os
import unittest
from unittest.mock import Mock, MagicMock

import psutil
from tests.test_audit_regressions import load_class


class ProcessSelectionTests(unittest.TestCase):
    def setUp(self):
        self.psutil = Mock(NoSuchProcess=psutil.NoSuchProcess,
                           AccessDenied=psutil.AccessDenied)
        cls = load_class('skills/system_control.py', 'SystemControl',
                         dict(psutil=self.psutil, os=os))
        self.control = cls.__new__(cls)

    def process(self, name, pid=987654):
        return Mock(info={'name': name, 'pid': pid})

    def test_blank_path_and_wildcard_never_enumerate_processes(self):
        for name in ('', '  ', None, '*', 'chrome?', 'C:\\chrome.exe'):
            self.assertIn('exact executable name', self.control.kill_process(name))
        self.psutil.process_iter.assert_not_called()

    def test_exact_name_not_substring_case_insensitive(self):
        exact = self.process('CHROME.EXE')
        unrelated = self.process('chromedriver.exe')
        missing = self.process(None)
        self.psutil.process_iter.return_value = [unrelated, missing, exact]
        self.assertIn('Killed 1', self.control.kill_process(' chrome '))
        exact.kill.assert_called_once_with()
        unrelated.kill.assert_not_called()
        missing.kill.assert_not_called()

    def test_partial_name_does_not_match(self):
        process = self.process('chrome.exe')
        self.psutil.process_iter.return_value = [process]
        self.assertIn('No processes killed', self.control.kill_process('chrom'))
        process.kill.assert_not_called()

    def test_protected_and_denied_processes_are_reported(self):
        processes = [self.process('jarvis.exe', pid) for pid in (0, 4, os.getpid())]
        denied = self.process('jarvis.exe')
        denied.kill.side_effect = psutil.AccessDenied(987654)
        self.psutil.process_iter.return_value = processes + [denied]
        self.assertIn('4 protected or access-denied', self.control.kill_process('jarvis.exe'))
        for process in processes:
            process.kill.assert_not_called()

    def test_disappearing_process_does_not_stop_other_matches(self):
        gone, active = self.process('demo.exe'), self.process('demo.exe')
        gone.kill.side_effect = psutil.NoSuchProcess(987654)
        self.psutil.process_iter.return_value = [gone, active]
        self.assertIn('Killed 1', self.control.kill_process('demo.exe'))
        active.kill.assert_called_once_with()


class VoiceDurationTests(unittest.TestCase):
    def setUp(self):
        import core.voice as voice_module
        self.voice = voice_module.VoiceEngine.__new__(voice_module.VoiceEngine)
        self.voice.sr_available = True
        self.voice.microphone = MagicMock()
        self.voice.recognizer = Mock()
        self.voice.recognizer.recognize_google.return_value = 'A complete command'

    def test_both_listeners_allow_fifteen_second_commands(self):
        for method in (self.voice.listen_for_command, self.voice.listen_continuously):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(), 'a complete command')
                self.assertEqual(self.voice.recognizer.listen.call_args.kwargs['phrase_time_limit'], 15)
                self.assertFalse(self.voice.is_listening)

    def test_explicit_phrase_limit_is_preserved(self):
        self.voice.listen_for_command(phrase_timeout=25)
        self.assertEqual(self.voice.recognizer.listen.call_args.kwargs['phrase_time_limit'], 25)


if __name__ == '__main__':
    unittest.main()
