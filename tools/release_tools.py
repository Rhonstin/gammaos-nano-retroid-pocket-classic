"""Verified split/reassembly of local firmware release assets. No network or flash I/O."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

CHUNK = 1024 * 1024
PART_BYTES = 1024 ** 3


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_name(value):
    if not isinstance(value, str) or not value or value in ('.', '..') or any(c in value for c in '/\\\x00'):
        raise ValueError('Release filenames must be plain basenames')
    return value


def valid_hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Expected a lowercase SHA256 digest')
    return value


def prepare(candidate, checkpoint, output, notes, part_bytes=PART_BYTES):
    candidate, output = Path(candidate), Path(output)
    public = json.loads(Path(checkpoint).read_text())
    manifest = json.loads((candidate / 'manifest.json').read_text())
    if manifest['status'].startswith('rejected'):
        raise ValueError('Candidate has a recorded defect')
    if not 0 < part_bytes <= PART_BYTES:
        raise ValueError('Parts must be at most 1 GiB')
    artifacts = public['artifacts']
    for name in ('system.img', 'system.sparse.img'):
        expected = artifacts[name]
        valid_hash(expected['sha256'])
        if manifest['artifacts'][name] != expected:
            raise ValueError('Candidate does not match public checkpoint: ' + name)
        path = candidate / name
        if path.stat().st_size != expected['size'] or digest(path) != expected['sha256']:
            raise ValueError('Candidate integrity mismatch: ' + name)
    output.mkdir(parents=True, exist_ok=False)
    parts, complete = [], hashlib.sha256()
    with (candidate / 'system.sparse.img').open('rb') as source:
        while True:
            first = source.read(min(CHUNK, part_bytes))
            if not first:
                break
            name = f'system.sparse.img.part{len(parts)+1:02d}'
            count, sha = 0, hashlib.sha256()
            with (output / name).open('xb') as target:
                block = first
                while block:
                    target.write(block)
                    sha.update(block)
                    complete.update(block)
                    count += len(block)
                    if count == part_bytes:
                        break
                    block = source.read(min(CHUNK, part_bytes - count))
            parts.append({'name': name, 'size': count, 'sha256': sha.hexdigest()})
    sparse = artifacts['system.sparse.img']
    if sum(p['size'] for p in parts) != sparse['size'] or complete.hexdigest() != sparse['sha256']:
        raise ValueError('Sparse image changed while being split')
    # Deliberate allowlist: never copy private device identifiers or raw logs.
    public_manifest = {
        'status': 'development-checkpoint-device-tested-partial-acceptance',
        'method': 'public GammaOS Core image integration; not an AOSP source build',
        'target': public['target'],
        'system_partition_bytes': artifacts['system.img']['size'],
        'artifacts': artifacts,
        'hardware_boot_verified': True,
        'ready_for_flash': False,
        'outstanding': public['remaining_validation'],
    }
    (output / 'manifest.json').write_text(json.dumps(public_manifest, indent=2) + '\n')
    release = {'schema': 1, 'version': public['version'], 'target': public['target'],
               'image': {'name': 'system.sparse.img', **sparse, 'parts': parts}}
    (output / 'release.json').write_text(json.dumps(release, indent=2) + '\n')
    shutil.copyfile(notes, output / 'RELEASE_NOTES.md')
    files = sorted(p for p in output.iterdir() if p.is_file())
    (output / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in files))
    return release


def join(manifest_path, output=None):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 1:
        raise ValueError('Unsupported release manifest schema')
    image = manifest['image']
    name, expected_hash = safe_name(image['name']), valid_hash(image['sha256'])
    parts = image['parts']
    if not isinstance(parts, list) or not 1 <= len(parts) <= 1000:
        raise ValueError('Invalid part count')
    seen, total, sources = set(), 0, []
    for part in parts:
        filename = safe_name(part['name'])
        if filename in seen:
            raise ValueError('Duplicate part filename')
        seen.add(filename)
        valid_hash(part['sha256'])
        if type(part['size']) is not int or not 0 < part['size'] <= PART_BYTES:
            raise ValueError('Invalid part size')
        source = manifest_path.parent / filename
        if source.is_symlink() or source.resolve().parent != manifest_path.parent.resolve():
            raise ValueError('Part must be a regular file in the release directory')
        if source.stat().st_size != part['size']:
            raise ValueError('Part size mismatch: ' + filename)
        sources.append((source, part))
        total += part['size']
    if total != image['size']:
        raise ValueError('Part sizes do not match image size')
    output = Path(output) if output else manifest_path.parent / name
    if output.exists() or output.is_symlink():
        raise FileExistsError('Output already exists: ' + str(output))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.' + output.name + '-', suffix='.partial',
                                         dir=output.parent, delete=False) as target:
            temporary = Path(target.name)
            complete = hashlib.sha256()
            for source, part in sources:
                partial = hashlib.sha256()
                with source.open('rb') as stream:
                    while block := stream.read(CHUNK):
                        partial.update(block)
                        complete.update(block)
                        target.write(block)
                if partial.hexdigest() != part['sha256']:
                    raise ValueError('Part checksum mismatch: ' + source.name)
            if complete.hexdigest() != expected_hash:
                raise ValueError('Assembled image checksum mismatch')
            target.flush()
            os.fsync(target.fileno())
        # Publish only after every hash passed; never overwrite a racing file.
        os.link(temporary, output)
        return output
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

