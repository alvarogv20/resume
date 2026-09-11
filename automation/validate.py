"""Isolated compilation; retain only the final PDF in the private build directory."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from pypdf import PdfReader
from .generate import ROOT, contact_tex
from .executables import resolve_tool


def compile_pdf(tex, destination, contacts, max_pages=2, tectonic=None):
    executable = resolve_tool('tectonic', tectonic)
    with tempfile.TemporaryDirectory(prefix='cv-build-') as folder:
        work = Path(folder)
        shutil.copyfile(ROOT / 'layout.tex', work / 'layout.tex')
        (work / 'cv.tex').write_text(tex, encoding='utf-8')
        if contacts:
            (work / 'contact.tex').write_text(contact_tex(contacts), encoding='utf-8')
        result = subprocess.run([executable, '--untrusted', '--keep-logs', 'cv.tex'], cwd=work,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
        if result.returncode or not (work / 'cv.pdf').exists():
            raise RuntimeError('LaTeX compilation failed; private compiler output was not published.')
        log = result.stdout + result.stderr
        if (work / 'cv.log').exists():
            log += (work / 'cv.log').read_text(encoding='utf-8', errors='replace')
        if re.search(r'Overfull \\[hv]box|Missing character:', log):
            raise ValueError('PDF has an overflow or missing glyph; adjust content before publishing.')
        reader = PdfReader(work / 'cv.pdf')
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
        if not 1 <= len(reader.pages) <= max_pages or len(text.strip()) < 500:
            raise ValueError('PDF page count or text extraction failed.')
        if contacts:
            compact = re.sub(r'\s+', '', text)
            for value in (contacts['email'], contacts['phone'], contacts['linkedin'].split('/in/')[1].rstrip('/')):
                if re.sub(r'\s+', '', value) not in compact:
                    raise ValueError('A required private contact is missing from the final PDF.')
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(work / 'cv.pdf', destination)
        return {'compiled': True, 'pages': len(reader.pages), 'text_extractable': True,
                'overflow_check': 'passed', 'contacts_included': bool(contacts),
                'visual_review': 'pending', 'semantic_grounding': 'model-audited; human review recommended'}
