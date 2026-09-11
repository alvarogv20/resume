import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from automation import publish


class PublishTests(unittest.TestCase):
    def test_unrelated_head_prevents_branch_and_push(self):
        calls = []
        def git(*args):
            calls.append(args)
            if args == ('remote', 'get-url', 'origin'):
                return 'https://github.com/example/resume.git'
            if args == ('rev-parse', 'FETCH_HEAD'):
                return 'base-commit'
            if args == ('rev-parse', 'HEAD'):
                return 'unrelated-commit'
            return ''
        with patch.dict('os.environ', {'GITHUB_REPOSITORY': 'example/resume', 'GH_TOKEN': 'test'}), \
                patch('sys.argv', ['publish', '--slug', 'test-role']), patch.object(publish, 'git', side_effect=git):
            with self.assertRaises(SystemExit):
                publish.main()
        self.assertFalse(any(call[0] in ('switch', 'push', 'add') for call in calls))

    def test_full_diff_guard_prevents_push(self):
        paths = ['roles/test-role/' + name for name in publish.FILES]
        calls = []
        def git(*args):
            calls.append(args)
            if args == ('remote', 'get-url', 'origin'):
                return 'https://github.com/example/resume.git'
            if args[0] == 'rev-parse':
                return 'base-commit'
            if args == ('diff', '--cached', '--name-only'):
                return '\n'.join(paths) if any(c[0] == 'add' for c in calls) else ''
            if args == ('diff', '--name-only', 'base-commit...HEAD'):
                return '\n'.join(paths + ['unrelated.py'])
            return ''
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for path in paths:
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text('public content', encoding='utf-8')
            with patch.dict('os.environ', {'GITHUB_REPOSITORY': 'example/resume', 'GH_TOKEN': 'test'}), \
                    patch('sys.argv', ['publish', '--slug', 'test-role']), patch.object(publish, 'ROOT', root), \
                    patch.object(publish, 'load_contacts', return_value={}), patch.object(publish, 'git', side_effect=git):
                with self.assertRaisesRegex(RuntimeError, 'Full PR diff'):
                    publish.main()
        self.assertFalse(any(call[0] == 'push' for call in calls))
