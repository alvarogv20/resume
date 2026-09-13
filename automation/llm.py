"""Provider-independent validation, checkpointing and bounded transport retries."""
from pathlib import Path
import time
import uuid

from jsonschema import ValidationError, validate

from .config import load_settings
from .providers import create_provider
from .providers.base import ProviderError
from .state import atomic_json, fingerprint

ROOT = Path(__file__).resolve().parents[1]


class LLM:
    def __init__(self, provider=None, model=None, *, settings=None, state=None,
                 output_guard=None, root=None):
        self.settings = settings or load_settings({'provider': provider, 'model': model})
        self.provider = self.settings.provider
        self.model = self.settings.model
        self.backend = create_provider(self.settings)
        self.state = state
        self.output_guard = output_guard
        self.root = Path(root) if root else ROOT
        self.diagnostics = (state.folder / 'diagnostics' if state else
                            self.root / '.private/diagnostics' / uuid.uuid4().hex)
        self.calls = []
        self.requests = 0
        self.started = time.monotonic()

    def preflight(self):
        self.backend.preflight()

    def remaining(self):
        remaining = self.settings.max_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ValueError('LLM elapsed-time budget exhausted; resume to continue.')
        return remaining

    def check(self, result, schema):
        try:
            validate(result, schema)
        except ValidationError:
            raise ValueError('LLM result does not match the stage schema.') from None
        if self.output_guard:
            self.output_guard(result)

    def request(self, stage, data, schema):
        try:
            return self._request(stage, data, schema)
        except ValueError as error:
            if str(error) != 'LLM result does not match the stage schema.':
                raise
            return self._request(stage, {**data, 'format_correction':
                'The previous response failed the supplied JSON schema. Return all required fields with correct types and no additional properties.'}, schema)

    def _request(self, stage, data, schema):
        if stage not in ('extract', 'adapt', 'audit', 'repair'):
            raise ValueError('Unknown LLM stage.')
        prompt = (self.root / 'automation/prompts' / f'{stage}.txt').read_text(encoding='utf-8')
        key = fingerprint({'prompt': prompt, 'data': data, 'schema': schema,
                           'settings': self.settings.identity()})
        cached = self.state.cached(key) if self.state else None
        if cached is not None:
            self.check(cached['result'], schema)
            self.calls.append({**cached['metadata'], 'cached': True, 'duration_seconds': 0})
            return cached['result']
        for attempt in range(self.settings.retries + 1):
            timeout = min(self.settings.timeout, self.remaining())
            if self.state:
                number = self.state.begin_request(self.settings.max_requests)
            else:
                if self.requests >= self.settings.max_requests:
                    raise ValueError('LLM request budget exhausted.')
                number = self.requests + 1
            self.requests += 1
            started = time.monotonic()
            meta = {'stage': stage, 'provider': self.provider, 'model': self.model,
                    'request': number, 'attempt': attempt + 1, 'cached': False}
            try:
                response = self.backend.request(prompt, data, schema, timeout)
                self.check(response.data, schema)
            except (ProviderError, ValueError) as error:
                meta.update(status='failed', error_type=type(error).__name__,
                            duration_seconds=round(time.monotonic() - started, 3))
                self.calls.append(meta)
                atomic_json(self.diagnostics / f'{number:03d}-{stage}.json', {'metadata': meta})
                if not isinstance(error, ProviderError) or not error.transient or attempt == self.settings.retries:
                    raise
                delay = error.retry_after if error.retry_after is not None else min(2 ** attempt, 30)
                if delay >= self.remaining():
                    raise ValueError('Retry would exceed LLM elapsed-time budget.') from None
                time.sleep(delay)
                continue
            meta.update(status='completed', usage=response.usage,
                        duration_seconds=round(time.monotonic() - started, 3))
            record = {'metadata': meta, 'result': response.data}
            atomic_json(self.diagnostics / f'{number:03d}-{stage}.json', record)
            if self.state:
                self.state.save(key, record)
            self.calls.append(meta)
            return response.data
