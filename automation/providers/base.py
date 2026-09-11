"""Small provider contract, sanitized errors and normalized token counts."""
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Result:
    data: dict
    usage: dict = field(default_factory=dict)


class Provider(Protocol):
    def preflight(self): ...
    def request(self, prompt, data, schema, timeout) -> Result: ...


class ProviderError(RuntimeError):
    def __init__(self, message, transient=False, retry_after=None):
        super().__init__(message)
        self.transient = transient
        self.retry_after = retry_after


def usage_counts(usage):
    if not isinstance(usage, dict):
        return {}
    result = {}
    for source, target in [('input_tokens', 'input_tokens'), ('prompt_tokens', 'input_tokens'),
                           ('output_tokens', 'output_tokens'), ('completion_tokens', 'output_tokens')]:
        value = usage.get(source)
        if type(value) is int and value >= 0:
            result[target] = value
    return result
