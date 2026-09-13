import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation import benchmark


class OfferCorpusTests(unittest.TestCase):
    def test_all_nine_saved_offers_are_usable_without_network(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden')):
            cases = benchmark.load_cases()
        self.assertEqual(len(cases), 9)
        self.assertEqual(len({c['job_id'] for c in cases}), 9)
        self.assertEqual({c['file'] for c in cases}, {p.name for p in benchmark.CORPUS.glob('*.html')})
        self.assertIn('es', {c['language'] for c in cases})
        self.assertIn('en', {c['language'] for c in cases})
        for case in cases:
            with self.subTest(offer=case['file']):
                self.assertNotIn('<style', case['text'])
                self.assertNotIn('font-size:', case['text'])
                self.assertNotIn('<li>', case['text'])
                if 'linkedin.com/jobs/view/' in case['url']:
                    self.assertIn(case['job_id'], case['url'])

    def test_listing_does_not_launch_generation(self):
        with patch.object(benchmark.subprocess, 'run') as run:
            self.assertEqual(benchmark.main([]), 0)
            run.assert_not_called()

    def test_failed_generation_is_not_a_pass(self):
        case = benchmark.load_cases()[0]
        for outcome in (subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired([], 2400)):
            with self.subTest(outcome=type(outcome).__name__), tempfile.TemporaryDirectory() as folder:
                with patch.object(benchmark.subprocess, 'run') as run, patch.object(benchmark, 'check_result') as check:
                    if isinstance(outcome, Exception):
                        run.side_effect = outcome
                    else:
                        run.return_value = outcome
                    result = benchmark.run_case(case, Path(folder), 'test', [])
                    self.assertEqual(result['status'], 'failed')
                    check.assert_not_called()

    def test_exit_zero_without_deliverables_is_a_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(benchmark.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), patch.object(benchmark, 'ROOT', Path(folder)):
                result = benchmark.run_case(benchmark.load_cases()[0], Path(folder), 'test', [])
                self.assertEqual(result['status'], 'failed')

    def test_batch_keeps_running_and_returns_failure(self):
        cases = benchmark.load_cases()
        outcomes = [{'status': 'failed'}] + [{'status': 'passed'} for _ in cases[1:]]
        with tempfile.TemporaryDirectory() as folder, patch.object(benchmark, 'ROOT', Path(folder)), patch.object(benchmark, 'run_case', side_effect=outcomes) as run:
            self.assertEqual(benchmark.main(['--generate']), 1)
            self.assertEqual(run.call_count, 9)
            self.assertEqual(len(list(Path(folder).rglob('results.json'))), 1)


class BenchmarkIdentifierTests(unittest.TestCase):
    def test_external_uppercase_ids_produce_cli_safe_slugs(self):
        import re
        cases = benchmark.load_cases()
        for case in cases:
            with self.subTest(offer=case['file']), tempfile.TemporaryDirectory() as folder:
                with patch.object(benchmark.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as run:
                    benchmark.run_case(case, Path(folder), 'test-batch', [])
                command = run.call_args.args[0]
                slug = command[command.index('--slug') + 1]
                self.assertRegex(slug, r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
                self.assertEqual(command[command.index('--url') + 1], case['url'])
