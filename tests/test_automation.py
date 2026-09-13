import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation.extract import canonical_url, check_public_url, page_text
from automation.generate import (assert_no_private_contacts, assert_no_public_contacts,
                                 contact_tex, load_contacts, render, tex_escape)
from automation.llm import LLM
from automation.match import validate_adaptation, validate_job
from automation.repair import repair


CONTACTS = {'email': 'private@example.org', 'phone': '+34 611 222 333',
            'linkedin': 'https://www.linkedin.com/in/test-private/'}


def fixture():
    profile = {'name': 'Test', 'location': 'Madrid', 'experience': [
        {'id': 'role-a', 'title': 'Engineer', 'company': 'A', 'location': 'Madrid', 'dates': '2021 - Present',
         'facts': [{'id': 'fact-a', 'text': 'Developed Python tools.'}]},
        {'id': 'role-b', 'title': 'Engineer', 'company': 'B', 'location': 'Madrid', 'dates': '2020 - 2021',
         'facts': [{'id': 'fact-b', 'text': 'Used MATLAB.'}]}],
        'skills': [], 'education': [], 'languages': []}
    job = {'title': 'Engineer', 'company': 'Employer', 'location': '', 'language': 'en',
           'conditions': [], 'responsibilities': [], 'requirements': [
               {'id': 'r01', 'text': 'Python', 'condition': '', 'logic': 'single', 'options': [],
                'priority': 'required', 'source_quote': 'Python'}]}
    claim = {'text': 'Python tools developer', 'evidence_ids': ['fact-a']}
    adapted = {'matches': [{'requirement_id': 'r01', 'status': 'direct', 'evidence_ids': ['fact-a'], 'rationale': 'Explicit'}],
               'headline': copy.deepcopy(claim), 'summary': copy.deepcopy(claim), 'skills': [copy.deepcopy(claim)],
               'experience': [{'role_id': 'role-a', 'bullets': [copy.deepcopy(claim)]},
                              {'role_id': 'role-b', 'bullets': [{'text': 'Used MATLAB.', 'evidence_ids': ['fact-b']}]}],
               'decisions': [], 'questions': []}
    return profile, job, adapted


class ExtractionTests(unittest.TestCase):
    def test_linkedin_search_becomes_specific_job(self):
        self.assertEqual(canonical_url('https://www.linkedin.com/jobs/search-results/?currentJobId=4441905971&trackingId=secret'),
                         'https://www.linkedin.com/jobs/view/4441905971/')

    def test_invalid_or_non_job_urls_rejected(self):
        for url in ('file:///etc/passwd', 'http://example.com', 'https://user:pass@example.com',
                    'https://www.linkedin.com/jobs/search/?keywords=engineer', 'https://example.com:22/a'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonical_url(url)

    def test_private_destination_rejected(self):
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError):
                check_public_url('https://example.com')

    def test_job_content_not_login_form(self):
        source = '<h2 class="top-card-layout__title">Engineer</h2><form>password</form><div class="show-more-less-html__markup"><p>Python &amp; MATLAB</p></div>'
        self.assertEqual(page_text(source), 'Engineer\nPython & MATLAB')

    def test_source_quote_must_exist(self):
        _, job, _ = fixture()
        with self.assertRaises(ValueError):
            validate_job(job, 'Completely different advert')


class EvidenceTests(unittest.TestCase):
    def test_faithful_draft_and_render(self):
        p, j, a = fixture()
        validate_adaptation(p, j, a)
        rendered = render(p, a, 'en')
        self.assertIn('2021 - Present', rendered)
        self.assertIn('Python tools developer', rendered)

    def test_unknown_evidence_rejected(self):
        p, j, a = fixture()
        a['summary']['evidence_ids'] = ['invented']
        with self.assertRaises(ValueError):
            validate_adaptation(p, j, a)

    def test_wrong_role_attribution_rejected(self):
        p, j, a = fixture()
        a['experience'][0]['bullets'][0]['evidence_ids'] = ['fact-b']
        with self.assertRaises(ValueError):
            validate_adaptation(p, j, a)

    def test_invented_years_rejected(self):
        p, j, a = fixture()
        a['summary']['text'] = 'Python engineer with 8 years of experience.'
        with self.assertRaises(ValueError):
            validate_adaptation(p, j, a)

    def test_unmatched_requirement_rejected(self):
        p, j, a = fixture()
        a['matches'] = []
        with self.assertRaises(ValueError):
            validate_adaptation(p, j, a)

    def test_unrelated_negative_phrase_does_not_veto_direct_match(self):
        p, j, a = fixture()
        a['matches'][0]['rationale'] = 'Python está documentado; no se documenta MATLAB, que esta oferta no exige.'
        validate_adaptation(p, j, a)

    def test_audit_repairs_restore_literal_facts_and_downgrade(self):
        p, j, a = fixture()
        audit = {'extraction_issues': [], 'unsupported_claims': [{'path': 'summary', 'fragment': 'developer', 'reason': 'Scope unsupported', 'valid_evidence_ids': ['fact-a']}],
                 'match_corrections': [{'requirement_id': 'r01', 'status': 'transferable', 'rationale': 'Uso documentado, formación no confirmada.'}]}
        fixed = repair(p, j, a, audit)
        self.assertEqual(fixed['summary']['text'], 'Developed Python tools. Used MATLAB.')
        self.assertEqual(fixed['matches'][0]['status'], 'transferable')
        self.assertEqual(a['matches'][0]['status'], 'direct')

    def test_bad_extraction_cannot_be_hidden_by_cv_repair(self):
        p, j, a = fixture()
        with self.assertRaises(ValueError):
            repair(p, j, a, {'extraction_issues': ['Alternatives lost']})

    def test_tex_injection_rejected(self):
        p, j, a = fixture()
        a['summary']['text'] = r'\input{contact.tex}'
        with self.assertRaises(ValueError):
            validate_adaptation(p, j, a)
        self.assertIn(r'\textbackslash{}', tex_escape(r'\input{secret}'))


class PrivacyTests(unittest.TestCase):
    def test_contacts_require_all_three_fields(self):
        with patch.dict('os.environ', {'CV_CONTACT_JSON': json.dumps({'email': 'x@y.com'})}):
            with self.assertRaises(ValueError):
                load_contacts()

    def test_private_contacts_only_in_contact_tex(self):
        with patch.dict('os.environ', {'CV_CONTACT_JSON': json.dumps(CONTACTS)}):
            self.assertEqual(load_contacts(), CONTACTS)
        self.assertIn(CONTACTS['email'], contact_tex(CONTACTS))
        p, _, a = fixture()
        assert_no_public_contacts(render(p, a, 'en'), CONTACTS)

    def test_private_contact_leaks_rejected_in_inputs(self):
        for text in (CONTACTS['email'], '34611222333', CONTACTS['linkedin']):
            with self.subTest(text=text), self.assertRaises(ValueError):
                assert_no_private_contacts(text, CONTACTS)

    def test_corporate_contacts_allowed_in_inputs(self):
        for text in ('jobs@company.example', 'https://www.linkedin.com/in/recruiter/'):
            with self.subTest(text=text):
                assert_no_private_contacts(text, CONTACTS)

    def test_all_email_and_linkedin_contacts_rejected_in_public_outputs(self):
        for text in (CONTACTS['email'], '34611222333', CONTACTS['linkedin'],
                     'jobs@company.example', 'https://www.linkedin.com/in/recruiter/'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                assert_no_public_contacts(text, CONTACTS)

    def test_codex_does_not_inherit_secrets_or_repo(self):
        def fake_run(command, **kwargs):
            self.assertNotIn('CV_CONTACT_JSON', kwargs['env'])
            self.assertNotIn('GH_TOKEN', kwargs['env'])
            self.assertIn('features.shell_tool=false', command)
            self.assertNotEqual(Path(kwargs['cwd']).resolve(), Path.cwd())
            output = Path(command[command.index('--output-last-message') + 1])
            output.write_text('{"supported":true,"issues":[],"extraction_issues":[],"unsupported_claims":[],"match_corrections":[]}', encoding='utf-8')
            return type('Result', (), {'returncode': 0})()
        with patch.dict('os.environ', {'CV_CONTACT_JSON': json.dumps(CONTACTS), 'GH_TOKEN': 'test-secret'}):
            with patch('subprocess.run', side_effect=fake_run):
                from automation.schemas import AUDIT
                self.assertTrue(LLM().request('audit', {}, AUDIT)['supported'])


if __name__ == '__main__':
    unittest.main()
