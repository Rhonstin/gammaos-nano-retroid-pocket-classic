#include <assert.h>
#include <errno.h>
#include <string.h>
#define CLASSIC_CHARGER_TEST 1
#define ioctl classic_test_ioctl
#include "../device/classic-charger-ioctl.c"

int *__errno(void) { return &errno; }
static int legacy_result = -13, legacy_calls, writes, light = 87;

long classic_charger_test_raw(long nr, long a, long b, long c) {
    switch (nr) {
    case 29:
        if ((unsigned int)b == CC_SETCRTC) { legacy_calls++; return legacy_result; }
        assert((unsigned int)b == 0x1234); return -7;
    case 56: assert(a == -100 && !strcmp((const char *)b, brightness_path)); return 8;
    case 57: assert(a == 8); return 0;
    case 63: {
        assert(a == 8 && c >= 4);
        char *p = (void *)b;
        if (light == 87) { memcpy(p, "87\n", 3); return 3; }
        assert(light == 0); memcpy(p, "0\n", 2); return 2;
    }
    case 64:
        if (a == 2) return c; /* Diagnostic log, not hardware. */
        assert(a == 8); writes++;
        if (c == 2 && !memcmp((const void *)b, "0\n", 2)) light = 0;
        else { assert(c == 3 && !memcmp((const void *)b, "87\n", 3)); light = 87; }
        return c;
    default: assert(!"Unexpected hardware operation"); return -1;
    }
}

int main(void) {
    struct drm_mode_crtc request = {0}; request.crtc_id = 14;
    request.mode_valid = 1; request.fb_id = 128;
    assert(classic_test_ioctl(9, CC_SETCRTC, &request) == -1 && errno == 13);
    assert(writes == 0 && legacy_calls == 1);
    request.mode_valid = request.fb_id = 0;
    assert(classic_test_ioctl(9, CC_SETCRTC, &request) == 0);
    assert(writes == 0 && legacy_calls == 1 && light == 87);

    legacy_result = 0; request.mode_valid = 1; request.fb_id = 128;
    assert(classic_test_ioctl(9, CC_SETCRTC, &request) == 0);
    assert(writes == 1 && legacy_calls == 2 && light == 87);
    request.mode_valid = request.fb_id = 0;
    assert(classic_test_ioctl(9, CC_SETCRTC, &request) == 0);
    assert(writes == 2 && legacy_calls == 2 && light == 0);
    request.mode_valid = 1; request.fb_id = 128;
    assert(classic_test_ioctl(9, CC_SETCRTC, &request) == 0);
    assert(writes == 3 && legacy_calls == 3 && light == 87);
    assert(classic_test_ioctl(9, 0x1234, (void *)0) == -1 && errno == 7);
    assert(writes == 3 && legacy_calls == 3 && light == 87);
    return 0;
}
