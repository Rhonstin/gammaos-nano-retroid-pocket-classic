import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from release_tools import join, prepare


class ReleaseIntegrity(unittest.TestCase):
    def fixture(self, root):
        candidate = root / 'candidate'
        candidate.mkdir()
        artifacts = {}
        for name, data in [('system.img', b'raw' * 40), ('system.sparse.img', bytes(range(251)) * 2)]:
            (candidate / name).write_bytes(data)
            artifacts[name] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        (candidate / 'manifest.json').write_text(json.dumps({'status': 'development', 'artifacts': artifacts,
                                                          'serial': 'PRIVATE-SERIAL', 'private_path': 'PRIVATE-PATH'}))
        checkpoint = root / 'checkpoint.json'
        checkpoint.write_text(json.dumps({'version': 'test', 'target': 'fixture', 'artifacts': artifacts,
                                          'remaining_validation': ['hardware']}))
        notes = root / 'notes.md'
        notes.write_text('Synthetic release test\n')
        bundle = root / 'bundle'
        prepare(candidate, checkpoint, bundle, notes, part_bytes=64)
        return candidate, bundle

    def test_roundtrip_and_public_metadata_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate, bundle = self.fixture(Path(tmp))
            result = join(bundle / 'release.json')
            self.assertEqual(result.read_bytes(), (candidate / 'system.sparse.img').read_bytes())
            self.assertNotIn('PRIVATE-', (bundle / 'manifest.json').read_text())
            self.assertTrue((bundle / 'SHA256SUMS').is_file())

    def test_corrupt_part_never_publishes_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, bundle = self.fixture(Path(tmp))
            part = bundle / 'system.sparse.img.part01'
            part.write_bytes(b'x' * part.stat().st_size)
            with self.assertRaisesRegex(ValueError, 'Part checksum'):
                join(bundle / 'release.json')
            self.assertFalse((bundle / 'system.sparse.img').exists())
            self.assertFalse(list(bundle.glob('*.partial')))

    def test_reordered_parts_fail_final_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, bundle = self.fixture(Path(tmp))
            p = bundle / 'release.json'
            data = json.loads(p.read_text())
            data['image']['parts'].reverse()
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'Assembled image checksum'):
                join(p)
            self.assertFalse((bundle / 'system.sparse.img').exists())

    def test_traversal_and_symlink_parts_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, bundle = self.fixture(Path(tmp))
            p = bundle / 'release.json'
            data = json.loads(p.read_text())
            data['image']['parts'][0]['name'] = '../outside'
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'basenames'):
                join(p)
            data['image']['parts'][0]['name'] = 'system.sparse.img.part01'
            p.write_text(json.dumps(data))
            part = bundle / 'system.sparse.img.part01'
            outside = bundle.parent / 'outside'
            part.rename(outside)
            part.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'regular file'):
                join(p)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, bundle = self.fixture(Path(tmp))
            target = bundle / 'system.sparse.img'
            target.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                join(bundle / 'release.json')
            self.assertEqual(target.read_bytes(), b'keep')

    def test_wrong_candidate_is_rejected_before_bundle_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, _ = self.fixture(root)
            (candidate / 'system.sparse.img').write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                prepare(candidate, root / 'checkpoint.json', root / 'bad', root / 'notes.md')
            self.assertFalse((root / 'bad').exists())


if __name__ == '__main__':
    unittest.main()

