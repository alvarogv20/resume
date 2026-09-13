"""Compile privately, measure layout issues and retain a review PDF on failure."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from pypdf import PdfReader
from .generate import ROOT, contact_tex
from .executables import resolve_tool
from .state import atomic_json


def layout_issues(log):
    return [{'axis': axis, 'points': float(points), 'line': line.strip()}
            for line in log.splitlines()
            for axis, points in re.findall(r'Overfull \\([hv])box \(([\d.]+)pt too (?:wide|high)\)', line)]


def compile_pdf(tex, destination, contacts, max_pages=2, tectonic=None):
    executable = resolve_tool('tectonic', tectonic)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cv-build-') as folder:
        work = Path(folder)
        shutil.copyfile(ROOT / 'layout.tex', work / 'layout.tex')
        if contacts:
            contact = contact_tex(contacts)
            if 'Perfil profesional' in tex:
                contact = contact.replace('Madrid, Spain', 'Madrid, España')
            (work / 'contact.tex').write_text(contact, encoding='utf-8')
        attempts = []
        for attempt in range(2):
            candidate = tex
            if attempt:
                candidate = tex.replace(r'\begin{document}',
                    r'\setlength{\emergencystretch}{2em}' '\n'
                    r'\setlength{\parskip}{2pt}' '\n'
                    r'\titlespacing*{\section}{0pt}{6pt}{3pt}' '\n'
                    r'\setlist[itemize]{leftmargin=13pt,itemsep=1pt,topsep=2pt,parsep=0pt}' '\n'
                    r'\begin{document}')
            (work / 'cv.tex').write_text(candidate, encoding='utf-8')
            (work / 'cv.pdf').unlink(missing_ok=True)
            result = subprocess.run([executable, '--untrusted', '--keep-logs', 'cv.tex'], cwd=work,
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
            log = result.stdout + result.stderr
            if (work / 'cv.log').exists():
                log += (work / 'cv.log').read_text(encoding='utf-8', errors='replace')
            # Full compiler output stays beside the private review PDF.
            destination.with_suffix('.log').write_text(log, encoding='utf-8')
            if result.returncode or not (work / 'cv.pdf').exists():
                raise RuntimeError('LaTeX compilation failed; inspect private compiler log.')
            shutil.copyfile(work / 'cv.pdf', destination)
            destination.with_suffix('.tex').write_text(candidate, encoding='utf-8')
            reader = PdfReader(destination)
            text = '\n'.join(page.extract_text() or '' for page in reader.pages)
            issues = layout_issues(log)
            missing = 'Missing character:' in log
            unknown_overflow = bool(re.search(r'Overfull \\[hv]box', log)) and not issues
            severe = missing or unknown_overflow or any(i['points'] > 1 for i in issues)
            attempts.append({'pages': len(reader.pages), 'overflow': issues, 'missing_glyph': missing})
            atomic_json(destination.with_suffix('.layout.json'), {'attempts': attempts})
            if not severe and 1 <= len(reader.pages) <= max_pages:
                break
        else:
            raise ValueError('PDF layout failed after one compaction; private review PDF and line diagnostics retained.')
        if len(text.strip()) < 500:
            raise ValueError('PDF text extraction failed; private review PDF retained.')
        if contacts:
            compact = re.sub(r'\s+', '', text)
            for value in (contacts['email'], contacts['phone'], contacts['linkedin'].split('/in/')[1].rstrip('/')):
                if re.sub(r'\s+', '', value) not in compact:
                    raise ValueError('A required private contact is missing from the final PDF.')
        return {'compiled': True, 'pages': len(reader.pages), 'text_extractable': True,
                'overflow_check': 'passed', 'layout_attempts': attempts,
                'layout_warnings': issues, 'compacted': bool(attempt), 'contacts_included': bool(contacts),
                'visual_review': 'pending', 'semantic_grounding': 'model-audited; human review recommended'}
