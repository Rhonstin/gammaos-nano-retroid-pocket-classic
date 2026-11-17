#!/usr/bin/env python3
"""Update or roll back the Nano system image, preserving userdata and bootloader.

Default validates the image and connected original Classic and prints the plan.
--execute enters stock fastbootd, flashes only system_a, then reboots.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--raw',action='store_true',
                        help='Flash system.img directly; compare its SHA-256 with the partition after boot')
    recovery=parser.add_mutually_exclusive_group()
    recovery.add_argument('--resume-plan',type=Path,
                        help='Resume an interrupted system update from its saved plan while already in fastbootd')
    recovery.add_argument('--fastbootd-plan',type=Path,
                          help='Update from fastbootd using the device identity recorded by a previous successful system update')
    options=parser.parse_args()
    candidate=options.candidate.resolve()
    manifest=json.loads((candidate/'manifest.json').read_text())
    if manifest['status'].startswith('rejected'):
        raise ValueError('The selected image has a recorded defect')
    image=candidate/('system.img' if options.raw else 'system.sparse.img')
    with image.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    expected=manifest['artifacts'][image.name]
    if image.stat().st_size!=expected['size'] or digest!=expected['sha256']:
        raise ValueError('System image integrity mismatch')
    adb=['adb','-s',options.serial]
    def shell(command):return subprocess.check_output(adb+['shell',command],timeout=15)
    size=manifest['system_partition_bytes']
    commands=[['resize-logical-partition','system_a',str(size)],['flash','system_a',str(image)]]
    if options.fastbootd_plan:
        previous=json.loads(options.fastbootd_plan.read_text())
        if (previous.get('serial')!=options.serial or previous.get('board_id')!=[34,0]
                or previous.get('erases_userdata') is not False
                or not re.fullmatch('[0-9a-f]{64}',previous.get('system_image_sha256',''))
                or not any(c[:2]==['flash','system_a'] for c in previous.get('completed',[]))):
            raise ValueError('Fastbootd identity plan is not a successful update of this original Classic')
        version='unavailable-in-fastbootd'
    elif options.resume_plan:
        previous=json.loads(options.resume_plan.read_text())
        # Use only the exact image and device whose ADB identity was recorded
        # before the interrupted operation; never execute commands from the file.
        if (previous.get('serial')!=options.serial or previous.get('board_id')!=[34,0]
                or previous.get('system_image_sha256')!=digest
                or previous.get('erases_userdata') is not False
                or previous.get('commands')!=commands
                or commands[0] not in previous.get('completed',[])):
            raise ValueError('Resume plan does not match this interrupted device/image update')
        version=previous['previous_version']
    else:
        board=subprocess.check_output(adb+['exec-out','cat','/sys/firmware/devicetree/base/qcom,board-id'],timeout=10)
        if board!=bytes.fromhex('0000002200000000'):
            raise ValueError('Requires original four-button Classic board <0x22 0>')
        device=shell('getprop ro.product.vendor.device').decode().strip()
        version=shell('getprop ro.gammaos.port.version').decode().strip()
        slot=shell('getprop ro.boot.slot_suffix').decode().strip()
        if device!='parrot' or slot!='_a' or not version.startswith('1.4.1-'):
            raise ValueError('Not the currently supported permanent Nano installation')
        if shell('getprop ro.gsid.image_running').strip()==b'1':
            raise ValueError('Disable DSU before updating the permanent OS')
        # Existing incremental packages need normal reinstallation in full Android,
        # where this release initializes ART and can remove their old artifacts.
        if shell('find /data/incremental -mindepth 1 -maxdepth 1 -type d 2>/dev/null').strip():
            raise ValueError('Reinstall incremental APKs with adb install --no-incremental -r in full Android before updating')
    plan={'serial':options.serial,'board_id':[34,0],'previous_version':version,
          'system_image_sha256':digest,'erases_userdata':False,'commands':commands,'completed':[]}
    if options.resume_plan:plan['resumes']=str(options.resume_plan.resolve())
    if options.fastbootd_plan:plan['verified_device_plan']=str(options.fastbootd_plan.resolve())
    if not options.execute:
        print(json.dumps(plan,indent=2));return
    logdir=ROOT/'evidence/updates'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    logdir.mkdir(parents=True,exist_ok=False)
    planfile=logdir/'plan.json';planfile.write_text(json.dumps(plan,indent=2)+'\n')
    if not (options.resume_plan or options.fastbootd_plan):
        subprocess.run(adb+['reboot','fastboot'],check=True,timeout=15)
    fastboot=['fastboot','-s',options.serial]
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        devices=subprocess.check_output(['fastboot','devices'],text=True)
        if any(line.split()[0]==options.serial for line in devices.splitlines() if line.split()):break
        time.sleep(1)
    else:raise RuntimeError('fastbootd did not appear; no image was written')
    inventory=subprocess.run(fastboot+['getvar','all'],capture_output=True,text=True,check=True,timeout=15)
    text=inventory.stdout+inventory.stderr;(logdir/'fastbootd.txt').write_text(text)
    values=dict(re.findall(r'^\(bootloader\) ([^\n]+):([^\n]*)$',text,re.M))
    for key,want in {'serialno':options.serial,'product':'parrot','is-userspace':'yes',
                     'unlocked':'yes','current-slot':'a','snapshot-update-status':'none'}.items():
        if values.get(key)!=want:raise ValueError('Unexpected fastbootd '+key)
    if int(values['partition-size:super'],16)!=6442450944:
        raise ValueError('Unexpected super size')
    with (logdir/'flash.log').open('w') as log:
        for command in commands:
            log.write('$ fastboot '+' '.join(command)+'\n');log.flush()
            subprocess.run(fastboot+command,stdout=log,stderr=log,check=True,timeout=300)
            plan['completed'].append(command);planfile.write_text(json.dumps(plan,indent=2)+'\n')
        subprocess.run(fastboot+['reboot'],stdout=log,stderr=log,check=True,timeout=15)
    print('System update flashed; userdata retained. Logs: '+str(logdir))

if __name__=='__main__':main()
