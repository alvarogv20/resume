import copy
import json
from pathlib import Path
import tempfile
import unittest

import yaml
from automation.generate import ROOT, render
from automation.localization import localized_profile
from automation.match import validate_adaptation, validate_claim, allowed_facts
from automation.repair import fallback
from automation.review import classify
from automation.state import RunState
from automation.validate import layout_issues
from test_automation import fixture
from test_providers import AUDITED


class ReviewRegressionTests(unittest.TestCase):
    def test_numeric_format_does_not_change_facts(self):
        for text in ('Managed 10.0 people.', 'Managed 10,0 people.'):
            validate_claim({'text': text, 'evidence_ids': ['team']}, {'team': 'Managed 10 people.'})
        with self.assertRaises(ValueError):
            validate_claim({'text': 'Managed 11 people.', 'evidence_ids': ['team']}, {'team': 'Managed 10 people.'})

    def test_skills_accept_experience_but_bullets_keep_role_scope(self):
        profile, _, _ = fixture()
        self.assertIn('fact-a', allowed_facts(profile, 'skill:0'))
        self.assertNotIn('fact-a', allowed_facts(profile, 'bullet:role-b:0'))

    def test_not_applicable_requires_condition_and_evidence(self):
        profile, job, adapted = fixture()
        adapted['matches'][0].update(status='not_applicable', rationale='La condición no se aplica según la evidencia.')
        with self.assertRaises(ValueError):
            validate_adaptation(profile, job, adapted)
        job['requirements'][0]['condition'] = 'Only for foreign qualifications'
        validate_adaptation(profile, job, adapted)
        adapted['matches'][0]['evidence_ids'] = []
        with self.assertRaises(ValueError):
            validate_adaptation(profile, job, adapted)

    def test_invalid_auditor_path_is_review_error(self):
        profile, job, adapted = fixture()
        audit = {**AUDITED, 'supported': False, 'unsupported_claims': [
            {'path': 'bullet:unknown:999', 'fragment': 'bad', 'reason': 'bad', 'valid_evidence_ids': []}]}
        result = classify(profile, job, adapted, audit)
        self.assertTrue(result['audit_errors'])
        self.assertFalse(result['cv_factual_issues'])

    def test_span_not_present_is_not_proof_of_falsity(self):
        profile, job, adapted = fixture()
        audit = {**AUDITED, 'supported': False, 'unsupported_claims': [
            {'path': 'summary', 'fragment': 'never written', 'reason': 'Scope', 'valid_evidence_ids': ['fact-a']}]}
        self.assertTrue(classify(profile, job, adapted, audit)['audit_errors'])

    def test_spanish_static_fields_and_fallbacks(self):
        profile = yaml.safe_load((ROOT / 'profile/profile.yaml').read_text(encoding='utf-8'))
        localized = localized_profile(profile, 'es')
        self.assertEqual(localized['languages'][0]['text'], 'Español: nativo')
        for path, limit in [('headline', 14), ('summary', 65), ('skill:0', 80), ('bullet:solute-loads:0', 32)]:
            claim = fallback(profile, path, [], limit, 'es')
            self.assertNotIn('Developed', claim['text'])
            self.assertNotIn('Manage ', claim['text'])
        adapted = {'headline': fallback(profile, 'headline', [], 14, 'es'),
                   'summary': fallback(profile, 'summary', [], 65, 'es'),
                   'skills': [fallback(profile, 'skill:0', [], 80, 'es')],
                   'experience': [{'role_id': r['id'], 'bullets': [fallback(profile, 'bullet:'+r['id']+':0', [], 32, 'es')]} for r in profile['experience']]}
        tex = render(profile, adapted, 'es')
        for english in ('Present', "Master's Degree", 'Spanish: Native', 'Madrid, Spain'):
            self.assertNotIn(english, tex)

    def test_source_change_requires_translation_update(self):
        profile = yaml.safe_load((ROOT / 'profile/profile.yaml').read_text(encoding='utf-8'))
        profile['experience'][0]['title'] = 'New unreviewed title'
        with self.assertRaisesRegex(ValueError, 'translation'):
            localized_profile(profile, 'es')

    def test_selective_resume_keeps_accepted_upstream_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            with RunState(folder, {'input': 1}) as state:
                for stage in ('extract', 'adapt', 'audit', 'repair'):
                    state.save(stage, {'metadata': {'stage': stage}, 'result': {}})
                    state.stage(stage, 'accepted')
            with RunState(folder, {'input': 1}, True) as state:
                state.invalidate('audit')
                self.assertIsNotNone(state.cached('extract'))
                self.assertIsNotNone(state.cached('adapt'))
                self.assertIsNone(state.cached('audit'))
                self.assertIsNone(state.cached('repair'))
                self.assertEqual(state.manifest['stages']['adapt']['status'], 'accepted')

    def test_overflow_diagnostics_measure_magnitude_and_line(self):
        result = layout_issues('Overfull \\hbox (0.15pt too wide) in paragraph at lines 10--11\nOverfull \\vbox (12.0pt too high) detected at line 30')
        self.assertEqual([x['points'] for x in result], [0.15, 12.0])
        self.assertIn('10--11', result[0]['line'])


    def test_editorial_feedback_is_not_a_material_extraction_block(self):
        profile, job, adapted = fixture()
        audit = {**AUDITED, 'extraction_issues': [{'severity': 'editorial', 'reason': 'Personality nuance', 'source_quote': 'Python'}]}
        result = classify(profile, job, adapted, audit, 'Python')
        self.assertEqual(result['extraction_warnings'], [])
        self.assertIn('Personality nuance', result['notes'])
        audit['extraction_issues'][0]['severity'] = 'material'
        self.assertEqual(classify(profile, job, adapted, audit, 'Python')['extraction_warnings'], ['Personality nuance'])

    def test_unique_exact_fragment_recovers_index_only_within_role(self):
        profile, job, adapted = fixture()
        adapted['experience'][0]['bullets'].append({'text': 'Unsupported scope in Python.', 'evidence_ids': ['fact-a']})
        audit = {**AUDITED, 'supported': False, 'unsupported_claims': [
            {'path': 'bullet:role-a:0', 'fragment': 'Unsupported scope', 'reason': 'Scope', 'valid_evidence_ids': ['fact-a']}]}
        result = classify(profile, job, adapted, audit)
        self.assertEqual(result['cv_factual_issues'][0]['path'], 'bullet:role-a:1')
        audit['unsupported_claims'][0]['path'] = 'bullet:role-b:0'
        self.assertTrue(classify(profile, job, adapted, audit)['audit_errors'])


    def test_unknown_unconfirmed_evidence_is_removed_without_inventing_support(self):
        from automation.review import normalize_matches
        profile, job, adapted = fixture()
        adapted['matches'][0].update(status='unconfirmed', evidence_ids=['unconfirmed-travel'])
        fixed = normalize_matches(profile, adapted)
        self.assertEqual(fixed['matches'][0]['status'], 'unconfirmed')
        self.assertEqual(fixed['matches'][0]['evidence_ids'], [])
        validate_adaptation(profile, job, fixed)
        self.assertEqual(fixed['experience'], adapted['experience'])

    def test_unknown_positive_evidence_downgrades_instead_of_certifying(self):
        from automation.review import normalize_matches
        profile, job, adapted = fixture()
        adapted['matches'][0]['evidence_ids'] = ['invented']
        fixed = normalize_matches(profile, adapted)
        self.assertEqual(fixed['matches'][0]['status'], 'unconfirmed')
        validate_adaptation(profile, job, fixed)


    def test_spurious_role_is_removed_and_real_roles_keep_their_evidence(self):
        from automation.review import normalize_roles
        profile, job, adapted = fixture()
        original = copy.deepcopy(adapted)
        adapted['experience'].append({'role_id': 'skills-tools', 'bullets': [{'text': 'Python', 'evidence_ids': ['fact-a']}]})
        adapted['experience'].reverse()
        fixed = normalize_roles(profile, adapted, 'en')
        self.assertEqual(fixed['experience'], original['experience'])
        validate_adaptation(profile, job, fixed)

    def test_missing_role_is_restored_from_its_own_literal_facts(self):
        from automation.review import normalize_roles
        profile, job, adapted = fixture()
        adapted['experience'].pop()
        fixed = normalize_roles(profile, adapted, 'en')
        self.assertEqual(fixed['experience'][1]['bullets'][0]['evidence_ids'], ['fact-b'])
        validate_adaptation(profile, job, fixed)

    def test_provider_schema_prevents_invented_role_and_evidence_ids(self):
        from jsonschema import validate, ValidationError
        from automation.schemas import scoped, ADAPTATION
        profile, job, adapted = fixture()
        schema = scoped(ADAPTATION, profile, job)
        validate(adapted, schema)
        adapted['experience'][0]['role_id'] = 'skills-tools'
        with self.assertRaises(ValidationError):
            validate(adapted, schema)
        adapted['experience'][0]['role_id'] = 'role-a'
        adapted['matches'][0]['evidence_ids'] = ['unconfirmed-travel']
        with self.assertRaises(ValidationError):
            validate(adapted, schema)


    def test_professional_headline_rejection_is_a_local_repair_finding(self):
        from automation.review import field_findings, literal_repairs
        profile, job, adapted = fixture()
        adapted['headline'] = {'text': 'Engineering Lead', 'evidence_ids': ['role-a']}
        findings = field_findings(profile, adapted)
        self.assertEqual([f['path'] for f in findings], ['headline'])
        fixed = literal_repairs(profile, job, adapted, findings, 'en')
        self.assertEqual(fixed['headline']['text'], 'Engineer')
        self.assertEqual(fixed['experience'], adapted['experience'])
        validate_adaptation(profile, job, fixed)
