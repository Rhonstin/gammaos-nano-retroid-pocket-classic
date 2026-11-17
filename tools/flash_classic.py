#!/usr/bin/env python3
"""Install the prepared development image through stock fastbootd.

Default prints the concrete plan. --execute performs it, including data erasure.
The original four-button Classic must already have been identified over ADB.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--system", type=Path, required=True, help="Candidate directory")
    parser.add_argument("--boot", type=Path, required=True, help="Prepared vendor_boot directory")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    system = args.system.resolve()
    boot = args.boot.resolve()
    for directory, names in ((system, ("system.sparse.img",)),
                             (boot, ("vendor_boot.img", "vbmeta.img", "vbmeta_system.img"))):
        manifest = json.loads((directory / "manifest.json").read_text())
        for name in names:
            path = directory / name
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if path.stat().st_size != manifest["artifacts"][name]["size"] or digest != manifest["artifacts"][name]["sha256"]:
                raise ValueError(f"Artifact integrity mismatch: {path}")
    info = subprocess.run(["fastboot", "-s", args.serial, "getvar", "all"],
                          capture_output=True, text=True, check=True)
    inventory = info.stdout + info.stderr
    variables = dict(re.findall(r"^\(bootloader\) ([^\n]+):([^\n]*)$", inventory, re.M))
    for key, value in {"serialno": args.serial, "product": "parrot", "unlocked": "yes",
                       "is-userspace": "yes", "current-slot": "a", "snapshot-update-status": "none"}.items():
        if variables.get(key) != value:
            raise ValueError(f"Unexpected fastbootd {key}: {variables.get(key)!r}")
    if int(variables["partition-size:super"], 16) != 6442450944:
        raise ValueError("Unexpected super partition size")
    size = json.loads((system / "manifest.json").read_text())["system_partition_bytes"]
    commands = []
    for partition in ("odm_a-cow", "product_a-cow", "system_a-cow", "product_a", "system_ext_a"):
        if f"partition-size:{partition}" in variables:
            commands.append(["delete-logical-partition", partition])
    commands += [["resize-logical-partition", "system_a", str(size)],
                 ["flash", "system_a", str(system / "system.sparse.img")],
                 ["flash", "vendor_boot_a", str(boot / "vendor_boot.img")],
                 ["flash", "vbmeta_a", str(boot / "vbmeta.img")],
                 ["flash", "vbmeta_system_a", str(boot / "vbmeta_system.img")],
                 ["erase", "userdata"], ["erase", "metadata"]]
    plan = {"serial": args.serial, "created_at": datetime.now(timezone.utc).isoformat(),
            "erases_all_userdata": True, "commands": commands, "completed": []}
    logdir = ROOT / "evidence/permanent-install"
    logdir.mkdir(parents=True, exist_ok=True)
    planfile = logdir / "plan.json"
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return
    if planfile.exists():
        raise ValueError("An installation log already exists; review it before another installation")
    (logdir / "fastbootd-before.txt").write_text(inventory)
    planfile.write_text(json.dumps(plan, indent=2) + "\n")
    with (logdir / "flash.log").open("w") as log:
        for command in commands:
            log.write("$ fastboot " + " ".join(command) + "\n")
            log.flush()
            subprocess.run(["fastboot", "-s", args.serial, *command],
                           stdout=log, stderr=log, check=True, timeout=300)
            plan["completed"].append(command)
            planfile.write_text(json.dumps(plan, indent=2) + "\n")
            print("Completed: " + " ".join(command[:2]), flush=True)
    print("Flashed successfully. Inspect the log, then reboot explicitly.")


if __name__ == "__main__":
    main()
