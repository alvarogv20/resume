"""Opt-in Chat Completions API contract, not universal provider compatibility."""
import json
from .base import ProviderError, Result, usage_counts
from .openai import OpenAIProvider


class CompatibleProvider(OpenAIProvider):
    def request(self, prompt, data, schema, timeout):
        format = {'type': self.settings.structured_output}
        if self.settings.structured_output == 'json_schema':
            format['json_schema'] = {'name': 'cv_result', 'strict': True, 'schema': schema}
        else:
            prompt += '\nReturn JSON matching this schema exactly:\n' + json.dumps(schema)
        body = {'model': self.settings.model, 'max_tokens': self.settings.max_output_tokens,
                'messages': [{'role': 'system', 'content': prompt},
                             {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}],
                'response_format': format}
        result = self.post('/chat/completions', body, timeout)
        try:
            choice = result['choices'][0]
            if choice['finish_reason'] != 'stop' or choice['message'].get('refusal'):
                raise ProviderError('Model refused or did not complete the response.')
            return Result(json.loads(choice['message']['content']), usage_counts(result.get('usage')))
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError('Compatible API returned no valid structured result.') from None
