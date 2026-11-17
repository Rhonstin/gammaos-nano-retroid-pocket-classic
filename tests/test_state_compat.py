"""Exercise the actual Java state decoder, including malformed external saves."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]


class StateCompat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        harness = cls.folder / 'StateHarness.java'
        harness.write_text('''import java.nio.file.*;
public class StateHarness {
 public static void main(String[] args) throws Exception {
  byte[] result=ClassicStateCompat.coreState(Files.readAllBytes(Paths.get(args[0])));
  if (result!=null) Files.write(Paths.get(args[1]),result);
 }
}''')
        subprocess.run(['javac', '--release', '8', '-d', str(cls.folder),
                        str(ROOT/'tools/android/ClassicStateCompat.java'), str(harness)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def decode(self, data, valid=True):
        source, target = self.folder/'input', self.folder/'output'
        source.write_bytes(data)
        target.unlink(missing_ok=True)
        result = subprocess.run(['java', '-cp', str(self.folder), 'StateHarness',
                                 str(source), str(target)], capture_output=True)
        self.assertEqual(result.returncode == 0, valid, result.stderr.decode())
        return target.read_bytes() if target.exists() else None

    def state(self, memory, before=b''):
        padding = bytes((-len(memory)) % 8)
        return (b'RASTATE\x01'+before+b'MEM '+struct.pack('<I', len(memory))
                +memory+padding+b'END '+bytes(4))

    def rzip(self, data, chunk=131072):
        frames = [zlib.compress(data[p:p+chunk]) for p in range(0, len(data), chunk)]
        return (b'#RZIPv\x01#'+struct.pack('<IQ', chunk, len(data))
                +b''.join(struct.pack('<I', len(f))+f for f in frames))

    def test_gpsp_sized_multichunk_container_and_optional_metadata(self):
        memory = bytes(range(256))*1664  # gpSP's 425984-byte state
        state = self.state(memory, b'RPLY'+struct.pack('<I', 3)+b'abc'+bytes(5))
        self.assertEqual(self.decode(self.rzip(state)), memory)
        self.assertEqual(self.decode(state), memory)

    def test_raw_gambatte_state_is_not_rewritten(self):
        raw = b'raw-libretro-state'*100
        self.assertIsNone(self.decode(raw))
        self.assertIsNone(self.decode(self.rzip(raw)))

    def test_truncated_oversized_and_ambiguous_saves_are_rejected(self):
        state = self.state(b'memory')
        cases = [state[:-1], state[:16], state+b'garbage',
                 b'RASTATE\x02'+state[8:],
                 b'RASTATE\x01MEM '+struct.pack('<I', 0xffffffff),
                 state[:-8]+state[8:],
                 self.rzip(state)[:-1],
                 self.rzip(state)+b'trailing',
                 b'#RZIPv\x01#'+struct.pack('<IQ', 131072, 1 << 40),
                 b'#RZIPv\x02#'+struct.pack('<IQ', 131072, 10)]
        for case in cases:
            with self.subTest(case=case[:20]):
                self.assertIsNone(self.decode(case, valid=False))


if __name__ == '__main__':
    unittest.main()
