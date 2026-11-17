/*
 * Copyright (C) 2026 GammaOS
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/*
 * Bounded C adaptation of NanoMenuDrm.cpp::drmAtomicModesetFallback from pinned
 * upstream fb4ecbf9ec9436b511c4978a90718e851bdf89ed. Only the original Classic's
 * single display is handled. Never disable its CRTC before the atomic handoff.
 */
#include "classic-drm-uapi.h"

static long control(int fd, unsigned int request, void *data) {
    return raw(29, fd, request, (long)data);
}

static int equal(const char *a, const char *b) {
    for (unsigned int i = 0; i < 32; i++) {
        if (a[i] != b[i]) return 0;
        if (!a[i]) return 1;
    }
    return 0;
}

static __u32 property(int fd, __u32 object, __u32 type, const char *name, __u64 *value) {
    struct drm_mode_obj_get_properties p = {0};
    p.obj_id = object; p.obj_type = type;
    if (control(fd, CC_OBJ_GETPROPERTIES, &p) < 0 || p.count_props > 64) return 0;
    __u32 ids[64]; __u64 values[64];
    p.props_ptr = (__u64)(unsigned long)ids;
    p.prop_values_ptr = (__u64)(unsigned long)values;
    if (control(fd, CC_OBJ_GETPROPERTIES, &p) < 0 || p.count_props > 64) return 0;
    for (__u32 i = 0; i < p.count_props; i++) {
        struct drm_mode_get_property info = {0}; info.prop_id = ids[i];
        if (control(fd, CC_GETPROPERTY, &info) >= 0 && equal(info.name, name)) {
            if (value) *value = values[i];
            return ids[i];
        }
    }
    return 0;
}

struct cc_commit {
    __u32 objects[67], counts[67], properties[160];
    __u64 values[160];
    unsigned int objects_used, properties_used;
};

static int add(struct cc_commit *c, __u32 object, __u32 prop, __u64 value) {
    if (!prop || c->properties_used >= 160) return 0;
    if (!c->objects_used || c->objects[c->objects_used - 1] != object) {
        if (c->objects_used >= 67) return 0;
        c->objects[c->objects_used] = object;
        c->counts[c->objects_used++] = 0;
    }
    c->properties[c->properties_used] = prop;
    c->values[c->properties_used++] = value;
    c->counts[c->objects_used - 1]++;
    return 1;
}

static long atomic_modeset(int fd, const struct drm_mode_crtc *crtc) {
    if (!crtc->mode_valid || !crtc->fb_id || crtc->count_connectors != 1 ||
        !crtc->set_connectors_ptr || !crtc->mode.hdisplay || !crtc->mode.vdisplay) return -22;
    struct drm_set_client_cap cap = {2, 1};
    if (control(fd, CC_SET_CLIENT_CAP, &cap) < 0) return -22;
    cap.capability = 3;
    if (control(fd, CC_SET_CLIENT_CAP, &cap) < 0) return -22;

    __u32 crtcs[32] = {0};
    struct drm_mode_card_res resources = {0};
    resources.count_crtcs = 32; resources.crtc_id_ptr = (__u64)(unsigned long)crtcs;
    if (control(fd, CC_GETRESOURCES, &resources) < 0 || resources.count_crtcs > 32) return -22;
    unsigned int index = 32;
    for (unsigned int i = 0; i < resources.count_crtcs; i++) if (crtcs[i] == crtc->crtc_id) index = i;
    if (index == 32) return -22;

    __u32 plane_ids[64] = {0};
    struct drm_mode_get_plane_res pr = {0};
    pr.count_planes = 64; pr.plane_id_ptr = (__u64)(unsigned long)plane_ids;
    if (control(fd, CC_GETPLANERESOURCES, &pr) < 0 || pr.count_planes > 64) return -22;
    struct cc_plane { __u32 id, possible, bound, fb_prop, crtc_prop; __u64 type; } planes[64] = {0};
    unsigned int count = 0, selected = 64;
    for (unsigned int i = 0; i < pr.count_planes; i++) {
        struct drm_mode_get_plane p = {0}; p.plane_id = plane_ids[i];
        if (control(fd, CC_GETPLANE, &p) < 0) continue;
        struct cc_plane *v = &planes[count++];
        v->id = p.plane_id; v->possible = p.possible_crtcs; v->bound = p.crtc_id;
        property(fd, v->id, CC_OBJECT_PLANE, "type", &v->type);
        v->fb_prop = property(fd, v->id, CC_OBJECT_PLANE, "FB_ID", 0);
        v->crtc_prop = property(fd, v->id, CC_OBJECT_PLANE, "CRTC_ID", 0);
    }
    /* Prefer the kernel's primary plane, and do not borrow another CRTC's plane. */
    for (unsigned int pass = 0; pass < 3 && selected == 64; pass++) {
        for (unsigned int i = 0; i < count; i++) {
            struct cc_plane *p = &planes[i];
            if (!(p->possible & (1U << index)) || (p->bound && p->bound != crtc->crtc_id)) continue;
            if ((pass == 0 && p->type == 1 && p->bound == crtc->crtc_id) ||
                (pass == 1 && p->type == 1) || pass == 2) { selected = i; break; }
        }
    }
    if (selected == 64) return -22;

    struct drm_mode_create_blob blob = {0};
    blob.data = (__u64)(unsigned long)&crtc->mode; blob.length = sizeof(crtc->mode);
    long result = control(fd, CC_CREATEPROPBLOB, &blob);
    if (result < 0) return result;
    struct cc_commit c = {0};
    __u32 conn = *(__u32 *)(unsigned long)crtc->set_connectors_ptr;
    __u32 plane = planes[selected].id;
    int valid = 1;
#define SET(object, kind, key, value) (valid &= add(&c, object, property(fd, object, kind, key, 0), value))
    SET(crtc->crtc_id, CC_OBJECT_CRTC, "ACTIVE", 1);
    SET(crtc->crtc_id, CC_OBJECT_CRTC, "MODE_ID", blob.blob_id);
    SET(conn, CC_OBJECT_CONNECTOR, "CRTC_ID", crtc->crtc_id);
    SET(plane, CC_OBJECT_PLANE, "FB_ID", crtc->fb_id);
    SET(plane, CC_OBJECT_PLANE, "CRTC_ID", crtc->crtc_id);
    SET(plane, CC_OBJECT_PLANE, "SRC_X", (__u64)crtc->x << 16);
    SET(plane, CC_OBJECT_PLANE, "SRC_Y", (__u64)crtc->y << 16);
    SET(plane, CC_OBJECT_PLANE, "SRC_W", (__u64)crtc->mode.hdisplay << 16);
    SET(plane, CC_OBJECT_PLANE, "SRC_H", (__u64)crtc->mode.vdisplay << 16);
    SET(plane, CC_OBJECT_PLANE, "CRTC_X", 0);
    SET(plane, CC_OBJECT_PLANE, "CRTC_Y", 0);
    SET(plane, CC_OBJECT_PLANE, "CRTC_W", crtc->mode.hdisplay);
    SET(plane, CC_OBJECT_PLANE, "CRTC_H", crtc->mode.vdisplay);
#undef SET
    for (unsigned int i = 0; i < count; i++) {
        if (i == selected || planes[i].bound != crtc->crtc_id) continue;
        valid &= add(&c, planes[i].id, planes[i].fb_prop, 0);
        valid &= add(&c, planes[i].id, planes[i].crtc_prop, 0);
    }
    struct drm_mode_atomic request = {0};
    request.flags = CC_ALLOW_MODESET; request.count_objs = c.objects_used;
    request.objs_ptr = (__u64)(unsigned long)c.objects;
    request.count_props_ptr = (__u64)(unsigned long)c.counts;
    request.props_ptr = (__u64)(unsigned long)c.properties;
    request.prop_values_ptr = (__u64)(unsigned long)c.values;
    result = valid ? control(fd, CC_ATOMIC, &request) : -22;
    /* The successful commit holds its own reference; drop the userspace blob. */
    struct drm_mode_destroy_blob destroy = {blob.blob_id};
    control(fd, CC_DESTROYPROPBLOB, &destroy);
    return result;
}
