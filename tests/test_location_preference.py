"""Location preference unification (audit UC 10.4)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class LocationPreferenceTests(unittest.TestCase):
    """One store of truth: the JARVIS_LOCATION env var drives weather + AI memory."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.environ = {k: v for k, v in os.environ.items() if k != 'JARVIS_LOCATION'}
        self.environ['APPDATA'] = self.temp.name
        self.env_patch = patch.dict(os.environ, self.environ, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        import core.config as config
        import core.memory as memory
        # Patch the actual consumers; reloading config leaves imported Config
        # references stale and does not redirect its project-local MEMORY_DIR.
        for target, attribute, value in (
            (config, 'APPDATA_DIR', Path(self.temp.name) / 'Jarvis'),
            (config, 'ENV_PATH', Path(self.temp.name) / 'Jarvis' / '.env'),
            (memory.Config, 'MEMORY_DIR', Path(self.temp.name) / 'memory'),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_saved_location_reaches_env_file_memory_and_weather(self):
        from core.config import save_location_preference, ENV_PATH
        from core.memory import MemoryManager
        from skills.weather import WeatherSkill

        save_location_preference('London, UK')
        self.assertEqual(os.environ['JARVIS_LOCATION'], 'London, UK')
        from dotenv import dotenv_values
        self.assertEqual(dotenv_values(ENV_PATH)['JARVIS_LOCATION'], 'London, UK')
        self.assertIn('London', MemoryManager().get_context_string())
        self.assertEqual(WeatherSkill()._get_auto_location(), 'London, UK')

    def test_cleared_location_removes_preference_everywhere(self):
        from core.config import save_location_preference
        from core.memory import MemoryManager

        save_location_preference('London, UK')
        save_location_preference(None)
        self.assertIsNone(os.environ.get('JARVIS_LOCATION'))
        self.assertNotIn('JARVIS_LOCATION',
                         Path(os.environ['APPDATA'], 'Jarvis', '.env').read_text(encoding='utf-8'))
        self.assertNotIn('User location', MemoryManager().get_context_string())

    def test_no_invented_city_when_nothing_set(self):
        from core.memory import MemoryManager
        self.assertNotIn('Chennai', MemoryManager().get_context_string())
        self.assertNotIn('User location', MemoryManager().get_context_string())

    def test_chat_stated_location_used_when_no_setting(self):
        from core.memory import MemoryManager
        memory = MemoryManager()
        memory.set_preference('location', 'Bristol')
        self.assertIn('Bristol', memory.get_context_string())

    def test_preference_survives_reload_and_clear_does_not_restore_legacy_city(self):
        from core.config import save_location_preference, load_env
        from core.memory import MemoryManager
        save_location_preference('Paris, France')
        os.environ.pop('JARVIS_LOCATION')
        load_env()
        self.assertEqual(os.environ['JARVIS_LOCATION'], 'Paris, France')
        memory = MemoryManager()
        memory.memory['preferences']['location'] = 'Legacy City'
        memory._save()
        save_location_preference(None)
        load_env()
        self.assertNotIn('User location', MemoryManager().get_context_string())
        self.assertNotIn('Legacy City', MemoryManager().get_context_string())

    def test_failed_save_keeps_previous_runtime_preference(self):
        from core.config import save_location_preference
        save_location_preference('Paris')
        with patch('dotenv.set_key', side_effect=PermissionError('read only')):
            with self.assertRaises(PermissionError):
                save_location_preference('Berlin')
        self.assertEqual(os.environ['JARVIS_LOCATION'], 'Paris')

    def test_rejects_multiline_location(self):
        from core.config import save_location_preference
        with self.assertRaises(ValueError):
            save_location_preference('London\nUNRELATED=value')
        self.assertNotIn('JARVIS_LOCATION', os.environ)

    def test_detection_failure_does_not_invent_city_or_reuse_cleared_cache(self):
        from core.config import save_location_preference
        from skills.weather import WeatherSkill
        weather = WeatherSkill()
        save_location_preference('Paris')
        self.assertEqual(weather._get_auto_location(), 'Paris')
        save_location_preference(None)
        with patch('skills.weather.requests.get', side_effect=OSError('offline')), \
             patch.object(weather, '_get_weather_from_web') as fetch_weather:
            self.assertIn('Specify a city', weather.get_weather())
            fetch_weather.assert_not_called()
        self.assertIsNone(weather.location_cache)




if __name__ == '__main__':
    unittest.main()
