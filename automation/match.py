"""Validate evidence links independently of the model's self-assessment."""
import re
from jsonschema import validate
from .schemas import ADAPTATION, JOB


def fact_index(profile):
    facts = {}
    for group in ('skills', 'education', 'languages'):
        for fact in profile[group]:
            if fact['id'] in facts:
                raise ValueError('Duplicate profile fact ID.')
            facts[fact['id']] = fact['text']
    for role in profile['experience']:
        if role['id'] in facts:
            raise ValueError('Duplicate profile role ID.')
        facts[role['id']] = ' | '.join(role[k] for k in ('title', 'company', 'dates'))
        for fact in role['facts']:
            if fact['id'] in facts:
                raise ValueError('Duplicate profile fact ID.')
            facts[fact['id']] = fact['text']
    return facts


def validate_job(job, source):
    validate(job, JOB)
    if not job['title'].strip() or not job['company'].strip() or not job['requirements']:
        raise ValueError('No complete job posting extracted; supply --job-text.')
    ids = [x['id'] for x in job['requirements']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate job requirement ID.')
    normalized = ' '.join(source.split())
    for requirement in job['requirements']:
        # Models sometimes add a final sentence mark; that is not a factual change.
        quote = ' '.join(requirement['source_quote'].split()).rstrip('.,;:')
        if not quote or quote not in normalized:
            raise ValueError('A requirement quote is not present in the source.')


def validate_adaptation(profile, job, adapted):
    validate(adapted, ADAPTATION)
    facts = fact_index(profile)
    role_ids = [role['id'] for role in profile['experience']]
    if [role['role_id'] for role in adapted['experience']] != role_ids:
        raise ValueError('All roles must retain master order and identity.')
    expected = {r['id'] for r in job['requirements']}
    received = [m['requirement_id'] for m in adapted['matches']]
    if set(received) != expected or len(received) != len(expected):
        raise ValueError('Every requirement must be matched exactly once.')
    for match in adapted['matches']:
        if set(match['evidence_ids']) - facts.keys():
            raise ValueError('Unknown match evidence.')
        if match['status'] in ('direct', 'transferable') and not match['evidence_ids']:
            raise ValueError('Positive match without evidence.')
    claims = [adapted['headline'], adapted['summary'], *adapted['skills']]
    for role, master in zip(adapted['experience'], profile['experience']):
        if not 1 <= len(role['bullets']) <= 4:
            raise ValueError('Each role needs 1-4 supported bullets.')
        allowed = {fact['id'] for fact in master['facts']}
        for bullet in role['bullets']:
            if set(bullet['evidence_ids']) - allowed:
                raise ValueError('Bullet cites evidence from the wrong role.')
        claims.extend(role['bullets'])
    for claim in claims:
        if not claim['text'].strip() or not claim['evidence_ids'] or set(claim['evidence_ids']) - facts.keys():
            raise ValueError('CV claim missing known evidence.')
        if re.search(r'@|https?://|linkedin\.com|[<>\\]', claim['text'], re.I):
            raise ValueError('CV claim contains contacts, markup or executable text.')
        numbers = set(re.findall(r'\d+(?:[.,]\d+)?', claim['text']))
        evidence = ' '.join(facts[i] for i in claim['evidence_ids'])
        if numbers - set(re.findall(r'\d+(?:[.,]\d+)?', evidence)):
            raise ValueError('CV claim contains unsupported numeric facts.')
    return facts
