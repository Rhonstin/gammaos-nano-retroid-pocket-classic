#!/usr/bin/env python3
"""Prepare a Classic vendor ramdisk for Nano's integrated product/system_ext.

Retains the connected console's stock DTB, modules, bootconfig and boot kernel.
Only removes the two separate logical mounts; Nano supplies both inside system.
"""
import argparse
import ctypes
import hashlib
import json
import re
from pathlib import Path
import shlex
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAGIC = bytes.fromhex("02214c18")


def lz4_legacy(data, compress=False):
    lib = ctypes.CDLL("liblz4.so.1")
    output = bytearray(MAGIC if compress else b"")
    if compress:
        lib.LZ4_compressBound.argtypes = [ctypes.c_int]
        lib.LZ4_compress_default.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        for pos in range(0, len(data), 8 * 1024 * 1024):
            block = data[pos:pos + 8 * 1024 * 1024]
            dest = ctypes.create_string_buffer(lib.LZ4_compressBound(len(block)))
            size = lib.LZ4_compress_default(block, dest, len(block), len(dest))
            if size <= 0:
                raise ValueError("LZ4 compression failed")
            output += struct.pack("<I", size) + dest.raw[:size]
    else:
        if data[:4] != MAGIC:
            raise ValueError("Expected legacy LZ4 ramdisk")
        lib.LZ4_decompress_safe.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        pos = 4
        while pos < len(data):
            size, = struct.unpack_from("<I", data, pos)
            pos += 4
            if not size:
                break
            block = data[pos:pos + size]
            if len(block) != size:
                raise ValueError("Truncated LZ4 block")
            pos += size
            dest = ctypes.create_string_buffer(8 * 1024 * 1024)
            count = lib.LZ4_decompress_safe(block, dest, size, len(dest))
            if count < 0:
                raise ValueError("Invalid LZ4 block")
            output += dest.raw[:count]
    return bytes(output)


def cpio_entries(data):
    pos = 0
    while True:
        header = data[pos:pos + 110]
        if header[:6] != b"070701":
            raise ValueError("Expected newc CPIO")
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        pos += 110
        name = data[pos:pos + fields[11] - 1].decode()
        pos = (pos + fields[11] + 3) & ~3
        body = data[pos:pos + fields[6]]
        if len(body) != fields[6]:
            raise ValueError("Truncated CPIO file")
        pos = (pos + fields[6] + 3) & ~3
        yield name, fields, body
        if name == "TRAILER!!!":
            break


def pack_cpio(entries):
    result = bytearray()
    for name, original_fields, body in entries:
        fields = list(original_fields)
        fields[6] = len(body)
        encoded = name.encode() + b"\0"
        fields[11] = len(encoded)
        result += b"070701" + b"".join(f"{value:08x}".encode() for value in fields)
        result += encoded
        result += b"\0" * (-len(result) % 4)
        result += body
        result += b"\0" * (-len(result) % 4)
    result += b"\0" * (-len(result) % 512)
    return bytes(result)


def patch_fstab(body):
    lines = body.decode().splitlines(keepends=True)
    removed = [line.split()[0] for line in lines
               if line.split() and line.split()[0] in ("product", "system_ext")]
    if sorted(removed) != ["product", "system_ext"]:
        raise ValueError("Unexpected stock logical mount layout")
    return "".join(line for line in lines if not line.split()
                   or line.split()[0] not in ("product", "system_ext")).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-boot", type=Path, required=True, help="Your own verified vendor_boot_a backup")
    parser.add_argument("--vendor-boot-sha256", required=True, help="SHA256 recorded when making that backup")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    stock = args.vendor_boot.resolve()
    expected = args.vendor_boot_sha256.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Expected a complete SHA256 for your vendor_boot backup")
    if hashlib.sha256(stock.read_bytes()).hexdigest() != expected:
        raise ValueError("Stock vendor_boot backup integrity mismatch")
    unpack = output / "stock"
    args_text = subprocess.check_output(["unpack_bootimg", "--boot_img", str(stock),
                                        "--out", str(unpack), "--format=mkbootimg"], text=True)
    boot_args = shlex.split(args_text)
    ramdisk = unpack / "vendor_ramdisk00"
    original = list(cpio_entries(lz4_legacy(ramdisk.read_bytes())))
    changed = []
    patched = []
    for name, fields, body in original:
        if name in ("first_stage_ramdisk/fstab.default", "first_stage_ramdisk/fstab.emmc"):
            body = patch_fstab(body)
            fields[6] = len(body)
            changed.append(name)
            (output / (Path(name).name + ".patched")).write_bytes(body)
        patched.append((name, fields, body))
    if len(changed) != 2:
        raise ValueError("Missing first-stage fstab files")
    compressed = lz4_legacy(pack_cpio(patched), compress=True)
    decoded = list(cpio_entries(lz4_legacy(compressed)))
    if decoded != patched:
        raise ValueError("Ramdisk roundtrip failed")
    replacement = output / "vendor_ramdisk.lz4"
    replacement.write_bytes(compressed)
    boot_args[boot_args.index("--vendor_ramdisk_fragment") + 1] = str(replacement)
    image = output / "vendor_boot.img"
    subprocess.run(["mkbootimg", *boot_args, "--vendor_boot", str(image)], check=True)
    if image.stat().st_size > stock.stat().st_size:
        raise ValueError("vendor_boot exceeds original partition")
    verify = output / "verify"
    subprocess.run(["unpack_bootimg", "--boot_img", str(image), "--out", str(verify)],
                   check=True, stdout=subprocess.DEVNULL)
    for name in ("dtb", "bootconfig"):
        if (unpack / name).read_bytes() != (verify / name).read_bytes():
            raise ValueError(f"Stock {name} changed")
    if list(cpio_entries(lz4_legacy((verify / "vendor_ramdisk00").read_bytes()))) != patched:
        raise ValueError("Final vendor_boot ramdisk differs")
    for name in ("vbmeta", "vbmeta_system"):
        subprocess.run(["avbtool", "make_vbmeta_image", "--flags", "3", "--padding_size", "65536",
                        "--output", str(output / (name + ".img"))], check=True)
    artifacts = {p.name: {"size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                 for p in (image, output / "vbmeta.img", output / "vbmeta_system.img")}
    (output / "manifest.json").write_text(json.dumps({"stock_vendor_boot_sha256": expected,
        "changed_ramdisk_entries": changed, "kernel_changed": False,
        "stock_dtb_and_bootconfig_verified": True, "avb_flags": 3, "artifacts": artifacts}, indent=2) + "\n")
    print(json.dumps(artifacts, indent=2))


if __name__ == "__main__":
    main()
