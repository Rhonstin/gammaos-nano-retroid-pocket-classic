# Validation checkpoint: 1.4.1-dev.23

Validated on one original four-button Pocket Classic, board `<0x22 0>`, SG4250P,
with stock vendor mapping 32.0 and stock Linux 5.10.209. Raw diagnostic logs and
owner identifiers remain private; the [public release summary](../release/1.4.1-dev.23.json)
contains selected results and artifact hashes without those identifiers.

| Area | Observed scope |
| --- | --- |
| Permanent boot | dev.23 full `system_a` SHA256 matches the tested raw image; Native/minimal boot completed |
| Controls | Owner checked all 14 buttons, all four touch corners and vibration |
| Audio | Speaker, both wired headphone channels; actual A2DP capture to a laptop |
| Wireless menu | Native Wi-Fi and Bluetooth controls used successfully |
| microSD | Read/write, unmount/remount, game launch and Game Boy Quick Resume |
| USB OTG storage | **Not tested: medium/adapter unavailable** |
| Sleep | Physical unplugged suspend and Power wake; successful cycles and one EBUSY freeze attempt recorded |
| Cooling | 120 seconds / eight workers, maximum observed 71.4°C; auto fan and Max/Auto settings retained |
| Power/charging | dev.23 actual off-mode atomic handoff; 255→0→255→0 brightness; short/long Power; owner confirmed battery image, blank/wake and manual boot to Nano |
| Emulation | Test scenarios on GBA, GB, N64, NDS, PSP and Dreamcast; no universal game compatibility claim |
| Quick Resume | GB state restored; fresh GBA progress survived Restart and Power Off |
| Android | Full Android round trip, app return and ordinary non-incremental APK lifecycle tested |
| Media/browser | Native photo, PCM audio, AVC/AAC video, pause/seek; HTTPS and JavaScript |
| Network storage | WebDAV R/W/reconnect; SMB read/range/read-only; FTP/implicit FTPS R/W; NFS R/W and complete listings of 259 files, spaces and Unicode |
| Update/rollback | dev.12→11→12 preserved userdata/saves/profiles; later dev.22/23 updates and full partition readbacks passed |
| VINTF | All nine runtime summary gates passed on dev.12; vendor/kernel/HAL XML retained in dev.23 |
| Host regression tests | 31 passed with the pinned Core reference: 25 port checks and six release-integrity checks; CI without references explicitly skips two pinned-library checks |

## Limits

- No other Classic revision, external storage bridge or broad game/accessory matrix
  has been certified. The original board profile excludes Rev Q.
- NFS 32 KiB transfers avoid the tested server's 64 KiB fragmented replies; general
  RPC fragment reassembly was not added. NFSv3 is the tested protocol.
- This Core uses implicit FTPS, not explicit AUTH TLS. A temporary test CA was
  removed after trusted-certificate FTPS validation; no fixture CA remains installed.
- The bundled GammaBrowser blocks cleartext HTTP; HTTPS/JavaScript were tested.
- Complete manufacturer factory restoration was not tested. Private pre-Nano
  backups contained an already modified Android 14 installation.
- AVB verifies an integrity hashtree with authentication `NONE`. Existing unlock,
  vendor and partition assumptions remain part of the development setup.

CI is host validation, not device validation. A successful fresh build or green
workflow does not extend this matrix to an untested unit or revision.

