"""Validate master facts and local dependencies before network/model work."""
from datetime import date
import re

from .match import fact_index
from .executables import resolve_tool


def validate_profile(profile):
    def text(value):
        return isinstance(value, str) and bool(value.strip())

    if not isinstance(profile, dict):
        raise ValueError('Profile must be a YAML object.')
    if type(profile.get('version')) is not int or profile['version'] < 1:
        raise ValueError('Profile version must be a positive integer.')
    try:
        date.fromisoformat(str(profile['reviewed_on']))
    except (KeyError, ValueError):
        raise ValueError('Profile needs a valid reviewed_on date.') from None
    if not all(text(profile.get(k)) for k in ('name', 'location')):
        raise ValueError('Profile needs name and location.')
    for group in ('experience', 'skills', 'education', 'languages'):
        if not isinstance(profile.get(group), list):
            raise ValueError('Profile groups must be lists.')
    if not profile['experience']:
        raise ValueError('Profile needs at least one experience role.')
    facts = [*profile['skills'], *profile['education'], *profile['languages']]
    for role in profile['experience']:
        if not isinstance(role, dict) or not all(text(role.get(k)) for k in ('id', 'title', 'company', 'dates', 'location')):
            raise ValueError('Profile role is missing required text fields.')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', role['id']):
            raise ValueError('Profile role IDs must use letters, digits, underscores or hyphens.')
        if not isinstance(role.get('facts'), list) or not role['facts']:
            raise ValueError('Every profile role needs evidence facts.')
        facts.extend(role['facts'])
    for fact in facts:
        if not isinstance(fact, dict) or not all(text(fact.get(k)) for k in ('id', 'text')):
            raise ValueError('Profile facts need nonempty IDs and text.')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', fact['id']):
            raise ValueError('Profile evidence IDs contain unsupported characters.')
    if 'unconfirmed' in profile and (not isinstance(profile['unconfirmed'], list)
                                     or not all(text(x) for x in profile['unconfirmed'])):
        raise ValueError('Profile unconfirmed facts must be a list of text.')
    fact_index(profile)


def check_tools(tectonic=None):
    return resolve_tool('tectonic', tectonic)
