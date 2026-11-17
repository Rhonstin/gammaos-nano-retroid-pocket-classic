#!/usr/bin/env python3
"""Fetch the pinned source subset, verifying Git blob hashes before writing."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def blob_hash(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def fetch(entry, lock):
    relative = Path(entry["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe source path: {relative}")
    target = ROOT / "upstream" / relative
    if target.is_file() and blob_hash(target.read_bytes()) == entry["git_blob"]:
        return "cached"
    repo = lock["repository"].removeprefix("https://github.com/")
    url = f"https://raw.githubusercontent.com/{repo}/{lock['commit']}/{relative.as_posix()}"
    for attempt in range(4):
        try:
            with urlopen(url, timeout=60) as response:
                data = response.read()
            if len(data) != entry["size"] or blob_hash(data) != entry["git_blob"]:
                raise ValueError(f"Source integrity mismatch: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".partial")
            temporary.write_bytes(data)
            temporary.replace(target)
            return "downloaded"
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=12, choices=range(1, 33))
    args = parser.parse_args()
    lock = json.loads((ROOT / "upstream.lock.json").read_text())
    counts = {"downloaded": 0, "cached": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        pending = {executor.submit(fetch, item, lock): item["path"] for item in lock["files"]}
        for index, future in enumerate(as_completed(pending), 1):
            try:
                counts[future.result()] += 1
            except Exception as error:
                counts["failed"] += 1
                print(f"FAILED {pending[future]}: {error}", flush=True)
            if index % 100 == 0:
                print(f"{index}/{len(pending)} {counts}", flush=True)
    print(json.dumps(counts), flush=True)
    return bool(counts["failed"])


if __name__ == "__main__":
    raise SystemExit(main())
