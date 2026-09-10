"""Publish an explicit allowlist of public results; never stage the build or contacts."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

from .generate import ROOT, assert_no_contacts, load_contacts

FILES = ['source.md', 'job.json', 'adaptation.json', 'match.md', 'cv.tex', 'decisions.md', 'validation.json']


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--slug', required=True)
    parser.add_argument('--base', default='master')
    parser.add_argument('--contacts', type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', args.slug):
        parser.error('Invalid slug.')
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token or not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
        parser.error('Set GITHUB_REPOSITORY=owner/repo and GH_TOKEN (never commit the token).')
    if git('diff', '--cached', '--name-only'):
        parser.error('Index is not empty. Commit your own staged work first.')
    remote = git('remote', 'get-url', 'origin')
    if remote.removesuffix('.git') not in ('https://github.com/' + repo, 'git@github.com:' + repo):
        parser.error('origin does not match the target repository.')
    contacts = load_contacts(args.contacts)
    paths = ['roles/' + args.slug + '/' + file for file in FILES]
    for path in paths:
        item = ROOT / path
        if item.is_symlink() or not item.resolve().is_relative_to(ROOT / 'roles'):
            parser.error('Invalid output path.')
        assert_no_contacts(item.read_text(encoding='utf-8'), contacts)
    branch = 'codex/cv-' + args.slug
    git('switch', '-c', branch)
    git('add', '--', *paths)
    if sorted(git('diff', '--cached', '--name-only').splitlines()) != sorted(paths):
        raise RuntimeError('Staged files differ from the publication allowlist.')
    git('commit', '-m', 'Add evidence-based CV adaptation: ' + args.slug)
    git('push', '-u', 'origin', branch)
    body = {'title': 'CV adaptation: ' + args.slug, 'head': branch, 'base': args.base, 'draft': True,
            'body': 'Adds the extracted job requirements, evidence match and tailored LaTeX CV. '
                    'The complete PDF and contacts remain on the private runner. '
                    'See validation.json for checks; visual review is required before applying.'}
    request = urllib.request.Request(f'https://api.github.com/repos/{repo}/pulls', data=json.dumps(body).encode(),
                                     headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                                              'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(request, timeout=30) as response:
        print(json.load(response)['html_url'])


if __name__ == '__main__':
    main()
