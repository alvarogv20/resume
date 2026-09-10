import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import yaml
from jsonschema import ValidationError
from .extract import canonical_url, fetch_job
from .generate import ROOT, assert_no_contacts, load_contacts, render
from .llm import LLM
from .match import validate_adaptation, validate_job
from .schemas import ADAPTATION, AUDIT, JOB
from .validate import compile_pdf


def digest(value):
    return hashlib.sha256(value).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate an evidence-linked CV; never submits an application.')
    parser.add_argument('--url', required=True)
    parser.add_argument('--job-text', type=Path, help='UTF-8 offer text if the site blocks extraction.')
    parser.add_argument('--slug', required=True, help='Unique safe directory, e.g. nordex-4441905971')
    parser.add_argument('--language', choices=['en', 'es'], default='en')
    parser.add_argument('--provider', choices=['codex', 'openai'], default='codex')
    parser.add_argument('--model', help='Default: gpt-5.6-luna (Codex), gpt-5-mini (API).')
    parser.add_argument('--contacts', type=Path)
    parser.add_argument('--max-pages', type=int, default=2)
    parser.add_argument('--tectonic')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', args.slug) or len(args.slug) > 90:
        parser.error('Use a slug with lowercase letters, digits and hyphens only (max 90).')
    if args.max_pages not in (1, 2):
        parser.error('max-pages must be 1 or 2.')
    destination = ROOT / 'roles' / args.slug
    if destination.exists():
        parser.error('That role directory exists. Use a new version suffix to preserve prior results.')
    contacts = load_contacts(args.contacts)
    profile_bytes = (ROOT / 'profile' / 'profile.yaml').read_bytes()
    profile = yaml.safe_load(profile_bytes)
    # Reject accidental contact additions before any network/model call.
    assert_no_contacts(profile_bytes.decode('utf-8'), contacts)
    url = canonical_url(args.url)
    print('Extracting public job content...', flush=True)
    if args.job_text:
        source = args.job_text.read_text(encoding='utf-8-sig')
        if not 250 <= len(source) <= 45000:
            raise ValueError('Job text must contain 250-45000 characters.')
        source_method = 'user-supplied-text'
    else:
        url, source = fetch_job(url)
        source_method = 'public-http'
    assert_no_contacts(source, contacts)
    llm = LLM(args.provider, args.model)
    print('LLM: extract requirements...', flush=True)
    job = llm.request('extract', {'source_text': source}, JOB)
    try:
        validate_job(job, source)
    except ValueError as error:
        job = llm.request('extract', {'source_text': source, 'previous_extraction': job,
                                     'correction_required': str(error)}, JOB)
        validate_job(job, source)
    # Identity/contact details are not needed for matching or drafting.
    model_profile = {k: v for k, v in profile.items() if k not in ('name', 'location')}
    print('LLM: match evidence and adapt CV...', flush=True)
    adapted = llm.request('adapt', {'master_profile': model_profile, 'job': job,
                                  'requested_language': args.language}, ADAPTATION)
    try:
        validate_adaptation(profile, job, adapted)
        print('LLM: verify factual support...', flush=True)
        audit = llm.request('audit', {'master_profile': model_profile, 'job': job, 'adaptation': adapted}, AUDIT)
    except ValueError as error:
        audit = {'supported': False, 'issues': [str(error)]}
    if not audit['supported'] or audit['issues']:
        # One bounded correction, not an open-ended agent loop.
        adapted = llm.request('adapt', {'master_profile': model_profile, 'job': job,
                                      'requested_language': args.language, 'previous_draft': adapted,
                                      'corrections_required': audit['issues']}, ADAPTATION)
        validate_adaptation(profile, job, adapted)
        audit = llm.request('audit', {'master_profile': model_profile, 'job': job, 'adaptation': adapted}, AUDIT)
        if not audit['supported'] or audit['issues']:
            raise ValueError('Evidence audit failed after correction; no result was published.')
    tex = render(profile, adapted, args.language)
    print('Compiling private PDF and checking text/layout...', flush=True)
    pdf_path = ROOT / 'build' / args.slug / 'cv.pdf'
    report = compile_pdf(tex, pdf_path, contacts, args.max_pages, args.tectonic)
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = 'unavailable'
    report.update({'source_url': url, 'source_method': source_method,
                   'generated_at': datetime.now(timezone.utc).isoformat(),
                   'profile_version': profile['version'], 'profile_sha256': digest(profile_bytes),
                   'source_sha256': digest(source.encode()), 'code_commit': commit,
                   'prompt_sha256': {p.name: digest(p.read_bytes()) for p in sorted((ROOT / 'automation/prompts').glob('*.txt'))},
                   'llm_calls': llm.calls, 'audit': audit, 'master_unchanged': True})
    if (ROOT / 'profile/profile.yaml').read_bytes() != profile_bytes:
        raise ValueError('Master changed during execution; rerun against a stable revision.')
    requirements = {r['id']: r for r in job['requirements']}
    analysis = ['# Cruce con el perfil', '', 'Cada coincidencia remite a hechos del perfil maestro.', '']
    for match in adapted['matches']:
        req = requirements[match['requirement_id']]
        analysis += [f"## {req['id']}: {req['text']}", f"Estado: {match['status']} ({req['priority']})",
                     f"Evidencias: {', '.join(match['evidence_ids']) or 'Sin evidencia documentada'}",
                     match['rationale'], '']
    decisions = '# Decisiones editoriales\n\n' + '\n'.join('- ' + x for x in adapted['decisions'])
    decisions += '\n\n## Pendiente de confirmar\n\n' + '\n'.join('- ' + x for x in adapted['questions']) + '\n'
    # Persist extracted facts and short supporting quotes, not a complete third-party advert.
    source_doc = (f'# Fuente de la oferta\n\nURL: {url}\n\nMétodo: {source_method}\n\n'
                  f"Fecha UTC: {report['generated_at']}\n\nSHA256 del texto leído: {report['source_sha256']}\n\n"
                  'El texto íntegro se procesa en memoria. Los datos relevantes y citas de soporte están en job.json.\n')
    files = {'source.md': source_doc, 'job.json': dumps(job), 'adaptation.json': dumps(adapted),
             'match.md': '\n'.join(analysis), 'cv.tex': tex, 'decisions.md': decisions,
             'validation.json': dumps(report)}
    for content in files.values():
        assert_no_contacts(content, contacts)
    with tempfile.TemporaryDirectory(prefix='cv-result-', dir=ROOT / 'roles') as staging:
        for name, content in files.items():
            (Path(staging) / name).write_text(content, encoding='utf-8')
        shutil.copytree(staging, destination)
    print(f'Ready: roles/{args.slug}; private PDF: build/{args.slug}/cv.pdf', flush=True)
    print('Visual review remains required before sending the application.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Avoid reflecting model content, contacts, HTTP bodies or source text in CI logs.
        print(f'Process stopped ({type(error).__name__}): {error}' if isinstance(error, (ValueError, RuntimeError))
              else f'Process stopped ({type(error).__name__}). Check local configuration and source availability.')
        raise SystemExit(1)
