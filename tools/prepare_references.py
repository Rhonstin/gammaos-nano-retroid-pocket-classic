#!/usr/bin/env python3
"""Download, verify and extract the public release references without root."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rk_super_range(stream, total_size):
    header = stream.read(102)
    if len(header) != 102 or header[:4] != b"RKFW":
        raise ValueError("Expected Rockchip RKFW container")
    offset, size = struct.unpack_from("<II", header, 0x21)
    if offset < 102 or offset + size > total_size or size < 2048:
        raise ValueError("RKAF range outside RKFW container")
    stream.seek(offset)
    table = stream.read(2048)
    if table[:4] != b"RKAF":
        raise ValueError("Missing embedded RKAF header")
    count = struct.unpack_from("<I", table, 0x88)[0]
    if count < 1 or 0x8c + count * 0x70 > len(table):
        raise ValueError("Invalid RKAF entry count")
    matches = []
    for index in range(count):
        entry = table[0x8c + index * 0x70:0x8c + (index + 1) * 0x70]
        if entry[:32].split(b"\0", 1)[0] != b"super":
            continue
        position, _, allocated, length = struct.unpack_from("<IIII", entry, 96)
        if not length or length > allocated or position < 2048 or position + allocated > size:
            raise ValueError("Invalid super entry range")
        matches.append((offset + position, length))
    if len(matches) != 1:
        raise ValueError("Expected exactly one super entry")
    return matches[0]


def prepare(download=False):
    releases = json.loads((ROOT / "release-inputs.json").read_text())
    for asset in releases:
        archive = ROOT / "downloads" / asset["name"]
        if not archive.exists():
            if not download:
                raise RuntimeError(f"Missing {archive}; use --download")
            archive.parent.mkdir(parents=True, exist_ok=True)
            partial = archive.with_name(archive.name + ".partial")
            with urlopen(asset["browser_download_url"], timeout=120) as response, partial.open("wb") as target:
                while block := response.read(4 * 1024 ** 2):
                    target.write(block)
            if partial.stat().st_size != asset["size"] or "sha256:" + digest(partial) != asset["digest"]:
                raise RuntimeError(f"Download integrity mismatch: {partial}")
            partial.replace(archive)
        if archive.stat().st_size != asset["size"] or "sha256:" + digest(archive) != asset["digest"]:
            raise RuntimeError(f"Archive integrity mismatch: {archive}")
        is_gkd = asset["tag"] == "v1.4.1-GKD350HULTRA"
        destination = ROOT / "out" / ("reference-gkd" if is_gkd else "reference-classic")
        destination.mkdir(parents=True, exist_ok=True)
        # -aos keeps already extracted files; the content lock below validates them.
        subprocess.run(["7z", "x", "-aos", "-p" + asset["public_archive_password"],
                        "-o" + str(destination), str(archive)], check=True)
        if is_gkd:
            firmware = destination / "GKD_350H_Ultra_GammaOS_Nano_v1.4.1.img"
            super_image = destination / "super.img"
            if not super_image.exists():
                with firmware.open("rb") as stream:
                    offset, size = rk_super_range(stream, firmware.stat().st_size)
                    stream.seek(offset)
                    partial = super_image.with_suffix(".partial")
                    with partial.open("wb") as target:
                        remaining = size
                        while remaining:
                            block = stream.read(min(remaining, 8 * 1024 ** 2))
                            if not block:
                                raise RuntimeError("Unexpected end of RKFW super entry")
                            target.write(block)
                            remaining -= len(block)
                    partial.replace(super_image)
            partitions = destination / "partitions"
            partitions.mkdir(exist_ok=True)
            if not (partitions / "system.img").exists():
                subprocess.run(["lpunpack", "-p", "system", str(super_image), str(partitions)], check=True)
    inputs = json.loads((ROOT / "artifact-inputs.json").read_text())
    for name, info in inputs.items():
        path = ROOT / name
        if path.stat().st_size != info["size"] or digest(path) != info["sha256"]:
            raise RuntimeError(f"Extracted image integrity mismatch: {path}")
    print(f"Verified {len(inputs)} extracted reference images.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    prepare(parser.parse_args().download)
