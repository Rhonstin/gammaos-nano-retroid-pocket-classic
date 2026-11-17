#!/usr/bin/env python3
"""Read-only ADB evidence collection for the original Pocket Classic port."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROPERTIES = (
    "ro.product.device", "ro.product.vendor.device", "ro.product.odm.device",
    "ro.product.model", "ro.product.vendor.model", "ro.product.manufacturer",
    "ro.board.platform", "ro.hardware", "ro.soc.manufacturer", "ro.soc.model",
    "ro.vendor.retro.name", "ro.config.fan.pwm.max.value",
    "ro.boot.product.vendor.sku", "ro.boot.product.hardware.sku",
    "ro.boot.dtb_idx", "ro.boot.dtbo_idx", "ro.boot.hardware",
    "ro.boot.avb_version", "ro.boot.vbmeta.device_state",
    "ro.product.cpu.abilist", "ro.build.fingerprint", "ro.vendor.build.fingerprint",
    "ro.build.version.sdk", "ro.build.version.release", "ro.vendor.build.version.sdk",
    "ro.vendor.build.security_patch", "ro.build.version.security_patch",
    "ro.vndk.version", "ro.treble.enabled", "ro.boot.slot_suffix",
    "ro.boot.flash.locked", "ro.boot.verifiedbootstate", "ro.boot.dynamic_partitions",
    "ro.surface_flinger.primary_display_orientation", "ro.sf.hwrotation",
    "sys.boot_completed", "init.svc.surfaceflinger", "init.svc.audioserver",
)
PROBES = {
    "kernel.txt": "uname -a; cat /proc/version",
    "kernel-config.txt": "zcat /proc/config.gz",
    "model.txt": "cat /sys/firmware/devicetree/base/model",
    "soc.txt": "for n in /sys/devices/soc0/soc_id /sys/devices/soc0/revision /sys/devices/soc0/machine /sys/devices/soc0/family; do echo \"$n\"; cat \"$n\"; done",
    "input.txt": "getevent -lp",
    "display.txt": "dumpsys display",
    "surfaceflinger.txt": "dumpsys SurfaceFlinger --display-id",
    "audio.txt": "cat /proc/asound/cards; dumpsys media.audio_policy",
    "vintf.txt": "lshal; cat /vendor/etc/vintf/manifest.xml /vendor/etc/vintf/manifest_parrot.xml /vendor/manifest.xml",
    "vintf-runtime.txt": "vintf -v",
    "mounts.txt": "cat /proc/mounts; df -k /data /system /vendor /product /system_ext",
    "partitions.txt": "ls -l /dev/block/by-name /dev/block/bootdevice/by-name /dev/block/mapper; cat /proc/partitions",
    "graphics.txt": "ls -l /dev/dri /dev/kgsl-3d0 /vendor/lib64/egl /vendor/lib64/hw; cat /sys/class/kgsl/kgsl-3d0/gpu_model",
    "power.txt": "for n in /sys/class/power_supply/battery/{capacity,status,temp,voltage_now,current_now} /sys/power/{state,mem_sleep,wakeup_count}; do echo \"$n\"; cat \"$n\"; done; dumpsys power",
    "controls.txt": "for n in /sys/class/leds/*/{brightness,max_brightness} /sys/class/backlight/*/{brightness,max_brightness} /sys/class/gpio5_pwm2/{duty,state,period} /sys/devices/virtual/fan_info/fan_info_data/{duty,state} /sys/devices/platform/odm/odm:mid_custom/{fan,fan_pwm} /sys/class/thermal/thermal_zone*/{type,temp}; do if [ -f \"$n\" ]; then echo \"$n\"; cat \"$n\"; fi; done",
    "vendor-init.txt": "ls /vendor/etc/init; grep -n -i -E 'fan|rpclassic|parrot|performance|thermal|gamepad' /vendor/etc/init/*.rc",
    "selinux.txt": "id; getenforce; ls -Z /dev/input /dev/dri /dev/kgsl-3d0",
}


def run_adb(arguments, serial=None, timeout=25):
    command = ["adb"] + (["-s", serial] if serial else []) + list(arguments)
    return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, check=False)


def parse_devices(output):
    devices = []
    for line in output.splitlines():
        if not line.strip() or line.startswith("List of devices") or line.startswith("*"):
            continue
        fields = line.split()
        if len(fields) >= 2:
            devices.append({"serial": fields[0], "state": fields[1]})
    return devices


def decode_board_id(data):
    # qcom,board-id is a DT property: big-endian 32-bit cells, not host endian.
    if len(data) != 8:
        raise ValueError(f"Expected two board-id cells (8 bytes), got {len(data)}")
    return list(struct.unpack(">II", data))


def assess_identity(properties, board_id, profile):
    issues = []
    names = [properties.get(k, "") for k in
             ("ro.product.device", "ro.product.vendor.device", "ro.product.odm.device")]
    if profile["codename"] not in names:
        issues.append("No product/vendor/odm codename matches parrot")
    if properties.get("ro.treble.enabled") != "true":
        issues.append("Treble support not confirmed")
    if profile["architecture"] not in properties.get("ro.product.cpu.abilist", "").split(","):
        issues.append("ARM64 userspace not confirmed")
    if board_id != profile["board_id"]:
        issues.append(f"Original Classic board-id required: expected {profile['board_id']}, got {board_id}")
    if properties.get("sys.boot_completed") != "1":
        issues.append("Android boot not completed")
    return {"identity_confirmed": not issues, "issues": issues,
            "firmware_compatibility_verified": False, "ready_for_flash": False}


def collect(output, serial=None):
    devices_result = run_adb(["devices", "-l"])
    if devices_result.returncode:
        raise RuntimeError(devices_result.stderr.decode(errors="replace"))
    devices = parse_devices(devices_result.stdout.decode(errors="replace"))
    available = [d for d in devices if d["state"] == "device" and
                 (serial is None or d["serial"] == serial)]
    if len(available) != 1:
        raise RuntimeError(f"Need exactly one authorized ADB device; found {len(available)}. "
                           "Connect Classic in Android, authorize USB debugging, "
                           "or select --serial when multiple devices are connected.")
    serial = available[0]["serial"]
    output.mkdir(parents=True, exist_ok=False)
    report = {"collected_at": datetime.now(timezone.utc).isoformat(),
              "method": "read-only adb; no root escalation, reboot, or partition writes",
              "probes": {}}
    script = "\n".join(f"printf '{p}='; getprop {p}" for p in PROPERTIES)
    result = run_adb(["shell", script], serial)
    if result.returncode:
        raise RuntimeError("Failed to read Android properties")
    properties = dict(line.split("=", 1) for line in result.stdout.decode(errors="replace").splitlines()
                      if "=" in line)
    (output / "properties.json").write_text(json.dumps(properties, indent=2) + "\n")
    board_id = None
    for path in ("/sys/firmware/devicetree/base/qcom,board-id", "/proc/device-tree/qcom,board-id"):
        result = run_adb(["exec-out", "cat", path], serial)
        if result.returncode == 0:
            (output / "board-id.bin").write_bytes(result.stdout)
            try:
                board_id = decode_board_id(result.stdout)
            except ValueError as error:
                report["board_id_error"] = str(error)
            break
    report["board_id"] = board_id
    profile = json.loads((ROOT / "device/profile.json").read_text())
    report["assessment"] = assess_identity(properties, board_id, profile)
    # Save partial results before slower optional probes, including on interruption.
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    for filename, command in PROBES.items():
        try:
            result = run_adb(["shell", command], serial)
            (output / filename).write_bytes(result.stdout)
            (output / (filename + ".stderr")).write_bytes(result.stderr)
            report["probes"][filename] = {"returncode": result.returncode}
        except subprocess.TimeoutExpired:
            report["probes"][filename] = {"error": "timeout"}
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" /
                        datetime.now(timezone.utc).strftime("device-%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()
    try:
        report = collect(args.output, args.serial)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(report["assessment"], indent=2))
    print(f"Evidence: {args.output}")
    return 0 if report["assessment"]["identity_confirmed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
