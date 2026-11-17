#!/usr/bin/env python3
"""Build the temporary physical acceptance-test APK using pinned SDK inputs."""
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'out/diagnostics'
out.mkdir(exist_ok=True)
sdk=ROOT/'out/android-sdk'
build=sdk/'android-15'
platform=sdk/'android-34/android.jar'
source=ROOT/'tools/android/diagnostics'
classes=out/'classes'; classes.mkdir(exist_ok=True)
dex=out/'dex';dex.mkdir(exist_ok=True)
def run(args):subprocess.run([str(a) for a in args],check=True)
run(['javac','--release','8','-encoding','UTF-8','-cp',platform,'-d',classes,source/'MainActivity.java'])
run(['java','-cp',ROOT/'out/android-helper/r8.jar','com.android.tools.r8.D8','--min-api','26',
     '--lib',platform,'--output',dex,*classes.rglob('*.class')])
unsigned=out/'unsigned.apk'
run([build/'aapt2','link','-I',platform,'--manifest',source/'AndroidManifest.xml',
     '--min-sdk-version','26','--target-sdk-version','34','--version-code','1',
     '--version-name','1.0','-o',unsigned])
with zipfile.ZipFile(unsigned,'a') as z:z.write(dex/'classes.dex','classes.dex')
run([build/'zipalign','-f','4',unsigned,out/'aligned.apk'])
key=out/'test-key.p12'
if not key.exists():
    run(['keytool','-genkeypair','-keystore',key,'-alias','classic-test','-storepass','android',
         '-keypass','android','-keyalg','RSA','-keysize','2048','-validity','3650',
         '-dname','CN=Classic Diagnostics Test Key'])
apk=out/'classic-diagnostics.apk'
run([build/'apksigner','sign','--ks',key,'--ks-key-alias','classic-test',
     '--ks-pass','pass:android','--key-pass','pass:android','--out',apk,out/'aligned.apk'])
run([build/'apksigner','verify',apk])
print(apk)
