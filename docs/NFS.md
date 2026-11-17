# NFS integration

Core 1.4.1 ships `libnfs.so` SHA256
`f610732e4761a1b541f9bc103670b206d8204624da9892591371d41cb4f0c3ea`.
Runtime tests against UNFS3 0.10.0 / libtirpc 1.3.5 exposed two independent
problems. The server exports only synthetic fixtures in an isolated container.

1. The RPC reader rejects a non-final record marker with the literal
   `Fragment support not yet working`. Large reads time out; packet capture
   contains 64 KiB non-final records. Negotiating default reads/writes of 32 KiB
   avoids this server's 64 KiB fragmentation. This is a transfer-size workaround,
   not general fragment reassembly. Directory buffer defaults remain 8 KiB.
2. The shipped `zdr_entry3` loops over the wire entries but decodes them into
   the same object, retaining only the last name. The server and an independent
   libnfs 5.0.3 client report both fixtures; the Core client reports one.
   The correction restores the standard `zdr_pointer` call for `nextentry`.

`tools/build_candidate.py::classic_nfs_compatibility` checks the whole original
library SHA and exact instructions. It changes the default transfer immediate
at `0x32a78` and 28 bytes at `0x4cc84`. The latter keeps the original function
frame, field readers, stack canary, return path, exported ABI, and ELF layout.
`device/classic-nfs-entry-link.S` is its assembly source. The source equivalent
is the final field of [upstream zdr_entry3](https://github.com/sahlberg/libnfs/blob/libnfs-6.0.2/nfs/libnfs-raw-nfs.c):

```c
return zdr_pointer(zdrs, (char **)&objp->nextentry,
                   sizeof(entry3), (zdrproc_t)zdr_entry3);
```

The repaired library SHA256 is
`551a97a831d5b79a8992d0f4814bc2172b1d11e8cc7eebf472056a0ff2741aff`.
No preload, new daemon, or policy permission is needed in the permanent image.

`tests/nfs_decoder_test.*` run the actual 180-byte original/repaired function
under qemu-aarch64, mapping its PLT calls to bounded test readers. The original
fails the linked-entry check; the repair preserves three distinct names,
file IDs and cookies, a single entry, and rejects every truncated test stream.
The assembler output is compared with the exact integrated instruction bytes.

The public checkpoint summary is in `release/1.4.1-dev.23.json` and
`docs/VALIDATION.md`. Raw packet captures and device logs remain in the private
development workspace and are not distributed in the source repository.
Permanent dev.23 tests covered complete listings before/after mutations and
259 names across multiple directory replies, including spaces and Unicode.

Plain FTP and trusted-certificate FTPS also passed 1 MiB/range/read/write/rename/
mkdir/delete checks. This release uses implicit `ftps://`, rather than explicit
AUTH TLS. Its UI has no self-signed certificate exception. Tests temporarily
bound a synthetic CA directory, verified encrypted control/data operations,
then removed that bind and confirmed the same valid-name certificate was
rejected. No fixture CA remains trusted. The public validation matrix summarizes the FTP/FTPS result.
