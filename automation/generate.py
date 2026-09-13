import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


def tex_escape(value):
    substitutions = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
                     '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}',
                     '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    return ''.join(substitutions.get(char, char) for char in str(value)).replace('\r', ' ').replace('\n', ' ')


def load_contacts(path=None):
    raw = os.environ.get('CV_CONTACT_JSON')
    if raw is None:
        location = Path(path) if path else ROOT / '.private' / 'contact.json'
        if not location.exists():
            raise ValueError('Private contact file missing. Create .private/contact.json from the example.')
        raw = location.read_text(encoding='utf-8-sig')
    contacts = json.loads(raw)
    if set(contacts) != {'email', 'phone', 'linkedin'}:
        raise ValueError('Contact JSON must have email, phone and linkedin only.')
    if not all(isinstance(x, str) and x.strip() and '\n' not in x for x in contacts.values()):
        raise ValueError('All three contacts are required, as single-line strings.')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', contacts['email']):
        raise ValueError('Invalid contact email.')
    if not re.fullmatch(r'\+?[\d ()-]{7,25}', contacts['phone']):
        raise ValueError('Invalid contact phone.')
    u = urlsplit(contacts['linkedin'])
    if (u.scheme != 'https' or u.hostname not in ('www.linkedin.com', 'linkedin.com')
            or not re.fullmatch(r'/in/[A-Za-z0-9_%\-]+/?', u.path)
            or u.query or u.fragment or u.username or u.password or u.port):
        raise ValueError('LinkedIn contact must be a clean HTTPS /in/ profile URL.')
    return contacts


def contact_tex(contacts):
    # Contacts enter only the isolated compile directory, after all model calls.
    url = contacts['linkedin'].rstrip('/')
    label = url.removeprefix('https://www.').removeprefix('https://')
    return (r'\renewcommand{\cvcontact}{Madrid, Spain | ' + tex_escape(contacts['phone'])
            + ' | ' + tex_escape(contacts['email']) + r'\\[2pt]\href{'
            + tex_escape(url) + '}{' + tex_escape(label) + '}}\n')


def render(profile, adapted, language):
    from .localization import localized_profile
    profile = localized_profile(profile, language)
    env = Environment(loader=FileSystemLoader(ROOT / 'templates'), undefined=StrictUndefined,
                      block_start_string='((*', block_end_string='*))',
                      variable_start_string='((=', variable_end_string='=))', autoescape=False)
    env.filters['tex'] = tex_escape
    labels = {'en': ['Professional Summary', 'Experience', 'Technical & Management Skills', 'Education', 'Languages'],
              'es': ['Perfil profesional', 'Experiencia', 'Competencias técnicas y de gestión', 'Formación', 'Idiomas']}[language]
    return env.get_template('tailored-cv.tex.j2').render(profile=profile, adapted=adapted,
                                                       roles=list(zip(profile['experience'], adapted['experience'])),
                                                       labels=labels)


def _contains_private_contact(text, contacts):
    normalized = re.sub(r'[^a-z0-9]', '', text.lower())
    for value in (contacts or {}).values():
        token = re.sub(r'[^a-z0-9]', '', value.lower())
        if token in normalized:
            return True
    return False


def assert_no_private_contacts(text, contacts):
    if _contains_private_contact(text, contacts):
        raise ValueError('Configured private contact found in input.')


def assert_no_public_contacts(text, contacts):
    if _contains_private_contact(text, contacts):
        raise ValueError('Private contact found in publishable output.')
    if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|linkedin\.com/in/', text, re.I):
        raise ValueError('A personal contact was found in publishable output.')


def sanitize_public(text, contacts):
    assert_no_private_contacts(text, contacts)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[contacto de tercero omitido]', text)
    return re.sub(r'(?:https?://)?(?:www\.)?linkedin\.com/in/[^\s"<>]+', '[perfil de tercero omitido]', text, flags=re.I)
