# Building

The integration runs without root on Linux. Allow at least 25 GiB of free working
space for public archives, extracted references and a candidate. The scripts use
GNU tools and are not a native Windows/macOS build workflow.

## Prerequisites

- Python 3.11 or later; normal build/test scripts use its standard library.
- GNU `cp`, Git, 7-Zip (`7z`), e2fsprogs (`debugfs`, `e2fsck`, `resize2fs`, `mke2fs`).
- Android host tools on `PATH`: `lpunpack`, `avbtool`, `img2simg`, `simg2img`.
- JDK 17+ (`java`, `javac`) and `aarch64-linux-gnu-gcc`.
- For all host tests: native `cc`, `qemu-aarch64` and arm64 GNU binutils.
- For device work: `adb` and `fastboot`.
- Experimental ramdisk preparation also needs `unpack_bootimg`, `mkbootimg`,
  and `liblz4.so.1`. Bluetooth sink validation needs Python D-Bus/GLib and BlueZ.

Use distro packages where available. Android tools can also be built from their
official AOSP projects: [liblp/lpunpack](https://android.googlesource.com/platform/system/core/+/refs/heads/main/fs_mgr/liblp/),
[AVB](https://android.googlesource.com/platform/external/avb/),
[libsparse](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/),
and [mkbootimg](https://android.googlesource.com/platform/system/tools/mkbootimg/).
Cross-libc is not needed: the small charger adapters are freestanding.

## Build

Run from the repository root:

```sh
python3 tools/prepare_references.py --download
python3 tools/prepare_android_tools.py --download
python3 tools/prepare_apps.py --download
python3 tools/build_candidate.py --output out/my-candidate
python3 -m unittest discover -s tests -v
```

`--output` must be a new directory. The reference tool verifies the public archive
passwords/digests in `release-inputs.json`, extracts them into `out/`, and checks
the image hashes in `artifact-inputs.json`. The Android tool lock pins R8 and
optional SDK inputs. `apps.lock.json` pins the bundled applications, libretro cores
and RetroArch assets (about 1.3 GB in `downloads/apps`; see [APPS](APPS.md)).
The build needs roughly 10 GB free for its output. No private device backup is used to build `system.img`.

The builder copies the reference image, removes its old footer, expands ext4,
unshares shared blocks, preserves file ownership/SELinux labels, integrates the
port and reads changed files back. It runs fsck, minimizes ext4, adds/verifies an
AVB hashtree and emits:

```text
system.img
system.sparse.img
manifest.json
SHA256SUMS
build.log
fsck-verification.txt
avb-verification.txt
```

The manifest records local helpers, retained original charger, NFS changes and
input provenance. A fresh build is a new candidate requiring verification; the
published dev.23 hashes identify the tested artifact, not an assertion that
all locally rebuilt images are byte-identical.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

CI installs native/arm64 compilers, qemu and e2fsprogs. It does not download several
gigabytes of firmware or flash hardware. The two pinned-library tests explicitly
skip when `out/reference-gkd/partitions/system.img` is absent. Prepare references
to run them: they compare the integrated bytes and execute the actual original
and repaired arm64 READDIR decoder under qemu.

Host tests cover identity/container bounds, first-stage mount edits, ext4 security
metadata, save normalization, charger atomic/ownership behavior, NFS decoder and
release integrity. Hardware results are separate in [VALIDATION](VALIDATION.md).

## Source research subset

```sh
python3 tools/fetch_upstream.py
patch --dry-run -p1 -d upstream < patches/0001-classic-display-and-audio.patch
```

`upstream.lock.json` pins the commit and Git blob hashes. This is a research subset,
not the full Android tree. `patches/0001` is a source adaptation, not the source
build used for the release ELF. The image integrator separately checks and edits
the pinned release binaries, including their exact original hashes.

