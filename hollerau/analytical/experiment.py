"""Fingerprints for reproducible evaluation; never infer a score or call a model."""

import hashlib
import json
import subprocess
from pathlib import Path


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(package, store):
    root = Path(__file__).resolve().parents[2]
    paths = sorted(p for folder in ('hollerau', 'arena_kit') for p in (root / folder).rglob('*.py')
                   if 'logs' not in p.relative_to(root).parts)
    source = {str(p.relative_to(root)): digest_file(p) for p in paths}
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, check=False)
    memory = hashlib.sha256()
    # Include committed WAL content through SQLite's consistent read transaction.
    with store.db:
        store.db.execute('BEGIN')
        for line in store.db.iterdump():
            memory.update(line.encode())
            memory.update(b'\n')
    data = {}
    for label, folder in (('package', package.root), ('release', package.release)):
        if folder:
            for path in sorted(p for p in folder.rglob('*') if p.is_file()):
                if any(part.startswith('.') for part in path.relative_to(folder).parts):
                    continue
                data[f'{label}/{path.relative_to(folder)}'] = digest_file(path)
    return {'git_commit': git.stdout.strip() if git.returncode == 0 else None,
            'source_sha256': source,
            'source_manifest_sha256': hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
            'initial_memory_sha256': memory.hexdigest(),
            'public_data_manifest_sha256': hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
            'public_data_files': len(data),
            'model_settings': {'astra_reasoning_effort': 'low', 'max_output_tokens': 4096},
            'comparison_warning': 'One fresh session is exploratory; historical best is not a matched control.'}
