#!/usr/bin/env python3
"""Build an OFFLINE bring-up image from verified public GammaOS release inputs.

This is image integration, not an AOSP compilation. No connected device is written.
Hardware compatibility, VINTF and the installation layout remain separate gates.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = "out/reference-gkd/partitions/system.img"
CLASSIC = "out/reference-classic/Retroid_Pocket_Classic_GammaOSNext_Lite_v1/flash"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def parse_properties(text):
    result = {}
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def merge_properties(original, overrides):
    # Remove old definitions so Android's duplicate-property resolution does not
    # silently keep another copy of a bring-up default.
    lines = [line for line in original.splitlines()
             if line.split("=", 1)[0].strip() not in overrides]
    lines.extend(["", "# Unofficial Pocket Classic Nano development port"])
    lines.extend(f"{key}={value}" for key, value in overrides.items())
    return "\n".join(lines) + "\n"


def classic_platform_literal(binary):
    """Retarget the pinned release's shared Qualcomm detector to parrot.

    This equal-length .rodata edit is specific to the Classic image. It changes
    no instructions, ELF layout, or ro.board.platform identity seen by the HAL.
    The equivalent maintainable source change is supplied separately as a patch.
    """
    if hashlib.sha256(binary).hexdigest() != "5dda3100f902dce69f7912814b4c1086b597a8006fc3251a7d7c74b3132bb4c2":
        raise RuntimeError("Unexpected upstream Nano executable")
    offset = 0x38d2f
    if binary[offset:offset + 7] != b"bengal\0" or binary.count(b"bengal\0") != 1:
        raise RuntimeError("Qualcomm platform literal changed")
    sections, = struct.unpack_from("<Q", binary, 40)
    entry_size, count = struct.unpack_from("<HH", binary, 58)
    containing = []
    for index in range(count):
        fields = struct.unpack_from("<IIQQQQIIQQ", binary, sections + index * entry_size)
        _, kind, flags, _, start, length, *_ = fields
        if start <= offset and offset + 7 <= start + length:
            containing.append((kind, flags))
    if containing != [(1, 0x32)]:  # PROGBITS, ALLOC|MERGE|STRINGS; never executable
        raise RuntimeError("Platform literal is outside the expected read-only string section")
    return binary[:offset] + b"parrot\0" + binary[offset + 7:]


def classic_state_cache_script(original):
    if hashlib.sha256(original).hexdigest() != "081dcd86a0218a502db299ff7dbd22f8ddbd302a13c200693c6e0b5a4e8e0d05":
        raise RuntimeError("Unexpected upstream Nano cache manager")
    hook = b'''# Classic: LibretroRunner 1.4.1 reads core bytes, not RetroArch RASTATE blocks.
# Normalize only the DE preview copies; keep CE saves in RetroArch's own format.
classic_state_compat() {
    CLASSPATH=/system/framework/classic-state.jar /system/bin/app_process /system/bin ClassicStateCompat 2>&1 | while IFS= read -r line; do
        log -t ClassicStateCompat "$line"
    done
    restorecon -R "$CACHE/states" "$CACHE/rom" 2>/dev/null
}

'''
    marker = b'OP="$1"\n'
    if original.count(marker) != 1:
        raise RuntimeError("Nano cache dispatch changed")
    patched = original.replace(marker, hook + marker)
    for operation in (b"populate", b"sync_to_cache"):
        old = b"do_" + operation + b" ;;"
        if patched.count(old) != 1:
            raise RuntimeError("Nano cache operation changed")
        patched = patched.replace(old, b"do_" + operation + b"; classic_state_compat ;;")
    return patched


def classic_nfs_compatibility(binary):
    """Repair pinned libnfs READDIR links and bound unsupported fragmented reads.

    Core 1.4.1's RPC reader rejects non-final record markers. libtirpc servers
    fragment large READ replies at 64 KiB, so negotiate 32 KiB reads/writes.
    This is a transfer-size workaround, not general RPC fragment support.
    patches/0002-classic-nfs-transfer-size.patch supplies the source equivalent.
    """
    if hashlib.sha256(binary).hexdigest() != "f610732e4761a1b541f9bc103670b206d8204624da9892591371d41cb4f0c3ea":
        raise RuntimeError("Unexpected upstream libnfs executable")
    offset = 0x32a78
    # nfs_init_context: mov w8,#0x100000; stp x8,x8,[x20,#40].
    # Only the immediate changes; both default readmax and writemax use it.
    if binary[offset:offset + 8] != bytes.fromhex("0802a05288a202a9"):
        raise RuntimeError("libnfs default transfer-size instructions changed")
    sections, = struct.unpack_from("<Q", binary, 40)
    entry_size, count = struct.unpack_from("<HH", binary, 58)
    executable = False
    for index in range(count):
        fields = struct.unpack_from("<IIQQQQIIQQ", binary, sections + index * entry_size)
        _, kind, flags, _, start, length, *_ = fields
        if start <= offset and offset + 8 <= start + length:
            executable = kind == 1 and flags == 6  # PROGBITS, ALLOC|EXECINSTR
    if not executable:
        raise RuntimeError("libnfs defaults are outside the expected text section")
    patched = binary[:offset] + bytes.fromhex("08009052") + binary[offset + 4:]
    # The shipped zdr_entry3 loop decodes every node into the same object.
    # Restore upstream's zdr_pointer(zdrs,&objp->nextentry,32,zdr_entry3).
    # Keep its existing prologue, field decoders, canary, epilogue and ELF ABI.
    offset = 0x4cc84
    original = bytes.fromhex("e1130091e00314aae141009480000034e80740b9c8fdff3520008052")
    replacement = bytes.fromhex("e00314aa616200910204805243fcff10e34100941f2003d51f2003d5")
    if patched[offset:offset + len(original)] != original:
        raise RuntimeError("libnfs READDIR decoder instructions changed")
    return patched[:offset] + replacement + patched[offset + len(original):]


def classic_power_dispatch(original):
    """Route only Nano's ordinary restart/power-off through the DE-cache flush."""
    patched = original
    for action, prefix in ((b"reboot", b"    write /data/misc/bootanim/nano_skip 0\n"),
                           (b"shutdown", b"")):
        old = b"on property:service.bootanim.nano_action=" + action + b"\n" + prefix + b"    setprop sys.powerctl " + action + b"\n"
        if patched.count(old) != 1:
            raise RuntimeError("Unexpected Nano power dispatcher: " + action.decode())
        new = b"on property:service.bootanim.nano_action=" + action + b"\n" + prefix + b"    exec_start classic-nano-" + action + b"\n"
        patched = patched.replace(old, new)
    return patched


def classic_charger_dispatch(original):
    # Init rejects overriding a vendor service from a system rc across the
    # Treble boundary. This image retains exactly the stock health 2.1 service
    # and selects the separately named Classic charger instead of class-starting
    # the incompatible vendor charger definition.
    old = b"on charger\n    class_start charger\n"
    if original.count(old) != 1:
        raise RuntimeError("Unexpected charger class dispatcher")
    return original.replace(old, b"on charger\n    start health-hal-2-1\n    start vendor.qti.light\n    exec_start classic-charger-prepare\n    start classic-charger\n")


class Builder:
    def __init__(self, output):
        self.output = output.resolve()
        self.log = None

    def run(self, argv, accepted=(0,)):
        result = subprocess.run([str(a) for a in argv], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False)
        self.log.write("$ " + " ".join(str(a) for a in argv) + "\n")
        if b"\0" in result.stdout:
            self.log.write(f"[binary stdout: {len(result.stdout)} bytes, SHA256 {hashlib.sha256(result.stdout).hexdigest()}]\n")
        else:
            self.log.write(result.stdout.decode(errors="replace"))
        self.log.write(result.stderr.decode(errors="replace"))
        self.log.flush()
        if result.returncode not in accepted:
            detail = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"Command failed ({result.returncode}): {argv[0]}" +
                               (f"\n{detail}" if detail else "; see build.log"))
        return result.stdout

    def read_image(self, image, path):
        return self.run(["debugfs", "-R", f"cat {path}", image])

    def compile_charger_entry(self):
        target = self.output / "classic-charger-entry"
        self.run(["aarch64-linux-gnu-gcc", "-nostdlib", "-static", "-ffreestanding", "-fno-builtin",
                  "-fno-stack-protector", "-fno-pie", "-no-pie", "-Os", "-Wl,-e,_start",
                  "-Wl,--build-id=none", "-Wl,-z,max-page-size=4096", "-s", "-o", target,
                  ROOT / "device/classic-charger-entry.c"])
        data = target.read_bytes()
        if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", data, 16) != (2, 183):
            raise RuntimeError("Charger entry is not a static arm64 ELF")
        offset, = struct.unpack_from("<Q", data, 32)
        size, count = struct.unpack_from("<HH", data, 54)
        if any(struct.unpack_from("<I", data, offset + i * size)[0] in (2, 3) for i in range(count)):
            raise RuntimeError("Charger entry unexpectedly needs a dynamic linker")
        return data

    def compile_charger_ioctl(self):
        target = self.output / "classic-charger-ioctl.so"
        self.run(["aarch64-linux-gnu-gcc", "-nostdlib", "-shared", "-fPIC", "-ffreestanding",
                  "-fno-builtin", "-fno-stack-protector", "-Os", "-Wl,--build-id=none",
                  "-Wl,-z,max-page-size=4096", "-o", target,
                  ROOT / "device/classic-charger-ioctl.c"])
        data = target.read_bytes()
        if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", data, 16) != (3, 183):
            raise RuntimeError("Charger ioctl diagnostic is not an arm64 shared ELF")
        return data

    def write_large_file(self, image, path, host_file, exists, mode="0100644",
                         context="u:object_r:system_file:s0"):
        """Stream a large input into the image and verify it by SHA-256 readback."""
        label = self.output / "integration" / "large.label"
        label.parent.mkdir(parents=True, exist_ok=True)
        label.write_bytes(context.encode() + b"\0")
        commands = ([f"rm {path}"] if exists else []) + [
            f'write "{host_file}" {path}',
            f"set_inode_field {path} mode {mode}",
            f"set_inode_field {path} uid 0",
            f"set_inode_field {path} gid 0",
            f'ea_set -f "{label}" {path} security.selinux',
        ]
        batch = self.output / "debugfs.commands"
        batch.write_text("\n".join(commands) + "\n")
        self.run(["debugfs", "-w", "-f", batch, image])
        readback = self.output / "integration" / "readback.tmp"
        readback.unlink(missing_ok=True)
        self.run(["debugfs", "-R", f'dump {path} "{readback}"', image])
        expected = sha256(Path(host_file))
        if not readback.exists() or sha256(readback) != expected:
            raise RuntimeError(f"Image readback differs: {path}")
        readback.unlink()
        attrs = self.run(["debugfs", "-R", f"ea_get {path} security.selinux", image])
        if context.encode() not in attrs:
            raise RuntimeError(f"Unexpected SELinux context for {path}")
        return expected

    def integrate_applications(self, image):
        """Update and add the applications and RetroArch payload pinned in apps.lock.json."""
        sys.path.insert(0, str(ROOT / "tools"))
        import retroarch_payload
        lock = json.loads((ROOT / "apps.lock.json").read_text())
        cache = ROOT / "downloads/apps"
        for entry in lock["apps"] + lock.get("files", []):
            path = cache / entry["file"]
            if path.stat().st_size != entry["size"] or sha256(path) != entry["sha256"]:
                raise RuntimeError(f"Application input mismatch: {entry['file']}; run tools/prepare_apps.py --download")
        # setup.sh installs the stock application set by file name on first boot.
        setup = self.read_image(image, "/system/bin/setup.sh")
        for entry in lock["apps"]:
            if "setup_reference" not in entry:
                continue
            old = ("/system/etc/" + entry["setup_reference"]).encode()
            if setup.count(old) != 1:
                raise RuntimeError(f"setup.sh reference changed: {old.decode()}")
            setup = setup.replace(old, entry["image_path"].encode())
        self.replace_file(image, "/system/bin/setup.sh", setup, "0100755",
                          context="u:object_r:gammaossetupwizard_exec:s0", gid=2000)
        self.create_directory(image, "/system/etc/classic-apps")
        installed = []
        for entry in lock["apps"]:
            replaced = entry.get("replaces")
            if replaced and replaced != entry["image_path"]:
                self.run(["debugfs", "-w", "-R", f"rm {replaced}", image])
            digest = self.write_large_file(image, entry["image_path"], cache / entry["file"],
                                           exists=(replaced == entry["image_path"]))
            installed.append({key: entry[key] for key in ("id", "package", "version", "version_code",
                                                          "image_path", "license", "role")}
                             | {"sha256": digest})
        # Pinned non-APK inputs (e.g. the Turnip driver package for Eden).
        extra, created = [], set()
        for entry in lock.get("files", []):
            directory = entry["image_path"].rsplit("/", 1)[0]
            if directory not in created:
                self.create_directory(image, directory)
                created.add(directory)
            digest = self.write_large_file(image, entry["image_path"], cache / entry["file"], exists=False)
            extra.append({key: entry[key] for key in ("id", "image_path", "license")} | {"sha256": digest})
        listing = ["# id|package|versionCode|apk|grants  (generated from apps.lock.json)"]
        listing += [f"{e['id']}|{e['package']}|{e['version_code']}|{e['image_path']}|{','.join(e['grants'])}"
                    for e in lock["apps"]]
        # RetroArch first-boot payload with the pinned nightly cores and frontend assets.
        original = self.output / "retroarch.orig.tar.xz"
        self.run(["debugfs", "-R", f'dump /system/etc/retroarch.tar.xz "{original}"', image])
        rebuilt = self.output / "retroarch.tar.xz"
        stats = retroarch_payload.build(original, rebuilt, lock, cache)
        payload_digest = self.write_large_file(image, "/system/etc/retroarch.tar.xz", rebuilt, exists=True)
        original.unlink()
        rebuilt.unlink()
        return {"applications": installed,
                "files": extra,
                "retained": lock["retained"],
                "retroarch_payload": {"sha256": payload_digest, "members": stats,
                                      "cores": len(lock["retroarch_payload"]["cores"]),
                                      "assets": [a["file"] for a in lock["retroarch_payload"]["assets"]]},
                "list": ("\n".join(listing) + "\n").encode(),
                "setup": setup}

    def create_directory(self, image, path):
        """Create a labelled directory and catch debugfs' silent command errors."""
        label = self.output / "directory.label"
        label.write_bytes(b"u:object_r:system_file:s0\0")
        commands = [f"mkdir {path}", f"set_inode_field {path} mode 040755",
                    f"set_inode_field {path} uid 0", f"set_inode_field {path} gid 0",
                    f'ea_set -f "{label}" {path} security.selinux']
        batch = self.output / "directory.commands"
        batch.write_text("\n".join(commands) + "\n")
        self.run(["debugfs", "-w", "-f", batch, image])
        metadata = self.run(["debugfs", "-R", f"stat {path}", image])
        attrs = self.run(["debugfs", "-R", f"ea_get {path} security.selinux", image])
        if b"Type: directory" not in metadata or b"Mode:  0755" not in metadata or b"u:object_r:system_file:s0" not in attrs:
            raise RuntimeError(f"Directory creation failed: {path}")

    def replace_file(self, image, path, data, mode, exists=True,
                     context="u:object_r:system_file:s0", gid=0):
        if exists:
            original_attrs = self.run(["debugfs", "-R", f"ea_get {path} security.selinux", image])
            if context.encode() not in original_attrs:
                raise RuntimeError(f"Refusing to change the existing SELinux type of {path}")
        host_file = self.output / "integration" / path.lstrip("/")
        host_file.parent.mkdir(parents=True, exist_ok=True)
        host_file.write_bytes(data)
        label = self.output / "integration" / "file.label"
        label.write_bytes(context.encode() + b"\0")
        commands = ([f"rm {path}"] if exists else []) + [
            f'write "{host_file}" {path}',
            f"set_inode_field {path} mode {mode}",
            f"set_inode_field {path} uid 0",
            f"set_inode_field {path} gid {gid}",
            f'ea_set -f "{label}" {path} security.selinux',
        ]
        batch = self.output / "debugfs.commands"
        batch.write_text("\n".join(commands) + "\n")
        self.run(["debugfs", "-w", "-f", batch, image])
        if self.read_image(image, path) != data:
            raise RuntimeError(f"Image readback differs: {path}")
        metadata = self.run(["debugfs", "-R", f"stat {path}", image]).decode()
        if f"Mode:  {mode[-4:]}" not in metadata:
            raise RuntimeError(f"Unexpected file mode for {path}: {metadata}")
        attrs = self.run(["debugfs", "-R", f"ea_get {path} security.selinux", image])
        if context.encode() not in attrs:
            raise RuntimeError(f"Missing SELinux context for {path}")

    def build(self):
        for program in ("debugfs", "avbtool", "e2fsck", "resize2fs", "cp", "img2simg", "javac", "java", "aarch64-linux-gnu-gcc"):
            if shutil.which(program) is None:
                raise RuntimeError(f"Missing program: {program}")
        lock = json.loads((ROOT / "artifact-inputs.json").read_text())
        for name, info in lock.items():
            path = ROOT / name
            if path.stat().st_size != info["size"] or sha256(path) != info["sha256"]:
                raise RuntimeError(f"Input integrity mismatch: {name}")
        self.output.mkdir(parents=True, exist_ok=False)
        with (self.output / "build.log").open("w") as self.log:
            charger_entry = self.compile_charger_entry()
            charger_ioctl = self.compile_charger_ioctl()
            helper = self.output / "time-helper"
            helper.mkdir()
            r8 = ROOT / "out/android-helper/r8.jar"
            if sha256(r8) != "59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439":
                raise RuntimeError("R8 compiler integrity mismatch")
            self.run(["javac", "--release", "8", "-d", helper,
                      ROOT / "tools/android/ClassicTimeSync.java"])
            self.run(["java", "-cp", r8, "com.android.tools.r8.D8", "--min-api", "26",
                      "--output", helper, helper / "ClassicTimeSync.class"])
            time_jar = helper / "classic-time.jar"
            with zipfile.ZipFile(time_jar, "w") as archive:
                entry = zipfile.ZipInfo("classes.dex", (2025, 1, 1, 0, 0, 0))
                padding = (-(30 + len(entry.filename) + 4)) % 4
                entry.extra = struct.pack("<HH", 0xD935, padding) + b"\0" * padding
                archive.writestr(entry, (helper / "classes.dex").read_bytes())
            state_helper = self.output / "state-helper"
            state_helper.mkdir()
            self.run(["javac", "--release", "8", "-d", state_helper,
                      ROOT / "tools/android/ClassicStateCompat.java"])
            self.run(["java", "-cp", r8, "com.android.tools.r8.D8", "--min-api", "26",
                      "--output", state_helper, state_helper / "ClassicStateCompat.class"])
            state_jar = state_helper / "classic-state.jar"
            with zipfile.ZipFile(state_jar, "w") as archive:
                entry = zipfile.ZipInfo("classes.dex", (2025, 1, 1, 0, 0, 0))
                padding = (-(30 + len(entry.filename) + 4)) % 4
                entry.extra = struct.pack("<HH", 0xD935, padding) + b"\0" * padding
                archive.writestr(entry, (state_helper / "classes.dex").read_bytes())
            systems_helper = self.output / "systems-helper"
            systems_helper.mkdir()
            self.run(["javac", "--release", "8", "-d", systems_helper,
                      ROOT / "tools/android/ClassicSystems.java"])
            self.run(["java", "-cp", r8, "com.android.tools.r8.D8", "--min-api", "26",
                      "--output", systems_helper, *sorted(systems_helper.glob("*.class"))])
            systems_jar = systems_helper / "classic-systems.jar"
            with zipfile.ZipFile(systems_jar, "w") as archive:
                entry = zipfile.ZipInfo("classes.dex", (2025, 1, 1, 0, 0, 0))
                padding = (-(30 + len(entry.filename) + 4)) % 4
                entry.extra = struct.pack("<HH", 0xD935, padding) + b"\0" * padding
                archive.writestr(entry, (systems_helper / "classes.dex").read_bytes())
            json.loads((ROOT / "device/classic-systems.json").read_text())
            controller = self.read_image(ROOT / CLASSIC / "vendor_custom.img", "/bin/retroidpad")
            if hashlib.sha256(controller).hexdigest() != "8a1bb2395dbd3a01f8c52f3f1c6c785767f273213a2221b9ed207f494b8bddfb":
                raise RuntimeError("Classic MCU bridge integrity mismatch")
            image = self.output / "system.img"
            self.run(["cp", "--reflink=auto", "--sparse=always", ROOT / SYSTEM, image])
            self.run(["avbtool", "erase_footer", "--image", image])
            # Source ext4 uses shared_blocks. Unshare before removing or replacing
            # any inode, otherwise debugfs can free a block used by another file.
            with image.open("r+b") as stream:
                # Headroom for the updated and added applications; resize2fs -M trims it.
                stream.truncate(image.stat().st_size + 2 * 1024 ** 3)
            self.run(["resize2fs", "-f", image])
            self.run(["e2fsck", "-fy", "-E", "unshare_blocks", image], accepted=(0, 1))
            stats = self.run(["debugfs", "-R", "stats", image])
            features = next(line for line in stats.splitlines() if line.startswith(b"Filesystem features:"))
            if b"shared_blocks" in features:
                raise RuntimeError("Filesystem still has shared blocks")
            defaults = parse_properties((ROOT / "device/port-defaults.prop").read_text())
            original = self.read_image(image, "/system/build.prop").decode()
            if "ro.build.version.sdk=34" not in original:
                raise RuntimeError("Expected Android 14 system image")
            merged = merge_properties(original, defaults).encode()
            self.replace_file(image, "/system/build.prop", merged, "0100644")
            # Init loads product defaults after vendor defaults. Stock Classic
            # vendor explicitly sets this read-only property to yes, overriding
            # the same key in system/build.prop before properties are published.
            product_props_path = "/system/product/etc/build.prop"
            product_props = merge_properties(self.read_image(image, product_props_path).decode(),
                                              {"ro.incremental.enable": "false"}).encode()
            self.replace_file(image, product_props_path, product_props, "0100644")
            nano_binary = classic_platform_literal(self.read_image(image, "/system/bin/gammaos-nano"))
            self.replace_file(image, "/system/bin/gammaos-nano", nano_binary, "0100755",
                              context="u:object_r:bootanim_exec:s0", gid=2000)
            nfs_binary = classic_nfs_compatibility(self.read_image(image, "/system/lib64/libnfs.so"))
            self.replace_file(image, "/system/lib64/libnfs.so", nfs_binary, "0100644",
                              context="u:object_r:system_lib_file:s0")
            native_charger = self.read_image(image, "/system/bin/charger")
            if hashlib.sha256(native_charger).hexdigest() != "b62ed2839510001acdb19fb8eab7821c62b15ba363bdb0cf8955464b53b29483":
                raise RuntimeError("Unexpected upstream charger executable")
            self.replace_file(image, "/system/bin/charger", charger_entry, "0100755",
                              context="u:object_r:charger_exec:s0", gid=2000)
            self.replace_file(image, "/system/bin/charger-core", native_charger, "0100755", exists=False,
                              context="u:object_r:charger_exec:s0", gid=2000)
            self.replace_file(image, "/system/lib64/classic-charger-ioctl.so", charger_ioctl, "0100644", exists=False,
                              context="u:object_r:system_lib_file:s0")
            policy_delta = (ROOT / "device/classic-policy.cil").read_bytes()
            policy = self.read_image(image, "/system/etc/selinux/plat_sepolicy.cil") + b"\n" + policy_delta
            self.replace_file(image, "/system/etc/selinux/plat_sepolicy.cil", policy, "0100644",
                              context="u:object_r:sepolicy_file:s0")
            # This port retains the original vendor's 32.0 mapping. A changed
            # platform fingerprint makes init compile the actual split policy.
            policy_inputs = policy + self.read_image(image, "/system/etc/selinux/mapping/32.0.cil")
            policy_inputs += self.read_image(image, "/system/etc/selinux/mapping/32.0.compat.cil")
            policy_fingerprint = (hashlib.sha256(policy_inputs).hexdigest() + "\n").encode()
            self.replace_file(image, "/system/etc/selinux/plat_sepolicy_and_mapping.sha256",
                              policy_fingerprint, "0100644")
            old_controller_rc = self.read_image(image, "/system/etc/init/gammapad.rc")
            if b"service gammapad /system/bin/gammapad" not in old_controller_rc:
                raise RuntimeError("Unexpected generic GammaPad service")
            self.replace_file(image, "/system/etc/init/gammapad.rc",
                              (ROOT / "device/gammapad.rc").read_bytes(), "0100644")
            profile = (ROOT / "device/profile.json").read_bytes()
            self.replace_file(image, "/system/etc/pocket-classic-port.json", profile,
                              "0100644", exists=False)
            integrated = {
                "/system/bin/classic-retroidpad": (controller, "0100755"),
                "/system/bin/classic-hardware.sh": ((ROOT / "device/classic-hardware.sh").read_bytes(), "0100755"),
                "/system/bin/classic-time.sh": ((ROOT / "device/classic-time.sh").read_bytes(), "0100755"),
                "/system/bin/classic-shaders.sh": ((ROOT / "device/classic-shaders.sh").read_bytes(), "0100755"),
                "/system/bin/classic-provision.sh": ((ROOT / "device/classic-provision.sh").read_bytes(), "0100755"),
                "/system/bin/classic-power.sh": ((ROOT / "device/classic-power.sh").read_bytes(), "0100755"),
                "/system/bin/classic-charger-probe.sh": ((ROOT / "device/classic-charger-probe.sh").read_bytes(), "0100755"),
                "/system/bin/classic-charger-prepare.sh": ((ROOT / "device/classic-charger-prepare.sh").read_bytes(), "0100755"),
                "/system/etc/init/classic.rc": ((ROOT / "device/classic.rc").read_bytes(), "0100644"),
                "/system/framework/classic-time.jar": (time_jar.read_bytes(), "0100644"),
                "/system/framework/classic-state.jar": (state_jar.read_bytes(), "0100644"),
            }
            # Core's system image omits minui's default charger resources. Keep
            # the stock charger service/domain and supply the six-frame assets
            # from the already pinned Classic reference, without changing power
            # key or automatic-boot behavior.
            charger_assets = {}
            for name, expected in (
                ("battery_fail.png", "a6adc7aaeee6bb1db8ad1dc3d6c2185b166fa106286092d300bfbb0aefae00a2"),
                ("battery_scale.png", "7c95e165f9696d9aa61cf5abcb5cbbafd6a00e3ebb50ac20e1fbc533834a8cfe"),
            ):
                path = "/system/etc/res/images/charger/" + name
                data = self.read_image(ROOT / CLASSIC / "system_custom.img", path)
                if hashlib.sha256(data).hexdigest() != expected:
                    raise RuntimeError(f"Charger resource integrity mismatch: {name}")
                charger_assets[path] = {"sha256": expected, "size": len(data)}
                integrated[path] = (data, "0100644")
            for directory in ("/system/etc/res", "/system/etc/res/images", "/system/etc/res/images/charger"):
                self.create_directory(image, directory)
            cache_script = classic_state_cache_script(self.read_image(image, "/system/bin/nano_cache.sh"))
            self.replace_file(image, "/system/bin/nano_cache.sh", cache_script, "0100755",
                              context="u:object_r:gammaoscustomization_exec:s0")
            init_path = "/system/etc/init/hw/init.rc"
            init_script = classic_charger_dispatch(classic_power_dispatch(self.read_image(image, init_path)))
            self.replace_file(image, init_path, init_script, "0100644")
            applications = self.integrate_applications(image)
            integrated.update({
                "/system/bin/classic-apps.sh": ((ROOT / "device/classic-apps.sh").read_bytes(), "0100755"),
                "/system/etc/classic-apps.list": (applications["list"], "0100644"),
                "/system/etc/classic-systems.json": ((ROOT / "device/classic-systems.json").read_bytes(), "0100644"),
                "/system/etc/classic-retroarch-payload.sha256":
                    ((applications["retroarch_payload"]["sha256"] + "\n").encode(), "0100644"),
                "/system/framework/classic-systems.jar": (systems_jar.read_bytes(), "0100644"),
            })
            profiles = sorted((ROOT / "device/profiles-src").glob("*/profile.json"))
            if profiles:
                self.create_directory(image, "/system/etc/classic-profiles")
            for manifest in profiles:
                emulator_profile = json.loads(manifest.read_text())
                package = emulator_profile["package"]
                if manifest.parent.name != package or not emulator_profile["marker"].startswith("/data/"):
                    raise RuntimeError(f"Invalid emulator profile: {manifest}")
                base = "/system/etc/classic-profiles/" + package
                self.create_directory(image, base)
                lines = ["marker|" + emulator_profile["marker"]]
                for target, source in emulator_profile["files"].items():
                    allowed = (f"/data/user/0/{package}/", f"/data/media/0/Android/data/{package}/", "/data/media/0/")
                    if not target.startswith(allowed) or "/" in source or "|" in target + source:
                        raise RuntimeError(f"Invalid profile entry {target} in {manifest}")
                    integrated[f"{base}/{source}"] = ((manifest.parent / source).read_bytes(), "0100644")
                    lines.append(f"{target}|{source}")
                integrated[f"{base}/profile.list"] = (("\n".join(lines) + "\n").encode(), "0100644")
            for path, (contents, mode) in integrated.items():
                self.replace_file(image, path, contents, mode, exists=False)
            self.run(["e2fsck", "-fy", image], accepted=(0, 1))
            self.run(["resize2fs", "-M", image])
            fsck_verification = self.run(["e2fsck", "-fn", image])
            (self.output / "fsck-verification.txt").write_bytes(fsck_verification)
            filesystem_bytes = image.stat().st_size
            # Development AVB descriptor has no trusted production signature.
            # The reference Classic vendor ramdisk has verification-free fstab
            # entries. Stock ramdisk/VBMeta compatibility must be checked separately.
            partition_bytes = (filesystem_bytes + 64 * 1024 ** 2 + 4095) // 4096 * 4096
            self.run(["avbtool", "add_hashtree_footer", "--image", image,
                      "--partition_name", "system", "--partition_size", partition_bytes,
                      "--hash_algorithm", "sha256", "--algorithm", "NONE",
                      "--salt", hashlib.sha256(merged).hexdigest(), "--do_not_generate_fec",
                      "--prop", "com.android.build.system.os_version:14",
                      "--prop", "com.android.build.system.security_patch:2025-06-01"])
            verification = self.run(["avbtool", "verify_image", "--image", image])
            (self.output / "avb-verification.txt").write_bytes(verification)
            for path, expected in (("/system/build.prop", merged),
                                   (product_props_path, product_props),
                                   ("/system/bin/gammaos-nano", nano_binary),
                                   ("/system/lib64/libnfs.so", nfs_binary),
                                   ("/system/bin/charger", charger_entry),
                                   ("/system/bin/charger-core", native_charger),
                                   ("/system/lib64/classic-charger-ioctl.so", charger_ioctl),
                                   ("/system/etc/selinux/plat_sepolicy.cil", policy),
                                   ("/system/etc/selinux/plat_sepolicy_and_mapping.sha256", policy_fingerprint),
                                   ("/system/etc/init/gammapad.rc", (ROOT / "device/gammapad.rc").read_bytes()),
                                   ("/system/etc/pocket-classic-port.json", profile)):
                if self.read_image(image, path) != expected:
                    raise RuntimeError(f"Final readback failed: {path}")
            final_label = self.run(["debugfs", "-R", "ea_list /system/bin/gammaos-nano", image])
            if b"u:object_r:bootanim_exec:s0" not in final_label:
                raise RuntimeError("Nano executable lost its bootanim_exec domain transition")
            for path, (contents, _) in integrated.items():
                if self.read_image(image, path) != contents:
                    raise RuntimeError(f"Final readback failed: {path}")
            sparse = self.output / "system.sparse.img"
            self.run(["img2simg", image, sparse])
            artifacts = {}
            for path in (image, sparse):
                artifacts[path.name] = {"size": path.stat().st_size, "sha256": sha256(path)}
            metadata = {
                "status": "offline-candidate-unverified-hardware",
                "built_at": datetime.now(timezone.utc).isoformat(),
                "method": "public GammaOS Nano 1.4.1 Core image integration; not a source build",
                "target": "original Retroid Pocket Classic, qcom board-id <0x22 0>",
                "filesystem_bytes": filesystem_bytes, "system_partition_bytes": partition_bytes,
                "avb_authentication": "NONE; hashtree integrity only",
                "source_patch_compiled_into_image": False,
                "charger_resources": {"source": CLASSIC + "/system_custom.img", "files": charger_assets},
                "charger_entry": {"method": "static arm64 entry preserving vendor credentials and original Core charger",
                    "entry_sha256": hashlib.sha256(charger_entry).hexdigest(),
                    "ioctl_compat_sha256": hashlib.sha256(charger_ioctl).hexdigest(),
                    "ioctl_compat_method": "Qualcomm SDE atomic EINVAL fallback and retained-CRTC canonical backlight blank/wake",
                    "original_core_sha256": hashlib.sha256(native_charger).hexdigest()},
                "selinux_integration": {"vendor_mapping": "32.0",
                    "delta_sha256": hashlib.sha256(policy_delta).hexdigest(),
                    "platform_inputs_fingerprint": policy_fingerprint.decode().strip(),
                    "global_permissive_added": False, "permissive_domains_added": []},
                "nfs_integration": {"file": "/system/lib64/libnfs.so",
                    "method": "restore READDIR nextentry decoding; default readmax/writemax 32 KiB avoids 64 KiB RPC fragments",
                    "offsets": ["0x32a78", "0x4cc84"], "sha256": hashlib.sha256(nfs_binary).hexdigest()},
                "binary_integration": {"file": "/system/bin/gammaos-nano",
                    "method": "equal-length Qualcomm platform literal bengal -> parrot in .rodata",
                    "offset": "0x38d2f", "sha256": hashlib.sha256(nano_binary).hexdigest()},
                "application_integration": {key: applications[key] for key in
                                            ("applications", "files", "retained", "retroarch_payload")},
                "hardware_boot_verified": False, "ready_for_flash": False,
                "required_classic_reference": CLASSIC,
                "inputs": lock, "artifacts": artifacts,
                "outstanding": ["this image's permanent install and boot chain", "controller autostart",
                                "audio and brightness", "sleep/wake and thermal controls",
                                "emulators and quick resume", "recovery and update validation"]}
            (self.output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
            (self.output / "SHA256SUMS").write_text("".join(
                f"{info['sha256']}  {name}\n" for name, info in artifacts.items()))
            print(json.dumps({key: metadata[key] for key in
                              ("status", "system_partition_bytes", "artifacts")}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="New output directory; existing directories are never overwritten")
    args = parser.parse_args()
    try:
        Builder(args.output).build()
    except (OSError, RuntimeError, subprocess.SubprocessError, StopIteration) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
