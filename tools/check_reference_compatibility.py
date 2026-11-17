#!/usr/bin/env python3
"""Check candidate/reference HAL XML under QEMU and reference kernel configuration.

This is an OFFLINE reference check. QEMU's runtime information belongs to the
host, so its full VintfObject runtime result is deliberately not a device gate.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
CLASSIC = ROOT / "out/reference-classic/Retroid_Pocket_Classic_GammaOSNext_Lite_v1/flash"


def command(args):
    return subprocess.run([str(a) for a in args], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True)


def read_file(image, path):
    result = command(["debugfs", "-R", f"cat {path}", image])
    if not result.stdout:
        raise RuntimeError(f"Could not read non-empty image file: {path}")
    return result.stdout


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract_kernel_config(kernel):
    marker = b"IKCFG_ST"
    position = 0
    while (position := kernel.find(marker, position)) >= 0:
        end = kernel.find(b"IKCFG_ED", position + len(marker))
        if end > position:
            try:
                return zlib.decompress(kernel[position + len(marker):end], 16 + zlib.MAX_WBITS).decode()
            except (zlib.error, UnicodeError):
                pass
        position += len(marker)
    raise ValueError("No valid embedded IKCONFIG gzip stream found")


def parse_kernel_config(text):
    values = {}
    for line in text.splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            # Current FCM 6 requirements use literal strings without escapes.
            values[key] = value[1:-1] if value.startswith('"') and value.endswith('"') else value
        elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
            values[line.split()[1]] = "n"
    return values


def check_kernel_matrix(config_text, matrix, version):
    values = parse_kernel_config(config_text)
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ValueError(f"Unrecognized kernel version: {version}")
    running = tuple(int(x) for x in match.groups())
    checked, mismatches, unsupported, selected = [], [], [], []

    def match_config(node):
        key, expected = node.findtext("key"), node.findtext("value")
        kind = node.find("value").get("type")
        if kind not in ("tristate", "string"):
            raise ValueError(f"Unsupported kernel config requirement type: {kind}")
        # A config key omitted by Kconfig is disabled. Only a tristate 'n'
        # requirement can match an absent key; strings must actually be set.
        actual = values.get(key, "n" if kind == "tristate" else None)
        return actual == expected, {"key": key, "type": kind,
                                    "expected": expected, "actual": actual}

    for entry in matrix.findall("kernel"):
        required = tuple(int(x) for x in entry.get("version").split("."))
        if running[:2] != required[:2]:
            continue
        if running < required:
            mismatches.append({"version_required": required, "version_actual": running})
            continue
        try:
            conditions = [c for block in entry.findall("conditions") for c in block.findall("config")]
            if not all(match_config(c)[0] for c in conditions):
                continue
            selected.append({"minimum_version": entry.get("version"), "level": entry.get("level"),
                             "conditions": [match_config(c)[1] for c in conditions]})
            for requirement in entry.findall("config"):
                success, item = match_config(requirement)
                checked.append(item)
                if not success:
                    mismatches.append(item)
        except ValueError as error:
            unsupported.append(str(error))
    return {"reference_version": version, "applicable_blocks": selected,
            "requirements_checked": len(checked), "mismatches": mismatches,
            "unsupported": unsupported,
            "passes_checked_requirements": bool(checked) and not mismatches and not unsupported}


def prepare_root(image, output):
    root = output / "root"
    for path in ("system/bin", "system/lib64", "system/etc", "system/system_ext/etc",
                 "system/product/etc", "vendor/etc", "apex/com.android.runtime",
                 "linkerconfig", "usr", "lib", "lib64", "proc", "dev", "sys", "tmp"):
        (root / path).mkdir(parents=True, exist_ok=True)
    runtime = output / "runtime.apex"
    runtime.write_bytes(read_file(image, "/system/apex/com.android.runtime.apex"))
    with zipfile.ZipFile(runtime) as archive:
        payload = output / "runtime-payload.img"
        payload.write_bytes(archive.read("apex_payload.img"))
    command(["debugfs", "-R", f'rdump / "{root / "apex/com.android.runtime"}"', payload])
    (root / "system/bin/linker64").symlink_to("/apex/com.android.runtime/bin/linker64")
    binary = root / "system/bin/vintf"
    binary.write_bytes(read_file(image, "/system/bin/vintf"))
    binary.chmod(0o755)
    pending, seen = [binary], set()
    while pending:
        path = pending.pop()
        dynamic = command(["readelf", "-dW", path]).stdout.decode()
        for name in re.findall(r"\(NEEDED\).*\[(.*?)\]", dynamic):
            if name in seen:
                continue
            seen.add(name)
            if (root / "apex/com.android.runtime/lib64/bionic" / name).exists():
                continue
            library = root / "system/lib64" / name
            library.write_bytes(read_file(image, "/system/lib64/" + name))
            pending.append(library)
    for source, source_path, destination in (
            (image, "/system/etc/vintf", "system/etc"),
            (image, "/system/system_ext/etc/vintf", "system/system_ext/etc"),
            (image, "/system/product/etc/vintf", "system/product/etc"),
            (CLASSIC / "vendor_custom.img", "/etc/vintf", "vendor/etc")):
        command(["debugfs", "-R", f'rdump {source_path} "{root / destination}"', source])
    for name in ("product", "system_ext"):
        (root / name).symlink_to("/system/" + name)
    # QEMU has no Android property area. Select the parrot vendor-SKU manifest
    # explicitly in this fixture, equivalent to ro.boot.product.vendor.sku=parrot.
    # This is only in the analysis root; the candidate/vendor images are unchanged.
    source_manifest = root / "vendor/etc/vintf/manifest_parrot.xml"
    shutil.copyfile(source_manifest, root / "vendor/etc/vintf/manifest.xml")
    return root, sorted(seen)


def check(candidate, output):
    image = candidate / "system.img"
    manifest = json.loads((candidate / "manifest.json").read_text())
    if sha256(image) != manifest["artifacts"]["system.img"]["sha256"]:
        raise RuntimeError("Candidate system hash mismatch")
    reference_lock = json.loads((ROOT / "artifact-inputs.json").read_text())
    for filename in ("boot_custom.img", "vendor_custom.img"):
        source = CLASSIC / filename
        relative = source.relative_to(ROOT).as_posix()
        if sha256(source) != reference_lock[relative]["sha256"]:
            raise RuntimeError(f"Classic reference hash mismatch: {filename}")
    output.mkdir(parents=True, exist_ok=False)
    root, dependencies = prepare_root(image, output)
    args = ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", root, "/"]
    for host_dir in ("/usr", "/lib", "/lib64"):
        if Path(host_dir).exists():
            args += ["--ro-bind", host_dir, host_dir]
    args += ["--proc", "/proc", "--dev", "/dev", shutil.which("qemu-aarch64"),
             "-E", "LD_LIBRARY_PATH=/system/lib64:/apex/com.android.runtime/lib64/bionic",
             "/system/bin/vintf"]
    result = command(args)
    text = result.stdout.decode(errors="replace")
    (output / "vintf.txt").write_bytes(result.stdout)
    (output / "vintf.stderr.txt").write_bytes(result.stderr)
    requirements = (
        "Device Manifest?    GOOD", "Device Matrix?      GOOD",
        "Framework Manifest? GOOD", "Framework Matrix?   GOOD",
        "Device HAL Manifest <==> Framework Compatibility Matrix? GOOD",
        "Framework HAL Manifest <==> Device Compatibility Matrix? GOOD")
    hal_checks = {line: line in text for line in requirements}
    command(["unpack_bootimg", "--boot_img", CLASSIC / "boot_custom.img", "--out", output / "boot"])
    kernel = (output / "boot/kernel").read_bytes()
    versions = re.findall(rb"Linux version ([0-9]+\.[0-9]+\.[^ \0\n]+)", kernel)
    if len(set(versions)) != 1:
        raise RuntimeError("Could not unambiguously identify the reference kernel version")
    config = extract_kernel_config(kernel)
    (output / "kernel.config").write_text(config)
    device_manifest = ET.parse(root / "vendor/etc/vintf/manifest.xml").getroot()
    level = device_manifest.get("target-level")
    matrix_path = root / f"system/etc/vintf/compatibility_matrix.{level}.xml"
    matrix = ET.parse(matrix_path).getroot()
    kernel_result = check_kernel_matrix(config, matrix, versions[0].decode())
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(),
              "scope": "offline public-reference HAL XML and embedded kernel config only",
              "candidate_sha256": manifest["artifacts"]["system.img"]["sha256"],
              "vendor_sku_fixture": "parrot", "fcm_level": level,
              "target_tool": "vintf from candidate Android 14, under qemu-aarch64 in a read-only bwrap root",
              "tool_sha256": sha256(root / "system/bin/vintf"),
              "resolved_libraries": dependencies, "hal_checks": hal_checks,
              "static_hal_compatibility": all(hal_checks.values()), "kernel_config": kernel_result,
              "framework_hal_requirements_in_fcm": sum(h.get("optional") != "true" for h in matrix.findall("hal")),
              "full_runtime_vintf_validated": False, "hardware_verified": False,
              "ready_for_flash": False,
              "limitations": ["Full runtime result printed by vintf uses the HOST kernel and is not valid for Classic.",
                              "Framework GSI FCM HAL entries are optional; a positive static result is not proof HALs work.",
                              "Classic reference kernel differs from the historical live device build.",
                              "ODM/APEX live fragments, property selections and kernel runtime still need device capture."]}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"static_hal_compatibility": report["static_hal_compatibility"],
                      "reference_kernel": kernel_result, "ready_for_flash": False}, indent=2))
    return report["static_hal_compatibility"] and kernel_result["passes_checked_requirements"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name in ("debugfs", "readelf", "bwrap", "qemu-aarch64", "unpack_bootimg"):
        if not shutil.which(name):
            parser.error(f"Missing required tool: {name}")
    try:
        passed = check(args.candidate.resolve(), args.output.resolve())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
