from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml
from .extract import canonical_url, fetch_job
from .generate import ROOT, assert_no_contacts, load_contacts, render
from .llm import LLM
from .match import validate_adaptation, validate_job
from .schemas import ADAPTATION, AUDIT, JOB
from .repair import repair
from .validate import compile_pdf
from .preflight import validate_profile, check_tools
from .state import RunState, atomic_json


def digest(value):
    return hashlib.sha256(value).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def run(args, settings):
    destination = ROOT / 'roles' / args.slug
    if destination.exists():
        raise ValueError('That role directory exists. Use a new version suffix to preserve prior results.')
    contacts = load_contacts(args.contacts)
    implementation = [*sorted((ROOT / 'automation').rglob('*.py')),
                      *sorted((ROOT / 'automation/prompts').glob('*.txt')),
                      ROOT / 'templates/tailored-cv.tex.j2', ROOT / 'layout.tex', ROOT / 'requirements.txt']
    implementation_hashes = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in implementation}
    profile_bytes = (ROOT / 'profile' / 'profile.yaml').read_bytes()
    profile = yaml.safe_load(profile_bytes)
    # Reject accidental contact additions before any network/model call.
    assert_no_contacts(profile_bytes.decode('utf-8'), contacts)
    validate_profile(profile)
    args.tectonic = check_tools(args.tectonic)
    url = canonical_url(args.url)
    supplied = args.job_text.read_text(encoding='utf-8-sig') if args.job_text else None
    if supplied is not None:
        if not 250 <= len(supplied) <= 45000:
            raise ValueError('Job text must contain 250-45000 characters.')
        assert_no_contacts(supplied, contacts)
    identity = {'url': url, 'supplied_text': digest(supplied.encode()) if supplied is not None else None,
                'profile': digest(profile_bytes), 'implementation': implementation_hashes,
                'language': args.language, 'settings': settings.identity()}
    runs_root = Path(os.environ.get('CV_RUNS_DIR') or ROOT / '.private/runs')
    with RunState(runs_root / args.slug, identity, args.resume) as state:
        llm = LLM(settings=settings, state=state, root=ROOT,
                  output_guard=lambda value: assert_no_contacts(dumps(value), contacts))
        llm.preflight()
        _generate(args, state, llm, profile, profile_bytes, implementation_hashes, contacts, url, supplied)


def _generate(args, state, llm, profile, profile_bytes, implementation_hashes, contacts, url, supplied):
    print('Extracting public job content...', flush=True)
    source_file = state.folder / 'source.json'
    if source_file.exists():
        saved = json.loads(source_file.read_text(encoding='utf-8'))
        source, source_method = saved['text'], saved['method']
        if digest(source.encode()) != saved['sha256']:
            raise ValueError('Saved source checksum failed; use a new slug.')
    else:
        if supplied is not None:
            source, source_method = supplied, 'user-supplied-text'
        else:
            url, source = fetch_job(url)
            source_method = 'public-http'
        assert_no_contacts(source, contacts)
        atomic_json(source_file, {'text': source, 'method': source_method, 'sha256': digest(source.encode())})
    assert_no_contacts(source, contacts)
    print('LLM: extract requirements...', flush=True)
    job = llm.request('extract', {'source_text': source}, JOB)
    try:
        validate_job(job, source)
    except ValueError as error:
        job = llm.request('extract', {'source_text': source, 'previous_extraction': job,
                                     'correction_required': str(error)}, JOB)
        validate_job(job, source)
    # Only evidence is needed: omit identity and administrative metadata (including YAML dates).
    model_profile = {k: profile[k] for k in ('experience', 'skills', 'education', 'languages', 'unconfirmed')
                     if k in profile}
    print('LLM: match evidence and adapt CV...', flush=True)
    adapted = llm.request('adapt', {'master_profile': model_profile, 'job': job,
                                  'requested_language': args.language}, ADAPTATION)
    try:
        validate_adaptation(profile, job, adapted)
    except ValueError as error:
        adapted = llm.request('adapt', {'master_profile': model_profile, 'job': job,
                                      'requested_language': args.language, 'previous_draft': adapted,
                                      'corrections_required': [str(error)]}, ADAPTATION)
        validate_adaptation(profile, job, adapted)
    print('LLM: verify factual support...', flush=True)
    audit = llm.request('audit', {'master_profile': model_profile, 'source_text': source,
                                 'job': job, 'adaptation': adapted}, AUDIT)
    extraction_repairs = None
    if audit['extraction_issues']:
        print('Correcting extraction and rebuilding the draft...', flush=True)
        extraction_repairs = audit['extraction_issues']
        job = llm.request('extract', {'source_text': source, 'previous_extraction': job,
                                     'corrections_required': extraction_repairs}, JOB)
        validate_job(job, source)
        adapted = llm.request('adapt', {'master_profile': model_profile, 'job': job,
                                      'requested_language': args.language}, ADAPTATION)
        validate_adaptation(profile, job, adapted)
        print('Auditing the corrected draft...', flush=True)
        audit = llm.request('audit', {'master_profile': model_profile, 'source_text': source,
                                     'job': job, 'adaptation': adapted}, AUDIT)
    repairs = None
    repair_history = []
    # Extraction is audited before this loop. Keep that accepted input fixed while
    # verifying conservative CV repairs, instead of reopening a different scope.
    if audit['extraction_issues']:
        raise ValueError('Semantic extraction audit failed after correction; review the source.')
    for _ in range(3):
        if audit['supported'] and not any(audit[k] for k in ('issues', 'unsupported_claims', 'match_corrections')):
            break
        if repairs is None:
            repairs = audit
        repair_history.append(audit)
        print('Applying conservative evidence repairs and re-auditing...', flush=True)
        adapted = repair(profile, job, adapted, audit)
        audit = llm.request('audit', {'audit_scope': 'adaptation', 'master_profile': model_profile,
                                     'job': job, 'adaptation': adapted}, AUDIT)
        if audit['extraction_issues']:
            raise ValueError('Auditor returned extraction findings outside the requested scope.')
    if not audit['supported'] or any(audit[k] for k in ('issues', 'unsupported_claims', 'match_corrections')):
        raise ValueError('Evidence audit failed after bounded corrections; no result was published.')
    tex = render(profile, adapted, args.language)
    print('Compiling private PDF and checking text/layout...', flush=True)
    pdf_path = ROOT / 'build' / args.slug / 'cv.pdf'
    staged_pdf = state.folder / 'cv.pdf'
    report = compile_pdf(tex, staged_pdf, contacts, args.max_pages, args.tectonic)
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = 'unavailable'
    report.update({'source_url': url, 'source_method': source_method,
                   'generated_at': datetime.now(timezone.utc).isoformat(),
                   'profile_version': profile['version'], 'profile_sha256': digest(profile_bytes),
                   'source_sha256': digest(source.encode()), 'code_commit': commit,
                   'implementation_sha256': implementation_hashes,
                   'prompt_sha256': {p.name: digest(p.read_bytes()) for p in sorted((ROOT / 'automation/prompts').glob('*.txt'))},
                   'llm_calls': llm.calls, 'llm_requests_total': state.manifest['requests'], 'audit': audit, 'repair_feedback': repairs,
                   'extraction_repair_feedback': extraction_repairs, 'master_unchanged': True})
    report['repair_history'] = repair_history
    if (ROOT / 'profile/profile.yaml').read_bytes() != profile_bytes:
        raise ValueError('Master changed during execution; rerun against a stable revision.')
    if any(digest((ROOT / p).read_bytes()) != h for p, h in implementation_hashes.items()):
        raise ValueError('Implementation changed during execution; rerun against a stable revision.')
    requirements = {r['id']: r for r in job['requirements']}
    analysis = ['# Cruce con el perfil', '', 'Cada coincidencia remite a hechos del perfil maestro.', '']
    for match in adapted['matches']:
        req = requirements[match['requirement_id']]
        analysis += [f"## {req['id']}: {req['text']}", f"Estado: {match['status']} ({req['priority']})",
                     f"Aplicabilidad: {req['condition'] or 'Sin condición adicional indicada'}",
                     f"Lógica: {req['logic']}; opciones: {', '.join(req['options']) or 'Requisito individual'}",
                     f"Evidencias: {', '.join(match['evidence_ids']) or 'Sin evidencia documentada'}",
                     match['rationale'], '']
    decisions = '# Decisiones editoriales\n\n' + '\n'.join('- ' + x for x in adapted['decisions'])
    decisions += '\n\n## Pendiente de confirmar\n\n' + '\n'.join('- ' + x for x in adapted['questions']) + '\n'
    # Persist extracted facts and short supporting quotes, not a complete third-party advert.
    source_doc = (f'# Fuente de la oferta\n\nURL: {url}\n\nMétodo: {source_method}\n\n'
                  f"Fecha UTC: {report['generated_at']}\n\nSHA256 del texto leído: {report['source_sha256']}\n\n"
                  'El texto íntegro se conserva sólo en checkpoints privados para reanudar. Las citas están en job.json.\n')
    files = {'source.md': source_doc, 'job.json': dumps(job), 'adaptation.json': dumps(adapted),
             'match.md': '\n'.join(analysis), 'cv.tex': tex, 'decisions.md': decisions,
             'validation.json': dumps(report)}
    for content in files.values():
        assert_no_contacts(content, contacts)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    # Copy through a sibling temp file: CV_RUNS_DIR may be on another volume.
    with tempfile.NamedTemporaryFile(dir=pdf_path.parent, suffix='.pdf', delete=False) as temp_pdf:
        temporary_pdf = Path(temp_pdf.name)
    try:
        shutil.copyfile(staged_pdf, temporary_pdf)
        temporary_pdf.replace(pdf_path)
    finally:
        temporary_pdf.unlink(missing_ok=True)
    (ROOT / 'roles').mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cv-result-', dir=ROOT / 'roles') as staging:
        for name, content in files.items():
            (Path(staging) / name).write_text(content, encoding='utf-8')
        Path(staging).rename(ROOT / 'roles' / args.slug)
    print(f'Ready: roles/{args.slug}; private PDF: build/{args.slug}/cv.pdf', flush=True)
    print('Visual review remains required before sending the application.', flush=True)
