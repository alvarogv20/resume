"""Classify auditor feedback and repair affected fields in one bounded batch."""
import copy
from jsonschema import ValidationError

from .match import allowed_facts, fact_index, validate_adaptation, validate_field
from .repair import claim_at, fallback
from .schemas import BATCH_REPAIR, scoped


def normalize_roles(profile, adapted, language):
    """Retain only real employers, never infer a role from a positional index."""
    result = copy.deepcopy(adapted)
    roles = []
    for master in profile['experience']:
        matching = [r for r in result['experience'] if r['role_id'] == master['id']]
        bullets = [b for r in matching for b in r['bullets']][:4]
        if not bullets:
            bullets = [fallback(profile, 'bullet:' + master['id'] + ':0', [], 32, language)]
        roles.append({'role_id': master['id'], 'bullets': bullets})
    if roles != result['experience']:
        result['decisions'].append('Experiencia normalizada a los empleos reales y al orden del perfil; se omiten bloques ajenos y se restauran omisiones con evidencia literal.')
    result['experience'] = roles
    return result


def normalize_matches(profile, adapted):
    """Remove nonexistent references without inventing replacement evidence."""
    result = copy.deepcopy(adapted)
    facts = fact_index(profile)
    for match in result['matches']:
        invalid = set(match['evidence_ids']) - facts.keys()
        if not invalid:
            continue
        match['evidence_ids'] = [i for i in match['evidence_ids'] if i in facts]
        if match['status'] in ('direct', 'transferable', 'not_applicable'):
            match['status'] = 'transferable' if match['evidence_ids'] else 'unconfirmed'
        match['rationale'] += ' Se han retirado referencias inexistentes; solo se conserva la evidencia conocida del perfil.'
        result['decisions'].append('Referencias de evidencia inválidas retiradas de ' + match['requirement_id'] + ': ' + ', '.join(sorted(invalid)))
    return result


def fields(adapted):
    yield 'headline', adapted['headline'], 14
    yield 'summary', adapted['summary'], 65
    for n, skill in enumerate(adapted['skills']):
        yield f'skill:{n}', skill, max(1, 80 // len(adapted['skills']))
    for role in adapted['experience']:
        for n, claim in enumerate(role['bullets']):
            yield f"bullet:{role['role_id']}:{n}", claim, 32


def classify(profile, job, adapted, audit, source=None):
    result = {'cv_factual_issues': [], 'match_warnings': [],
              'extraction_warnings': [], 'audit_errors': [], 'notes': list(audit['issues'])}
    for finding in audit['extraction_issues']:
        if (not finding['reason'].strip() or not finding['source_quote'].strip()
                or (source is not None and ' '.join(finding['source_quote'].split()) not in ' '.join(source.split()))):
            result['audit_errors'].append('Feedback de extracción sin cita verificable')
        elif finding['severity'] == 'editorial':
            result['notes'].append(finding['reason'])
        else:
            result['extraction_warnings'].append(finding['reason'])
    known = {path: claim for path, claim, _ in fields(adapted)}
    seen = set()
    for finding in audit['unsupported_claims']:
        finding = dict(finding)
        path = finding['path']
        if path in known and finding['fragment'].strip() and finding['fragment'] not in known[path]['text']:
            # Recover an off-by-one index only from a unique exact span within
            # the same role/field group; never move evidence across employers.
            group = path.rsplit(':', 1)[0] + ':' if ':' in path else None
            candidates = [p for p, c in known.items() if group and p.startswith(group)
                          and finding['fragment'] in c['text']
                          and not set(finding['valid_evidence_ids']) - allowed_facts(profile, p).keys()]
            if len(candidates) == 1:
                path = candidates[0]
                result['notes'].append('Índice del auditor corregido por fragmento exacto: ' + finding['path'] + ' → ' + path)
                finding['path'] = path
        if (path not in known or path in seen or not finding['fragment'].strip()
                or finding['fragment'] not in known[path]['text'] or not finding['reason'].strip()
                or set(finding['valid_evidence_ids']) - allowed_facts(profile, path).keys()):
            result['audit_errors'].append('Feedback de afirmación no accionable: ' + path)
            continue
        seen.add(path)
        result['cv_factual_issues'].append(finding)
    for correction in audit['match_corrections']:
        candidate = copy.deepcopy(adapted)
        match = next((m for m in candidate['matches'] if m['requirement_id'] == correction['requirement_id']), None)
        if match is None:
            result['audit_errors'].append('Corrección de requisito desconocido')
            continue
        match.update(correction)
        try:
            validate_adaptation(profile, job, candidate)
        except ValueError:
            result['audit_errors'].append('Corrección de encaje inválida: ' + correction['requirement_id'])
            continue
        result['match_warnings'].append(correction)
    if not audit['supported'] and not any(result[k] for k in ('cv_factual_issues', 'match_warnings', 'extraction_warnings', 'audit_errors')):
        result['audit_errors'].append('Auditoría negativa sin correcciones accionables')
    # General prose never proves a factual error, but must remain visible.
    return result


def fix_matches(adapted, corrections):
    result = copy.deepcopy(adapted)
    for correction in corrections:
        next(m for m in result['matches'] if m['requirement_id'] == correction['requirement_id']).update(correction)
    return result


def repair_batch(profile, job, adapted, findings, llm, language):
    result = copy.deepcopy(adapted)
    limits = {path: limit for path, _, limit in fields(result)}
    requests = []
    for finding in findings:
        path = finding['path']
        requests.append({'path': path, 'previous_text': claim_at(result, path)['text'],
                         'allowed_evidence': allowed_facts(profile, path), 'rejection': finding,
                         'max_words': limits[path]})
    response = llm.request('repair', {'fields': requests, 'requested_language': language},
                           scoped(BATCH_REPAIR, profile, job, [r['path'] for r in requests]))
    candidates = {item['path']: item['claim'] for item in response['claims']}
    if len(candidates) != len(response['claims']) or set(candidates) != {r['path'] for r in requests}:
        raise ValueError('Batch repair must return each requested field exactly once.')
    for path, claim in candidates.items():
        validate_field(profile, path, claim, limits[path])
        claim_at(result, path).update(claim)
    validate_adaptation(profile, job, result)
    return result


def literal_repairs(profile, job, adapted, findings, language):
    result = copy.deepcopy(adapted)
    limits = {path: limit for path, _, limit in fields(result)}
    for finding in findings:
        path = finding['path']
        claim_at(result, path).update(fallback(profile, path, finding['valid_evidence_ids'], limits[path], language))
    validate_adaptation(profile, job, result)
    return result


def length_findings(adapted):
    findings = []
    skills_long = sum(len(c['text'].split()) for c in adapted['skills']) > 80
    for path, claim, limit in fields(adapted):
        if path.startswith('skill:') and not skills_long:
            continue
        if len(claim['text'].split()) > limit:
            findings.append({'path': path, 'fragment': claim['text'],
                             'reason': f'Shorten this field to at most {limit} words.',
                             'valid_evidence_ids': claim['evidence_ids']})
    return findings


def field_findings(profile, adapted):
    """Repair all locally invalid fields together, not just oversized ones."""
    findings = []
    skills_long = sum(len(c['text'].split()) for c in adapted['skills']) > 80
    for path, claim, limit in fields(adapted):
        if path.startswith('skill:') and not skills_long:
            limit = 80
        try:
            validate_field(profile, path, claim, limit)
        except (ValueError, ValidationError) as error:
            allowed = allowed_facts(profile, path)
            findings.append({'path': path, 'fragment': claim['text'], 'reason': str(error),
                             'valid_evidence_ids': [i for i in claim['evidence_ids'] if i in allowed]})
    return findings
