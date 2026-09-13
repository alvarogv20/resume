"""Private, atomic checkpoints with exclusive per-run ownership."""
import hashlib
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class RunState:
    def __init__(self, folder, identity, resume=False):
        self.folder = Path(folder)
        self.identity = fingerprint(identity)
        self.resume = resume
        self.lock = self.folder / 'active.lock'

    def __enter__(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock.open('x', encoding='utf-8') as stream:
                stream.write('Run active. Remove only after verifying no process owns this run.\n')
        except FileExistsError:
            raise ValueError('Run is locked; another process may be active. See troubleshooting.md.') from None
        try:
            manifest = self.folder / 'manifest.json'
            if manifest.exists():
                if not self.resume:
                    raise ValueError('Private checkpoints exist. Use --resume or a new slug.')
                self.manifest = json.loads(manifest.read_text(encoding='utf-8'))
                if self.manifest['identity'] != self.identity:
                    raise ValueError('Resume inputs changed; use a new slug.')
            else:
                if self.resume:
                    raise ValueError('No checkpoint exists for --resume.')
                self.manifest = {'identity': self.identity, 'requests': 0}
                atomic_json(manifest, self.manifest)
            return self
        except BaseException:
            self.lock.unlink(missing_ok=True)
            raise

    def __exit__(self, *args):
        self.lock.unlink(missing_ok=True)

    def begin_request(self, limit):
        if self.manifest['requests'] >= limit:
            raise ValueError('LLM request budget exhausted; explicitly increase max_requests to continue.')
        self.manifest['requests'] += 1
        atomic_json(self.folder / 'manifest.json', self.manifest)
        return self.manifest['requests']

    def cached(self, key):
        path = self.folder / 'cache' / (key + '.json')
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def save(self, key, record):
        atomic_json(self.folder / 'cache' / (key + '.json'), record)

    def stage(self, name, status, **details):
        now = datetime.now(timezone.utc)
        previous = self.manifest.setdefault('stages', {}).get(name, {})
        started = now.isoformat() if status == 'running' else previous.get('started_at', now.isoformat())
        self.manifest['stages'][name] = {'status': status, 'started_at': started,
            'duration_seconds': round((now - datetime.fromisoformat(started)).total_seconds(), 3), **details}
        atomic_json(self.folder / 'manifest.json', self.manifest)

    def invalidate(self, stage):
        order = ['extract', 'adapt', 'audit', 'repair', 'export']
        affected = set(order[order.index(stage):])
        for path in (self.folder / 'cache').glob('*.json'):
            record = json.loads(path.read_text(encoding='utf-8'))
            if record['metadata']['stage'] in affected:
                path.unlink()
        for name in affected:
            self.manifest.setdefault('stages', {}).pop(name, None)
        derived = {'extract': ['job.json', 'draft.json', 'adaptation.json', 'match.md', 'decisions.md'],
                   'adapt': ['draft.json', 'adaptation.json', 'match.md', 'decisions.md'],
                   'audit': ['adaptation.json', 'match.md', 'decisions.md'], 'export': []}
        archive = self.folder / 'history' / uuid.uuid4().hex
        for name in derived.get(stage, []) + ['cv.tex', 'cv.pdf', 'cv.log', 'cv.layout.json', 'validation.json', 'status.json']:
            path = self.folder / name
            if path.exists():
                archive.mkdir(parents=True, exist_ok=True)
                path.rename(archive / name)
        atomic_json(self.folder / 'manifest.json', self.manifest)
