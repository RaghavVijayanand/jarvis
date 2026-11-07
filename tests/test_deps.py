"""core.deps: turning "No module named 'x'" into an actionable install message."""
import unittest

from core.deps import missing_package_message


class MissingPackageMessageTests(unittest.TestCase):
    def test_known_package_gets_pip_name_and_hint(self):
        exc = ModuleNotFoundError("No module named 'pyaudio'")
        exc.name = "pyaudio"
        msg = missing_package_message(exc, "The microphone")
        self.assertIn("The microphone needs the 'pyaudio' package", msg)
        self.assertIn("pip install PyAudio", msg)
        self.assertIn("pipwin", msg)                       # the Windows-build fallback is included

    def test_known_package_without_extra_hint_has_no_trailing_parens(self):
        exc = ModuleNotFoundError("No module named 'winsdk'")
        exc.name = "winsdk"
        msg = missing_package_message(exc, "Now playing")
        self.assertEqual(msg, "Now playing needs the 'winsdk' package, which isn't installed. "
                               "Install it with: pip install winsdk")

    def test_unknown_module_falls_back_to_its_own_name(self):
        exc = ModuleNotFoundError("No module named 'frobnicate'")
        exc.name = "frobnicate"
        msg = missing_package_message(exc, "Something")
        self.assertIn("pip install frobnicate", msg)

    def test_non_module_error_falls_back_to_str(self):
        exc = OSError("no default input device")
        msg = missing_package_message(exc, "The microphone")
        self.assertEqual(msg, "The microphone: no default input device")

    def test_module_not_found_without_name_falls_back_to_str(self):
        exc = ModuleNotFoundError("mystery")
        exc.name = None
        msg = missing_package_message(exc, "Something")
        self.assertEqual(msg, "Something: mystery")


if __name__ == "__main__":
    unittest.main()
