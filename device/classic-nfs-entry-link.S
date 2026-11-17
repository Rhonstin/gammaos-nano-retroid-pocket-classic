/* Equivalent of the standard libnfs zdr_entry3 final field:
 * zdr_pointer(zdrs, &objp->nextentry, sizeof(entry3), zdr_entry3).
 * This snippet replaces only the broken loop tail in the pinned Core ELF.
 * x20 = zdrs, x19 = objp; preserve the original frame and canary checks.
 * Assemble at 0x4cc84; resolve original_zdr_entry3=0x4cc18 and
 * original_zdr_pointer=0x5d420 (the original ELF's PLT entry).
 */
.text
.global classic_nfs_entry_link
classic_nfs_entry_link:
    mov x0, x20
    add x1, x19, #24
    mov w2, #32
    adr x3, original_zdr_entry3
    bl original_zdr_pointer
    nop
    nop
