/* Preserve the vendor service's UID/domain/capabilities while retaining the
 * native charger's early stderr. Stock init discards that output here.
 * Freestanding Linux arm64 syscalls avoid any pre-APEX libc dependency. */
#if !defined(__aarch64__)
#error This entry is only for the original arm64 Pocket Classic.
#endif
enum { SYS_DUP3 = 24, SYS_OPENAT = 56, SYS_CLOSE = 57, SYS_WRITE = 64,
       SYS_EXIT = 93, SYS_EXECVE = 221 };

static long call(long nr, long a, long b, long c, long d) {
    register long x8 __asm__("x8") = nr;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3) : "memory", "cc");
    return x0;
}

__attribute__((noreturn)) void charger_entry(long *stack) {
    char **environment = (char **)(stack + stack[0] + 2);
    long fd = call(SYS_OPENAT, -100, (long)"/dev/kmsg", 1 | 02000000, 0);
    if (fd >= 0) {
        call(SYS_DUP3, fd, 1, 0, 0);
        call(SYS_DUP3, fd, 2, 0, 0);
        if (fd > 2) call(SYS_CLOSE, fd, 0, 0, 0);
    }
    static const char message[] = "<6>ClassicChargerEntry: executing original Core charger\n";
    call(SYS_WRITE, 2, (long)message, sizeof(message) - 1, 0);
    char *argv[2];
    argv[0] = "charger-core";
    argv[1] = (void *)0;
    call(SYS_EXECVE, (long)"/system/bin/charger-core", (long)argv, (long)environment, 0);
    static const char failed[] = "<3>ClassicChargerEntry: exec charger-core failed\n";
    call(SYS_WRITE, 2, (long)failed, sizeof(failed) - 1, 0);
    call(SYS_EXIT, 127, 0, 0, 0);
    for (;;) {}
}

__asm__(".global _start\n_start:\nmov x0, sp\nbl charger_entry\nb .\n");
