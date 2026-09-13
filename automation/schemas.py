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
           'requirements': array(obj({'id': S, 'text': S, 'condition': S,
                                     'logic': {'type': 'string', 'enum': ['single', 'any', 'all']},
                                     'options': STRINGS,
                                     'priority': {'type': 'string', 'enum': ['required', 'preferred', 'unspecified']},
                                     'source_quote': S}))})
ADAPTATION = obj({
    'matches': array(obj({'requirement_id': S,
                         'status': {'type': 'string', 'enum': ['direct', 'transferable', 'gap', 'unconfirmed', 'not_applicable']},
                         'evidence_ids': STRINGS, 'rationale': S})),
    'headline': CLAIM, 'summary': CLAIM,
    'experience': array(obj({'role_id': S, 'bullets': array(CLAIM)})),
    'skills': array(CLAIM), 'decisions': STRINGS, 'questions': STRINGS})
AUDIT = obj({'supported': {'type': 'boolean'}, 'issues': STRINGS,
             'extraction_issues': array(obj({
                 'severity': {'type': 'string', 'enum': ['material', 'editorial']},
                 'reason': S, 'source_quote': S})), 'unsupported_claims': array(obj({
                 'path': S, 'fragment': S, 'reason': S, 'valid_evidence_ids': STRINGS})),
             'match_corrections': array(obj({'requirement_id': S,
                                            'status': {'type': 'string', 'enum': ['direct', 'transferable', 'gap', 'unconfirmed', 'not_applicable']},
                                            'rationale': S}))})

BATCH_REPAIR = obj({'claims': array(obj({'path': S, 'claim': CLAIM}))})

# Express deterministic structural limits at the provider boundary as well.
ADAPTATION['properties']['skills'].update(minItems=1, maxItems=3)
ADAPTATION['properties']['experience']['items']['properties']['bullets'].update(minItems=1, maxItems=4)
CLAIM['properties']['text'] = {'type': 'string', 'minLength': 1}
CLAIM['properties']['evidence_ids'] = {'type': 'array', 'items': S, 'minItems': 1}


def scoped(schema, profile, job=None, paths=None):
    """Give providers the same finite ID vocabulary enforced by local validators."""
    import json
    from .match import fact_index
    # The base schemas share S/STRINGS dictionaries. A JSON round-trip expands
    # those aliases so a role enum cannot accidentally constrain unrelated text.
    result = json.loads(json.dumps(schema))
    evidence = list(fact_index(profile))
    roles = [r['id'] for r in profile['experience']]
    requirements = [r['id'] for r in job['requirements']] if job else None

    def visit(node):
        if isinstance(node, dict):
            for name, prop in node.get('properties', {}).items():
                if name in ('evidence_ids', 'valid_evidence_ids'):
                    prop['items'] = {'type': 'string', 'enum': evidence}
                elif name == 'role_id':
                    prop['enum'] = roles
                elif name == 'requirement_id' and requirements:
                    prop['enum'] = requirements
                elif name == 'path' and paths:
                    prop['enum'] = list(paths)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)
    visit(result)
    return result
