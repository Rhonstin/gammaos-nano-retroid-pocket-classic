#!/usr/bin/env python3
"""Run a local script through the connected Classic's stock root service."""
import argparse
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def execute(script, serial, timeout=3600):
    token = uuid.uuid4().hex
    remote = f"/data/local/tmp/classic-{token}.sh"
    request = f"/data/local/tmp/classic-{token}.request"
    log_path = f"/data/local/tmp/classic-{token}.log"
    exit_path = f"/data/local/tmp/classic-{token}.exit"
    helper = ROOT / "out/android-helper/classicroot.jar"
    def adb(args, **kwargs):
        return subprocess.run(["adb", "-s", serial] + args, check=True, **kwargs)
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "request.txt"
        path.write_text(f"/system/bin/sh {remote}")
        wrapper = Path(temporary) / "run.sh"
        wrapper.write_text("#!/system/bin/sh\n(\n" + script.read_text() +
                           f"\n) >{log_path} 2>&1\nresult=$?\nchmod 644 {log_path}\n"
                           f"echo $result >{exit_path}\nchmod 644 {exit_path}\n")
        adb(["push", str(helper), "/data/local/tmp/classicroot.jar"], stdout=subprocess.DEVNULL)
        adb(["push", str(wrapper), remote], stdout=subprocess.DEVNULL)
        adb(["push", str(path), request], stdout=subprocess.DEVNULL)
        try:
            result = adb(["shell", "CLASSPATH=/data/local/tmp/classicroot.jar app_process /system/bin ClassicRoot " + shlex.quote(request)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            deadline = time.monotonic() + timeout
            code = b""
            while time.monotonic() < deadline:
                status = subprocess.run(["adb", "-s", serial, "shell", "cat", exit_path],
                                        capture_output=True, check=False)
                if status.returncode == 0 and status.stdout.strip().isdigit():
                    code = status.stdout.strip()
                    break
                time.sleep(0.5)
            output = adb(["exec-out", "cat", log_path], stdout=subprocess.PIPE).stdout
            sys.stdout.buffer.write(output)
            sys.stderr.buffer.write(result.stderr)
            sys.stdout.flush()
            if not code:
                raise RuntimeError("No verified root-command exit file")
            return int(code)
        finally:
            adb(["shell", "rm", "-f", remote, request, log_path, exit_path], stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("script", type=Path)
    args = parser.parse_args()
    raise SystemExit(execute(args.script, args.serial))
