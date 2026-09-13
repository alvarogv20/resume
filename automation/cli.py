"""Shared command-line configuration for local and workflow entrypoints."""
import argparse
from pathlib import Path
import re

from .config import load_settings, PROVIDERS


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Generate an evidence-linked CV; never submits an application.')
    parser.add_argument('--url', required=True)
    parser.add_argument('--job-text', type=Path, help='UTF-8 offer text if the site blocks extraction.')
    parser.add_argument('--slug', required=True, help='Unique safe directory, e.g. employer-job-id')
    parser.add_argument('--language', choices=['en', 'es'], default='en')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--provider', choices=PROVIDERS)
    for option in ('model', 'base-url', 'api-key-env', 'reasoning', 'structured-output'):
        parser.add_argument('--' + option)
    for option in ('timeout', 'retries', 'max-requests', 'max-seconds', 'max-output-tokens'):
        parser.add_argument('--' + option, type=int)
    parser.add_argument('--contacts', type=Path)
    parser.add_argument('--max-pages', type=int, choices=[1, 2], default=2)
    parser.add_argument('--tectonic')
    parser.add_argument('--resume', action='store_true', help='Reuse private checkpoints for this slug.')
    parser.add_argument('--restart-from', choices=['extract', 'adapt', 'audit', 'export'],
                        help='With --resume, invalidate this stage and its dependent responses.')
    parser.add_argument('--analysis-only', action='store_true', help='Save private analysis/draft without requiring a compiler or contacts.')
    args = parser.parse_args(argv)
    if args.restart_from and not args.resume:
        parser.error('--restart-from requires --resume')
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', args.slug) or len(args.slug) > 90:
        parser.error('Use lowercase letters, digits and hyphens only (max 90).')
    return args, load_settings(vars(args))
