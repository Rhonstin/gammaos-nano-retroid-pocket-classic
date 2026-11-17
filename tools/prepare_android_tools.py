#!/usr/bin/env python3
"""Verify/download pinned Java-to-DEX tools; optionally prepare the test APK SDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--download',action='store_true')
parser.add_argument('--diagnostics',action='store_true')
options=parser.parse_args()
lock=json.loads((ROOT/'android-tools.lock.json').read_text())
for name,info in lock.items():
    if name!='r8' and not options.diagnostics:continue
    path=ROOT/info['file'];path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        if not options.download:raise SystemExit('Missing '+str(path)+'; pass --download')
        tmp=path.with_suffix(path.suffix+'.part')
        with urllib.request.urlopen(info['url']) as response,tmp.open('wb') as stream:
            while chunk:=response.read(1024*1024):stream.write(chunk)
        tmp.replace(path)
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if path.stat().st_size!=info['size'] or digest!=info['sha256']:
        raise SystemExit('Input integrity mismatch: '+str(path))
    if 'extract_to' in info:
        target=ROOT/info['extract_to'];target.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(target)
            for entry in archive.infolist():
                mode=entry.external_attr>>16
                if mode and not entry.is_dir():os.chmod(target/entry.filename,mode&0o777)
    print('Verified '+name)

helper=ROOT/'out/android-helper/root-build';helper.mkdir(parents=True,exist_ok=True)
subprocess.run(['javac','--release','8','-d',str(helper),str(ROOT/'tools/android/ClassicRoot.java')],check=True)
subprocess.run(['java','-cp',str(ROOT/lock['r8']['file']),'com.android.tools.r8.D8','--min-api','26',
                '--output',str(helper),str(helper/'ClassicRoot.class')],check=True)
with zipfile.ZipFile(ROOT/'out/android-helper/classicroot.jar','w') as archive:
    archive.writestr(zipfile.ZipInfo('classes.dex',(2025,1,1,0,0,0)),(helper/'classes.dex').read_bytes())
print('Built stock root-bridge helper')
