# Installation and updates

The supported identity is the original four-button Classic, board `<0x22 0>`,
vendor `parrot`. Validation used one unlocked unit with its existing OpenABL,
stock vendor mapping 32.0 and stock 5.10 kernel. No bootloader or manufacturer
factory-restoration package is included. Rev Q is outside this profile.

## Updating an existing permanent Nano installation

The updater requires an existing `1.4.1-*` port installation, slot A, the supported
board/vendor, no active DSU, and no unresolved incremental APK installation. It
checks the image hash and stock fastbootd layout before changing **only `system_a`**.

Find your device serial with `adb devices` and set it in your shell:

```sh
DEVICE_SERIAL=YOUR_DEVICE_SERIAL
python3 tools/update_classic.py --serial "$DEVICE_SERIAL" --candidate out/my-candidate --raw
```

Review the concrete dry-run plan, then execute the same candidate:

```sh
python3 tools/update_classic.py --serial "$DEVICE_SERIAL" --candidate out/my-candidate --raw --execute
adb -s "$DEVICE_SERIAL" shell getprop ro.gammaos.port.version
adb -s "$DEVICE_SERIAL" shell sha256sum /dev/block/mapper/system_a
```

Compare the full partition SHA256 with the candidate's `manifest.json`. Logs stay
under ignored `evidence/updates/`. The updater enters **userspace fastbootd with
`adb reboot fastboot`**. `adb reboot bootloader` entered EDL on the tested setup;
it is not the documented entry point.

To roll back, use a previously verified candidate directory with the same updater.
A dev.12 → dev.11 → dev.12 cycle preserved saves and performance/fan settings on
the test unit. This does not establish compatibility with arbitrary older images.

## First installation: experimental development tooling

`update_classic.py` is **not** a first-install script. Initial development used a
device-specific vendor ramdisk adaptation, stock fastbootd and a data wipe. There
is no generally validated stock-to-Nano installer for all original Classics.

The included tools preserve that work for review and further development:

1. Collect identity read-only with `python3 tools/collect_device.py --serial "$DEVICE_SERIAL"`.
2. Keep your own verified partition backups outside Git. A backup of a modified
   Android installation is not a manufacturer factory image.
3. Prepare the supported vendor ramdisk from **your own** verified backup:

```sh
python3 tools/prepare_install.py \
  --vendor-boot /path/to/your/vendor_boot_a.img \
  --vendor-boot-sha256 YOUR_RECORDED_64_CHARACTER_SHA256 \
  --output out/initial-boot
```

4. The experimental flash tool expects already-identified hardware in stock
   fastbootd. Inspect its dry run with:

```sh
python3 tools/flash_classic.py --serial "$DEVICE_SERIAL" \
  --system out/my-candidate --boot out/initial-boot
```

Its `--execute` plan changes logical layout, `vendor_boot_a`, vbmeta partitions,
and erases userdata/metadata. It is separate from the data-preserving updater.
Bootloader unlocking, EDL recovery and stock firmware acquisition are not automated.

## Everyday operation

- Power Off with USB connected enters off-mode charging: a short RETROID startup,
  battery animation, then screen blank. Short Power shows the battery again;
  holding Power about 2–3 seconds starts Nano. Off-mode USB has no ADB.
- The native power menu switches between Nano and full Android.
- For ADB APK delivery use `adb install --no-incremental -r application.apk`.
- Use `python3 tools/nano_input.py --serial "$DEVICE_SERIAL" ...` only when testing
  native gamepad navigation; the tool injects actual evdev events.

