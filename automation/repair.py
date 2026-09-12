"""Bounded field repair with typed, evidence-only deterministic fallbacks."""
import copy
import itertools
from jsonschema import ValidationError
from .match import fact_index, validate_adaptation, validate_professional_field, WORD_LIMITS, WORD_TARGETS
from .schemas import CLAIM


def claim_at(adapted, path):
    if path in ('headline', 'summary'):
        return adapted[path]
    parts = path.split(':')
    if len(parts) == 2 and parts[0] == 'skill' and parts[1].isdigit():
        return adapted['skills'][int(parts[1])]
    if len(parts) == 3 and parts[0] == 'bullet' and parts[2].isdigit():
        role = next(r for r in adapted['experience'] if r['role_id'] == parts[1])
        return role['bullets'][int(parts[2])]
    raise ValueError('Unknown claim path from audit.')


def allowed_facts(profile, path):
    if path.startswith('bullet:'):
        role = next(r for r in profile['experience'] if r['id'] == path.split(':')[1])
        return {f['id']: f['text'] for f in role['facts']}
    if path.startswith('skill:'):
        return {f['id']: f['text'] for f in profile['skills']}
    return fact_index(profile)


def fallback(profile, path, preferred, limit):
    experience = {f['id']: f['text'] for r in profile['experience'] for f in r['facts']}
    skills = {f['id']: f['text'] for f in profile['skills']}
    if path == 'headline':
        candidates = {r['id']: r['title'] for r in profile['experience']}
    elif path == 'summary':
        candidates = {**experience, **skills}
    else:
        candidates = allowed_facts(profile, path)
    # Prefer retained evidence within each professional category, never education.
    ids = sorted(candidates, key=lambda i: (i not in experience if path == 'summary' else False,
                                           i not in preferred))
    sizes = (3, 2) if path == 'summary' else (1,)
    for size in sizes:
        for selected in itertools.combinations(ids, size):
            text = ' '.join(candidates[i] for i in selected)
            if text.strip() and len(text.split()) <= limit:
                return {'text': text, 'evidence_ids': list(selected)}
    raise ValueError(f'No safe {path} fallback fits the current word limit.')


def repair(profile, job, adapted, audit, llm=None, attempts=None, language='en'):
    if audit['extraction_issues']:
        raise ValueError('Semantic extraction audit failed; review the source before generating a CV.')
    if not audit['match_corrections'] and not audit['unsupported_claims']:
        raise ValueError('Audit rejected the draft without actionable corrections.')
    attempts = attempts if attempts is not None else {}
    result = copy.deepcopy(adapted)
    matches = {m['requirement_id']: m for m in result['matches']}
    for correction in audit['match_corrections']:
        if correction['requirement_id'] not in matches:
            raise ValueError('Audit correction refers to an unknown requirement.')
        matches[correction['requirement_id']].update(correction)
    seen = set()
    for finding in audit['unsupported_claims']:
        path = finding['path']
        if path in seen:
            raise ValueError('Duplicate claim path from audit.')
        seen.add(path)
        claim = claim_at(result, path)
        allowed = allowed_facts(profile, path)
        if not finding['fragment'].strip() or not finding['reason'].strip():
            raise ValueError('Audit must explain the exact failing fragment.')
        if set(finding['valid_evidence_ids']) - allowed.keys():
            raise ValueError('Audit retained evidence outside the field scope.')
        limit = 65 if path == 'summary' else 14 if path == 'headline' else 32
        if path.startswith('skill:'):
            limit = 80 - sum(len(s['text'].split()) for s in result['skills'] if s is not claim)
        error = None
        while llm is not None and attempts.get(path, 0) < 2:
            attempts[path] = attempts.get(path, 0) + 1
            payload = {'field': path, 'previous_text': claim['text'],
                       'allowed_evidence': allowed, 'rejection': finding,
                       'instruction': 'Remove only the problematic assertion; preserve supported content.',
                       'requested_language': language,
                       'length_limits': {'max_words': limit, 'headline': 14, 'summary': 65,
                                         'bullet': 32, 'skills_total': 80},
                       'validation_error': error, 'attempt': attempts[path]}
            try:
                regenerated = llm.request('repair', payload, CLAIM)
            except ValueError as exc:
                if str(exc) != 'LLM result does not match the stage schema.':
                    raise
                error = str(exc)
                continue
            candidate = copy.deepcopy(result)
            claim_at(candidate, path).update(regenerated)
            try:
                if set(regenerated['evidence_ids']) - allowed.keys():
                    raise ValueError('Repair cites evidence outside the field scope.')
                validate_adaptation(profile, job, candidate)
            except (ValueError, ValidationError) as exc:
                error = str(exc)
                continue
            claim.update(regenerated)
            break
        else:
            claim.update(fallback(profile, path, finding['valid_evidence_ids'], limit))
    result['decisions'].append('Campos rechazados reparados con evidencia; fallback específico tras agotar los intentos generativos.')
    validate_adaptation(profile, job, result)
    return result


def repair_lengths(profile, adapted, llm, attempts=None, language='en'):
    """Repair oversized professional fields independently, before full validation/audit."""
    attempts = attempts if attempts is not None else {}
    result = copy.deepcopy(adapted)
    for field, limit in WORD_LIMITS.items():
        claim = result[field]
        if len(claim['text'].split()) <= limit:
            continue
        allowed = allowed_facts(profile, field)
        error = f"{field}: {len(claim['text'].split())} words; maximum: {limit} words."
        while attempts.get(field, 0) < 2:
            attempts[field] = attempts.get(field, 0) + 1
            payload = {
                'field': field, 'previous_text': claim['text'],
                'allowed_evidence': allowed, 'requested_language': language,
                'instruction': 'Shorten only this field. Preserve supported meaning and evidence; add no claims.',
                'rejection': {'path': field, 'fragment': claim['text'], 'reason': error,
                              'valid_evidence_ids': [i for i in claim['evidence_ids'] if i in allowed]},
                'length_limits': {'max_words': WORD_TARGETS[field], 'hard_max_words': limit},
                'validation_error': error, 'attempt': attempts[field],
            }
            try:
                regenerated = llm.request('repair', payload, CLAIM)
            except ValueError as exc:
                if str(exc) != 'LLM result does not match the stage schema.':
                    raise
                error = str(exc)
                continue
            try:
                validate_professional_field(profile, field, regenerated)
            except (ValueError, ValidationError) as exc:
                error = str(exc)
                claim = regenerated
                continue
            result[field] = regenerated
            break
        else:
            result[field] = fallback(profile, field, result[field]['evidence_ids'], limit)
            validate_professional_field(profile, field, result[field])
    return result
