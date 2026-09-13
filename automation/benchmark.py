"""Run the saved offer corpus through the real pipeline (explicit opt-in)."""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .extract import canonical_url, page_text
from .generate import ROOT
from .state import atomic_json

CORPUS = ROOT / 'tests/fixtures/offers'


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.url = self.job_id = self.language = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html':
            self.language = attrs.get('lang')
        if tag == 'meta' and attrs.get('name') == 'fixture-source':
            self.url = attrs.get('content')
        if 'data-job-id' in attrs:
            self.job_id = attrs['data-job-id']


def load_cases():
    manifest = json.loads((CORPUS / 'manifest.json').read_text(encoding='utf-8'))
    cases = []
    for entry in manifest:
        path = CORPUS / entry['file']
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError(f'Fixture checksum changed: {path.name}')
        html = raw.decode('utf-8-sig')
        meta = Metadata()
        meta.feed(html)
        url = canonical_url(meta.url)
        if meta.job_id != entry['job_id'] or url != entry['url'] or meta.language != entry['language']:
            raise ValueError(f'Fixture metadata changed: {path.name}')
        text = page_text(html)
        if not 250 <= len(text) <= 45000:
            raise ValueError(f'Invalid offer text length: {path.name}')
        cases.append({**entry, 'text': text})
    return cases


def check_result(slug):
    role = ROOT / 'roles' / slug
    for name in ('source.md', 'job.json', 'adaptation.json', 'match.md', 'cv.tex',
                 'decisions.md', 'validation.json'):
        if not (role / name).is_file() or not (role / name).stat().st_size:
            raise ValueError(f'Missing deliverable: {name}')
    report = json.loads((role / 'validation.json').read_text(encoding='utf-8'))
    if not (report['compiled'] and report['text_extractable'] and report['contacts_included']
            and report['master_unchanged'] and 1 <= report['pages'] <= 2
            and report['overflow_check'] == 'passed' and report['status'] == 'ready'):
        raise ValueError('Generation did not pass validation')
    if any(report['review'][k] for k in ('cv_factual_issues', 'extraction_warnings', 'audit_errors')):
        raise ValueError('Unresolved audit findings')
    from pypdf import PdfReader
    pdf = ROOT / 'build' / slug / 'cv.pdf'
    reader = PdfReader(pdf)
    if len(reader.pages) != report['pages'] or len(''.join(p.extract_text() or '' for p in reader.pages).strip()) < 500:
        raise ValueError('Final PDF does not match validation')
    usage = {}
    for call in report['llm_calls']:
        if not call.get('cached'):
            for key, value in call.get('usage', {}).items():
                if isinstance(value, (int, float)):
                    usage[key] = usage.get(key, 0) + value
    return {**{k: report[k] for k in ('pages', 'llm_requests_total', 'visual_review', 'warnings')},
            'usage': usage, 'source_sha256': report['source_sha256'],
            'profile_sha256': report['profile_sha256'], 'code_commit': report['code_commit']}


def run_case(case, folder, prefix, options):
    slug = f"{prefix}-{case['job_id'].lower()}"
    source = folder / f"{case['job_id']}.txt"
    source.write_text(case['text'], encoding='utf-8')
    command = [sys.executable, '-m', 'automation.run', '--url', case['url'],
               '--job-text', str(source), '--slug', slug, '--language', case['language'], *options]
    started = time.monotonic()
    result = {'file': case['file'], 'slug': slug, 'language': case['language'], 'status': 'failed'}
    try:
        with (folder / f"{case['job_id']}.log").open('w', encoding='utf-8') as log:
            process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     timeout=2400)
        result['exit_code'] = process.returncode
        if process.returncode == 0:
            result.update(check_result(slug))
            result['status'] = 'passed'
    except Exception as error:
        # A malformed artifact (including an unreadable PDF) fails this case,
        # but must not prevent the remaining offers from being evaluated.
        result['error_type'] = type(error).__name__
    result['seconds'] = round(time.monotonic() - started, 2)
    if result['status'] != 'passed':
        checkpoint = Path(os.environ.get('CV_RUNS_DIR') or ROOT / '.private/runs') / slug / 'status.json'
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text(encoding='utf-8'))
            result['pipeline_status'] = saved.get('status')
            result['failed_stage'] = saved.get('failed_stage')
            result['error_type'] = saved.get('error_type', result.get('error_type'))
            result['llm_calls'] = saved.get('llm_calls', [])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', action='store_true', help='Use the real LLM and compiler')
    for name in ('config', 'provider', 'model', 'contacts', 'tectonic'):
        parser.add_argument('--' + name)
    args = parser.parse_args(argv)
    cases = load_cases()
    if not args.generate:
        for case in cases:
            print(f"{case['file']} [{case['language']}] {len(case['text'])} characters")
        print('Corpus validated. Use --generate for real acceptance testing.')
        return 0
    prefix = 'bench-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
    folder = ROOT / '.private/benchmarks' / prefix
    folder.mkdir(parents=True)
    options = []
    for name in ('config', 'provider', 'model', 'contacts', 'tectonic'):
        if getattr(args, name):
            options.extend(['--' + name, getattr(args, name)])
    results = []
    for case in cases:
        results.append(run_case(case, folder, prefix, options))
        atomic_json(folder / 'results.json', results)
        print(f"{case['file']}: {results[-1]['status']}", flush=True)
    print(f'Results: {folder / "results.json"}')
    return 0 if all(r['status'] == 'passed' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
