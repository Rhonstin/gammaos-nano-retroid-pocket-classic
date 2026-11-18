# Applications and game systems (dev.26)

Dev.26 updates GammaOS' bundled applications, adds standalone emulators for newer
consoles and a Steam entry, and wires them into Nano's **Game** column. Every
binary is pinned by size and SHA-256 in [`apps.lock.json`](../apps.lock.json) and
downloaded outside Git:

```sh
python3 tools/prepare_apps.py --download   # fetch and verify the locked inputs
python3 tools/prepare_apps.py --verify     # offline check of the cache
python3 tools/prepare_apps.py --update-lock  # maintainer: re-pin nightly cores/assets
```

## Bundled applications

| Application | Version | Role | Source |
| --- | --- | --- | --- |
| RetroArch (aarch64) | 1.22.2 nightly 2026-11-17 | update | buildbot.libretro.com |
| PPSSPP | 1.20.4 | update | ppsspp.org |
| Flycast | 2.7 | update | GitHub flyinghead/flycast |
| Aurora Store | 4.8.4 | update | GitLab AuroraOSS |
| Firefox Beta | 161.0b4 | update | archive.mozilla.org |
| DroidDeck (Steam) | 0.7.1 | new | GitHub Droid-Deck/DroidDeck |
| ARMSX2 (PS2), armv8.2 / Android 13+ build | 2.9.5 | new | GitHub ARMSX2/ARMSX2 |
| Dolphin (GameCube, Wii) | 2609b | new | dolphin-emu.org |
| Azahar (3DS), vanilla | 2126.2 | new | GitHub azahar-emu/azahar |
| Vita3K (PS Vita) | continuous 0.2.1 | new | GitHub Vita3K/Vita3K |

Retained, with the reason recorded in the lock: Daijisho 1.8.1 (newer than its last
public release), DraStic r2.6.0.4a (final release), M64Plus FZ 3.0.335 (no newer
public APK), MiXplorer 6.64.3 (downloads require an XDA login), Magisk 30.6 (root
payload coupled to GammaOS setup). Updated APKs keep their original signers, so
they install over existing copies.

The RetroArch first-boot payload is rebuilt by `tools/retroarch_payload.py`: 146
libretro cores are replaced by the pinned nightly arm64-v8a builds (FAKE-08 has
none and stays stock), and the pinned frontend archives (assets, Android
autoconfig, RDB databases, info, overlays, GLSL and slang shaders) are overlaid.
GammaOS' own presets and configuration stay untouched.

## How the image applies them

- `setup.sh` (first boot) installs the updated stock set by their new file names.
- `classic-apps.sh`, run by `classic-provision.sh` on each boot after setup:
  1. installs a bundled APK when missing or older; a newer or differently signed
     copy is left alone; grants storage/notification permissions;
  2. refreshes an existing RetroArch installation once from the new payload
     (cores, info, assets, autoconfig, databases, overlays, shaders only);
  3. merges the extra Nano systems (below) with `ClassicSystems`;
  4. points DroidDeck's library export at `ROMs/steam` and lifts Android 14's
     child-process limit DroidDeck needs;
  5. applies emulator profiles from `device/profiles-src` once, only for an
     emulator that has never written its own configuration.

## Nano game systems

`device/classic-systems.json` defines the systems; `ClassicSystems` adds each one
to `/data/system/nano_systems.json` once its emulator is installed. Nano 1.4.1
reloads the file when its mtime changes. A system the user deletes is never
re-added; a system is refreshed to a newer definition only while it still equals
what the helper last wrote.

| Nano entry | Folder (`/sdcard/ROMs/…`) | Emulator | Launch |
| --- | --- | --- | --- |
| Steam Games | `steam` | DroidDeck | `VIEW` of the `.steam` file (DroidDeck's own export format) |
| PlayStation 2 | `ps2` | ARMSX2 | `VIEW` content URI |
| GameCube | `gc` | Dolphin | `AutoStartFile` + content URI |
| Wii | `wii` | Dolphin | `AutoStartFile` + content URI |
| Nintendo 3DS | `n3ds` | Azahar | `VIEW` content URI |
| Nintendo Switch | `switch` | Eden Legacy (owner-installed, see below) | `VIEW` content URI |
| Sega Saturn | `saturn` | RetroArch YabaSanshiro core | libretro core |

Nano 1.4.1 substitutes only `{file.uri}`, `{file.path}` and `{file.mime}`; the
framework grants the target package read access to the content URI. The Nano
package for each system is the emulator itself, so Nano's process-death return
and *Close Current App* act on the right process. A new top-level XMB column would
need a rebuilt Nano binary and is not part of this image.

**PlayStation:** once a PS1 BIOS (scph5500/5501/5502/1001/7001/101 or
`ps1_rom.bin`) is in `/sdcard/RetroArch/system`, the PlayStation entry moves from
PCSX ReARMed to SwanStation one time. Without a BIOS PCSX ReARMed and its HLE BIOS
remain, keeping the validated Quick Resume path.

## Profiles

| Emulator | Profile |
| --- | --- |
| Dolphin | GammaPad (`Xbox Wireless Controller`) mapped to GameCube pad 1 (positional A/B/X/Y, Z on R1, C-stick on the right stick, D-pad on the hat) and Wii Remote + Nunchuk (pointer on the right stick); touch overlay off; analytics declined |
| Azahar | touch overlay off (its first-run wizard still asks for a user folder) |

## Requirements the image cannot provide

- **Steam:** DroidDeck downloads its ~3 GB Linux runtime on first *Play* and needs
  a Steam login. Adreno 613 is outside DroidDeck's tested GPUs.
- **PS2:** ARMSX2's setup requires the owner's PS2 BIOS (`/sdcard/BIOS/ps2`).
- **Switch:** Eden is not part of the image (see below) and needs the owner's keys and firmware for commercial software.
- **3DS:** Azahar asks for a user folder once (Storage Access Framework).
- **PS Vita:** Vita3K starts games by title ID, which Nano 1.4.1 cannot pass; use
  it from *Applications*.

See [VALIDATION](VALIDATION.md) for what was exercised on hardware.

## Display defaults applied by `classic-apps.sh`

After dev.26, `classic-apps.sh` also turns off two debug counters once: Flycast's FPS
readout (`rend.ShowFPS`, enabled by GammaOS's `flycast.tar.xz`) and Eden's performance
bar (`show_performance_overlay`). Each key is rewritten in place as soon as the
emulator's own config exists (Eden creates it on first launch), recorded under
`/data/misc/classic/tweak-*`, and never touched again, so the owner can re-enable it.
Validated on the dev.26 console by running the updated script; it ships in the next image.

## Nintendo Switch: installing Eden yourself (dev.29+)

From dev.29 the image does not contain any Switch emulator. Eden is GPL software, but it
descends from a project that was shut down after legal action and its own code hosting
has been subject to takedown notices, so this project does not redistribute it. Nano's
Nintendo Switch entry, the Turnip driver and the Eden defaults below are already in the
image and switch on by themselves once Eden is installed:

1. Get the Android **Legacy** build of Eden (package `dev.legacy.eden_emulator`, the
   variant for GPUs older than the Snapdragon 865 class) from the Eden project's own
   official release channel. Do not use mirrors or repackaged APKs.
2. Copy the APK to the console and install it, e.g. `adb install Eden-*-legacy.apk`, or
   open it in MiXplorer and allow installation from that app when Android asks.
3. Start Eden once, finish its first-run wizard and point its games folder at
   `ROMs/switch`. This creates its configuration.
4. Put `prod.keys`, `title.keys` and the firmware dumped from **your own** Switch into
   `/sdcard/BIOS/switch/` and install them through Eden's setup (the firmware version
   must not be newer than the keys support).
5. Reboot. On the next boot `classic-apps.sh` adds **Nintendo Switch** to Nano's Game
   column and selects the bundled Turnip driver and the Dynarmic CPU backend.

Games are only those you own and dumped yourself; nothing of that kind ships here.

## Eden defaults for the Adreno 613 (dev.28)

`apps.lock.json` gains a `files` section for pinned non-APK inputs. The first is the
Mesa Turnip AdrenoTools package `turnip-axfl3-003-android.zip` (armsx2-turnip build
axfl3-003, MIT), installed at `/system/etc/classic-drivers/`. Once Eden has written its
`config.ini`, `classic-apps.sh` copies the package into Eden's `gpu_drivers` (app owner
and SELinux category label) and, only where the setting is still Eden's default, selects
it as the GPU driver and switches the CPU backend from NCE to Dynarmic. With the stock
driver Eden's VulkanWorker crashes; with NCE the tested commercial title crashed.
