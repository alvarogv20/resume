import json
import os
import socket
import urllib.error
import urllib.request

from .base import ProviderError, Result, usage_counts


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('API redirects are not supported; check base_url.')


class OpenAIProvider:
    def __init__(self, settings):
        self.settings = settings

    def preflight(self):
        if not os.environ.get(self.settings.api_key_env, '').strip():
            raise ValueError('The configured API key environment variable is missing.')

    def post(self, endpoint, body, timeout):
        self.preflight()
        request = urllib.request.Request(self.settings.base_url.rstrip('/') + endpoint,
                                         data=json.dumps(body).encode(),
                                         headers={'Authorization': 'Bearer ' + os.environ[self.settings.api_key_env],
                                                  'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            after = error.headers.get('Retry-After', '') if error.headers else ''
            raise ProviderError(f'API request failed (HTTP {error.code}).',
                                transient=error.code in (408, 429, 500, 502, 503, 504),
                                retry_after=min(int(after), 60) if after.isdigit() else None) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            raise ProviderError('API connection failed or timed out.', transient=True) from None
        except ValueError:
            raise ProviderError('API returned invalid JSON.') from None
        if not isinstance(result, dict):
            raise ProviderError('API returned an invalid response envelope.')
        return result

    def request(self, prompt, data, schema, timeout):
        body = {'model': self.settings.model, 'store': False,
                'max_output_tokens': self.settings.max_output_tokens,
                'input': [{'role': 'developer', 'content': prompt},
                          {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}],
                'text': {'format': {'type': 'json_schema', 'name': 'cv_result',
                                    'strict': True, 'schema': schema}}}
        result = self.post('/responses', body, timeout)
        if result.get('status') != 'completed':
            raise ProviderError('Model response incomplete; no CV was produced.')
        try:
            parts = [part for item in result.get('output', []) for part in item.get('content', [])]
            if any(part.get('type') == 'refusal' for part in parts):
                raise ProviderError('Model refused the request.')
            text = ''.join(part.get('text', '') for part in parts if part.get('type') == 'output_text')
            return Result(json.loads(text), usage_counts(result.get('usage')))
        except (ValueError, TypeError, AttributeError):
            raise ProviderError('Model returned no valid structured result.') from None
