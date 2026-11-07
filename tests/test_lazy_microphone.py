"""Hardware-free tests of the production VoiceEngine class."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch



class LazyMicrophoneTests(unittest.TestCase):
    def setUp(self):
        self.sr = Mock()
        self.sr.Microphone.return_value = MagicMock()
        self.sr.Microphone.list_microphone_names.return_value = ['Default', 'USB']
        tts = Mock()
        tts.init.return_value.getProperty.return_value = []
        import core.voice as voice_module
        for name, value in (('sr', self.sr), ('pyttsx3', tts)):
            patcher = patch.object(voice_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.voice = voice_module.VoiceEngine()
        self.voice.recognizer.recognize_google.return_value = 'Hello'

    def test_constructor_does_not_open_or_enumerate_microphones(self):
        self.sr.Microphone.assert_not_called()
        self.sr.Microphone.list_microphone_names.assert_not_called()
        self.voice.recognizer.adjust_for_ambient_noise.assert_not_called()
        self.assertIsNone(self.voice.microphone)

    def test_first_listen_opens_and_calibrates_once(self):
        self.assertEqual(self.voice.listen_for_command(), 'hello')
        self.assertEqual(self.voice.listen_for_command(), 'hello')
        self.sr.Microphone.assert_called_once_with(device_index=None)
        self.voice.recognizer.adjust_for_ambient_noise.assert_called_once()
        self.assertFalse(self.voice.is_listening)

    def test_continuous_listener_also_initializes_microphone(self):
        self.assertEqual(self.voice.listen_continuously(), 'hello')
        self.sr.Microphone.assert_called_once_with(device_index=None)
        self.assertFalse(self.voice.is_listening)

    def test_missing_device_is_retryable(self):
        self.sr.Microphone.side_effect = [OSError('no device'), MagicMock()]
        self.assertIsNone(self.voice.listen_for_command())
        self.voice.recognizer.listen.assert_not_called()
        self.assertIsNone(self.voice.microphone)
        self.assertFalse(self.voice.is_listening)
        self.assertEqual(self.voice.listen_for_command(), 'hello')

    def test_failed_initial_calibration_is_retryable(self):
        self.voice.recognizer.adjust_for_ambient_noise.side_effect = [OSError('busy'), None]
        self.assertFalse(self.voice._ensure_microphone())
        self.assertIsNone(self.voice.microphone)
        self.assertTrue(self.voice._ensure_microphone())

    def test_failed_replacement_keeps_previous_device_and_index(self):
        self.assertTrue(self.voice.set_microphone(0))
        previous = self.voice.microphone
        self.voice.recognizer.adjust_for_ambient_noise.side_effect = OSError('busy')
        self.assertFalse(self.voice.set_microphone(1))
        self.assertIs(self.voice.microphone, previous)
        self.assertEqual(self.voice.selected_mic_index, 0)

    def test_successful_selection_is_reused_by_listener(self):
        self.assertTrue(self.voice.set_microphone(1))
        self.assertEqual(self.voice.listen_for_command(), 'hello')
        self.sr.Microphone.assert_called_once_with(device_index=1)
        self.assertEqual(self.voice.selected_mic_index, 1)

    def test_invalid_selection_does_not_open_hardware(self):
        self.assertFalse(self.voice.set_microphone(9))
        self.sr.Microphone.assert_not_called()

    def test_explicit_calibration_initializes_and_reports_failure(self):
        self.assertTrue(self.voice.calibrate_microphone())
        self.voice.recognizer.adjust_for_ambient_noise.side_effect = OSError('busy')
        self.assertFalse(self.voice.calibrate_microphone())


if __name__ == '__main__':
    unittest.main()
