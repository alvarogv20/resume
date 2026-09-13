"""Backward-compatible entrypoint: python -m automation.run."""
from .cli import parse_args
from .pipeline import run


def main(argv=None):
    args, settings = parse_args(argv)
    report = run(args, settings)
    return 0 if report['status'] == 'ready' else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # Never expose raw model payloads, network bodies or configuration secrets.
        from .providers.base import ProviderError
        message = str(error) if type(error) is ValueError or isinstance(error, ProviderError) else 'Check local configuration and diagnostics.'
        print(f'Process stopped ({type(error).__name__}): {message}')
        raise SystemExit(1)
