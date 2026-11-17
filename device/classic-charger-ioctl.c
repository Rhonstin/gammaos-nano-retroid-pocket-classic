/* Classic-only compatibility for the native charger's DRM handoff and panel
 * light. No private Android C++ ABI; Bionic supplies the thread-local errno. */
#if !defined(__aarch64__) && !defined(CLASSIC_CHARGER_TEST)
#error arm64 only
#endif
extern int *__errno(void);

#if defined(CLASSIC_CHARGER_TEST)
extern long classic_charger_test_raw(long nr, long a, long b, long c);
#define raw classic_charger_test_raw
#else
static long raw(long nr, long a, long b, long c) {
    register long x8 __asm__("x8") = nr;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2) : "memory", "cc");
    return x0;
}
#endif

static char *text(char *p, const char *s) {
    while (*s) *p++ = *s++;
    return p;
}

static char *hex(char *p, unsigned long n) {
    p = text(p, "0x");
    for (int bit = 60; bit >= 0; bit -= 4) *p++ = "0123456789abcdef"[(n >> bit) & 15];
    return p;
}

#include "classic-charger-atomic.h"

static unsigned int saved_brightness = 150;
static unsigned int owned_crtc;
static unsigned int attempted_crtc;
static const char brightness_path[] = "/sys/class/backlight/panel0-backlight/brightness";

static void remember_brightness(void) {
    long fd = raw(56, -100, (long)brightness_path, 02000000);
    if (fd < 0) return;
    char buffer[16]; long n = raw(63, fd, (long)buffer, sizeof(buffer));
    raw(57, fd, 0, 0);
    unsigned int value = 0;
    for (long i = 0; i < n && buffer[i] >= '0' && buffer[i] <= '9'; i++) {
        value = value * 10 + buffer[i] - '0';
        if (value > 4095) return;
    }
    if (value) saved_brightness = value;
}

static long backlight(unsigned int value) {
    long fd = raw(56, -100, (long)brightness_path, 1 | 02000000);
    if (fd < 0) return fd;
    char buffer[6], reverse[4]; unsigned int n = 0, count = 0;
    do { reverse[count++] = '0' + value % 10; value /= 10; } while (value && count < 4);
    while (count) buffer[n++] = reverse[--count];
    buffer[n++] = '\n';
    long result = raw(64, fd, (long)buffer, n);
    raw(57, fd, 0, 0);
    return result == n ? 0 : (result < 0 ? result : -5);
}

int ioctl(int fd, int request, ...) {
    __builtin_va_list args;
    __builtin_va_start(args, request);
    void *arg = __builtin_va_arg(args, void *);
    __builtin_va_end(args);
    long result;
    if ((unsigned int)request == CC_SETCRTC && arg) {
        const struct drm_mode_crtc *crtc = arg;
        if (crtc->mode_valid && crtc->fb_id) {
            attempted_crtc = crtc->crtc_id;
            remember_brightness();
            result = control(fd, CC_SETCRTC, arg);
            if (result == -22) {
                result = atomic_modeset(fd, crtc);
                char message[96], *p = text(message, "<6>ClassicChargerIoctl: atomic modeset result=");
                p = hex(p, result); *p++ = '\n'; raw(64, 2, (long)message, p - message);
            }
            if (!result) {
                owned_crtc = crtc->crtc_id;
                long light = backlight(saved_brightness);
                char message[96], *p = text(message, "<6>ClassicChargerIoctl: restore backlight result=");
                p = hex(p, light); *p++ = '\n'; raw(64, 2, (long)message, p - message);
            }
        } else if (owned_crtc == crtc->crtc_id && !crtc->mode_valid && !crtc->fb_id) {
            /* SDE's continuous-splash handoff cannot survive a legacy CRTC
             * teardown. Keep scanout valid and control the actual panel light. */
            remember_brightness();
            result = backlight(0);
            char message[96], *p = text(message, "<6>ClassicChargerIoctl: blank backlight result=");
            p = hex(p, result); *p++ = '\n'; raw(64, 2, (long)message, p - message);
        } else if (attempted_crtc == crtc->crtc_id && !owned_crtc && !crtc->mode_valid && !crtc->fb_id) {
            /* Failed handoff: leave the previous owner's scanout and light
             * alone. In particular, a full Android HWC client may own DRM. */
            result = 0;
        } else result = control(fd, CC_SETCRTC, arg);
        char buffer[256], *p = text(buffer, "<6>ClassicChargerIoctl: SETCRTC fd=");
        p = hex(p, fd); p = text(p, " crtc="); p = hex(p, crtc->crtc_id);
        p = text(p, " fb="); p = hex(p, crtc->fb_id);
        p = text(p, " mode_valid="); p = hex(p, crtc->mode_valid);
        p = text(p, " flags="); p = hex(p, crtc->mode.flags);
        p = text(p, " result="); p = hex(p, result); *p++ = '\n';
        raw(64, 2, (long)buffer, p - buffer);
    } else result = raw(29, fd, (unsigned int)request, (long)arg);
    if (result < 0) { *__errno() = (int)-result; return -1; }
    return (int)result;
}
