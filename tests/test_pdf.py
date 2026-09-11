"""Optional real compiler smoke test; set TECTONIC_BIN to opt in."""
import os
from pathlib import Path
import tempfile
import unittest

import yaml
from automation.generate import ROOT, render
from automation.validate import compile_pdf
from test_automation import CONTACTS


@unittest.skipUnless(os.environ.get('TECTONIC_BIN'), 'Set TECTONIC_BIN for a real PDF compile')
class PDFTests(unittest.TestCase):
    def test_real_compiler_and_extractable_contacts(self):
        profile = yaml.safe_load((ROOT / 'profile/profile.yaml').read_text(encoding='utf-8'))
        adapted = {'headline': {'text': profile['headline']},
                   'summary': {'text': profile['skills'][0]['text']},
                   'skills': profile['skills'][:2],
                   'experience': [{'role_id': role['id'], 'bullets': role['facts'][:2]}
                                  for role in profile['experience']]}
        with tempfile.TemporaryDirectory(prefix='cv-pdf-test-') as folder:
            destination = Path(folder) / 'cv.pdf'
            report = compile_pdf(render(profile, adapted, 'en'), destination, CONTACTS)
            self.assertTrue(report['compiled'])
            self.assertTrue(report['text_extractable'])
            self.assertTrue(report['contacts_included'])
            self.assertEqual(report['visual_review'], 'pending')
            self.assertLessEqual(report['pages'], 2)
