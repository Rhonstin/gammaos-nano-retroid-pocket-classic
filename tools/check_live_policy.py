#!/usr/bin/env python3
"""Compile the proposed CIL with the actual vendor inputs without loading it."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import shlex
import struct

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--serial',required=True)
parser.add_argument('--candidate',type=Path)
parser.add_argument('--output',type=Path,default=ROOT/'evidence/permanent-validation/policy-compile')
options=parser.parse_args()
ADB=['adb','-s',options.serial]
out=options.output
out.mkdir(parents=True,exist_ok=True)
remote='/data/local/tmp/classic-policy-validation'
def shell(command):
    return subprocess.run(ADB+['shell',command],capture_output=True,check=True).stdout
shell('mkdir -p '+remote)
patch=ROOT/'device/classic-policy.cil'
subprocess.run(ADB+['push',str(patch),remote+'/classic-policy.cil'],check=True)
if options.candidate:
    data=subprocess.check_output(['debugfs','-R','cat /system/etc/selinux/plat_sepolicy.cil',str(options.candidate/'system.img')],stderr=subprocess.DEVNULL)
    (out/'candidate-plat.cil').write_bytes(data)
    subprocess.run(ADB+['push',str(out/'candidate-plat.cil'),remote+'/candidate-plat.cil'],check=True)
version=shell('cat /vendor/etc/selinux/plat_sepolicy_vers.txt').decode().strip()
policy=shell('cat /sys/fs/selinux/policy')
identifier_size,=struct.unpack_from('<I',policy,4)
binary_version,=struct.unpack_from('<I',policy,8+identifier_size)
paths=['/system/etc/selinux/plat_sepolicy.cil',
       f'/system/etc/selinux/mapping/{version}.cil',f'/system/etc/selinux/mapping/{version}.compat.cil',
       '/system_ext/etc/selinux/system_ext_sepolicy.cil',
       f'/system_ext/etc/selinux/mapping/{version}.cil',f'/system_ext/etc/selinux/mapping/{version}.compat.cil',
       '/product/etc/selinux/product_sepolicy.cil',f'/product/etc/selinux/mapping/{version}.cil',
       '/vendor/etc/selinux/plat_pub_versioned.cil','/vendor/etc/selinux/vendor_sepolicy.cil',
       '/odm/etc/selinux/odm_sepolicy.cil']
present=[]
for path in paths:
    if shell('if [ -r '+path+' ]; then echo present; fi').strip():present.append(path)
results=[]
for mode in ['baseline','classic']:
    target=remote+'/'+mode+'.policy'
    args=['/system/bin/secilc',present[0],'-m','-M','true','-G','-N','-c',str(binary_version),
          '-o',target,'-f','/dev/null',*present[1:]]
    if mode=='classic':
        if options.candidate:args[1]=remote+'/candidate-plat.cil'
        else:args.append(remote+'/classic-policy.cil')
    r=subprocess.run(ADB+['shell',shlex.join(args)],capture_output=True)
    (out/(mode+'.log')).write_bytes(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError('CIL compilation failed: '+mode)
    data=shell('cat '+target)
    (out/(mode+'.policy')).write_bytes(data)
    results.append({'mode':mode,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
(out/'report.json').write_text(json.dumps({'policy_version':binary_version,'vendor_mapping':version,
    'inputs':present,'patch_sha256':hashlib.sha256(patch.read_bytes()).hexdigest(),'results':results},indent=2)+'\n')
print(json.dumps(results,indent=2))
