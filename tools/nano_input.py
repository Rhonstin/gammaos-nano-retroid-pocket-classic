#!/usr/bin/env python3
"""Send test inputs through Nano's actual evdev gamepad path."""
import argparse
import shlex
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
parser.add_argument("keys", nargs="+")
args = parser.parse_args()
adb = ["adb", "-s", args.serial]
inventory = subprocess.check_output(adb + ["shell", "for n in /sys/class/input/event*/device/name; do echo \"$n:$(cat \"$n\")\"; done"], text=True)
nodes = [line.split("/")[4] for line in inventory.splitlines()
         if line.endswith(":Xbox Wireless Controller")]
if len(nodes) != 1:
    raise SystemExit("Expected one GammaPad Xbox Wireless Controller")
device = "/dev/input/" + nodes[0]
buttons = {"a": (1, 304, 1), "b": (1, 305, 1), "x": (1, 307, 1),
           "y": (1, 308, 1), "start": (1, 315, 1), "select": (1, 314, 1),
           "up": (3, 17, -1), "down": (3, 17, 1),
           "left": (3, 16, -1), "right": (3, 16, 1)}
buttons["power_hold"] = (1, 116, 1)
buttons.update({"l1": (1, 310, 1), "r1": (1, 311, 1),
                "l2": (1, 312, 1), "r2": (1, 313, 1)})
commands = []
for key in args.keys:
    name, _, repetitions = key.partition(":")
    event, code, value = buttons[name]
    target = device
    hold = "0.06"
    if name == "power_hold":
        power_nodes = [line.split("/")[4] for line in inventory.splitlines()
                       if line.endswith(":pmic_pwrkey")]
        if len(power_nodes) != 1:
            raise SystemExit("Expected one physical pmic_pwrkey")
        target = "/dev/input/" + power_nodes[0]
        hold = "1"
    for _ in range(int(repetitions or "1")):
        commands.extend([f"sendevent {target} {event} {code} {value}",
                         f"sendevent {target} 0 0 0", "sleep " + hold,
                         f"sendevent {target} {event} {code} 0",
                         f"sendevent {target} 0 0 0", "sleep 0.16"])
subprocess.run(adb + ["shell", "\n".join(commands)], check=True)
time.sleep(0.6)
