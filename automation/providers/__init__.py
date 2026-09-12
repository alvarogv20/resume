"""Explicit provider registry: never fall back to another service."""
from .codex import CodexProvider
from .openai import OpenAIProvider
from .compatible import CompatibleProvider


def create_provider(settings):
    return {'codex': CodexProvider, 'openai': OpenAIProvider,
            'compatible': CompatibleProvider}[settings.provider](settings)
