"""Strict model output schemas, shared by Codex, API and local validation."""
def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def array(item):
    return {'type': 'array', 'items': item}


S = {'type': 'string'}
STRINGS = array(S)
CLAIM = obj({'text': S, 'evidence_ids': STRINGS})
JOB = obj({'title': S, 'company': S, 'location': S, 'language': S,
           'conditions': STRINGS, 'responsibilities': STRINGS,
           'requirements': array(obj({'id': S, 'text': S,
                                     'priority': {'type': 'string', 'enum': ['required', 'preferred', 'unspecified']},
                                     'source_quote': S}))})
ADAPTATION = obj({
    'matches': array(obj({'requirement_id': S,
                         'status': {'type': 'string', 'enum': ['direct', 'transferable', 'gap', 'unconfirmed']},
                         'evidence_ids': STRINGS, 'rationale': S})),
    'headline': CLAIM, 'summary': CLAIM,
    'experience': array(obj({'role_id': S, 'bullets': array(CLAIM)})),
    'skills': array(CLAIM), 'decisions': STRINGS, 'questions': STRINGS})
AUDIT = obj({'supported': {'type': 'boolean'}, 'issues': STRINGS})
