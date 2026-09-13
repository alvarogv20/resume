"""Evidence adaptation with persistent stages and bounded, focused corrections."""
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
from .generate import ROOT, assert_no_private_contacts, assert_no_public_contacts, load_contacts, render, sanitize_public
from .llm import LLM
from .match import validate_adaptation, validate_job
from .schemas import ADAPTATION, AUDIT, JOB, obj, scoped
from .review import classify, fix_matches, repair_batch, literal_repairs, field_findings, normalize_matches, normalize_roles, fields
from .reports import analysis_documents
from .validate import compile_pdf
from .preflight import validate_profile, check_tools
from .state import RunState, atomic_json


def digest(value):
    return hashlib.sha256(value).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def run(args, settings):
    if (ROOT / 'roles' / args.slug).exists():
        raise ValueError('That role directory exists. Use a new version suffix to preserve prior results.')
    profile_bytes = (ROOT / 'profile/profile.yaml').read_bytes()
    profile = yaml.safe_load(profile_bytes)
    validate_profile(profile)
    # Missing contacts affect export, not analysis. Known contacts never reach a model.
    contacts = None
    contact_error = None
    try:
        contacts = load_contacts(args.contacts)
    except (ValueError, OSError) as error:
        contact_error = str(error)
    assert_no_private_contacts(profile_bytes.decode('utf-8'), contacts)
    implementation = [*sorted((ROOT / 'automation').rglob('*.py')),
                      *sorted((ROOT / 'automation/prompts').glob('*.txt')),
                      ROOT / 'templates/tailored-cv.tex.j2', ROOT / 'layout.tex', ROOT / 'requirements.txt']
    hashes = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in implementation}
    url = canonical_url(args.url)
    supplied = args.job_text.read_text(encoding='utf-8-sig') if args.job_text else None
    if supplied is not None:
        if not 250 <= len(supplied) <= 45000:
            raise ValueError('Job text must contain 250-45000 characters.')
        assert_no_private_contacts(supplied, contacts)
    identity = {'url': url, 'supplied_text': digest(supplied.encode()) if supplied is not None else None,
                'profile': digest(profile_bytes), 'implementation': hashes,
                'language': args.language, 'settings': settings.identity()}
    runs_root = Path(os.environ.get('CV_RUNS_DIR') or ROOT / '.private/runs')
    with RunState(runs_root / args.slug, identity, args.resume) as state:
        if getattr(args, 'restart_from', None):
            state.invalidate(args.restart_from)
        llm = LLM(settings=settings, state=state, root=ROOT,
                  output_guard=lambda value: assert_no_private_contacts(dumps(value), contacts))
        try:
            llm.preflight()
            return _generate(args, state, llm, profile, profile_bytes, hashes, contacts, contact_error, url, supplied)
        except Exception as error:
            stage = state.manifest.get('active_stage', 'preflight')
            state.stage(stage, 'failed', error_type=type(error).__name__, message=str(error))
            failure_status = 'render_failed' if stage == 'export' else 'requires_review'
            for name in ('match.md', 'decisions.md'):
                path = state.folder / name
                if path.exists():
                    content = path.read_text(encoding='utf-8').replace('Estado: ready', 'Estado: ' + failure_status, 1)
                    path.write_text(content, encoding='utf-8')
            atomic_json(state.folder / 'status.json', {'status': failure_status,
                        'failed_stage': stage, 'error_type': type(error).__name__, 'message': str(error),
                        'analysis_preserved': (state.folder / 'match.md').exists(), 'llm_calls': llm.calls})
            raise


def _generate(args, state, llm, profile, profile_bytes, hashes, contacts, contact_error, url, supplied):
    def stage(name):
        state.manifest['active_stage'] = name
        state.stage(name, 'running')
        print(f'Stage: {name}', flush=True)

    stage('extract')
    source_file = state.folder / 'source.json'
    if source_file.exists():
        saved = json.loads(source_file.read_text(encoding='utf-8'))
        source, method = saved['text'], saved['method']
        if digest(source.encode()) != saved['sha256']:
            raise ValueError('Saved source checksum failed; use a new slug.')
    else:
        if supplied is None:
            url, source = fetch_job(url)
            method = 'public-http'
        else:
            source, method = supplied, 'user-supplied-text'
        assert_no_private_contacts(source, contacts)
        atomic_json(source_file, {'text': source, 'method': method, 'sha256': digest(source.encode())})
    assert_no_private_contacts(source, contacts)
    job = llm.request('extract', {'source_text': source}, JOB)
    try:
        validate_job(job, source)
    except ValueError as error:
        job = llm.request('extract', {'source_text': source, 'previous_extraction': job,
                                     'correction_required': str(error)}, JOB)
        validate_job(job, source)
    atomic_json(state.folder / 'job.json', job)
    state.stage('extract', 'accepted')
    model_profile = {k: profile[k] for k in ('experience', 'skills', 'education', 'languages', 'unconfirmed') if k in profile}
    stage('adapt')
    adapted = llm.request('adapt', {'master_profile': model_profile, 'job': job,
                                  'requested_language': args.language}, scoped(ADAPTATION, profile, job))
    atomic_json(state.folder / 'draft.json', adapted)
    adapted = normalize_matches(profile, adapted)
    adapted = normalize_roles(profile, adapted, args.language)
    local_findings = field_findings(profile, adapted)
    if local_findings:
        try:
            adapted = repair_batch(profile, job, adapted, local_findings, llm, args.language)
        except ValueError:
            adapted = literal_repairs(profile, job, adapted, local_findings, args.language)
    # Structural errors are saved for targeted diagnosis; no whole-CV regeneration.
    validate_adaptation(profile, job, adapted)
    state.stage('adapt', 'accepted')
    warnings = []

    def persist(status):
        analysis, decisions = analysis_documents(profile, job, adapted, status, warnings)
        atomic_json(state.folder / 'adaptation.json', adapted)
        atomic_json(state.folder / 'job.json', job)
        (state.folder / 'match.md').write_text(analysis, encoding='utf-8')
        (state.folder / 'decisions.md').write_text(decisions, encoding='utf-8')
        atomic_json(state.folder / 'status.json', {'status': status, 'warnings': warnings, 'llm_calls': llm.calls})
        return analysis, decisions

    persist('requires_review')
    stage('audit')
    audit = llm.request('audit', {'master_profile': model_profile, 'source_text': source,
                                'job': job, 'adaptation': adapted},
                        scoped(AUDIT, profile, job, [p for p, _, _ in fields(adapted)]))
    initial_audit = audit
    review = classify(profile, job, adapted, audit, source)
    extraction_feedback = review['extraction_warnings']
    repair_history = []
    adapted = fix_matches(adapted, review['match_warnings'])
    if extraction_feedback:
        # Correct job and matching only. Accepted CV prose is never regenerated here.
        bundle_schema = obj({'job': JOB, 'matches': ADAPTATION['properties']['matches']})
        bundle = llm.request('extract', {'source_text': source, 'previous_extraction': job,
                            'previous_matches': adapted['matches'], 'master_profile': model_profile,
                            'corrections_required': extraction_feedback, 'correction_bundle': True}, scoped(bundle_schema, profile))
        validate_job(bundle['job'], source)
        candidate = normalize_matches(profile, {**adapted, 'matches': bundle['matches']})
        validate_adaptation(profile, bundle['job'], candidate)
        job, adapted = bundle['job'], candidate
    warnings.extend('Encaje corregido: ' + c['requirement_id'] + ': ' + c['rationale'] for c in review['match_warnings'])
    if review['cv_factual_issues']:
        stage('repair')
        repair_history.append(review['cv_factual_issues'])
        try:
            adapted = repair_batch(profile, job, adapted, review['cv_factual_issues'], llm, args.language)
        except ValueError:
            adapted = literal_repairs(profile, job, adapted, review['cv_factual_issues'], args.language)
        state.stage('repair', 'accepted')
    if extraction_feedback or review['cv_factual_issues']:
        persist('requires_review')
        stage('audit')
        audit = llm.request('audit', {'audit_scope': 'full' if extraction_feedback else 'adaptation',
                            'master_profile': model_profile, 'job': job, 'adaptation': adapted,
                            **({'source_text': source} if extraction_feedback else {})},
                            scoped(AUDIT, profile, job, [p for p, _, _ in fields(adapted)]))
        review = classify(profile, job, adapted, audit, source)
        adapted = fix_matches(adapted, review['match_warnings'])
        if review['cv_factual_issues']:
            # End the loop with literal, role-scoped evidence, not another model cycle.
            repair_history.append(review['cv_factual_issues'])
            adapted = literal_repairs(profile, job, adapted, review['cv_factual_issues'], args.language)
            warnings.append('Afirmaciones sustituidas por textos literales del perfil o traducciones de presentación tras la revisión.')
            review['cv_factual_issues'] = []
    warnings += review['extraction_warnings'] + review['audit_errors'] + review['notes']
    status = 'requires_review' if review['audit_errors'] or review['extraction_warnings'] else 'ready'
    state.stage('audit', 'accepted' if status == 'ready' else 'requires_review', review=review)
    analysis, decisions = persist(status)
    if getattr(args, 'analysis_only', False):
        print(f'Private analysis: {state.folder}', flush=True)
        return {'status': status, 'exported': False}
    stage('export')
    tex = render(profile, adapted, args.language)
    (state.folder / 'cv.tex').write_text(tex, encoding='utf-8')
    if contact_error:
        raise ValueError(contact_error)
    args.tectonic = check_tools(args.tectonic)
    staged_pdf = state.folder / 'cv.pdf'
    report = compile_pdf(tex, staged_pdf, contacts, args.max_pages, args.tectonic)
    if report.get('compacted'):
        tex = staged_pdf.with_suffix('.tex').read_text(encoding='utf-8')
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = 'unavailable'
    if (ROOT / 'profile/profile.yaml').read_bytes() != profile_bytes or any(digest((ROOT / p).read_bytes()) != h for p, h in hashes.items()):
        raise ValueError('Master or implementation changed during execution; rerun against a stable revision.')
    report.update({'status': status, 'warnings': warnings, 'review': review,
                   'source_url': url, 'source_method': method,
                   'generated_at': datetime.now(timezone.utc).isoformat(),
                   'profile_version': profile['version'], 'profile_sha256': digest(profile_bytes),
                   'source_sha256': digest(source.encode()), 'code_commit': commit,
                   'implementation_sha256': hashes, 'requested_language': args.language,
                   'llm_calls': llm.calls, 'llm_requests_total': state.manifest['requests'],
                   'audit': audit, 'initial_audit': initial_audit, 'repair_history': repair_history,
                   'extraction_repair_feedback': extraction_feedback, 'master_unchanged': True})
    atomic_json(state.folder / 'validation.json', report)
    state.stage('export', 'accepted', pages=report['pages'])
    if status != 'ready':
        print(f'Private review draft and PDF: {state.folder}', flush=True)
        return report
    source_doc = f'# Fuente de la oferta\n\nURL: {url}\n\nMétodo: {method}\n\nSHA256: {digest(source.encode())}\n'
    files = {'source.md': source_doc, 'job.json': dumps(job), 'adaptation.json': dumps(adapted),
             'match.md': analysis, 'cv.tex': tex, 'decisions.md': decisions, 'validation.json': dumps(report)}
    files = {name: sanitize_public(content, contacts) for name, content in files.items()}
    for content in files.values():
        assert_no_public_contacts(content, contacts)
    pdf_path = ROOT / 'build' / args.slug / 'cv.pdf'
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(staged_pdf, pdf_path)
    (ROOT / 'roles').mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cv-result-', dir=ROOT / 'roles') as staging:
        for name, content in files.items():
            (Path(staging) / name).write_text(content, encoding='utf-8')
        Path(staging).rename(ROOT / 'roles' / args.slug)
    print(f'Ready: roles/{args.slug}; private PDF: {pdf_path}', flush=True)
    print('Visual review remains required before sending the application.', flush=True)
    return report
