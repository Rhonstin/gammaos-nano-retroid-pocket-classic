#!/usr/bin/env python3
"""Run a bounded CPU load on the original Classic and record real temperatures.

Uses current user profiles and stock frequency limits. The remote supervisor
stops its workers on its own deadline even if the host connection disappears.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import signal
import subprocess
import time
import uuid

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--serial',required=True)
parser.add_argument('--duration',type=int,default=120,choices=range(10,301))
parser.add_argument('--workers',type=int,default=8,choices=range(1,9))
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
adb=['adb','-s',args.serial]
def shell(command):
    return subprocess.check_output(adb+['shell',command],text=True,timeout=12).strip()
board=subprocess.check_output(adb+['exec-out','cat','/sys/firmware/devicetree/base/qcom,board-id'],timeout=10)
if board!=bytes.fromhex('0000002200000000') or shell('id -u')!='0':
    raise RuntimeError('Requires root ADB on the original Classic board <0x22 0>')
tag='classic-thermal-'+uuid.uuid4().hex[:10]
remote='/data/local/tmp/'+tag+'.sh'
body='''#!/system/bin/sh
pids=""
cleanup() {
    trap - 0 1 2 15
    for worker in $pids; do
        case "$(tr '\\0' ' ' 2>/dev/null < /proc/$worker/cmdline)" in
            *TAG-*) kill -TERM "$worker" 2>/dev/null;;
        esac
    done
    exit 0
}
trap cleanup 0 1 2 15
for index in WORKERS; do
    sh -c 'while :; do :; done' TAG-$index &
    pids="$pids $!"
done
echo "$pids" > PIDFILE
sleep DURATION
'''.replace('WORKERS',' '.join(str(i) for i in range(args.workers))).replace('DURATION',str(args.duration)).replace('PIDFILE',shlex.quote(remote+'.pids')).replace('TAG',tag)
args.output.parent.mkdir(parents=True,exist_ok=True)
source=args.output.with_suffix('.remote.sh');source.write_text(body)
subprocess.run(adb+['push',str(source),remote],check=True,stdout=subprocess.DEVNULL)
paths={
    'little_mc':'/sys/class/thermal/thermal_zone22/temp',
    'big_mc':'/sys/class/thermal/thermal_zone23/temp',
    'gpu_mc':'/sys/class/thermal/thermal_zone28/temp',
    'little_khz':'/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq',
    'big_khz':'/sys/devices/system/cpu/cpufreq/policy6/scaling_cur_freq',
    'gpu_hz':'/sys/class/kgsl/kgsl-3d0/devfreq/cur_freq',
    'fan_state':'/sys/class/gpio5_pwm2/state',
    'fan_duty':'/sys/class/gpio5_pwm2/duty',
    'fan_period':'/sys/class/gpio5_pwm2/period',
}
query='\n'.join('printf '+shlex.quote(key+'=')+'; cat '+path for key,path in paths.items())
start=time.monotonic()
report={'started':datetime.now(timezone.utc).isoformat(),'workers':args.workers,
        'duration_seconds':args.duration,'boot_id':shell('cat /proc/sys/kernel/random/boot_id'),
        'profile_before':shell('getprop persist.gammaos.performance_mode'),
        'fan_mode_before':shell('getprop persist.gammaos.fan_mode'),'samples':[]}
stopping=False
def stop(*ignored):
    global stopping
    stopping=True
signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
pid=None
try:
    pid=int(shell('nohup sh '+shlex.quote(remote)+' > /dev/null 2>&1 < /dev/null & echo $!'))
    report['worker_pids']=shell('cat '+shlex.quote(remote+'.pids')).split()
    if len(report['worker_pids'])!=args.workers:
        raise RuntimeError('Remote supervisor did not start the requested workers')
    while not stopping and time.monotonic()-start<=args.duration:
        sample={'seconds':round(time.monotonic()-start,2)}
        for line in shell(query).splitlines():
            key,value=line.split('=',1);sample[key]=int(value)
        report['samples'].append(sample)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
        if len(report['samples'])%10==1:print(json.dumps(sample),flush=True)
        if max(sample[k] for k in ('little_mc','big_mc','gpu_mc'))>=80000:
            report['stopped_at_temperature_limit']=True;break
        time.sleep(2)
finally:
    # The supervisor trap and its own deadline both stop only this run's workers.
    if pid and shell('cat /proc/sys/kernel/random/boot_id')==report['boot_id']:
        command=shell('tr "\\0" " " 2>/dev/null < /proc/'+str(pid)+'/cmdline || true')
        if remote in command:shell('kill -TERM '+str(pid))
        for worker in report.get('worker_pids',[]):
            command=shell('tr "\\0" " " 2>/dev/null < /proc/'+worker+'/cmdline || true')
            if tag+'-' in command:shell('kill -TERM '+worker)
        time.sleep(.3)
        workers=report.get('worker_pids',[])
        report['workers_stopped']=len(workers)==args.workers and all(shell('if [ ! -e /proc/'+p+' ]; then echo yes; fi')=='yes' for p in workers)
    report['profile_after']=shell('getprop persist.gammaos.performance_mode')
    report['system_server_running']=bool(shell('pidof system_server'))
    report['max_temperature_c']=max((max(s[k] for k in ('little_mc','big_mc','gpu_mc'))/1000 for s in report['samples']),default=None)
    report['passed']=bool(report['samples']) and report.get('workers_stopped',False) and report['system_server_running'] and report['profile_after']==report['profile_before'] and not report.get('stopped_at_temperature_limit',False)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    shell('rm -f '+shlex.quote(remote)+' '+shlex.quote(remote+'.pids'))
print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2),flush=True)
if not report['passed']:raise SystemExit(1)
