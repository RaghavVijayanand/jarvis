import struct
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.conversation import FRAME, FRAME_S, ConversationMode, EchoGuard, rms, words


def tone(level: int) -> bytes:
    return struct.pack(f"<{FRAME}h", *([level, -level] * (FRAME // 2)))


class EchoGuardTests(unittest.TestCase):
    def guard(self, spoken="the weather in delhi is sunny today", noise=50.0):
        g = EchoGuard()
        g.begin(spoken, noise)
        return g

    def test_rms_and_words(self):
        self.assertAlmostEqual(rms(tone(1000)), 1000.0)
        self.assertEqual(rms(b""), 0.0)
        self.assertEqual(words("It's SUNNY, today!"), ["it's", "sunny", "today"])

    def test_own_words_are_echo_new_words_are_the_user(self):
        g = self.guard()
        self.assertFalse(g.user_words(["weather", "in", "delhi", "sunny"]))   # JARVIS hearing itself
        self.assertTrue(g.user_words(["sunny", "play", "music"]))            # two new words in a row
        self.assertFalse(g.user_words(["sunny", "the", "uh"]))               # filler isn't evidence
        self.assertTrue(g.user_words(["stop"]))                               # stop words cut in at once

    def test_stop_word_jarvis_is_saying_itself_is_not_an_interrupt(self):
        g = self.guard("please wait while I check")
        self.assertFalse(g.user_words(["please", "wait"]))

    def test_headphones_any_real_speech_interrupts(self):
        g = self.guard(noise=50.0)
        quiet = [g.feed(tone(60), 60.0) for _ in range(int(0.6 / FRAME_S))]   # no echo coming back
        self.assertFalse(any(quiet))
        loud = [g.feed(tone(2000), 2000.0) for _ in range(int(0.3 / FRAME_S))]
        self.assertTrue(loud[-1])

    def test_speakers_without_recognizer_need_clearly_louder_speech(self):
        g = self.guard(noise=50.0)
        echo = [g.feed(tone(900), 900.0) for _ in range(int(1.0 / FRAME_S))]  # JARVIS through the speakers
        self.assertFalse(any(echo))
        same = [g.feed(tone(1300), 1300.0) for _ in range(int(0.6 / FRAME_S))]
        self.assertFalse(any(same))                     # echo getting a bit louder isn't the user
        user = [g.feed(tone(5000), 5000.0) for _ in range(int(0.6 / FRAME_S))]
        self.assertTrue(user[-1])


class FakeVoice:
    def __init__(self):
        self.is_speaking = False
        self.speaking_text = ""
        self.spoken = []
        self.stopped = 0

    def speak(self, text, summarize=False):
        self.spoken.append(text)

    def stop_speaking(self):
        self.stopped += 1


class TurnTests(unittest.TestCase):
    def make(self, replies=None, transcripts=None):
        events = []
        jarvis = SimpleNamespace(voice_engine=FakeVoice(), stream=None, _voice_mode=False)
        jarvis.process_command = Mock(side_effect=replies or (lambda text, use_voice=False: f"re: {text}"))
        queue = list(transcripts or [])
        conv = ConversationMode(jarvis, on_event=lambda kind, info: events.append((kind, info)),
                                transcriber=lambda audio: queue.pop(0) if queue else "",
                                model_loader=lambda say: None)
        return conv, jarvis, events

    def test_turn_is_answered_and_spoken(self):
        conv, jarvis, events = self.make(transcripts=["what's the time"])
        conv._transcribing = 1
        conv._take_turn(b"audio")
        jarvis.process_command.assert_called_once_with("what's the time", use_voice=False)
        self.assertEqual(jarvis.voice_engine.spoken, ["re: what's the time"])
        self.assertIn(("heard", {"text": "what's the time"}), events)

    def test_silence_or_noise_is_ignored(self):
        conv, jarvis, events = self.make(transcripts=[""])
        conv._transcribing = 1
        conv._take_turn(b"noise")
        jarvis.process_command.assert_not_called()
        self.assertEqual(conv._transcribing, 0)

    def test_talking_while_jarvis_thinks_merges_into_one_request(self):
        gate = threading.Event()

        def slow(text, use_voice=False):
            if text == "open spotify":
                gate.wait(2)
            return f"re: {text}"
        conv, jarvis, _ = self.make(replies=slow, transcripts=["open spotify", "and play some jazz"])
        conv._transcribing = 1
        first = threading.Thread(target=conv._take_turn, args=(b"1",))
        first.start()
        time.sleep(0.1)
        conv._transcribing += 1
        second = threading.Thread(target=conv._take_turn, args=(b"2",))
        second.start()
        time.sleep(0.1)
        gate.set()
        first.join(3)
        second.join(3)
        self.assertEqual(jarvis.process_command.call_args.args[0], "open spotify and play some jazz")
        self.assertEqual(jarvis.voice_engine.spoken, ["re: open spotify and play some jazz"])   # stale answer dropped

    def test_spoken_confirmation(self):
        conv, jarvis, _ = self.make(transcripts=["yes go ahead"])
        result = {}
        asker = threading.Thread(target=lambda: result.setdefault("ok", conv.ask_yes_no("Delete it?", timeout=3)))
        asker.start()
        time.sleep(0.1)
        conv._transcribing = 1
        conv._take_turn(b"yes")
        asker.join(3)
        self.assertTrue(result["ok"])
        jarvis.process_command.assert_not_called()      # the answer went to the question, not a new turn

    def test_interrupt_stops_speech_but_keeps_the_turn(self):
        conv, jarvis, events = self.make()
        before = conv._turn
        conv._interrupt()
        self.assertEqual(jarvis.voice_engine.stopped, 1)
        self.assertEqual(conv._turn, before)
        self.assertIn(("interrupted", {}), events)

    def test_mic_loop_end_to_end(self):
        """Fake mic: silence, a spoken request, silence → one transcribed turn."""
        conv, jarvis, events = self.make(transcripts=["hello jarvis"])
        frames = [tone(40)] * 20 + [tone(3000)] * 20 + [tone(40)] * 40
        deadline = time.time() + 3

        def read(n, exception_on_overflow=False):
            if frames:
                return frames.pop(0)
            time.sleep(0.01)                            # mic stays quiet until JARVIS has answered
            if jarvis.voice_engine.spoken or time.time() > deadline:
                conv._stop.set()
            return tone(40)
        stream = SimpleNamespace(read=read)
        conv._calibrate(stream, seconds=0.3)
        conv._loop(stream)
        self.assertEqual(jarvis.voice_engine.spoken, ["re: hello jarvis"])
        self.assertIn(("listening", {}), events)


if __name__ == "__main__":
    unittest.main()
