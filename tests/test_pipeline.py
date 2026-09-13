from contextlib import ExitStack
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml
from automation import pipeline
from automation.cli import parse_args
from automation.preflight import validate_profile
from automation.providers.base import Result
from automation.match import validate_job, validate_adaptation
from test_automation import fixture, CONTACTS
from test_providers import AUDITED


class PipelineTests(unittest.TestCase):
    def setup_run(self, folder, stack):
        root = Path(folder)
        original = pipeline.ROOT
        shutil.copytree(original / 'automation', root / 'automation', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(original / 'templates', root / 'templates')
        for file in ('layout.tex', 'requirements.txt'):
            shutil.copyfile(original / file, root / file)
        (root / 'profile').mkdir()
        profile, job, adapted = fixture()
        profile.update(version=1, reviewed_on='2026-09-11')
        (root / 'profile/profile.yaml').write_text(yaml.safe_dump(profile), encoding='utf-8')
        source = root / 'offer.txt'
        source.write_text('Python ' * 50, encoding='utf-8')
        args, settings = parse_args(['--url', 'https://example.org/job', '--slug', 'test-role', '--job-text', str(source)])
        stack.enter_context(patch.dict('os.environ', {'CV_CONTACT_JSON': json.dumps(CONTACTS)}, clear=True))
        stack.enter_context(patch('automation.pipeline.ROOT', root))
        stack.enter_context(patch('automation.generate.ROOT', root))
        stack.enter_context(patch('automation.pipeline.check_tools'))
        stack.enter_context(patch('automation.pipeline.subprocess.check_output', return_value='test-commit'))
        provider = Mock()
        provider.request.side_effect = [Result(job), Result(adapted), Result(AUDITED)]
        stack.enter_context(patch('automation.llm.create_provider', return_value=provider))
        return root, args, settings, provider, profile

    @staticmethod
    def compile_ok(tex, destination, contacts, max_pages, tectonic):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b'fake-pdf-for-orchestration-test')
        return {'compiled': True, 'pages': 1, 'visual_review': 'pending'}

    def test_resume_after_compile_failure_avoids_model_calls(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            with patch('automation.pipeline.compile_pdf', side_effect=RuntimeError('compiler failure')):
                with self.assertRaises(RuntimeError):
                    pipeline.run(args, settings)
            self.assertEqual(provider.request.call_count, 3)
            self.assertFalse((root / 'roles/test-role').exists())
            args.resume = True
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                pipeline.run(args, settings)
            self.assertEqual(provider.request.call_count, 3)
            report = json.loads((root / 'roles/test-role/validation.json').read_text())
            self.assertTrue(all(call['cached'] for call in report['llm_calls']))
            self.assertEqual(report['llm_requests_total'], 3)
            self.assertTrue((root / 'build/test-role/cv.pdf').exists())
            self.assertEqual(len(list((root / 'roles/test-role').iterdir())), 7)
            with self.assertRaisesRegex(ValueError, 'exists'):
                pipeline.run(args, settings)

    def test_invalid_profile_stops_before_provider_or_fetch(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, profile = self.setup_run(folder, stack)
            profile['experience'][1]['facts'][0]['id'] = 'fact-a'
            (root / 'profile/profile.yaml').write_text(yaml.safe_dump(profile), encoding='utf-8')
            with patch('automation.pipeline.fetch_job') as fetch, self.assertRaisesRegex(ValueError, 'Duplicate'):
                pipeline.run(args, settings)
            provider.request.assert_not_called()
            fetch.assert_not_called()

    def test_source_change_invalidates_resume(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            with patch('automation.pipeline.compile_pdf', side_effect=RuntimeError('failure')):
                with self.assertRaises(RuntimeError):
                    pipeline.run(args, settings)
            args.job_text.write_text('Another Python role ' * 50, encoding='utf-8')
            args.resume = True
            with self.assertRaisesRegex(ValueError, 'changed'):
                pipeline.run(args, settings)
            self.assertEqual(provider.request.call_count, 3)

    def test_corporate_email_in_offer_and_profile_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, profile = self.setup_run(folder, stack)
            args.job_text.write_text(('Python jobs@company.example ' * 20), encoding='utf-8')
            profile['skills'].append({'id': 'contact-route', 'text': 'Recruiting contact: careers@employer.example'})
            (root / 'profile/profile.yaml').write_text(yaml.safe_dump(profile), encoding='utf-8')
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                pipeline.run(args, settings)
            self.assertEqual(provider.request.call_count, 3)
            self.assertTrue((root / 'roles/test-role').exists())

    def test_extraction_repair_preserves_cv_and_only_recomputes_matches(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            audit = {**AUDITED, 'extraction_issues': [{'severity': 'material', 'reason': 'Lost qualifier', 'source_quote': 'Python'}]}
            corrected = copy.deepcopy(job)
            corrected['requirements'][0]['condition'] = 'For this role'
            provider.request.side_effect = [Result(job), Result(adapted), Result(audit),
                Result({'job': corrected, 'matches': adapted['matches']}), Result(AUDITED)]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                pipeline.run(args, settings)
            self.assertEqual(provider.request.call_count, 5)
            self.assertEqual(json.loads((root / 'roles/test-role/adaptation.json').read_text()), adapted)
            self.assertEqual(provider.request.call_args_list[3].args[1]['previous_extraction'], job)

    def test_unresolved_extraction_keeps_private_analysis_and_review_pdf(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            audit = {**AUDITED, 'extraction_issues': [{'severity': 'material', 'reason': 'Lost qualifier', 'source_quote': 'Python'}]}
            provider.request.side_effect = [Result(job), Result(adapted), Result(audit),
                Result({'job': job, 'matches': adapted['matches']}), Result(audit)]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                result = pipeline.run(args, settings)
            self.assertEqual(result['status'], 'requires_review')
            self.assertTrue((root / '.private/runs/test-role/match.md').exists())
            self.assertTrue((root / '.private/runs/test-role/cv.pdf').exists())
            self.assertFalse((root / 'roles/test-role').exists())

    def test_nonactionable_audit_is_review_not_proven_false(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            provider.request.side_effect = [Result(job), Result(adapted), Result({**AUDITED, 'supported': False, 'issues': ['General concern']})]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                result = pipeline.run(args, settings)
            self.assertEqual(result['status'], 'requires_review')
            self.assertEqual(result['review']['cv_factual_issues'], [])
            self.assertTrue(result['review']['audit_errors'])
            self.assertEqual(provider.request.call_count, 3)

    def test_gap_and_match_correction_do_not_block(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            audit = {**AUDITED, 'match_corrections': [{'requirement_id': 'r01', 'status': 'gap', 'rationale': 'No cumple el requisito.'}]}
            provider.request.side_effect = [Result(job), Result(adapted), Result(audit)]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                result = pipeline.run(args, settings)
            self.assertEqual(result['status'], 'ready')
            self.assertIn('gap', (root / 'roles/test-role/match.md').read_text())
            self.assertEqual(provider.request.call_count, 3)

    def test_batch_repairs_two_fields_without_rebuilding_cv(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            findings = [{'path': path, 'fragment': 'developer', 'reason': 'Scope', 'valid_evidence_ids': ['fact-a']} for path in ('summary', 'skill:0')]
            audit = {**AUDITED, 'supported': False, 'unsupported_claims': findings}
            batch = {'claims': [{'path': path, 'claim': {'text': 'Developed Python tools.', 'evidence_ids': ['fact-a']}} for path in ('summary', 'skill:0')]}
            provider.request.side_effect = [Result(job), Result(adapted), Result(audit), Result(batch), Result(AUDITED)]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                result = pipeline.run(args, settings)
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(provider.request.call_count, 5)
            self.assertEqual(len(provider.request.call_args_list[3].args[1]['fields']), 2)
            self.assertEqual(provider.request.call_args.args[1]['audit_scope'], 'adaptation')

    def test_length_repair_is_local_and_audited(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            oversized = copy.deepcopy(adapted)
            oversized['experience'][0]['bullets'][0]['text'] = 'Python ' * 33
            batch = {'claims': [{'path': 'bullet:role-a:0', 'claim': adapted['experience'][0]['bullets'][0]}]}
            provider.request.side_effect = [Result(job), Result(oversized), Result(batch), Result(AUDITED)]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                pipeline.run(args, settings)
            self.assertEqual(provider.request.call_args.args[1]['adaptation'], adapted)
            self.assertEqual(provider.request.call_count, 4)

    def test_repeated_factual_rejection_ends_with_literal_evidence(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            rejected = {**AUDITED, 'supported': False, 'unsupported_claims': [{'path': 'summary', 'fragment': 'developer', 'reason': 'Scope unsupported', 'valid_evidence_ids': ['fact-a']}]}
            batch = {'claims': [{'path': 'summary', 'claim': adapted['summary']}]}
            provider.request.side_effect = [Result(job), Result(adapted), Result(rejected), Result(batch), Result(rejected)]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                result = pipeline.run(args, settings)
            final = json.loads((root / 'roles/test-role/adaptation.json').read_text())
            self.assertEqual(final['summary']['text'], 'Developed Python tools. Used MATLAB.')
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(provider.request.call_count, 5)

    def test_missing_contacts_keeps_analysis(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            with patch('automation.pipeline.load_contacts', side_effect=ValueError('Missing contacts')):
                with self.assertRaisesRegex(ValueError, 'Missing contacts'):
                    pipeline.run(args, settings)
            self.assertTrue((root / '.private/runs/test-role/match.md').exists())
            self.assertTrue((root / '.private/runs/test-role/adaptation.json').exists())
            self.assertEqual(provider.request.call_count, 3)

    def test_corporate_email_in_source_quote_is_redacted_only_for_publication(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            args.job_text.write_text('Python jobs@company.example ' * 20, encoding='utf-8')
            job['requirements'][0]['source_quote'] = 'Python jobs@company.example'
            provider.request.side_effect = [Result(job), Result(adapted), Result(AUDITED)]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                pipeline.run(args, settings)
            self.assertIn('jobs@company.example', (root / '.private/runs/test-role/job.json').read_text())
            self.assertNotIn('jobs@company.example', (root / 'roles/test-role/job.json').read_text())

    def test_analysis_only_needs_neither_contacts_nor_compiler(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            args.analysis_only = True
            with patch('automation.pipeline.load_contacts', side_effect=ValueError('Missing contacts')), patch('automation.pipeline.compile_pdf') as compile:
                result = pipeline.run(args, settings)
            self.assertEqual(result['status'], 'ready')
            self.assertFalse(result['exported'])
            compile.assert_not_called()
            self.assertTrue((root / '.private/runs/test-role/match.md').exists())

    def test_compile_failure_marks_preserved_analysis_as_failed_export(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            with patch('automation.pipeline.compile_pdf', side_effect=ValueError('PDF layout failed')):
                with self.assertRaises(ValueError):
                    pipeline.run(args, settings)
            checkpoint = root / '.private/runs/test-role'
            self.assertIn('Estado: render_failed', (checkpoint / 'match.md').read_text())
            status = json.loads((checkpoint / 'status.json').read_text())
            self.assertEqual(status['failed_stage'], 'export')
            self.assertTrue(status['analysis_preserved'])


class ValidationTests(unittest.TestCase):
    def test_master_profile_is_valid(self):
        validate_profile(yaml.safe_load((pipeline.ROOT / 'profile/profile.yaml').read_text(encoding='utf-8')))

    def test_explicit_alternatives_require_options(self):
        _, job, _ = fixture()
        job['requirements'][0].update(logic='any', options=['Python', 'MATLAB'])
        validate_job(job, 'Python')
        job['requirements'][0]['options'] = []
        with self.assertRaisesRegex(ValueError, 'options'):
            validate_job(job, 'Python')

    def test_word_limits_fail_before_compilation(self):
        for field, limit in [('headline', 14), ('summary', 65)]:
            profile, job, adapted = fixture()
            adapted[field]['text'] = 'word ' * (limit + 1)
            with self.assertRaisesRegex(ValueError, 'words'):
                validate_adaptation(profile, job, adapted)
