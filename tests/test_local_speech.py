import threading
import unittest
from unittest.mock import patch

import numpy as np

from core import local_speech
from core.config import Config


class SplitTests(unittest.TestCase):
    def test_short_first_chunk_then_grouped_sentences(self):
        text = "Done. I've opened Spotify for you. It's playing lo-fi now. Want anything else? Just ask."
        chunks = local_speech.split_sentences(text)
        self.assertEqual(chunks[0], "Done. I've opened Spotify for you.")     # tiny opener joins the next one
        self.assertEqual(" ".join(chunks), text)
        self.assertTrue(all(len(c) <= 200 for c in chunks))

    def test_empty(self):
        self.assertEqual(local_speech.split_sentences("  "), [])


class KokoroSpeakTests(unittest.TestCase):
    def make(self, synth=None):
        voice = local_speech.KokoroVoice()
        voice._kokoro = object()                                      # "loaded"
        voice.synth = synth or (lambda text: (np.zeros(240, dtype=np.float32), 24000))
        return voice

    def test_plays_every_chunk_in_order(self):
        made, played = [], []
        voice = self.make(lambda text: made.append(text) or (text, 24000))
        with patch.object(local_speech, "_play", lambda s, r, stop: played.append(s)):
            self.assertTrue(voice.speak("First one here. Second sentence follows. Third.", threading.Event()))
        self.assertEqual(played, made)
        self.assertEqual(" ".join(played), "First one here. Second sentence follows. Third.")

    def test_stop_cuts_it_off(self):
        stop = threading.Event()
        played = []

        def play(samples, rate, ev):
            played.append(samples)
            stop.set()                                                # user talks over the first chunk
        voice = self.make(lambda text: (text, 24000))
        with patch.object(local_speech, "_play", play):
            voice.speak("One sentence is long enough here. Two. Three. Four is the last one.", stop)
        self.assertEqual(len(played), 1)

    def test_synthesis_failure_before_any_audio_falls_back(self):
        def boom(text):
            raise RuntimeError("onnx")
        voice = self.make(boom)
        with patch.object(local_speech, "_play", lambda *a: None):
            self.assertFalse(voice.speak("Hello there, how are you?", threading.Event()))


class WhisperTests(unittest.TestCase):
    def ears(self, text):
        class Seg:
            def __init__(self, t):
                self.text, self.no_speech_prob = t, 0.1

        class Model:
            def transcribe(self, audio, **kw):
                return [Seg(text)], None
        e = local_speech.WhisperEars()
        e._backend = ("cpu", Model())
        return e

    def pcm(self, seconds):
        return (np.ones(int(16000 * seconds), dtype=np.int16) * 1000).tobytes()

    def test_transcribes(self):
        self.assertEqual(self.ears(" Open Spotify.").transcribe(self.pcm(1.5)), "Open Spotify.")

    def test_hallucination_on_a_short_clip_is_dropped(self):
        self.assertEqual(self.ears(" Thank you.").transcribe(self.pcm(1.0)), "")
        self.assertEqual(self.ears(" Thank you.").transcribe(self.pcm(3.0)), "Thank you.")   # long: really said
        self.assertEqual(self.ears("hi").transcribe(self.pcm(0.1)), "")                         # a click

    def test_off_when_google_is_chosen(self):
        with patch.object(Config, "STT_ENGINE", "google"):
            self.assertIsNone(local_speech.transcribe(self.pcm(1)))


class DownloadTests(unittest.TestCase):
    def fake_get(self, body, length):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.headers = {"content-length": str(length)}
        resp.iter_content.return_value = [body]
        return patch("requests.get", return_value=resp)

    def test_complete_download_is_published(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, self.fake_get(b"abcd", 4):
            target = Path(d) / "m.onnx"
            self.assertTrue(local_speech._download("https://x/m", target, "m"))
            self.assertEqual(target.read_bytes(), b"abcd")

    def test_truncated_download_is_discarded(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, self.fake_get(b"ab", 4):
            target = Path(d) / "m.onnx"
            self.assertFalse(local_speech._download("https://x/m", target, "m"))
            self.assertEqual(list(Path(d).iterdir()), [])        # neither the model nor a .part left


class LocalOnlyTests(unittest.TestCase):
    """JARVIS_LOCAL_ONLY promises nothing goes to the cloud — that includes voice."""

    def test_voice_never_uses_google_or_edge_tts(self):
        from unittest.mock import MagicMock
        from core import voice as voice_mod
        from core import conversation
        engine = voice_mod.VoiceEngine.__new__(voice_mod.VoiceEngine)
        engine.recognizer = MagicMock()
        engine.tts_engine = MagicMock()
        engine._tts_lock, engine._stop_speaking = threading.Lock(), threading.Event()
        engine._speak_edge_tts = MagicMock(return_value=True)
        with patch.object(Config, "LOCAL_ONLY", True), patch.object(Config, "STT_ENGINE", "google"), \
                patch.object(Config, "TTS_ENGINE", "edge"), patch.object(voice_mod, "_EDGE_TTS_AVAILABLE", True), \
                patch.dict(Config.VOICE_SETTINGS, {"enabled": True}):
            self.assertIsNone(engine._recognize(MagicMock()))
            engine.speak("hello")
            with patch("speech_recognition.Recognizer") as rec:
                conversation.transcribe(b"\0\0" * 100)
        engine.recognizer.recognize_google.assert_not_called()
        rec.return_value.recognize_google.assert_not_called()
        engine._speak_edge_tts.assert_not_called()
        engine.tts_engine.say.assert_called_once_with("hello")      # offline SAPI voice instead


if __name__ == "__main__":
    unittest.main()
