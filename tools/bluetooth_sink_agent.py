#!/usr/bin/env python3
"""Pair only the specified owned console with the host A2DP sink for testing.

Uses the application's own BlueZ agent, leaving the desktop default agent alone.
The console must be temporarily discoverable. A new test bond is removed on exit.
BlueZ Agent1 protocol: https://github.com/bluez/bluez/blob/master/doc/org.bluez.Agent.rst
"""
import argparse
import json
from pathlib import Path
import signal
import time
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--peer',required=True)
parser.add_argument('--state',type=Path,required=True)
parser.add_argument('--timeout',type=int,default=600)
options=parser.parse_args()
peer=options.peer.upper()
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus=dbus.SystemBus()
manager=dbus.Interface(bus.get_object('org.bluez','/'),'org.freedesktop.DBus.ObjectManager')
objects=manager.GetManagedObjects()
adapter_path=next(str(p) for p,i in objects.items() if 'org.bluez.Adapter1' in i
                  and '0000110b-0000-1000-8000-00805f9b34fb' in i['org.bluez.Adapter1'].get('UUIDs',[]))
adapter=dbus.Interface(bus.get_object('org.bluez',adapter_path),'org.bluez.Adapter1')
agent_manager=dbus.Interface(bus.get_object('org.bluez','/org/bluez'),'org.bluez.AgentManager1')
agent_path='/dev/classic/validation_agent'
state={'peer':peer,'adapter':adapter_path,'started':time.time(),'events':[]}
device_path=None
attempted=False
paired_before=False
trusted_before=False
connected_before=False
profile_requested=False
loop=GLib.MainLoop()

def record(kind,detail=''):
    state['events'].append({'elapsed':round(time.time()-state['started'],3),'kind':kind,'detail':str(detail)})
    options.state.parent.mkdir(parents=True,exist_ok=True)
    options.state.write_text(json.dumps(state,indent=2)+'\n')
    print(kind,flush=True)

class Rejected(dbus.DBusException):
    _dbus_error_name='org.bluez.Error.Rejected'

class Agent(dbus.service.Object):
    def check(self,device):
        if str(device)!=adapter_path+'/dev_'+peer.replace(':','_'):
            raise Rejected('Not the console under test')
    @dbus.service.method('org.bluez.Agent1',in_signature='',out_signature='')
    def Release(self):record('agent_released')
    @dbus.service.method('org.bluez.Agent1',in_signature='o',out_signature='s')
    def RequestPinCode(self,device):self.check(device);return '0000'
    @dbus.service.method('org.bluez.Agent1',in_signature='o',out_signature='u')
    def RequestPasskey(self,device):self.check(device);return dbus.UInt32(0)
    @dbus.service.method('org.bluez.Agent1',in_signature='ou',out_signature='')
    def RequestConfirmation(self,device,passkey):self.check(device);record('peer_confirmation')
    @dbus.service.method('org.bluez.Agent1',in_signature='o',out_signature='')
    def RequestAuthorization(self,device):self.check(device);record('peer_authorization')
    @dbus.service.method('org.bluez.Agent1',in_signature='os',out_signature='')
    def AuthorizeService(self,device,uuid):
        self.check(device)
        if str(uuid) not in {'0000110a-0000-1000-8000-00805f9b34fb','0000110b-0000-1000-8000-00805f9b34fb',
                             '0000110c-0000-1000-8000-00805f9b34fb','0000110d-0000-1000-8000-00805f9b34fb',
                             '0000110e-0000-1000-8000-00805f9b34fb','0000110f-0000-1000-8000-00805f9b34fb'}:raise Rejected('Not an audio test service')
        record('audio_service_authorized',uuid)
    @dbus.service.method('org.bluez.Agent1',in_signature='',out_signature='')
    def Cancel(self):record('agent_cancelled')

agent=Agent(bus,agent_path)
agent_manager.RegisterAgent(agent_path,'NoInputNoOutput')

def pair_ok():record('paired')
def pair_error(error):record('pair_error',error)
def profile_ok():record('audio_profile_connected')
def profile_error(error):record('profile_error',error)

def poll():
    global device_path,attempted,paired_before,trusted_before,connected_before,profile_requested
    try:
        for path,interfaces in manager.GetManagedObjects().items():
            info=interfaces.get('org.bluez.Device1')
            if info and str(info.get('Address','')).upper()==peer:
                device_path=str(path)
                device=dbus.Interface(bus.get_object('org.bluez',device_path),'org.bluez.Device1')
                if not attempted:
                    attempted=True;paired_before=bool(info.get('Paired',False));trusted_before=bool(info.get('Trusted',False))
                    connected_before=bool(info.get('Connected',False))
                    state['paired_before']=paired_before;state['trusted_before']=trusted_before
                    state['connected_before']=connected_before
                    record('console_found')
                    if not paired_before:device.Pair(reply_handler=pair_ok,error_handler=pair_error,timeout=90)
                if info.get('Paired',False) and not profile_requested:
                    profile_requested=True
                    dbus.Interface(bus.get_object('org.bluez',device_path),'org.freedesktop.DBus.Properties').Set('org.bluez.Device1','Trusted',True)
                    device.ConnectProfile('0000110a-0000-1000-8000-00805f9b34fb',reply_handler=profile_ok,error_handler=profile_error,timeout=45)
                state['paired']=bool(info.get('Paired',False));state['connected']=bool(info.get('Connected',False))
                options.state.write_text(json.dumps(state,indent=2)+'\n')
                break
    except dbus.DBusException as error:record('poll_error',error)
    if time.time()-state['started']>options.timeout:loop.quit();return False
    return True

def stop(*ignored):loop.quit()
signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
try:
    adapter.StartDiscovery();record('discovering_console')
    GLib.timeout_add(1000,poll)
    loop.run()
finally:
    try:adapter.StopDiscovery()
    except dbus.DBusException:pass
    if device_path:
        try:
            device=dbus.Interface(bus.get_object('org.bluez',device_path),'org.bluez.Device1')
            if not connected_before:device.Disconnect()
            if not paired_before:adapter.RemoveDevice(device_path)
            else:dbus.Interface(bus.get_object('org.bluez',device_path),'org.freedesktop.DBus.Properties').Set('org.bluez.Device1','Trusted',trusted_before)
        except dbus.DBusException as error:record('cleanup_error',error)
    try:agent_manager.UnregisterAgent(agent_path)
    except dbus.DBusException:pass
    record('cleanup_complete')
