#include <assert.h>
#include <string.h>

static long raw(long nr, long fd, long request, long arg);
#include "../device/classic-charger-atomic.h"

static int fault, atomic_calls, blobs, destroys;
static const char *keys[] = {"ACTIVE", "MODE_ID", "CRTC_ID", "FB_ID", "type",
    "SRC_X", "SRC_Y", "SRC_W", "SRC_H", "CRTC_X", "CRTC_Y", "CRTC_W", "CRTC_H"};

static long raw(long nr, long fd, long request, long arg) {
    (void)fd; assert(nr == 29);
    void *data = (void *)arg;
    switch ((unsigned int)request) {
    case CC_SET_CLIENT_CAP: return 0;
    case CC_GETRESOURCES: {
        struct drm_mode_card_res *p = data;
        __u32 *ids = (void *)(unsigned long)p->crtc_id_ptr;
        ids[0] = 14; ids[1] = 99; p->count_crtcs = fault == 5 ? 33 : 2;
        return 0;
    }
    case CC_GETPLANERESOURCES: {
        struct drm_mode_get_plane_res *p = data;
        __u32 *ids = (void *)(unsigned long)p->plane_id_ptr;
        ids[0] = 50; ids[1] = 51; ids[2] = 52; p->count_planes = 3; return 0;
    }
    case CC_GETPLANE: {
        struct drm_mode_get_plane *p = data;
        p->possible_crtcs = fault == 2 ? 0 : (p->plane_id == 52 ? 2 : 1);
        p->crtc_id = p->plane_id == 52 ? 99 : 14; return 0;
    }
    case CC_OBJ_GETPROPERTIES: {
        struct drm_mode_obj_get_properties *p = data;
        unsigned int capacity = p->count_props;
        p->count_props = fault == 1 ? 65 : sizeof(keys) / sizeof(keys[0]);
        if (p->props_ptr && p->prop_values_ptr) {
            __u32 *ids = (void *)(unsigned long)p->props_ptr;
            __u64 *values = (void *)(unsigned long)p->prop_values_ptr;
            for (unsigned int i = 0; i < capacity && i < p->count_props; i++) {
                ids[i] = p->obj_id * 16 + i + 1;
                values[i] = i == 4 && p->obj_id != 51 ? 1 : 0;
            }
        }
        return 0;
    }
    case CC_GETPROPERTY: {
        struct drm_mode_get_property *p = data;
        strcpy(p->name, keys[(p->prop_id % 16) - 1]); return 0;
    }
    case CC_CREATEPROPBLOB: {
        if (fault == 4) return -12;
        struct drm_mode_create_blob *p = data;
        assert(p->length == 68); p->blob_id = 731; blobs++; return 0;
    }
    case CC_DESTROYPROPBLOB:
        assert(((struct drm_mode_destroy_blob *)data)->blob_id == 731); destroys++; return 0;
    case CC_ATOMIC: {
        atomic_calls++;
        struct drm_mode_atomic *p = data;
        assert(p->flags == CC_ALLOW_MODESET && p->count_objs == 4);
        const __u32 *objects = (void *)(unsigned long)p->objs_ptr;
        const __u32 *counts = (void *)(unsigned long)p->count_props_ptr;
        const __u32 *properties = (void *)(unsigned long)p->props_ptr;
        const __u64 *values = (void *)(unsigned long)p->prop_values_ptr;
        const __u32 want_objects[] = {14, 66, 50, 51}, want_counts[] = {2, 1, 10, 2};
        const __u64 want_values[] = {1, 731, 14, 128, 14, 0, 0, 1080ULL << 16,
            1240ULL << 16, 0, 0, 1080, 1240, 0, 0};
        assert(!memcmp(objects, want_objects, sizeof(want_objects)));
        assert(!memcmp(counts, want_counts, sizeof(want_counts)));
        assert(!memcmp(values, want_values, sizeof(want_values)));
        unsigned int at = 0;
        for (unsigned int i = 0; i < 4; i++)
            for (unsigned int j = 0; j < counts[i]; j++) assert(properties[at++] / 16 == objects[i]);
        return fault == 3 ? -13 : 0;
    }
    default: assert(!"Unexpected ioctl or destructive legacy SETCRTC"); return -1;
    }
}

int main(void) {
    __u32 connector = 66;
    struct drm_mode_crtc crtc = {0};
    crtc.mode_valid = 1; crtc.crtc_id = 14; crtc.fb_id = 128;
    crtc.count_connectors = 1; crtc.set_connectors_ptr = (__u64)(unsigned long)&connector;
    crtc.mode.hdisplay = 1080; crtc.mode.vdisplay = 1240;
    struct drm_mode_crtc before = crtc;
    assert(atomic_modeset(9, &crtc) == 0);
    assert(atomic_calls == 1 && blobs == 1 && destroys == 1);
    assert(!memcmp(&before, &crtc, sizeof(crtc)));
    for (fault = 1; fault <= 5; fault++) {
        atomic_calls = blobs = destroys = 0;
        assert(atomic_modeset(9, &crtc) == (fault == 3 ? -13 : fault == 4 ? -12 : -22));
        assert(atomic_calls == (fault == 3));
        assert(blobs == destroys);
    }
    fault = 0; crtc.count_connectors = 2;
    assert(atomic_modeset(9, &crtc) == -22);
    return 0;
}
