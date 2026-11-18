#!/usr/bin/env python3
"""Rebuild GammaOS' RetroArch first-boot payload with the cores and assets pinned in apps.lock.json.

The upstream archive (retroarch.tar.xz, extracted by setup.sh to / after the APK install)
carries RetroArch's app data, configuration and GammaOS-specific shaders. This tool streams
it member by member and:
  * replaces each libretro core that apps.lock.json pins (cores it does not pin stay stock);
  * overlays the pinned frontend archives (assets, android autoconfig, rdb databases, info,
    overlays, GLSL and slang shaders) onto their directories: changed files are replaced,
    new files are added, and nothing absent from an archive is removed, so GammaOS' own
    presets (Sharp-Shimmerless, gammaScale) and configuration stay intact.
Every added member inherits owner, group and permission bits from the original tree.
Output is a single xz stream with the same -6 preset and CRC64 check as the source.
"""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP = "data/data/com.retroarch.aarch64"
# zip archive -> (directory inside the payload, only this top-level folder of the zip or None)
ASSET_TARGETS = {
    "assets.zip": (APP + "/assets", None),
    "autoconfig.zip": (APP + "/autoconfig", "android"),
    "database-rdb.zip": (APP + "/database/rdb", None),
    "info.zip": (APP + "/info", None),
    "overlays.zip": (APP + "/overlays", None),
    "shaders_glsl.zip": (APP + "/shaders/shaders_glsl", None),
    "shaders_slang.zip": (APP + "/shaders/shaders_slang", None),
}


def sha256_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_member(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise RuntimeError(f"Unsafe archive member name: {name}")
    return str(path)


def planned_files(lock, cache):
    """Return {payload path: (zip path, member)} for every pinned replacement file."""
    payload = lock["retroarch_payload"]
    plan = {}
    for entry in payload["cores"] + payload["assets"]:
        archive = cache / entry["file"]
        if archive.stat().st_size != entry["size"] or sha256_file(archive) != entry["sha256"]:
            raise RuntimeError(f"Unverified payload input: {entry['file']}; run tools/prepare_apps.py --download")
    for entry in payload["cores"]:
        archive = cache / entry["file"]
        name = Path(entry["file"]).name[:-len(".zip")]
        with zipfile.ZipFile(archive) as bundle:
            if bundle.namelist() != [name]:
                raise RuntimeError(f"Unexpected core archive layout: {entry['file']}")
        plan[f"{APP}/cores/{name}"] = (archive, name)
    for entry in payload["assets"]:
        archive = cache / entry["file"]
        target, folder = ASSET_TARGETS[Path(entry["file"]).name]
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if info.is_dir():
                    continue
                member = safe_member(info.filename)
                if folder is not None:
                    if not member.startswith(folder + "/"):
                        continue
                plan[f"{target}/{member}"] = (archive, info.filename)
    return plan


def build(source, output, lock, cache):
    plan = planned_files(lock, cache)
    pending = dict(plan)
    zips = {}

    def payload_bytes(path):
        archive, member = plan[path]
        bundle = zips.get(archive) or zips.setdefault(archive, zipfile.ZipFile(archive))
        return bundle.read(member)

    reader = subprocess.Popen(["xz", "-dc", str(source)], stdout=subprocess.PIPE)
    with output.open("wb") as sink:
        writer = subprocess.Popen(["xz", "-6", "-T0", "-C", "crc64", "-c"],
                                  stdin=subprocess.PIPE, stdout=sink)
        templates = {}            # directory -> (dir member, a file member inside it)
        directories = set()
        stats = {"replaced": 0, "added": 0, "kept": 0}
        with tarfile.open(fileobj=reader.stdout, mode="r|") as original, \
                tarfile.open(fileobj=writer.stdin, mode="w|", format=tarfile.GNU_FORMAT) as rebuilt:
            for member in original:
                name = member.name.rstrip("/")
                parent = str(PurePosixPath(name).parent)
                if member.isdir():
                    directories.add(name)
                    templates.setdefault(name, [member, None])
                    rebuilt.addfile(member)
                    continue
                if member.isfile():
                    if parent in templates and templates[parent][1] is None:
                        templates[parent][1] = member
                    if name in pending:
                        data = payload_bytes(name)
                        del pending[name]
                        replacement = copy.copy(member)
                        replacement.size = len(data)
                        rebuilt.addfile(replacement, io.BytesIO(data))
                        stats["replaced"] += 1
                        continue
                    rebuilt.addfile(member, original.extractfile(member))
                else:
                    rebuilt.addfile(member)
                stats["kept"] += 1

            def nearest(path):
                probe = PurePosixPath(path)
                while str(probe) not in templates:
                    probe = probe.parent
                    if str(probe) in (".", ""):
                        raise RuntimeError(f"No template directory for {path}")
                return templates[str(probe)]

            for name in sorted(pending):
                parents = list(PurePosixPath(name).parents)[::-1]
                for directory in parents:
                    directory = str(directory)
                    # Ancestors of the app tree are not archive members; tar creates them.
                    if not directory.startswith(APP + "/") or directory in directories:
                        continue
                    dir_template = nearest(directory)[0]
                    created = copy.copy(dir_template)
                    created.name = directory
                    rebuilt.addfile(created)
                    directories.add(directory)
                    templates[directory] = [created, None]
                dir_template, file_template = nearest(str(PurePosixPath(name).parent))
                data = payload_bytes(name)
                added = copy.copy(file_template or dir_template)
                added.type = tarfile.REGTYPE
                added.name = name
                added.size = len(data)
                added.mode = (file_template.mode if file_template else dir_template.mode & 0o666)
                if name.endswith(".so"):
                    added.mode |= 0o500 & dir_template.mode
                rebuilt.addfile(added, io.BytesIO(data))
                stats["added"] += 1
        writer.stdin.close()
        if writer.wait() != 0:
            raise RuntimeError("xz compression failed")
    reader.stdout.close()
    if reader.wait() != 0:
        raise RuntimeError("xz decompression of the original payload failed")
    for bundle in zips.values():
        bundle.close()
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Original retroarch.tar.xz from the base image")
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    lock = json.loads((ROOT / "apps.lock.json").read_text())
    try:
        stats = build(options.source, options.output, lock, ROOT / "downloads/apps")
    except (OSError, RuntimeError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
