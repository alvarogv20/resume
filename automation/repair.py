"""Conservative, deterministic repairs: downgrade matches or restore literal facts."""
import copy
from .match import fact_index, validate_adaptation


def repair(profile, job, adapted, audit):
    if audit['extraction_issues']:
        raise ValueError('Semantic extraction audit failed; review the source before generating a CV.')
    if not audit['match_corrections'] and not audit['unsupported_claims']:
        raise ValueError('Audit rejected the draft without actionable corrections.')
    result = copy.deepcopy(adapted)
    facts = fact_index(profile)
    matches = {m['requirement_id']: m for m in result['matches']}
    for correction in audit['match_corrections']:
        if correction['requirement_id'] not in matches:
            raise ValueError('Audit correction refers to an unknown requirement.')
        matches[correction['requirement_id']].update(correction)
    for path in audit['unsupported_claims']:
        if path in ('headline', 'summary'):
            claim = result[path]
        elif path.startswith('skill:'):
            claim = result['skills'][int(path.split(':')[1])]
        elif path.startswith('bullet:'):
            _, role_id, index = path.split(':')
            role = next(r for r in result['experience'] if r['role_id'] == role_id)
            claim = role['bullets'][int(index)]
        else:
            raise ValueError('Unknown claim path from audit.')
        # No rewriting by another generator: use exactly one evidenced master fact.
        evidence_id = claim['evidence_ids'][0]
        claim['text'] = facts[evidence_id]
        claim['evidence_ids'] = [evidence_id]
    result['decisions'].append('La auditoría aplicó correcciones conservadoras: coincidencias rebajadas y afirmaciones dudosas sustituidas por hechos literales del maestro.')
    validate_adaptation(profile, job, result)
    return result
