"""Focused regression for the user-facing overwrite confirmation flow."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skills.file_manager import FileManagerSkill


class OverwriteConfirmationTests(unittest.TestCase):
    def test_create_prompt_yes_preserves_proposed_content(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(FileManagerSkill, '_default_documents_folder',
                              return_value=Path(directory)):
                skill = FileManagerSkill()
            path = Path(directory) / 'notes.txt'

            created = skill.route_command('create file notes.txt with content original')
            self.assertIn('created successfully', created)
            self.assertEqual(path.read_text(encoding='utf-8'), 'original')

            prompt = skill.route_command('create file notes.txt with content Replacement Text')
            self.assertIn('Reply yes to overwrite, or cancel', prompt)
            self.assertEqual(path.read_text(encoding='utf-8'), 'original')

            confirmed = skill.route_command('yes')
            self.assertIn('created successfully', confirmed)
            self.assertEqual(path.read_text(encoding='utf-8'), 'Replacement Text')
            self.assertIsNone(skill.route_command('yes'))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        with patch.object(FileManagerSkill, '_default_documents_folder', return_value=self.directory):
            self.skill = FileManagerSkill()
        self.path = self.directory / 'notes.txt'
        self.path.write_text('original', encoding='utf-8')

    def request_overwrite(self):
        return self.skill.route_command('create file notes.txt with content Replacement Text')

    def test_cancel_preserves_original(self):
        self.request_overwrite()
        self.assertIn('cancelled', self.skill.route_command('cancel'))
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'original')
        self.assertIsNone(self.skill.route_command('yes'))

    def test_external_change_is_not_overwritten(self):
        self.request_overwrite()
        self.path.write_text('edited elsewhere', encoding='utf-8')
        self.assertIn('file changed', self.skill.route_command('yes'))
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'edited elsewhere')

    def test_expired_confirmation_does_not_write(self):
        with patch('skills.file_manager.time.monotonic', return_value=0):
            self.request_overwrite()
        with patch('skills.file_manager.time.monotonic', return_value=121):
            self.assertIn('expired', self.skill.route_command('yes'))
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'original')

    def test_unrelated_turn_invalidates_confirmation(self):
        self.request_overwrite()
        self.assertIsNone(self.skill.route_command('what time is it'))
        self.assertIsNone(self.skill.route_command('yes'))
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'original')

    def test_directory_change_does_not_redirect_pending_write(self):
        self.request_overwrite()
        other = self.directory / 'other'
        other.mkdir()
        self.skill.change_directory(str(other))
        self.assertIn('created successfully', self.skill.route_command('yes'))
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'Replacement Text')
        self.assertFalse((other / 'notes.txt').exists())

    def test_wrong_confirmation_filename_is_rejected(self):
        self.request_overwrite()
        self.assertIn('does not match', self.skill.route_command('overwrite other.txt'))
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'original')
        self.assertIn('created successfully', self.skill.route_command('overwrite notes.txt'))

    def test_create_at_location_retains_content_for_confirmation(self):
        self.skill.create_file_at_location('notes.txt', content='Unicode: café 日本語')
        self.assertIn('created successfully', self.skill.route_command('yes'))
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'Unicode: café 日本語')

    def test_jarvis_routes_confirmation_before_classifier(self):
        from unittest.mock import Mock, patch
        from tests.test_audit_regressions import bare_jarvis
        app, module = bare_jarvis()
        app.file_skill = self.skill
        app._classify_command_intent = Mock(side_effect=AssertionError('Unexpected AI classification'))
        with patch.object(module, 'console'):
            self.assertIn('Reply yes', app.process_command(
                'create file notes.txt with content New Content', use_voice=False))
            self.assertIn('created successfully', app.process_command('yes', use_voice=False))
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'New Content')
        app._classify_command_intent.assert_not_called()


if __name__ == '__main__':
    unittest.main()
