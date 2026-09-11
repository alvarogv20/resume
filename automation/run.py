"""Backward-compatible entrypoint: python -m automation.run."""
from .cli import parse_args
from .pipeline import run


def main(argv=None):
    args, settings = parse_args(argv)
    run(args, settings)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never expose raw model payloads, network bodies or configuration secrets.
        from .providers.base import ProviderError
        message = str(error) if type(error) is ValueError or isinstance(error, ProviderError) else 'Check local configuration and diagnostics.'
        print(f'Process stopped ({type(error).__name__}): {message}')
        raise SystemExit(1)
