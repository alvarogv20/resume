import copy
import unittest
from unittest.mock import Mock
from jsonschema import validate, ValidationError
from automation.match import validate_adaptation
from automation.repair import repair, fallback, repair_lengths
from automation.schemas import AUDIT
from test_automation import fixture


def rejection(path='summary', valid=None):
    return {'supported': False, 'issues': ['Unsupported scope'], 'extraction_issues': [],
            'match_corrections': [], 'unsupported_claims': [
                {'path': path, 'fragment': 'expert', 'reason': 'Evidence shows use, not expertise',
                 'valid_evidence_ids': valid or ['fact-a']}]}


class RepairTests(unittest.TestCase):
    def test_airbus_education_first_preserves_professional_summary(self):
        p, j, a = fixture()
        p['education'] = [{'id': 'degree', 'text': 'Master in Engineering'}]
        a['summary'] = {'text': 'Engineering expert developing Python tools.',
                        'evidence_ids': ['degree', 'fact-a']}
        llm = Mock()
        llm.request.return_value = {'text': 'Developed Python tools.', 'evidence_ids': ['fact-a']}
        fixed = repair(p, j, a, rejection(), llm, {})
        payload = llm.request.call_args.args[1]
        self.assertEqual(payload['previous_text'], a['summary']['text'])
        self.assertEqual(payload['rejection']['reason'], 'Evidence shows use, not expertise')
        self.assertIn('degree', payload['allowed_evidence'])
        self.assertEqual(payload['length_limits']['max_words'], 65)
        self.assertEqual(fixed['summary']['text'], 'Developed Python tools.')
        self.assertEqual(fixed['experience'], a['experience'])
        fixed = repair(p, j, a, rejection())
        self.assertEqual(fixed['summary']['evidence_ids'], ['fact-a', 'fact-b'])

    def test_two_invalid_generations_use_typed_fallback(self):
        p, j, a = fixture()
        llm = Mock()
        llm.request.return_value = {'text': 'word ' * 66, 'evidence_ids': ['fact-a']}
        attempts = {}
        fixed = repair(p, j, a, rejection(), llm, attempts)
        self.assertEqual(llm.request.call_count, 2)
        self.assertIn('words', llm.request.call_args.args[1]['validation_error'])
        self.assertEqual(attempts, {'summary': 2})
        self.assertEqual(fixed['summary']['evidence_ids'], ['fact-a', 'fact-b'])

    def test_semantic_rejections_exhaust_shared_counter(self):
        p, j, a = fixture()
        llm = Mock()
        llm.request.return_value = copy.deepcopy(a['summary'])
        attempts = {}
        for _ in range(3):
            a = repair(p, j, a, rejection(), llm, attempts)
        self.assertEqual(llm.request.call_count, 2)
        self.assertEqual(a['summary']['text'], 'Developed Python tools. Used MATLAB.')

    def test_field_specific_fallbacks(self):
        p, _, _ = fixture()
        p['skills'] = [{'id': 'skill-python', 'text': 'Python'}]
        self.assertEqual(fallback(p, 'headline', [], 14),
                         {'text': 'Engineer', 'evidence_ids': ['role-a']})
        self.assertEqual(fallback(p, 'bullet:role-b:0', ['fact-a'], 32),
                         {'text': 'Used MATLAB.', 'evidence_ids': ['fact-b']})
        self.assertEqual(fallback(p, 'skill:0', [], 80),
                         {'text': 'Python', 'evidence_ids': ['skill-python']})
        with self.assertRaisesRegex(ValueError, 'No safe'):
            fallback(p, 'summary', [], 1)

    def test_degenerate_fields_rejected_even_with_extra_professional_citations(self):
        p, j, a = fixture()
        p['education'] = [{'id': 'degree', 'text': 'Master in Engineering'}]
        p['languages'] = [{'id': 'language', 'text': 'English: Advanced'}]
        for field in ('summary', 'headline'):
            for text in ('Master in Engineering', 'English: Advanced', '2021', 'Engineer | A | 2021 - Present'):
                candidate = copy.deepcopy(a)
                candidate[field] = {'text': text, 'evidence_ids': ['fact-a', 'role-a', 'degree', 'language']}
                with self.subTest(field=field, text=text), self.assertRaises(ValueError):
                    validate_adaptation(p, j, candidate)

    def test_auditor_requires_structured_findings(self):
        validate(rejection(), AUDIT)
        old = rejection()
        old['unsupported_claims'] = ['summary']
        with self.assertRaises(ValidationError):
            validate(old, AUDIT)

    def test_wrong_role_retained_evidence_rejected(self):
        p, j, a = fixture()
        with self.assertRaisesRegex(ValueError, 'outside the field scope'):
            repair(p, j, a, rejection('bullet:role-b:0'))


class LengthRepairTests(unittest.TestCase):
    def test_both_fields_repaired_independently_and_rest_preserved(self):
        p, j, a = fixture()
        original = copy.deepcopy(a)
        a['headline']['text'] = 'Engineer ' * 15
        a['summary']['text'] = 'Developed Python tools ' * 23
        llm = Mock()
        llm.request.side_effect = [original['headline'], original['summary']]
        fixed = repair_lengths(p, a, llm)
        self.assertEqual(fixed, original)
        self.assertEqual(len(a['headline']['text'].split()), 15)
        calls = llm.request.call_args_list
        self.assertEqual([c.args[1]['field'] for c in calls], ['headline', 'summary'])
        self.assertIn('69 words', calls[1].args[1]['validation_error'])
        self.assertEqual(calls[1].args[1]['length_limits']['max_words'], 55)
        validate_adaptation(p, j, fixed)

    def test_invalid_evidence_then_long_text_use_validated_fallback(self):
        p, j, a = fixture()
        a['summary']['text'] = 'Python ' * 66
        llm = Mock()
        llm.request.side_effect = [
            {'text': 'Engineer', 'evidence_ids': ['unknown']},
            {'text': 'Python ' * 66, 'evidence_ids': ['fact-a']}]
        attempts = {}
        fixed = repair_lengths(p, a, llm, attempts)
        self.assertEqual(fixed['summary']['text'], 'Developed Python tools. Used MATLAB.')
        self.assertEqual(attempts, {'summary': 2})
        self.assertIn('known evidence', llm.request.call_args_list[1].args[1]['validation_error'])
        validate_adaptation(p, j, fixed)
        repair_lengths(p, a, llm, attempts)
        self.assertEqual(llm.request.call_count, 2)

    def test_budget_failure_propagates_and_noop_does_not_call_model(self):
        p, _, a = fixture()
        llm = Mock()
        self.assertEqual(repair_lengths(p, a, llm), a)
        llm.request.assert_not_called()
        a['headline']['text'] = 'Engineer ' * 15
        llm.request.side_effect = ValueError('LLM request budget exhausted')
        with self.assertRaisesRegex(ValueError, 'budget'):
            repair_lengths(p, a, llm)
