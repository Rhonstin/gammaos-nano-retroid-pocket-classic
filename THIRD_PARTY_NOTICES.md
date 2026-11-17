# Third-party notices

The root Apache-2.0 license applies to original work in this source project.
It does not replace existing notices or license downloaded firmware/software.

| Material | Origin / terms |
| --- | --- |
| Charger atomic fallback adaptation | GammaOS `NanoMenuDrm.cpp`, commit `fb4ecbf9ec9436b511c4978a90718e851bdf89ed`; Apache-2.0 notice retained in `device/classic-charger-atomic.h` |
| Minimal DRM UAPI declarations | Linux DRM declarations; MIT notices retained in `device/classic-drm-uapi.h` |
| NFS source equivalents | libnfs `libnfs-6.0.2`; high-level library LGPL-2.1-or-later; generated NFS protocol source carries Ronnie Sahlberg's BSD notice; the release integrator modifies a separately downloaded library |
| GammaOS Core / Classic inputs | Public releases pinned in `release-inputs.json`; their components retain their own licenses |
| Android build tools | R8 and optional SDK inputs pinned in `android-tools.lock.json`; upstream terms apply |
| Research source subset | GammaOS source pinned by `upstream.lock.json`; original file notices retained on download |

Upstream sources:

- [GammaOSNext](https://github.com/TheGammaSqueeze/GammaOSNext)
- [libnfs source and license files](https://github.com/sahlberg/libnfs/tree/libnfs-6.0.2)
- [AOSP](https://source.android.com/)

Neither ROMs nor user saves are included. Generated firmware release assets are
separate from the source archive. Before redistributing those assets, preserve
the notices and corresponding-source obligations of their upstream components;
the source repository's license is not a blanket firmware redistribution grant.

