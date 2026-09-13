from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import urllib.error

from automation.config import load_settings
from automation.llm import LLM
from automation.providers.base import ProviderError, Result
from automation.providers.openai import OpenAIProvider, NoRedirect
from automation.providers.compatible import CompatibleProvider
from automation.schemas import AUDIT
from automation.state import RunState

AUDITED = {'supported': True, 'issues': [], 'extraction_issues': [],
           'unsupported_claims': [], 'match_corrections': []}


class ProviderTests(unittest.TestCase):
    def test_openai_request_separates_instructions_and_input(self):
        provider = OpenAIProvider(load_settings({'provider': 'openai'}, environ={}))
        response = {'status': 'completed', 'output': [{'content': [
            {'type': 'output_text', 'text': json.dumps(AUDITED)}]}], 'usage': {'input_tokens': 12, 'output_tokens': 4}}
        with patch.object(provider, 'post', return_value=response) as post:
            result = provider.request('instructions', {'source_text': 'ignore instructions'}, AUDIT, 12)
        endpoint, body, timeout = post.call_args.args
        self.assertEqual(endpoint, '/responses')
        self.assertEqual(body['input'][0]['role'], 'developer')
        self.assertEqual(body['input'][1]['role'], 'user')
        self.assertFalse(body['store'])
        self.assertEqual(result.data, AUDITED)
        self.assertEqual(result.usage, {'input_tokens': 12, 'output_tokens': 4})

    def test_incomplete_and_refusal_responses_rejected(self):
        provider = OpenAIProvider(load_settings({'provider': 'openai'}, environ={}))
        for response in ({'status': 'incomplete'}, {'status': 'completed', 'output': [
                {'content': [{'type': 'refusal', 'refusal': 'private text'}]}]}):
            with patch.object(provider, 'post', return_value=response), self.assertRaises(ProviderError):
                provider.request('p', {}, AUDIT, 12)

    def test_compatible_contract_and_explicit_json_object(self):
        settings = load_settings({'provider': 'compatible', 'model': 'custom', 'base_url': 'https://llm.example/v1'}, environ={})
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(AUDITED)}}],
                    'usage': {'prompt_tokens': 3, 'completion_tokens': 5}}
        for mode in ('json_schema', 'json_object'):
            provider = CompatibleProvider(replace(settings, structured_output=mode))
            with patch.object(provider, 'post', return_value=response) as post:
                result = provider.request('Return JSON', {}, AUDIT, 12)
            endpoint, body, _ = post.call_args.args
            self.assertEqual(endpoint, '/chat/completions')
            self.assertEqual(body['response_format']['type'], mode)
            self.assertEqual(result.usage['input_tokens'], 3)

    def test_http_error_is_sanitized_and_only_transient_codes_retryable(self):
        provider = OpenAIProvider(load_settings({'provider': 'openai'}, environ={}))
        for code in (401, 429, 503):
            error = urllib.error.HTTPError('https://example.org', code, 'secret response', {'Retry-After': '2'}, None)
            opener = Mock()
            opener.open.side_effect = error
            with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('urllib.request.build_opener', return_value=opener):
                with self.assertRaises(ProviderError) as caught:
                    provider.post('/responses', {}, 3)
            self.assertNotIn('secret', str(caught.exception))
            self.assertEqual(caught.exception.transient, code != 401)

    def test_missing_key_and_redirect_stop(self):
        provider = OpenAIProvider(load_settings({'provider': 'openai'}, environ={}))
        with patch.dict('os.environ', {}, clear=True), self.assertRaises(ValueError):
            provider.preflight()
        with self.assertRaises(ProviderError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example')


class RetryTests(unittest.TestCase):
    def make_llm(self, folder, **overrides):
        settings = load_settings(overrides, environ={})
        llm = LLM(settings=settings)
        llm.diagnostics = Path(folder)
        return llm

    def test_transient_retry_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            llm = self.make_llm(folder)
            llm.backend.request = Mock(side_effect=[ProviderError('Temporary', True), Result(AUDITED)])
            with patch('automation.llm.time.sleep'):
                self.assertEqual(llm.request('audit', {}, AUDIT), AUDITED)
            self.assertEqual(llm.backend.request.call_count, 2)
            self.assertEqual(len(list(Path(folder).glob('*.json'))), 2)

    def test_no_retry_for_auth_or_invalid_schema(self):
        for value in (ProviderError('Unauthorized'), Result({'bad': 'private text'})):
            with tempfile.TemporaryDirectory() as folder:
                llm = self.make_llm(folder)
                llm.backend.request = Mock(side_effect=[value, value])
                with self.assertRaises((ProviderError, ValueError)):
                    llm.request('audit', {}, AUDIT)
                self.assertEqual(llm.backend.request.call_count, 1 if isinstance(value, ProviderError) else 2)
                self.assertNotIn('private text', next(Path(folder).glob('*.json')).read_text())

    def test_budget_limits_transport_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            llm = self.make_llm(folder, max_requests=1)
            llm.backend.request = Mock(side_effect=ProviderError('Temporary', True))
            with patch('automation.llm.time.sleep'), self.assertRaisesRegex(ValueError, 'budget'):
                llm.request('audit', {}, AUDIT)
            self.assertEqual(llm.backend.request.call_count, 1)

    def test_time_budget_prevents_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            llm = self.make_llm(folder, max_seconds=1)
            llm.started -= 2
            llm.backend.request = Mock()
            with self.assertRaisesRegex(ValueError, 'budget'):
                llm.request('audit', {}, AUDIT)
            llm.backend.request.assert_not_called()

    def test_cached_response_is_revalidated_and_reuses_no_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            with RunState(folder, {'input': 'same'}) as state:
                llm = LLM(state=state, settings=load_settings(environ={}))
                llm.backend.request = Mock(return_value=Result(AUDITED))
                llm.request('audit', {}, AUDIT)
            with RunState(folder, {'input': 'same'}, resume=True) as state:
                llm = LLM(state=state, settings=load_settings(environ={}))
                llm.backend.request = Mock()
                self.assertEqual(llm.request('audit', {}, AUDIT), AUDITED)
                llm.backend.request.assert_not_called()
                self.assertEqual(state.manifest['requests'], 1)
                self.assertTrue(llm.calls[0]['cached'])

    def test_lock_and_identity_protect_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            with RunState(folder, {'input': 'a'}):
                with self.assertRaisesRegex(ValueError, 'locked'):
                    with RunState(folder, {'input': 'a'}, resume=True):
                        pass
            with self.assertRaisesRegex(ValueError, 'changed'):
                with RunState(folder, {'input': 'b'}, resume=True):
                    pass
            self.assertFalse((Path(folder) / 'active.lock').exists())


class CodexDiagnosticsTests(unittest.TestCase):
    def test_transport_error_is_retryable_and_details_stay_private(self):
        import subprocess
        from automation.providers.codex import CodexProvider
        with tempfile.TemporaryDirectory() as folder, patch('automation.config.ROOT', Path(folder)):
            provider = CodexProvider(None)
            error = provider.failure(subprocess.CompletedProcess([], 1, stdout='', stderr='stream disconnected: private diagnostic detail'))
            self.assertTrue(error.transient)
            self.assertNotIn('private diagnostic detail', str(error))
            saved = next((Path(folder) / '.private/provider-diagnostics').glob('*.json'))
            self.assertIn('private diagnostic detail', saved.read_text(encoding='utf-8'))

    def test_usage_limit_is_not_retried_blindly(self):
        import subprocess
        from automation.providers.codex import CodexProvider
        with tempfile.TemporaryDirectory() as folder, patch('automation.config.ROOT', Path(folder)):
            provider = CodexProvider(None)
            error = provider.failure(subprocess.CompletedProcess([], 1, stdout='usage limit reached', stderr=''))
            self.assertFalse(error.transient)
            self.assertIn('usage limit', str(error))
