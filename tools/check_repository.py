#!/usr/bin/env python3
"""Check the Git publication file set for private/generated artifacts and large files."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'out', 'evidence', 'backups', 'private', 'downloads', 'upstream', '.git', '.venv', '__pycache__'}
PRIVATE = [re.compile(rb'/home/[^/\s]+/'), re.compile(rb'(?<!\d)192\.168\.\d{1,3}\.\d{1,3}(?!\d)'),
           re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
           re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'), re.compile(rb'github_pat_[A-Za-z0-9_]{50,}')]


def check():
    try:
        result = subprocess.run(['git', 'ls-files', '--cached', '-z'], cwd=ROOT,
                                capture_output=True, check=True)
        paths = [ROOT / name.decode() for name in result.stdout.split(b'\0') if name]
    except (OSError, subprocess.CalledProcessError):
        paths = []
    if not paths:
        paths = [p for p in ROOT.rglob('*') if p.is_file() and not EXCLUDED.intersection(p.relative_to(ROOT).parts)]
    errors = []
    for path in paths:
        relative = path.relative_to(ROOT)
        if EXCLUDED.intersection(relative.parts) or path.is_symlink():
            errors.append(str(relative) + ': excluded directory or symlink')
            continue
        if not path.is_file():
            errors.append(str(relative) + ': missing file')
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            errors.append(str(relative) + ': source publication file exceeds 2 MiB')
            continue
        if path.suffix.lower() in {'.img', '.bin', '.so', '.apk', '.jar', '.zip', '.7z', '.pcap', '.log'}:
            errors.append(str(relative) + ': generated/binary artifact')
            continue
        if path.suffix.lower() == '.png' and relative.parts[0] == 'assets':
            continue  # Selected, manually reviewed UI screenshot.
        data = path.read_bytes()
        if b'\0' in data:
            errors.append(str(relative) + ': unexpected binary content')
        if path.name != 'check_repository.py' and any(pattern.search(data) for pattern in PRIVATE):
            errors.append(str(relative) + ': possible private path/address/credential')
    for error in errors:
        print(error)
    if errors:
        return 1
    print(f'Publication check passed: {len(paths)} source/documentation files')
    return 0


if __name__ == '__main__':
    raise SystemExit(check())

