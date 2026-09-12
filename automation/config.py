"""Typed, provider-scoped configuration. Credentials are never config values."""
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ('codex', 'openai', 'compatible')
DEFAULTS = {
    'codex': {'model': 'gpt-5.6-luna', 'reasoning': 'medium', 'timeout': 600},
    'openai': {'model': 'gpt-5-mini', 'base_url': 'https://api.openai.com/v1',
               'api_key_env': 'OPENAI_API_KEY', 'timeout': 180},
    'compatible': {'api_key_env': 'LLM_API_KEY', 'timeout': 180},
}


@dataclass(frozen=True)
class Settings:
    provider: str = 'codex'
    model: str = ''
    base_url: str = ''
    api_key_env: str = ''
    reasoning: str = 'medium'
    structured_output: str = 'json_schema'
    timeout: int = 600
    retries: int = 2
    max_requests: int = 18
    max_seconds: int = 1800
    max_output_tokens: int = 12000

    def identity(self):
        # Operational budgets may be increased when resuming, without invalidating content.
        return {k: v for k, v in asdict(self).items()
                if k not in ('timeout', 'retries', 'max_requests', 'max_seconds')}


def load_settings(overrides=None, environ=None):
    overrides = overrides or {}
    env = os.environ if environ is None else environ
    path = Path(overrides.get('config') or env.get('CV_CONFIG') or ROOT / 'config/default.toml')
    with path.open('rb') as stream:
        doc = tomllib.load(stream)
    fields = set(Settings.__dataclass_fields__)
    if set(doc) - fields - {'providers'}:
        raise ValueError('Unknown configuration field.')
    sections = doc.get('providers', {})
    if not isinstance(sections, dict) or set(sections) - set(PROVIDERS):
        raise ValueError('Unknown provider configuration.')
    for section in sections.values():
        if not isinstance(section, dict) or set(section) - fields or 'provider' in section:
            raise ValueError('Unknown provider setting; store credentials only in environment variables.')
    provider = overrides.get('provider') or env.get('CV_PROVIDER') or doc.get('provider', 'codex')
    if provider not in PROVIDERS:
        raise ValueError('Provider must be codex, openai or compatible.')
    values = {**asdict(Settings()), **DEFAULTS[provider],
              **{k: v for k, v in doc.items() if k != 'providers'}, **sections.get(provider, {})}
    for field in fields:
        value = env.get('CV_' + field.upper())
        if value is not None and value != '':
            values[field] = value
        if overrides.get(field) is not None:
            values[field] = overrides[field]
    values['provider'] = provider
    for key, bounds in {'timeout': (1, 3600), 'retries': (0, 5), 'max_requests': (1, 100),
                        'max_seconds': (1, 86400), 'max_output_tokens': (1, 100000)}.items():
        raw = values[key]
        if isinstance(raw, bool) or not re.fullmatch(r'\d+', str(raw)):
            raise ValueError(f'{key} must be an integer.')
        values[key] = int(raw)
        if not bounds[0] <= values[key] <= bounds[1]:
            raise ValueError(f'{key} is outside its supported range.')
    for key in fields - {'timeout', 'retries', 'max_requests', 'max_seconds', 'max_output_tokens'}:
        if not isinstance(values[key], str) or any(c in values[key] for c in '\r\n\x00'):
            raise ValueError(f'Invalid {key}.')
    if not values['model'].strip():
        raise ValueError('Set an explicit model for this provider.')
    if values['reasoning'] not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
        raise ValueError('Unsupported reasoning setting.')
    if values['structured_output'] not in ('json_schema', 'json_object'):
        raise ValueError('structured_output must be json_schema or json_object.')
    if provider != 'codex':
        url = urlsplit(values['base_url'])
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment):
            raise ValueError('API base_url must be HTTPS without credentials, query or fragment.')
        if provider == 'openai' and values['base_url'].rstrip('/') != 'https://api.openai.com/v1':
            raise ValueError('Use provider compatible for a third-party endpoint.')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', values['api_key_env']):
            raise ValueError('api_key_env must name an environment variable.')
    return Settings(**values)
