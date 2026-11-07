"""SoftwareManager: winget wrapped as search/list/install/uninstall/upgrade, with
subprocess mocked so these run without Windows or winget installed."""
import subprocess
import unittest
from unittest.mock import Mock, patch

from skills.software_manager import Package, SoftwareManager, _parse_table


def _table(rows, cols=("Name", "Id", "Version", "Source")):
    widths = {"Name": 22, "Id": 28, "Version": 14, "Available": 14, "Source": 8}
    header = "".join(c.ljust(widths[c]) for c in cols)
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append("".join(str(row.get(c.lower(), "")).ljust(widths[c]) for c in cols))
    return "\n".join(lines) + "\n"


def proc(stdout="", returncode=0, stderr=""):
    return Mock(stdout=stdout, stderr=stderr, returncode=returncode)


class ParseTableTests(unittest.TestCase):
    def test_parses_rows_into_packages(self):
        text = _table([{"name": "VLC media player", "id": "VideoLAN.VLC", "version": "3.0.20", "source": "winget"},
                       {"name": "7-Zip", "id": "7zip.7zip", "version": "23.01", "source": "winget"}])
        packages = _parse_table(text)
        self.assertEqual(len(packages), 2)
        self.assertEqual(packages[0], Package("VLC media player", "VideoLAN.VLC", "3.0.20", "winget"))
        self.assertEqual(packages[1].id, "7zip.7zip")

    def test_no_header_returns_empty(self):
        self.assertEqual(_parse_table("No package found matching input criteria."), [])

    def test_str_includes_version(self):
        self.assertEqual(str(Package("7-Zip", "7zip.7zip", "23.01")), "7-Zip (7zip.7zip) v23.01")


class AvailabilityTests(unittest.TestCase):
    def test_unavailable_when_winget_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            sm = SoftwareManager()
            self.assertFalse(sm.available())
            self.assertIn("winget isn't available", sm.install("vlc"))

    def test_available_when_winget_responds(self):
        with patch("subprocess.run", return_value=proc("v1.6.0")):
            self.assertTrue(SoftwareManager().available())


class SearchListTests(unittest.TestCase):
    def setUp(self):
        self.sm = SoftwareManager()
        self.sm._available = True

    def test_search_parses_results(self):
        text = _table([{"name": "VLC media player", "id": "VideoLAN.VLC", "version": "3.0.20"}])
        with patch("subprocess.run", return_value=proc(text)):
            results = self.sm.search("vlc")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, "VideoLAN.VLC")

    def test_is_installed_true_and_false(self):
        text = _table([{"name": "7-Zip", "id": "7zip.7zip", "version": "23.01"}])
        with patch("subprocess.run", return_value=proc(text)):
            self.assertTrue(self.sm.is_installed("7-Zip"))
        with patch("subprocess.run", return_value=proc("No installed package found.")):
            self.assertFalse(self.sm.is_installed("nonexistent thing"))

    def test_format_list_empty(self):
        self.assertEqual(self.sm.format_list([], "nothing here"), "nothing here")
        self.assertEqual(self.sm.format_list([Package("7-Zip", "7zip.7zip")], "x"), "• 7-Zip (7zip.7zip)")


class WriteActionTests(unittest.TestCase):
    def setUp(self):
        self.sm = SoftwareManager()
        self.sm._available = True

    def test_install_success(self):
        search_text = _table([{"name": "VLC media player", "id": "VideoLAN.VLC", "version": "3.0.20"}])
        with patch("subprocess.run", side_effect=[proc(search_text), proc("Successfully installed", 0)]):
            result = self.sm.install("vlc")
        self.assertIn("Installed VLC media player (VideoLAN.VLC)", result)

    def test_install_not_found(self):
        with patch("subprocess.run", return_value=proc("No package found matching input criteria.")):
            result = self.sm.install("totally-not-a-real-app")
        self.assertIn("couldn't find", result)

    def test_install_failure_includes_exit_code(self):
        search_text = _table([{"name": "Thing", "id": "Vendor.Thing", "version": "1.0"}])
        with patch("subprocess.run", side_effect=[proc(search_text), proc("", 1, "installer error")]):
            result = self.sm.install("thing")
        self.assertIn("failed (exit 1)", result)

    def test_uninstall_not_installed(self):
        with patch("subprocess.run", return_value=proc("No installed package found matching input criteria.")):
            result = self.sm.uninstall("nope")
        self.assertIn("doesn't look like it's installed", result)

    def test_uninstall_success(self):
        list_text = _table([{"name": "7-Zip", "id": "7zip.7zip", "version": "23.01"}])
        with patch("subprocess.run", side_effect=[proc(list_text), proc("Successfully uninstalled", 0)]):
            result = self.sm.uninstall("7-zip")
        self.assertIn("Uninstalled 7-Zip (7zip.7zip)", result)

    def test_upgrade_all(self):
        with patch("subprocess.run", return_value=proc("2 packages have available upgrades", 0)):
            result = self.sm.upgrade()
        self.assertIn("available upgrades", result)

    def test_upgrade_all_nothing_to_do(self):
        with patch("subprocess.run", return_value=proc("", 0)):
            result = self.sm.upgrade("all")
        self.assertIn("already current", result)

    def test_upgrade_one_not_installed(self):
        with patch("subprocess.run", return_value=proc("No installed package found matching input criteria.")):
            result = self.sm.upgrade("nope")
        self.assertIn("doesn't look like it's installed", result)

    def test_timeout_gives_a_reasonable_message(self):
        search_text = _table([{"name": "Thing", "id": "Vendor.Thing", "version": "1.0"}])
        with patch("subprocess.run", side_effect=[proc(search_text), subprocess.TimeoutExpired("winget", 300)]):
            result = self.sm.install("thing")
        self.assertIn("taking a while", result)


if __name__ == "__main__":
    unittest.main()
