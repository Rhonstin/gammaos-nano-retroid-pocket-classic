# Publishing this project

The Git repository contains source, documentation and reviewed public checkpoint
metadata. Firmware, private diagnostics and device backups remain outside Git.
No publishing tool in this repository contacts GitHub or changes a device.

## Source repository

```sh
python3 tools/check_repository.py
python3 -m unittest discover -s tests -v
git status --short
```

Choose the GitHub owner/name, create an empty repository, then connect and push
this local repository. These are manual publication steps:

```sh
git remote add origin git@github.com:YOUR_ACCOUNT/gammaos-nano-retroid-pocket-classic.git
git push -u origin main
```

The workflow runs host tests with read-only permissions. It never flashes a device
or uploads a firmware release. Enable issues and set the repository description to:

> Unofficial GammaOS Nano 1.4.1 port for the original Retroid Pocket Classic.

Suggested topics: `retroid-pocket-classic`, `gammaos`, `android`, `handheld`, `firmware`.

## Firmware assets

Regular Git history is not used for images. GitHub limits regular Git files to
100 MiB, and each release asset must be under 2 GiB. See GitHub's
[file limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
and [release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

Prepare the exact tested checkpoint locally:

```sh
python3 tools/prepare_release.py \
  --candidate /path/to/verified/port-1.4.1-dev.23 \
  --checkpoint release/1.4.1-dev.23.json \
  --notes release/1.4.1-dev.23.md \
  --output out/releases/1.4.1-dev.23
```

The tool verifies both original images against the reviewed checkpoint and the
candidate manifest. It emits three sparse-image parts of at most 1 GiB,
`release.json`, a public updater `manifest.json`, release notes and `SHA256SUMS`.
It does not copy raw diagnostic logs, serials, private paths or the local manifest
wholesale. A failed run does not produce a successful release declaration.

The prepared bundle is a **draft prerelease**. Retain the upstream firmware
notices and satisfy applicable corresponding-source requirements before distributing
binary assets; see [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md). No assets
have been uploaded by preparing the local bundle.

## Download and reassemble

Keep all parts and manifests together. From a source checkout:

```sh
python3 tools/join_image.py --manifest /path/to/downloads/release.json
```

Each part and the assembled sparse image are checked. The tool refuses path
traversal, symlink parts and an existing output file. No flashing occurs.
`SHA256SUMS` lists the files that are actually in the download bundle; the full
assembled image hash is in `release.json` and `manifest.json`.

For an already-supported Nano installation, use the assembled sparse candidate:

```sh
DEVICE_SERIAL=YOUR_DEVICE_SERIAL
python3 tools/update_classic.py --serial "$DEVICE_SERIAL" --candidate /path/to/downloads
# Review the plan, then repeat with --execute.
```

Do not pass `--raw` for this download bundle: it contains only the sparse image.
After boot, compare the full `system_a` SHA256 with `manifest.json`'s
`artifacts.system.img.sha256`. First-install scope is in [INSTALLING](INSTALLING.md).

