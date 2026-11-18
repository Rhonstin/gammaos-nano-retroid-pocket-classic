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

## Dev.29 (built, not flashed)

Dev.29 removes Eden from the image; the owner installs it (see [APPS](APPS.md)). Nano's
Switch entry, the Turnip driver and the Eden defaults stay and activate only when
`dev.legacy.eden_emulator` is installed. The installed console keeps its owner-installed
Eden, so the Switch results below remain valid for that setup.

## Dev.28 installed (flashed 2026-11-18)

Dev.28 adds the pinned Mesa Turnip package and the one-time Eden defaults step. After
`update_classic.py --raw --execute` the console reports `1.4.1-dev.28` and the full
`system_a` SHA-256 equals the image (`ae968737…dba1`); userdata was kept. First boot
logged `eden-defaults: applied`, placed `turnip-axfl3-003-android.zip` in Eden's
`gpu_drivers` and left the already chosen driver and CPU backend unchanged. The owner then
ran Drop Duchy on dev.28 and confirmed it works.

## Dev.27 installed (flashed 2026-11-18)

Dev.27 differs from dev.26 only by the one-time Flycast/Eden debug-counter step in
`classic-apps.sh`. After `update_classic.py --raw --execute` the console reports
`1.4.1-dev.27` and the full `system_a` SHA-256 equals the image (`acc48df8…8d42`);
userdata was kept. The dev.26 results below carry over unchanged.

| Entry | Result |
| --- | --- |
| Commercial Switch title (owner's Drop Duchy NSP, 01002840271CC000 v0, key generation 21) | Listed in Nano and handed to Eden. Needed three owner-side changes, all on the console only: (1) owner prod.keys/title.keys for firmware 22.5.0 merged into the working set (only the `_14`/`_15` generation keys added; the supplied file's `*kek_source_*` entries carry a stray trailing `00` byte and its extra BIS/eticket keys made Eden report missing keys); (2) Mesa Turnip 27.0.0-devel (the AdrenoTools package ARMSX2 downloads) selected as Eden's GPU driver — the stock Adreno 613 driver crashes Eden's VulkanWorker (no logicOp/multiViewport); (3) CPU backend Dynarmic instead of NCE (NCE: guest crash with unmapped InvalidateNCE). Result: title screen v1.2.19.6 rendered, gamepad A reached the main menu and its EULA prompt (left for the owner), 63 °C |
| Key-file note | Files written into Eden's external data by root must get the app's SELinux category label (`media_rw_data_file:s0:c76,…`), otherwise Eden shows "Encryption keys are missing" |

## Dev.26 installed (flashed 2026-11-18)

`update_classic.py --raw --execute` resized and flashed `system_a` only (userdata kept).
After reboot `ro.gammaos.port.version` = `1.4.1-dev.26` and the full `system_a`
SHA-256 equals the image (`024aa583…6dd112`). First-boot provisioning logged
`nano_systems.json unchanged`; app versions, Nano systems and the SwanStation migration persisted.

| Entry (launched through Nano's gamepad path) | Result |
| --- | --- |
| Game column | Steam Games, PlayStation 2, GameCube, Wii, Nintendo 3DS, Nintendo Switch, Sega Saturn present |
| Steam Games | DroidDeck-exported `Half-Life.steam` / `Underkeep Demo.steam` listed; Half-Life reached its main menu; Nano regained focus after DroidDeck closed |
| PlayStation (SwanStation) | Hover Racing ran; Quick Menu → Restart: Nano resumed the game after boot and RetroArch reported "Auto-loading save state … succeeded" |
| GBA / PSP / Dreamcast | Apotris (LCD shader, state restored), Ape Escape Racing demo (PPSSPP 1.20.4), Hyper Final Fight 3 (Flycast 2.7) |
| PlayStation 2 (ARMSX2) | ISO9660 test disc (SYSTEM.CNF → Open PS2 Loader 1.1.0) booted through the owner BIOS into the OPL menu |
| GameCube / Wii (Dolphin) | 240p Test Suite 1.10b: GameCube ISO menu and Wii DOL screen rendered |
| Nintendo 3DS (Azahar) | `ftpd.3dsx` 3.2.1 ran, saw the console Wi-Fi and started its server |
| Nintendo Switch (Eden) | Owner firmware 19.0.0 shown in the overlay; `hbmenu.nro` drew at 49 FPS (its `launchInit()` message is expected without a homebrew loader) |
| Sega Saturn (YabaSanshiro) | Save Game Copier 3.6.18 (cue/iso) booted through the owner BIOS to its menu |
| Commercial PS2 title | Owner's Berwick Saga (SLPS-25497, English patch v2.3, 4.3 GB ISO) launched from Nano: intro FMV, title menu and memory-card screen with gamepad input, 46 °C |
| Overlay / shader audit | RetroArch: touch overlay off, shaders + per-core presets on (12 cores incl. SwanStation), auto save/load on; PPSSPP: touch controls off, UpscaleSharpBilinear; Dolphin and Azahar: input overlay off; Eden: input overlay off, performance bar turned off; Flycast: FPS counter turned off (rechecked from Nano); ARMSX2: touch controls hidden while the gamepad is connected; Vita3K: performance overlay and update prompt off |

## Dev.26 pre-flash checks (dev.24 installed)

On the dev.24 console the new emulators were installed with `adb`, the systems were
merged by `ClassicSystems`, and launches went through Nano's real gamepad path with
freely distributable homebrew placed in the ROM folders:

| Entry | Result |
| --- | --- |
| Nano Game column | Steam Games, PlayStation 2, GameCube, Wii, Nintendo 3DS, Nintendo Switch, Sega Saturn appear with icons; Nano reloaded the merged file |
| GameCube / Wii (Dolphin 2609b) | Content URI with spaces received and booted (`JITARM64`, OpenGL ES and Vulkan, HLE). Swiss r2119 stayed black, but the GPL 240p Test Suite 1.10b rendered its full menu as a GameCube ISO and its startup screen as a Wii DOL |
| 3DS (Azahar 2126.2) | After its first-run wizard, `ftpd.3dsx` ran on Vulkan from Nano |
| Switch (Eden 0.2.1 Legacy) | File received and emulation started. `ftpd.nro` (deko3d) aborted inside Eden's GPU macro engine (emulator defect); `hbmenu.nro` 3.6.1 drew its console at 60.5 FPS. With owner prod.keys/title.keys and firmware 19.0.0 (229 NCAs in `nand/system/Contents/registered`) Eden reports firmware 19.0.0 and loads system NCAs, but its QLaunch and Mii-edit applets end in a fatal error. No commercial title tested |
| PS2 (ARMSX2 2.9.5) | Opened from Nano. With owner BIOS dumps (SCPH-70000/70004/70012, v02.00, all detected) its wizard finished: ROMs/ps2 as game folder, automatic performance tuning on, ARMSX2 Turnip driver axfl3-003 installed; "Boot BIOS" reached the PS2 language-selection screen. A locally built ISO9660 disc (SYSTEM.CNF → Open PS2 Loader 1.1.0, GPL) opened through the Nano content-URI intent booted via BIOS into the OPL menu. No commercial PS2 disc tested |
| PS Vita (Vita3K 0.2.1) | Official Sony firmware 3.74 and font package installed through its first-run wizard (`vs0`/`sa0`/`pd0` populated); update nag disabled. No Nano Game entry: Vita3K installs titles into its own `ux0` and has no file-launch intent |
| Steam (DroidDeck 0.7.1) | Opened from Nano with the `.steam` file; DroidDeck flags Adreno 613 as below its tested hardware. Over Wi-Fi it downloaded its runtime (3.3 GB) and the Steam client; after the owner signed in, Half-Life (appid 70, DroidDeck-Proton 11-12.8) installed and ran its main menu and the opening tram ride in 3D (58 °C, 2.6 GB RAM free). Underkeep Demo exited at start: its SDL3 reported "No displays available" under Wine (title-specific). DroidDeck exports `.steam` files only for installed games after a session |
| Provisioning (`classic-apps.sh` with the dev.26 image's files, path-redirected) | Upgraded RetroArch, PPSSPP, Flycast, Aurora and Firefox in place; refreshed RetroArch cores/assets once (owner and `app_data_file` label kept; SwanStation hash equals the pinned nightly); left Nano systems unchanged; set DroidDeck's export folder; skipped Dolphin/Azahar profiles because both were already configured; 33 s |
| Regression after the upgrade, launched from Nano | Game Boy (Gambatte nightly, LCD grid shader, input reached the game), GBA (gpSP nightly, GBA Color preset, auto state restored), PlayStation (PCSX ReARMed nightly), PSP (PPSSPP 1.20.4), Dreamcast (Flycast 2.7) |
| Saturn (YabaSanshiro) | With owner saturn_bios.bin the real BIOS 1.01 boot logo played and the GPL Save Game Copier 3.6.18 disc (cue/iso) reached its menu |
| PlayStation (SwanStation) | Owner scph5501 present → `ClassicSystems` migrated `psx` to SwanStation once (recorded in state); Hover Racing (PSXDEV) booted through the BIOS and ran in 3D; existing PCSX auto-state untouched, memory card differed only in 3 directory bytes |
| Not exercised | PS2 and Switch commercial software (owner BIOS/keys), Steam games beyond the two titles above, flashing the dev.26 image itself |
| Host tests | 42 passed (11 new: systems merge, payload rebuild, lock/profile consistency) |

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

