"""Offline audit regressions: brain providers, routing safety, alarms, shell refusal."""
import ast
from datetime import datetime
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_class(relative_path, class_name, namespace):
    """Compile one class from a source file without importing its module."""
    tree = ast.parse((ROOT / relative_path).read_text(encoding='utf-8-sig'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / relative_path), 'exec'), namespace)
    return namespace[class_name]


def ok_response(payload):
    response = Mock(status_code=200)
    response.json.return_value = payload
    return response


class BrainTestCase(unittest.TestCase):
    """Real core.brain module with an isolated Config and no network."""

    def setUp(self):
        from core import brain as brain_module
        from core.config import Config
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for attr, value in dict(LOGS_DIR=Path(self.temp.name), CACHE_DIR=Path(self.temp.name),
                                OPENROUTER_API_KEY='test-key', GEMINI_API_KEY='', DEFAULT_MODEL='',
                                REQUEST_TIMEOUT=45, OLLAMA_URL='http://localhost:11434').items():
            patcher = patch.object(Config, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.Config = Config
        for target, value in ((brain_module, 'MemoryManager'),):
            patcher = patch.object(target, value, Mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(brain_module.MultiModelBrain, '_check_local_models', return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.module = brain_module
        self.cls = brain_module.MultiModelBrain
        self.brain = self.cls()
        self.brain._get_system_prompt = Mock(return_value='Test system prompt')

    def use(self, name, **cfg):
        self.brain.available_models = {name: cfg}
        self.brain.current_model = name


class BrainRegressionTests(BrainTestCase):
    def test_no_keys_and_no_local_models_means_no_default(self):
        self.Config.OPENROUTER_API_KEY = ''
        self.brain.current_model = None
        self.brain._initialize_providers()
        self.brain._set_default_model()
        self.assertEqual(self.brain.available_models, {})
        self.assertIsNone(self.brain.current_model)
        reply = self.brain.process_command('hi')
        self.assertIn('No model selected', reply)
        self.assertTrue(reply.is_error)

    def test_openrouter_message_occurs_once_and_timeout_is_set(self):
        self.use('or', provider='openrouter', model_id='m', context_window=8192)
        with patch('requests.post', return_value=ok_response(
                {'choices': [{'message': {'content': 'answer'}}]})) as post:
            self.assertEqual(self.brain.process_command('hello'), 'answer')
        args = post.call_args.kwargs
        self.assertEqual(args['timeout'], (5, 45))
        self.assertEqual([m['content'] for m in args['json']['messages']].count('hello'), 1)
        self.assertEqual([m['role'] for m in self.brain.conversation_history], ['user', 'assistant'])

    def test_internal_requests_do_not_persist_history_or_memory(self):
        self.use('or', provider='openrouter', model_id='m')
        with patch.object(self.brain, '_call_model', return_value='GENERAL'):
            self.assertEqual(self.brain.process_command('classify this', use_context=False), 'GENERAL')
        self.brain.memory.extract_from_message.assert_not_called()
        self.assertEqual(self.brain.conversation_history, [])
        self.assertFalse(self.brain._history_file.exists())

    def test_provider_errors_are_flagged_not_stored(self):
        self.use('or', provider='openrouter', model_id='m')
        failing = Mock(status_code=401, text='bad key')
        failing.json.return_value = {'error': {'message': 'User not found'}}
        with patch('requests.post', return_value=failing):
            reply = self.brain.process_command('hello')
        self.assertTrue(reply.is_error)
        self.assertIn('invalid API key', reply)
        self.assertEqual(self.brain.conversation_history, [])

    def test_failover_to_next_model(self):
        self.brain.available_models = {'a': dict(provider='openrouter', model_id='a'),
                                       'b': dict(provider='openrouter', model_id='b')}
        self.brain.current_model = 'a'
        not_found = Mock(status_code=404, text='')
        not_found.json.return_value = {'error': {'message': 'No endpoints'}}
        with patch('requests.post', side_effect=[not_found, ok_response(
                {'choices': [{'message': {'content': 'from b'}}]})]):
            reply = self.brain.process_command('hello')
        self.assertFalse(reply.is_error)
        self.assertIn('from b', reply)
        self.assertEqual(reply.model, 'b')

    def test_clear_history_persists_across_reload(self):
        self.brain.conversation_history = [{'role': 'user', 'content': 'old'}]
        self.brain._save_history()
        self.brain.clear_history()
        self.brain._load_history()
        self.assertEqual(self.brain.conversation_history, [])
        self.assertEqual(self.brain._history_file.read_text().strip(), '[]')

    def test_ollama_context_matches_advertised_size(self):
        self.use('local', provider='ollama', model_id='local-test', context_window=8192)
        with patch('requests.post', return_value=ok_response({'message': {'content': 'local answer'}})) as post:
            self.assertEqual(self.brain.process_command('hello'), 'local answer')
        args = post.call_args.kwargs
        self.assertEqual(args['json']['options']['num_ctx'], 8192)
        self.assertEqual(args['timeout'], (5, 45))
        self.assertEqual(len(args['json']['messages']), 2)

    def test_gemini_uses_openai_endpoint_without_duplicate_turn(self):
        self.Config.GEMINI_API_KEY = 'g-key'
        self.use('gemini', provider='gemini', model_id='gemini-flash-latest')
        with patch('requests.post', return_value=ok_response(
                {'choices': [{'message': {'content': 'gemini answer'}}]})) as post:
            self.assertEqual(self.brain.process_command('hello'), 'gemini answer')
        self.assertIn('generativelanguage.googleapis.com', post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer g-key')
        contents = [m['content'] for m in post.call_args.kwargs['json']['messages']]
        self.assertEqual(contents.count('hello'), 1)

    def test_benchmark_times_each_model_and_restores_current(self):
        self.brain.available_models = {'a': dict(provider='openrouter', model_id='a'),
                                       'b': dict(provider='openrouter', model_id='b')}
        self.brain.current_model = 'a'
        with patch.object(self.brain, '_call_model', side_effect=['ok text', self.module.ProviderError('down')]):
            report = self.brain.benchmark_models()
        self.assertIn('a', report)
        self.assertIn('failed: down', report)
        self.assertEqual(self.brain.current_model, 'a')


class HistoryBudgetTests(BrainTestCase):
    """UC 10.2: request history must fit the model's context window."""

    def test_budget_defaults_and_reserves_headroom(self):
        self.assertEqual(self.cls._history_budget(8192), (8192 - 1024) * 4)
        self.assertEqual(self.cls._history_budget(None), 7168 * 4)
        self.assertEqual(self.cls._history_budget('bad'), 7168 * 4)
        self.assertEqual(self.cls._history_budget(0), 7168 * 4)
        self.assertEqual(self.cls._history_budget(64), 128 * 4)

    def test_window_keeps_newest_turns_within_budget(self):
        for index in range(12):
            self.brain.conversation_history.append({'role': 'user', 'content': f'old{index}'})
        self.brain.conversation_history += [
            {'role': 'user', 'content': 'A' * 100},
            {'role': 'assistant', 'content': 'B' * 100},
            {'role': 'user', 'content': 'C' * 100},
        ]
        window = self.brain._history_window(2 * (100 + 8))
        self.assertEqual([m['content'] for m in window], ['B' * 100, 'C' * 100])

    def test_oversized_turn_is_dropped_and_order_preserved(self):
        self.brain.conversation_history = [
            {'role': 'user', 'content': 'x' * 200},
            {'role': 'assistant', 'content': 'y' * 60},
            {'role': 'user', 'content': 'z' * 10},
        ]
        window = self.brain._history_window(100)
        self.assertEqual([m['content'] for m in window], ['y' * 60, 'z' * 10])

    def test_openrouter_request_respects_history_budget(self):
        self.brain.conversation_history = [
            {'role': 'user', 'content': 'x' * 40000},
            {'role': 'assistant', 'content': 'y' * 40000},
            {'role': 'user', 'content': 'earlier question'},
        ]
        self.use('or', provider='openrouter', model_id='m', context_window=8192)
        with patch('requests.post', return_value=ok_response(
                {'choices': [{'message': {'content': 'answer'}}]})) as post:
            self.assertEqual(self.brain.process_command('final question'), 'answer')
        sent = post.call_args.kwargs['json']['messages']
        contents = [m['content'] for m in sent]
        self.assertEqual(contents.count('final question'), 1)
        self.assertNotIn('x' * 40000, contents)
        history = [m for m in sent if m['role'] in ('user', 'assistant')][:-1]
        self.assertLessEqual(sum(len(m['content']) for m in history), self.cls._history_budget(8192))

    def test_whole_prompt_plus_reply_fits_the_window(self):
        """System prompt, question and reply share the window: history only gets the rest."""
        self.brain.conversation_history = [{'role': 'user' if i % 2 == 0 else 'assistant',
                                            'content': f'{i}' * 3000} for i in range(10)]
        self.use('or', provider='openrouter', model_id='m', context_window=8192)
        with patch('requests.post', return_value=ok_response(
                {'choices': [{'message': {'content': 'answer'}}]})) as post:
            self.brain.process_command('q' * 2000, max_tokens=1500)
        sent = post.call_args.kwargs['json']['messages']
        used = sum(len(m['content']) for m in sent) + 1500 * 4
        self.assertLessEqual(used, self.cls._history_budget(8192))
        self.assertGreater(len(sent), 2)                 # some history still fits


def bare_jarvis():
    """A JARVIS object without running __init__ (no hardware, no threads)."""
    import jarvis as jarvis_module
    app = jarvis_module.JARVIS.__new__(jarvis_module.JARVIS)
    app.is_sleeping = False
    app.voice_engine = Mock()
    app.shutdown = Mock()
    return app, jarvis_module


class SafetyRoutingTests(unittest.TestCase):
    def setUp(self):
        self.jarvis, self.module = bare_jarvis()
        self.jarvis._classify_command_intent = Mock(return_value='GENERAL')
        self.jarvis._handle_classified_command = Mock(return_value='normal answer')
        patcher = patch.object(self.module, 'console')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_lifecycle_words_inside_questions_do_not_trigger_actions(self):
        for command in ['How do I quit smoking?', "Don't go to sleep yet", 'Why do I wake early?']:
            with self.subTest(command=command):
                self.assertEqual(self.jarvis.process_command(command, use_voice=False), 'normal answer')
                self.jarvis.shutdown.assert_not_called()
                self.assertFalse(self.jarvis.is_sleeping)

    def test_exact_exit_still_works(self):
        self.jarvis.process_command('quit', use_voice=False)
        self.jarvis.shutdown.assert_called_once_with()

    def test_weather_passes_original_query(self):
        self.jarvis.weather_skill = Mock()
        self.jarvis.weather_skill.get_weather.return_value = 'London weather'
        result = type(self.jarvis)._handle_classified_command(self.jarvis, 'Weather in London', 'WEATHER', False)
        self.assertEqual(result, 'London weather')
        self.jarvis.weather_skill.get_weather.assert_called_once_with('Weather in London')

    def test_alarm_rolls_over_month_and_year_without_scheduler(self):
        for now in [datetime(2026, 1, 31, 23), datetime(2026, 12, 31, 23), datetime(2028, 2, 29, 23)]:
            with self.subTest(now=now), patch('threading.Thread') as thread, \
                    patch('handlers.schedule.datetime', Mock(now=Mock(return_value=now))):
                self.assertIn('Alarm set', self.jarvis._set_alarm('7 am', use_voice=False))
                thread.return_value.start.assert_called_once_with()

    def test_alarm_uses_persistent_scheduler_when_available(self):
        self.jarvis.task_scheduler = Mock()
        self.jarvis.task_scheduler.schedule_alarm.return_value = 'Alarm set for 7:00 AM Wednesday.'
        with patch('handlers.schedule.datetime', Mock(now=Mock(return_value=datetime(2026, 1, 31, 23)))):
            self.assertIn('Alarm set', self.jarvis._set_alarm('set an alarm for 7 am', use_voice=False))
        at = self.jarvis.task_scheduler.schedule_alarm.call_args.args[0]
        self.assertEqual((at.month, at.day, at.hour), (2, 1, 7))

    def test_shell_skill_refuses_without_subprocess(self):
        subprocess = Mock()
        cls = load_class('skills/system_control.py', 'SystemControl', dict(subprocess=subprocess))
        result = cls.__new__(cls).run_command('echo test')
        self.assertIn('disabled', result)
        subprocess.run.assert_not_called()

    def test_no_shell_tool_is_exposed_to_models(self):
        names = []
        for path in sorted((ROOT / 'handlers').glob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            names += [node.args[0].value for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr == 'add' and node.args and isinstance(node.args[0], ast.Constant)]
        self.assertIn('open_app_or_website', names)
        for forbidden in ('run_command', 'shell', 'powershell', 'cmd', 'execute'):
            self.assertNotIn(forbidden, names)


if __name__ == '__main__':
    unittest.main()
