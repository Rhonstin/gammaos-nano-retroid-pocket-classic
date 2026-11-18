#!/usr/bin/env python3
"""Pin, download and verify the applications and RetroArch payload integrated by dev.26+.

`apps.lock.json` is the only source of truth for the build. `--download` fetches a missing
or damaged cache entry and refuses any byte that does not match the lock. `--update-lock`
is a maintainer operation: it resolves the RetroArch nightly core and asset sets that the
lock names, downloads them once and records their sizes and SHA-256 digests.
Downloads live in downloads/apps (outside Git); nothing is installed on a device here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "apps.lock.json"
CACHE = ROOT / "downloads/apps"
AGENT = "gammaos-classic-port-prepare/1"
BUILDBOT = "https://buildbot.libretro.com"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                shutil.copyfileobj(response, temporary, 1024 * 1024)
        except BaseException:
            Path(temporary.name).unlink(missing_ok=True)
            raise
    Path(temporary.name).replace(target)


def verified(entry):
    path = CACHE / entry["file"]
    return path.is_file() and path.stat().st_size == entry["size"] and sha256(path) == entry["sha256"]


def entries(lock):
    yield from lock["apps"]
    yield from lock.get("files", [])
    payload = lock["retroarch_payload"]
    yield from payload["cores"]
    yield from payload["assets"]


def download(lock):
    failures = []
    for entry in entries(lock):
        if verified(entry):
            continue
        path = CACHE / entry["file"]
        print(f"download {entry['file']}", flush=True)
        try:
            fetch(entry["url"], path)
        except OSError as error:
            failures.append(f"{entry['file']}: {error}")
            continue
        if not verified(entry):
            path.rename(path.with_name(path.name + ".rejected"))
            failures.append(f"{entry['file']}: size/SHA-256 differs from apps.lock.json")
    if failures:
        raise RuntimeError("Inputs not verified:\n  " + "\n  ".join(failures))
    print("All application inputs verified")


def listing(url):
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode(errors="replace")


def pin(url, name):
    path = CACHE / name
    fetch(url, path)
    return {"file": name, "url": url, "size": path.stat().st_size, "sha256": sha256(path)}


def update_lock(lock):
    """Re-pin the nightly libretro cores (same set as before) and frontend asset archives."""
    payload = lock["retroarch_payload"]
    available = set(re.findall(r"([a-z0-9_]+_libretro_android\.so\.zip)",
                               listing(f"{BUILDBOT}/nightly/android/latest/arm64-v8a/")))
    cores = []
    for name in payload["core_names"]:
        archive = name + ".zip"
        if archive not in available:
            print(f"keep stock {name}: not published for android arm64-v8a")
            continue
        print(f"pin {archive}", flush=True)
        cores.append(pin(f"{BUILDBOT}/nightly/android/latest/arm64-v8a/{archive}", "cores/" + archive))
    assets = []
    for name in payload["asset_names"]:
        print(f"pin {name}", flush=True)
        assets.append(pin(f"{BUILDBOT}/assets/frontend/{name}", "assets/" + name))
    payload["cores"], payload["assets"] = cores, assets
    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    print(f"apps.lock.json: {len(cores)} cores, {len(assets)} asset archives")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--download", action="store_true", help="Fetch and verify every locked input")
    mode.add_argument("--verify", action="store_true", help="Verify the local cache without network access")
    mode.add_argument("--update-lock", action="store_true", help="Maintainer: re-pin nightly cores and assets")
    options = parser.parse_args()
    lock = json.loads(LOCK.read_text())
    try:
        if options.update_lock:
            update_lock(lock)
        elif options.download:
            download(lock)
        else:
            bad = [entry["file"] for entry in entries(lock) if not verified(entry)]
            if bad:
                raise RuntimeError("Unverified inputs:\n  " + "\n  ".join(bad))
            print("All application inputs verified")
    except (OSError, RuntimeError, KeyError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
