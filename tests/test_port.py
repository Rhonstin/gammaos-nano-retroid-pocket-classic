"""Host checks for firmware identity and image/container integrity handling."""
import io
import json
from pathlib import Path
import struct
import sys
import subprocess
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from collect_device import assess_identity, decode_board_id, parse_devices
from build_candidate import Builder, merge_properties, parse_properties, classic_power_dispatch, classic_charger_dispatch, classic_nfs_compatibility
from prepare_references import rk_super_range
from check_reference_compatibility import check_kernel_matrix, extract_kernel_config
from prepare_install import patch_fstab


class NfsCompatibility(unittest.TestCase):
    def test_pinned_library_transfer_defaults_and_identity_guard(self):
        image = ROOT / "out/reference-gkd/partitions/system.img"
        if not image.exists() or not shutil.which("debugfs"):
            self.skipTest("Pinned Core image and debugfs needed")
        original = subprocess.check_output(["debugfs", "-R", "cat /system/lib64/libnfs.so", str(image)],
                                           stderr=subprocess.DEVNULL)
        patched = classic_nfs_compatibility(original)
        self.assertEqual(len(patched), len(original))
        self.assertEqual(patched[:0x32a78], original[:0x32a78])
        self.assertEqual(patched[0x32a7c:0x4cc84], original[0x32a7c:0x4cc84])
        self.assertEqual(patched[0x4cca0:], original[0x4cca0:])
        instruction, store = struct.unpack_from("<II", patched, 0x32a78)
        self.assertEqual(instruction & 0xffe0001f, 0x52800008)  # MOVZ W8, imm16
        self.assertEqual((instruction >> 5) & 0xffff, 32768)
        self.assertEqual(store, 0xa902a288)  # STP X8,X8,[X20,#40]
        for invalid in (patched, original[:-1], b"\x00" + original[1:]):
            with self.assertRaisesRegex(RuntimeError, "Unexpected upstream libnfs"):
                classic_nfs_compatibility(invalid)

    def test_actual_arm64_decoder_preserves_entries_and_rejects_truncation(self):
        image = ROOT / "out/reference-gkd/partitions/system.img"
        programs = ("debugfs", "qemu-aarch64", "aarch64-linux-gnu-gcc", "aarch64-linux-gnu-ld", "aarch64-linux-gnu-objcopy")
        if not image.exists() or any(not shutil.which(p) for p in programs):
            self.skipTest("Pinned Core and arm64 test tools needed")
        original = subprocess.check_output(["debugfs", "-R", "cat /system/lib64/libnfs.so", str(image)],
                                           stderr=subprocess.DEVNULL)
        patched = classic_nfs_compatibility(original)
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            subprocess.run(["aarch64-linux-gnu-gcc", "-c", str(ROOT / "device/classic-nfs-entry-link.S"), "-o", "link.o"], cwd=d, check=True)
            subprocess.run(["aarch64-linux-gnu-ld", "--build-id=none", "-Ttext=0x4cc84", "-e", "classic_nfs_entry_link",
                            "--defsym=original_zdr_entry3=0x4cc18", "--defsym=original_zdr_pointer=0x5d420",
                            "-o", "link.elf", "link.o"], cwd=d, check=True)
            subprocess.run(["aarch64-linux-gnu-objcopy", "-O", "binary", "--only-section=.text", "link.elf", "link.bin"], cwd=d, check=True)
            self.assertEqual((d / "link.bin").read_bytes(), patched[0x4cc84:0x4cca0])
            for binary, expected in ((original, 2), (patched, 0)):
                (d / "decoder.bin").write_bytes(binary[0x4cc18:0x4cccc])
                subprocess.run(["aarch64-linux-gnu-gcc", "-nostdlib", "-static", "-no-pie", "-fno-pie", "-ffreestanding",
                                "-fno-builtin", "-fno-stack-protector", "-mbranch-protection=none", "-Os",
                                "-Wl,--build-id=none", "-Wl,-z,max-page-size=4096", "-Wl,-T," + str(ROOT / "tests/nfs_decoder_test.ld"),
                                "-o", "test", str(ROOT / "tests/nfs_decoder_test.c"), str(ROOT / "tests/nfs_decoder_test.S")], cwd=d, check=True)
                result = subprocess.run(["qemu-aarch64", "./test"], cwd=d, timeout=10)
                self.assertEqual(result.returncode, expected)


class DeviceIdentity(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / "device/profile.json").read_text())
        self.properties = {"ro.product.device": "generic", "ro.product.vendor.device": "parrot",
                           "ro.product.cpu.abilist": "arm64-v8a,armeabi-v7a,armeabi",
                           "ro.treble.enabled": "true", "sys.boot_completed": "1"}

    def test_original_from_vendor_codename(self):
        result = assess_identity(self.properties, decode_board_id(bytes.fromhex("0000002200000000")), self.profile)
        self.assertTrue(result["identity_confirmed"])
        self.assertFalse(result["ready_for_flash"])
        self.assertFalse(result["firmware_compatibility_verified"])

    def test_revq_and_unknown_board_rejected(self):
        for board in ([0x1000b, 0], None, [0x22000000, 0], [0x22, 1]):
            with self.subTest(board=board):
                self.assertFalse(assess_identity(self.properties, board, self.profile)["identity_confirmed"])

    def test_missing_properties_do_not_confirm_identity(self):
        self.assertFalse(assess_identity({}, [0x22, 0], self.profile)["identity_confirmed"])

    def test_malformed_board_property_rejected(self):
        for raw in (b"", b"\0" * 4, b"\0" * 12, b"permission denied"):
            with self.assertRaises(ValueError):
                decode_board_id(raw)

    def test_unauthorized_and_offline_devices_remain_distinct(self):
        devices = parse_devices("List of devices attached\nA unauthorized\nB offline\nC device product:parrot\n")
        self.assertEqual([d["serial"] for d in devices if d["state"] == "device"], ["C"])


class FirmwareContainer(unittest.TestCase):
    def container(self, count=1, position=2048, allocated=512, length=400):
        data = bytearray(4096)
        data[:4] = b"RKFW"
        struct.pack_into("<II", data, 0x21, 102, 3072)
        data[102:106] = b"RKAF"
        struct.pack_into("<I", data, 102 + 0x88, count)
        start = 102 + 0x8c
        data[start:start + 5] = b"super"
        struct.pack_into("<IIII", data, start + 96, position, 0, allocated, length)
        return bytes(data)

    def test_rkaf_offsets_are_relative_to_inner_header(self):
        self.assertEqual(rk_super_range(io.BytesIO(self.container()), 4096), (2150, 400))

    def test_out_of_bounds_entries_rejected_before_copy(self):
        for options in ({"count": 200}, {"position": 3000}, {"length": 600}, {"length": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                rk_super_range(io.BytesIO(self.container(**options)), 4096)

    def test_properties_have_one_effective_definition(self):
        merged = merge_properties("# old\npersist.bootanim.skip_nano=1\nx=y\npersist.bootanim.skip_nano=1\n",
                                  {"persist.bootanim.skip_nano": "0"})
        self.assertEqual(merged.count("persist.bootanim.skip_nano="), 1)
        self.assertEqual(parse_properties(merged), {"x": "y", "persist.bootanim.skip_nano": "0"})


class KernelCompatibility(unittest.TestCase):
    def matrix(self, extra="", version="5.10.43"):
        return ET.fromstring(f'''<compatibility-matrix>
          <kernel version="{version}" level="6">
            <config><key>CONFIG_ANDROID_BINDER_IPC</key><value type="tristate">y</value></config>
          </kernel>{extra}</compatibility-matrix>''')

    def test_arch_conditions_are_applied(self):
        extra = '''<kernel version="5.10.43" level="6">
          <conditions><config><key>CONFIG_X86</key><value type="tristate">y</value></config></conditions>
          <config><key>CONFIG_MISSING_X86_FEATURE</key><value type="tristate">y</value></config>
        </kernel>'''
        result = check_kernel_matrix("CONFIG_ANDROID_BINDER_IPC=y\nCONFIG_ARM64=y\n",
                                     self.matrix(extra), "5.10.209-android12-9")
        self.assertTrue(result["passes_checked_requirements"])
        self.assertEqual(result["requirements_checked"], 1)

    def test_required_missing_config_and_old_patchlevel_fail(self):
        for config, version in (("", "5.10.209"), ("CONFIG_ANDROID_BINDER_IPC=y\n", "5.10.42")):
            with self.subTest(config=config, version=version):
                result = check_kernel_matrix(config, self.matrix(), version)
                self.assertFalse(result["passes_checked_requirements"])

    def test_empty_or_unsupported_check_does_not_pass(self):
        self.assertFalse(check_kernel_matrix("", self.matrix(), "6.1.0")["passes_checked_requirements"])
        matrix = self.matrix()
        matrix.find("kernel/config/value").set("type", "unknown")
        result = check_kernel_matrix("CONFIG_ANDROID_BINDER_IPC=y", matrix, "5.10.209")
        self.assertFalse(result["passes_checked_requirements"])
        self.assertTrue(result["unsupported"])

    def test_false_marker_cannot_hide_embedded_config(self):
        config = b"CONFIG_ARM64=y\n"
        binary = b"IKCFG_STinvalid\0padding" + b"IKCFG_ST" + zlib.compress(config, wbits=31) + b"IKCFG_ED"
        self.assertEqual(extract_kernel_config(binary), config.decode())


class FirstStageMounts(unittest.TestCase):
    def test_only_integrated_mounts_removed(self):
        source = (b"# product is embedded\n\n"
                  b"system /system ext4 ro wait,logical,avb\n"
                  b"product /product ext4 ro wait,logical,avb\n"
                  b"system_ext /system_ext ext4 ro wait,logical,avb\n"
                  b"vendor /vendor ext4 ro wait,logical,avb\n"
                  b"/dev/block/userdata /data f2fs noatime wait,fileencryption=aes\n")
        self.assertEqual(patch_fstab(source), source.replace(
            b"product /product ext4 ro wait,logical,avb\n", b"").replace(
            b"system_ext /system_ext ext4 ro wait,logical,avb\n", b""))

    def test_unexpected_layout_is_rejected(self):
        for source in (b"system /system ext4 ro wait\n", b"product /product ext4 ro wait\n",
                       b"product /product ext4 ro wait\nproduct /product ext4 ro wait\n"):
            with self.assertRaises(ValueError):
                patch_fstab(source)


class ExecutableSecurityMetadata(unittest.TestCase):
    def test_replacement_cannot_silently_remove_init_domain_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "filesystem.img"
            with image.open("wb") as stream:
                stream.truncate(8 * 1024 * 1024)
            subprocess.run(["mke2fs", "-q", "-F", "-t", "ext4", str(image)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            builder = Builder(root)
            builder.log = io.StringIO()
            builder.replace_file(image, "/nano", b"original", "0100755", exists=False,
                                 context="u:object_r:bootanim_exec:s0", gid=2000)
            with self.assertRaisesRegex(RuntimeError, "SELinux type"):
                builder.replace_file(image, "/nano", b"broken", "0100755")
            self.assertEqual(builder.read_image(image, "/nano"), b"original")
            builder.replace_file(image, "/nano", b"updated", "0100755",
                                 context="u:object_r:bootanim_exec:s0", gid=2000)
            self.assertEqual(builder.read_image(image, "/nano"), b"updated")
            # debugfs ea_list omits long values; ea_get must verify this label.
            context = "u:object_r:gammaoscustomization_exec:s0"
            builder.replace_file(image, "/cache", b"original", "0100755", exists=False,
                                 context=context)
            builder.replace_file(image, "/cache", b"updated", "0100755", context=context)
            self.assertEqual(builder.read_image(image, "/cache"), b"updated")
            builder.create_directory(image, "/res")
            builder.create_directory(image, "/res/images")
            builder.replace_file(image, "/res/images/battery", b"six frames", "0100644", exists=False)
            self.assertEqual(builder.read_image(image, "/res/images/battery"), b"six frames")
            with self.assertRaisesRegex(RuntimeError, "Directory creation failed"):
                builder.create_directory(image, "/missing/child")


class NativePowerDispatch(unittest.TestCase):
    def test_flush_only_for_native_restart_and_shutdown(self):
        original = (b'on property:service.bootanim.nano_action=reboot\n'
                    b'    write /data/misc/bootanim/nano_skip 0\n'
                    b'    setprop sys.powerctl reboot\n\n'
                    b'on property:service.bootanim.nano_action=shutdown\n'
                    b'    setprop sys.powerctl shutdown\n\n'
                    b'on property:service.bootanim.nano_action=recovery\n'
                    b'    setprop sys.powerctl reboot,recovery\n')
        patched = classic_power_dispatch(original)
        self.assertIn(b'exec_start classic-nano-reboot', patched)
        self.assertIn(b'exec_start classic-nano-shutdown', patched)
        self.assertTrue(patched.endswith(original[original.index(b'on property:service.bootanim.nano_action=recovery'):]))
        with self.assertRaises(RuntimeError):
            classic_power_dispatch(patched)

    def test_charger_routes_only_the_known_classic_services(self):
        original = b'on charger\n    class_start charger\n\non boot\n    class_start hal\n'
        patched = classic_charger_dispatch(original)
        self.assertIn(b'start classic-charger\n', patched)
        self.assertIn(b'start health-hal-2-1\n', patched)
        self.assertTrue(patched.endswith(b'on boot\n    class_start hal\n'))
        for invalid in (patched, original + original):
            with self.assertRaises(RuntimeError):
                classic_charger_dispatch(invalid)


class ChargerEntry(unittest.TestCase):
    @unittest.skipUnless(shutil.which("aarch64-linux-gnu-gcc") and shutil.which("qemu-aarch64"),
                         "arm64 cross compiler and qemu required")
    def test_bootstrap_entry_runs_without_libc_or_apex(self):
        with tempfile.TemporaryDirectory() as directory:
            builder = Builder(Path(directory))
            builder.log = io.StringIO()
            builder.compile_charger_entry()
            result = subprocess.run(["qemu-aarch64", str(Path(directory) / "classic-charger-entry")],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 127)
            self.assertIn("executing original Core charger", result.stderr)
            self.assertIn("exec charger-core failed", result.stderr)

    @unittest.skipUnless(shutil.which("cc"), "host C compiler required")
    def test_atomic_handoff_bounds_properties_and_blob_lifetime(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "charger-atomic-test"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-o", str(target),
                            str(ROOT / "tests/charger_atomic_test.c")], check=True)
            subprocess.run([str(target)], check=True, timeout=5)

    @unittest.skipUnless(shutil.which("cc"), "host C compiler required")
    def test_only_owned_display_is_blanked_and_brightness_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "charger-ioctl-test"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-o", str(target),
                            str(ROOT / "tests/charger_ioctl_test.c")], check=True)
            subprocess.run([str(target)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
