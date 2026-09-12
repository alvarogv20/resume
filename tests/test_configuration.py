import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from automation.executables import resolve_tool

from automation.config import load_settings


class ConfigurationTests(unittest.TestCase):
    def test_tool_discovered_beside_python_when_path_is_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            python = Path(folder) / 'python.exe'
            tool = Path(folder) / ('tectonic.exe' if os.name == 'nt' else 'tectonic')
            tool.touch()
            with patch('automation.executables.sys.executable', str(python)), \
                    patch.dict('os.environ', {}, clear=True), \
                    patch('automation.executables.shutil.which', side_effect=[None, str(tool)]):
                self.assertEqual(resolve_tool('tectonic'), str(tool.resolve()))

    def test_invalid_explicit_tool_never_silently_falls_back(self):
        with patch('automation.executables.shutil.which', return_value=None) as which:
            with self.assertRaisesRegex(ValueError, 'executable missing'):
                resolve_tool('tectonic', 'missing-tool')
            self.assertEqual(which.call_count, 1)

    def test_default_and_provider_scoped_models(self):
        self.assertEqual(load_settings(environ={}).provider, 'codex')
        self.assertEqual(load_settings(environ={}).model, 'gpt-5.6-luna')
        self.assertEqual(load_settings({'provider': 'openai'}, environ={}).model, 'gpt-5-mini')

    def test_cli_over_environment_over_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.toml'
            path.write_text('provider="openai"\n[providers.openai]\nmodel="file-model"\n', encoding='utf-8')
            env = {'CV_CONFIG': str(path), 'CV_MODEL': 'env-model', 'CV_MAX_REQUESTS': '7'}
            settings = load_settings({'model': 'cli-model'}, environ=env)
            self.assertEqual((settings.provider, settings.model, settings.max_requests), ('openai', 'cli-model', 7))
            self.assertEqual(load_settings(environ=env).model, 'env-model')
            self.assertEqual(load_settings({'config': path}, environ={}).model, 'file-model')

    def test_unknown_provider_and_incomplete_compatible_fail(self):
        for options in ({'provider': 'typo'}, {'provider': 'compatible'},
                        {'provider': 'compatible', 'model': 'x'}, {'max_requests': -1}, {'retries': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                load_settings(options, environ={})

    def test_compatible_requires_safe_explicit_endpoint(self):
        for url in ('http://example.org/v1', 'https://key:secret@example.org/v1', 'https://example.org/v1?key=x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                load_settings({'provider': 'compatible', 'model': 'x', 'base_url': url}, environ={})
        result = load_settings({'provider': 'compatible', 'model': 'x', 'base_url': 'https://example.org/v1'}, environ={})
        self.assertEqual(result.api_key_env, 'LLM_API_KEY')

    def test_credentials_cannot_be_stored_in_toml(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.toml'
            path.write_text('api_key="test-secret"', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_settings({'config': path}, environ={})
