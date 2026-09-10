"""Fetch public job pages without credentials; reject private network destinations."""
import html
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser

MAX_BYTES = 2_000_000


def canonical_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Job URL must be HTTPS without credentials.')
    if parsed.port not in (None, 443):
        raise ValueError('Only HTTPS port 443 is supported.')
    host = parsed.hostname.lower()
    if host == 'linkedin.com' or host.endswith('.linkedin.com'):
        job_id = urllib.parse.parse_qs(parsed.query).get('currentJobId', [''])[0]
        match = re.search(r'/jobs/view/(?:[^/]*-)?(\d+)/?$', parsed.path)
        if match:
            job_id = match.group(1)
        if not re.fullmatch(r'\d{6,20}', job_id):
            raise ValueError('LinkedIn URL must identify a specific job.')
        return f'https://www.linkedin.com/jobs/view/{job_id}/'
    # Drop tracking identifiers and fragments; keep functional query parameters.
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query)
             if not k.lower().startswith(('utm_', 'tracking', 'refid'))]
    return urllib.parse.urlunsplit(('https', parsed.netloc, parsed.path,
                                    urllib.parse.urlencode(query), ''))


def check_public_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Unsafe redirect or URL.')
    addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private/local network URLs are not supported.')


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        elif tag in ('p', 'br', 'li', 'h1', 'h2', 'h3', 'div'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def clean_html(raw):
    parser = TextParser()
    parser.feed(raw)
    return '\n'.join(line.strip() for line in html.unescape(''.join(parser.parts)).splitlines()
                     if line.strip())


def page_text(raw):
    # Prefer the actual job description over login forms/navigation on LinkedIn.
    m = re.search(r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', raw, re.S)
    if m:
        title = re.search(r'<h2[^>]*top-card-layout__title[^>]*>(.*?)</h2>', raw, re.S)
        company = re.search(r'<a[^>]*topcard__org-name-link[^>]*>(.*?)</a>', raw, re.S)
        location = re.search(r'<span[^>]*topcard__flavor--bullet[^>]*>(.*?)</span>', raw, re.S)
        return '\n'.join(clean_html(x.group(1)) for x in (title, company, location, m) if x)
    for block in re.findall(r'<script[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', raw, re.S):
        try:
            objects = json.loads(block)
            objects = objects if isinstance(objects, list) else [objects]
            objects += [n for obj in list(objects) if isinstance(obj, dict) for n in obj.get('@graph', [])]
            for obj in objects:
                if isinstance(obj, dict) and obj.get('@type') == 'JobPosting':
                    return clean_html(json.dumps(obj, ensure_ascii=False))
        except (ValueError, TypeError):
            continue
    return clean_html(raw)


def fetch_job(url):
    canonical = canonical_url(url)
    target = canonical
    if 'www.linkedin.com/jobs/view/' in canonical:
        target = 'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/' + canonical.rstrip('/').split('/')[-1]
    check_public_url(target)
    request = urllib.request.Request(target, headers={'User-Agent': 'Mozilla/5.0 CVResearch/1.0'})
    with urllib.request.build_opener(SafeRedirect()).open(request, timeout=30) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Job page exceeds the size limit; provide a text extract.')
    text = page_text(raw.decode('utf-8', errors='replace'))
    if len(text) < 250:
        raise ValueError('No usable job description. Use --job-text with the offer text.')
    if len(text) > 45000:
        raise ValueError('Page is too noisy. Use --job-text with just the offer description.')
    return canonical, text
