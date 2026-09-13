"""Validate evidence links independently of the model's self-assessment."""
import re
from decimal import Decimal
from jsonschema import validate
from .schemas import ADAPTATION, JOB, CLAIM


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


WORD_LIMITS = {'headline': 14, 'summary': 65}
WORD_TARGETS = {'headline': 12, 'summary': 55}


def validate_claim(claim, facts):
    validate(claim, CLAIM)
    if not claim['text'].strip() or not claim['evidence_ids'] or set(claim['evidence_ids']) - facts.keys():
        raise ValueError('CV claim missing known evidence.')
    if re.search(r'@|https?://|linkedin\.com|[<>\\]', claim['text'], re.I):
        raise ValueError('CV claim contains contacts, markup or executable text.')
    numbers = numeric_values(claim['text'])
    evidence = ' '.join(facts[i] for i in claim['evidence_ids'])
    if numbers - numeric_values(evidence):
        raise ValueError('CV claim contains unsupported numeric facts.')


def numeric_values(text):
    return {Decimal(x.replace(',', '.')) for x in re.findall(r'\d+(?:[.,]\d+)?', text)}


def allowed_facts(profile, path):
    if path.startswith('bullet:'):
        role = next(r for r in profile['experience'] if r['id'] == path.split(':')[1])
        return {f['id']: f['text'] for f in role['facts']}
    return fact_index(profile)


def validate_field(profile, path, claim, limit=None):
    validate_claim(claim, allowed_facts(profile, path))
    if path in WORD_LIMITS:
        validate_professional_field(profile, path, claim)
    maximum = limit if limit is not None else WORD_LIMITS.get(path, 32 if path.startswith('bullet:') else 80)
    if len(claim['text'].split()) > maximum:
        raise ValueError(f'{path} exceeds {maximum} words.')


def validate_professional_field(profile, field, claim):
    facts = fact_index(profile)
    validate_claim(claim, facts)
    count = len(claim['text'].split())
    if count > WORD_LIMITS[field]:
        raise ValueError(f'{field}: {count} words; maximum: {WORD_LIMITS[field]} words.')
    professional = {f['id'] for r in profile['experience'] for f in r['facts']}
    professional.update(f['id'] for f in profile['skills'])
    titles = {r['id']: r['title'] for r in profile['experience']}
    from .localization import ES
    administrative = {f['text'].strip().casefold() for group in ('education', 'languages') for f in profile[group]}
    administrative.update(facts[r['id']].strip().casefold() for r in profile['experience'])
    text = claim['text'].strip()
    title_only = field == 'headline' and any(
        text.casefold() in (titles.get(i, '').casefold(), ES.get(titles.get(i, ''), '').casefold())
        for i in claim['evidence_ids'])
    if (not (set(claim['evidence_ids']) & professional or title_only)
            or text.casefold() in administrative or not re.search(r'[^\W\d_]', text)):
        raise ValueError(f'{field} must describe professional experience or competencies, not education, language, dates or administration.')


def validate_adaptation(profile, job, adapted):
    validate(adapted, ADAPTATION)
    if not 1 <= len(adapted['skills']) <= 3 or sum(len(s['text'].split()) for s in adapted['skills']) > 80:
        raise ValueError('Skills need 1-3 lines totaling at most 80 words.')
    facts = fact_index(profile)
    for field in WORD_LIMITS:
        validate_professional_field(profile, field, adapted[field])
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
        if match['status'] == 'not_applicable':
            requirement = next(r for r in job['requirements'] if r['id'] == match['requirement_id'])
            if not requirement['condition'].strip() or not match['rationale'].strip() or not match['evidence_ids']:
                raise ValueError('Not applicable needs a condition, justification and evidence.')
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
        validate_claim(claim, facts)
    return facts
