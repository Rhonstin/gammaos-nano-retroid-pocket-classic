# Integration architecture

The base is the pinned public GKD Nano 1.4.1 Core image. Public Classic references
supply the original controller bridge and charger resources. Stock Classic vendor,
kernel and modules are retained. Downloaded firmware and private backups are not
stored in this source repository.

| Component | Purpose |
| --- | --- |
| `port-defaults.prop`, `profile.json` | Classic identity, VNDK 32 and development defaults |
| `gammapad.rc`, `classic.rc` | Controller, hardware, provisioning, power and charger services |
| `classic-hardware.sh` | Frequency, fan and sleep behavior through board sysfs |
| `ClassicStateCompat.java`, `classic-power.sh` | Normalize preview state copies and flush fresh saves before reboot/off |
| `classic-charger-entry.c` | Redirect charger diagnostics and execute the unchanged original `charger-core` |
| `classic-charger-prepare.sh` | Apply stock-equivalent ownership to the actual panel backlight node |
| `classic-charger-ioctl.c`, `classic-charger-atomic.h` | Scoped Qualcomm SDE display handoff and backlight blank/wake |
| `classic-policy.cil` | Small explicit compatibility delta; no new permissive domain |
| `classic-nfs-entry-link.S` | Source for the 28-byte READDIR decoder repair |
| `classic-charger-probe.sh` | Opt-in, root-owned, single-use, bounded off-mode diagnostic run |

The charger keeps UID `system`, domain `charger`, and required boot/alarm/wake
capabilities. A separate service avoids an init override across the Treble boundary.
Its preload is scoped to the charger process; normal HWC/SurfaceFlinger are retained.
The shim keeps the CRTC alive and operates the canonical panel brightness node.
If display ownership was not acquired, it leaves the existing owner's light alone.

The original Core charger and upstream ELF inputs are checked by hash. Nano's
Qualcomm platform literal is retargeted without changing its ELF layout. NFS's
two compatibility changes are described in [NFS](NFS.md). Original source licenses
and notices remain attached to adapted code.

SELinux remains Enforcing. The inherited upstream bootanim domain is already
permissive; the port does not claim that every inherited domain is strict.
The source subset and source patches are provided separately from release-binary
integration, and the manifest distinguishes these methods.

