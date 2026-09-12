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
        if not requirement['id'].strip() or not requirement['text'].strip():
            raise ValueError('Requirement ID and text must be nonempty.')
        options = requirement['options']
        if requirement['logic'] == 'single' and options:
            raise ValueError('A single requirement must have no alternative options.')
        if requirement['logic'] != 'single' and (len(options) < 2 or len(set(options)) != len(options)
                                                  or any(not x.strip() for x in options)):
            raise ValueError('Grouped requirements need at least two distinct nonempty options.')


def validate_adaptation(profile, job, adapted):
    validate(adapted, ADAPTATION)
    if len(adapted['headline']['text'].split()) > 14 or len(adapted['summary']['text'].split()) > 65:
        raise ValueError('Headline must be at most 14 words; summary at most 65 words.')
    if not 1 <= len(adapted['skills']) <= 3 or sum(len(s['text'].split()) for s in adapted['skills']) > 80:
        raise ValueError('Skills need 1-3 lines totaling at most 80 words.')
    facts = fact_index(profile)
    professional = {f['id'] for r in profile['experience'] for f in r['facts']}
    professional.update(f['id'] for f in profile['skills'])
    titles = {r['id']: r['title'] for r in profile['experience']}
    administrative = {f['text'].strip().casefold() for group in ('education', 'languages') for f in profile[group]}
    administrative.update(facts[r['id']].strip().casefold() for r in profile['experience'])
    for field in ('summary', 'headline'):
        claim = adapted[field]
        text = claim['text'].strip()
        title_only = field == 'headline' and any(
            text.casefold() == titles.get(i, '').casefold() for i in claim['evidence_ids'])
        if (not (set(claim['evidence_ids']) & professional or title_only)
                or text.casefold() in administrative or not re.search(r'[^\W\d_]', text)):
            raise ValueError(f'{field} must describe professional experience or competencies, not education, language, dates or administration.')
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
        if match['status'] == 'direct' and re.search(
                r'not (?:evidenced|documented|explicit|fully)|no (?:evidence|explicit evidence)|'
                r'not supported|sin evidencia|no (?:acreditad|documentad)|no se (?:acredita|documenta)|'
                r'parcial|partially', match['rationale'], re.I):
            raise ValueError('A direct match rationale admits missing or partial evidence; use transferable/unconfirmed.')
    claims = [adapted['headline'], adapted['summary'], *adapted['skills']]
    for role, master in zip(adapted['experience'], profile['experience']):
        if not 1 <= len(role['bullets']) <= 4:
            raise ValueError('Each role needs 1-4 supported bullets.')
        allowed = {fact['id'] for fact in master['facts']}
        for bullet in role['bullets']:
            if len(bullet['text'].split()) > 32:
                raise ValueError('Experience bullets must be at most 32 words.')
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
