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

    def test_semantic_extraction_repair_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            audit = {**AUDITED, 'supported': False, 'extraction_issues': ['Lost qualifier']}
            corrected = copy.deepcopy(job)
            corrected['requirements'][0]['condition'] = 'For this role'
            provider.request.side_effect = [Result(job), Result(adapted), Result(audit),
                                            Result(corrected), Result(adapted), Result(AUDITED)]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                pipeline.run(args, settings)
            self.assertEqual(provider.request.call_count, 6)
            report = json.loads((root / 'roles/test-role/validation.json').read_text())
            self.assertEqual(report['extraction_repair_feedback'], ['Lost qualifier'])

    def test_extraction_regression_reports_final_findings_without_publishing(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            first = {**AUDITED, 'supported': False,
                     'extraction_issues': ['Keep the shared three-year threshold']}
            remaining = ['r06: System Engineering AND MBSE, not OR',
                         'r07: Continuous improvement AND process management, not OR']
            second = {**AUDITED, 'supported': False, 'extraction_issues': remaining}
            corrected = copy.deepcopy(job)
            corrected['requirements'][0]['condition'] = 'Shared threshold'
            provider.request.side_effect = [Result(job), Result(adapted), Result(first),
                                            Result(corrected), Result(adapted), Result(second)]
            with patch('automation.pipeline.compile_pdf') as compile:
                with self.assertRaises(ValueError) as caught:
                    pipeline.run(args, settings)
            message = str(caught.exception)
            self.assertIn('Semantic extraction audit failed after correction', message)
            for finding in remaining:
                self.assertIn(finding, message)
            self.assertNotIn(first['extraction_issues'][0], message)
            self.assertEqual(provider.request.call_count, 6)
            correction_input = provider.request.call_args_list[3].args[1]
            self.assertEqual(correction_input['previous_extraction'], job)
            self.assertEqual(correction_input['corrections_required'], first['extraction_issues'])
            compile.assert_not_called()
            self.assertFalse((root / 'roles/test-role').exists())
            self.assertFalse((root / 'build/test-role/cv.pdf').exists())

    def test_repair_audits_use_accepted_job_without_reopening_extraction(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            first = {**AUDITED, 'supported': False, 'unsupported_claims': [{'path': 'summary', 'fragment': 'developer', 'reason': 'Scope unsupported', 'valid_evidence_ids': ['fact-a']}]}
            second = {**AUDITED, 'supported': False, 'match_corrections': [
                {'requirement_id': 'r01', 'status': 'transferable', 'rationale': 'Partial support'}]}
            provider.request.side_effect = [Result(job), Result(adapted), Result(first), Result(adapted['summary']), Result(second), Result(AUDITED)]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                pipeline.run(args, settings)
            for call in provider.request.call_args_list[4:]:
                self.assertEqual(call.args[1]['audit_scope'], 'adaptation')
                self.assertNotIn('source_text', call.args[1])
            report = json.loads((root / 'roles/test-role/validation.json').read_text())
            self.assertEqual(len(report['repair_history']), 2)

    def test_length_repairs_are_audited_on_every_adaptation_route(self):
        for route in ('initial', 'validation_retry', 'extraction_retry'):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
                root, args, settings, provider, _ = self.setup_run(folder, stack)
                _, job, adapted = fixture()
                oversized = copy.deepcopy(adapted)
                oversized['summary']['text'] = 'Python ' * 66
                outputs = [Result(job)]
                if route == 'validation_retry':
                    invalid = copy.deepcopy(adapted)
                    invalid['matches'] = []
                    outputs.append(Result(invalid))
                elif route == 'extraction_retry':
                    outputs += [Result(adapted), Result({**AUDITED, 'supported': False,
                                                       'extraction_issues': ['Lost qualifier']})]
                    corrected = copy.deepcopy(job)
                    corrected['requirements'][0]['condition'] = 'For this role'
                    outputs.append(Result(corrected))
                outputs += [Result(oversized), Result(adapted['summary']), Result(AUDITED)]
                provider.request.side_effect = outputs
                with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                    pipeline.run(args, settings)
                final_audit = provider.request.call_args.args[1]
                self.assertEqual(final_audit['adaptation']['summary'], adapted['summary'])
                self.assertTrue((root / 'roles/test-role').exists())
                self.assertEqual(provider.request.call_count, len(outputs))

    def test_length_budget_failure_does_not_regenerate_entire_draft(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            _, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            adapted['summary']['text'] = 'Python ' * 66
            provider.request.side_effect = [Result(job), Result(adapted),
                                            ValueError('LLM request budget exhausted')]
            with patch('automation.pipeline.compile_pdf') as compile:
                with self.assertRaisesRegex(ValueError, 'budget'):
                    pipeline.run(args, settings)
            self.assertEqual(provider.request.call_count, 3)
            compile.assert_not_called()

    def test_length_fallback_is_audited_before_compilation(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            oversized = copy.deepcopy(adapted)
            oversized['summary']['text'] = 'Python ' * 66
            provider.request.side_effect = [Result(job), Result(oversized),
                Result(oversized['summary']), Result(oversized['summary']), Result(AUDITED)]
            with patch('automation.pipeline.compile_pdf', side_effect=self.compile_ok):
                pipeline.run(args, settings)
            self.assertEqual(provider.request.call_args.args[1]['adaptation']['summary']['text'],
                             'Developed Python tools. Used MATLAB.')

    def test_repeated_rejection_stops_without_pdf(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root, args, settings, provider, _ = self.setup_run(folder, stack)
            _, job, adapted = fixture()
            rejected = {**AUDITED, 'supported': False, 'unsupported_claims': [{'path': 'summary', 'fragment': 'developer', 'reason': 'Scope unsupported', 'valid_evidence_ids': ['fact-a']}]}
            provider.request.side_effect = [Result(job), Result(adapted), Result(rejected), Result(adapted['summary']), Result(rejected), Result(adapted['summary']), Result(rejected), Result(rejected)]
            with patch('automation.pipeline.compile_pdf') as compile, self.assertRaisesRegex(ValueError, 'bounded'):
                pipeline.run(args, settings)
            compile.assert_not_called()
            self.assertFalse((root / 'roles/test-role').exists())


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
