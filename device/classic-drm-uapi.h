/*
 * Copyright (c) 2007 Dave Airlie <airlied@linux.ie>
 * Copyright (c) 2007 Jakob Bornecrantz <wallbraker@gmail.com>
 * Copyright (c) 2008 Red Hat Inc.
 * Copyright (c) 2007-2008 Tungsten Graphics, Inc., Cedar Park, TX., USA
 * Copyright (c) 2007-2008 Intel Corporation
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
 * IN THE SOFTWARE.
 */


/* Minimal pinned Linux DRM UAPI for the freestanding Classic charger shim. */
#pragma once
typedef unsigned short __u16;
typedef unsigned int __u32;
typedef unsigned long long __u64;
#define DRM_DISPLAY_MODE_LEN 32
#define DRM_PROP_NAME_LEN 32

struct drm_mode_modeinfo {
	__u32 clock;
	__u16 hdisplay;
	__u16 hsync_start;
	__u16 hsync_end;
	__u16 htotal;
	__u16 hskew;
	__u16 vdisplay;
	__u16 vsync_start;
	__u16 vsync_end;
	__u16 vtotal;
	__u16 vscan;

	__u32 vrefresh;

	__u32 flags;
	__u32 type;
	char name[DRM_DISPLAY_MODE_LEN];
};

struct drm_mode_card_res {
	__u64 fb_id_ptr;
	__u64 crtc_id_ptr;
	__u64 connector_id_ptr;
	__u64 encoder_id_ptr;
	__u32 count_fbs;
	__u32 count_crtcs;
	__u32 count_connectors;
	__u32 count_encoders;
	__u32 min_width;
	__u32 max_width;
	__u32 min_height;
	__u32 max_height;
};

struct drm_mode_crtc {
	__u64 set_connectors_ptr;
	__u32 count_connectors;

	__u32 crtc_id; /**< Id */
	__u32 fb_id; /**< Id of framebuffer */

	__u32 x; /**< x Position on the framebuffer */
	__u32 y; /**< y Position on the framebuffer */

	__u32 gamma_size;
	__u32 mode_valid;
	struct drm_mode_modeinfo mode;
};

struct drm_mode_get_plane {
	__u32 plane_id;

	__u32 crtc_id;
	__u32 fb_id;

	__u32 possible_crtcs;
	__u32 gamma_size;

	__u32 count_format_types;
	__u64 format_type_ptr;
};

struct drm_mode_get_plane_res {
	__u64 plane_id_ptr;
	__u32 count_planes;
};

struct drm_mode_get_property {
	__u64 values_ptr; /* values and blob lengths */
	__u64 enum_blob_ptr; /* enum and blob id ptrs */

	__u32 prop_id;
	__u32 flags;
	char name[DRM_PROP_NAME_LEN];

	__u32 count_values;
	/* This is only used to count enum values, not blobs. The _blobs is
	 * simply because of a historical reason, i.e. backwards compat. */
	__u32 count_enum_blobs;
};

struct drm_mode_obj_get_properties {
	__u64 props_ptr;
	__u64 prop_values_ptr;
	__u32 count_props;
	__u32 obj_id;
	__u32 obj_type;
};

struct drm_mode_atomic {
	__u32 flags;
	__u32 count_objs;
	__u64 objs_ptr;
	__u64 count_props_ptr;
	__u64 props_ptr;
	__u64 prop_values_ptr;
	__u64 reserved;
	__u64 user_data;
};

struct drm_mode_create_blob {
	/** @data: Pointer to data to copy. */
	__u64 data;
	/** @length: Length of data to copy. */
	__u32 length;
	/** @blob_id: Return: new property ID. */
	__u32 blob_id;
};

struct drm_mode_destroy_blob {
	__u32 blob_id;
};

struct drm_set_client_cap { __u64 capability, value; };

#define CC_DRM_IOWR(n, t) (0xc0006400U | ((unsigned int)sizeof(struct t) << 16) | (n))

#define CC_GETRESOURCES CC_DRM_IOWR(0xA0, drm_mode_card_res)

#define CC_SETCRTC CC_DRM_IOWR(0xA2, drm_mode_crtc)

#define CC_GETPROPERTY CC_DRM_IOWR(0xAA, drm_mode_get_property)

#define CC_GETPLANERESOURCES CC_DRM_IOWR(0xB5, drm_mode_get_plane_res)

#define CC_GETPLANE CC_DRM_IOWR(0xB6, drm_mode_get_plane)

#define CC_OBJ_GETPROPERTIES CC_DRM_IOWR(0xB9, drm_mode_obj_get_properties)

#define CC_ATOMIC CC_DRM_IOWR(0xBC, drm_mode_atomic)

#define CC_CREATEPROPBLOB CC_DRM_IOWR(0xBD, drm_mode_create_blob)

#define CC_DESTROYPROPBLOB CC_DRM_IOWR(0xBE, drm_mode_destroy_blob)

#define CC_SET_CLIENT_CAP (0x4000640dU | ((unsigned int)sizeof(struct drm_set_client_cap) << 16))
#define CC_OBJECT_CRTC 0xccccccccU
#define CC_OBJECT_CONNECTOR 0xc0c0c0c0U
#define CC_OBJECT_PLANE 0xeeeeeeeeU
#define CC_ALLOW_MODESET 0x0400U
_Static_assert(sizeof(struct drm_mode_crtc) == 104, "DRM CRTC UAPI");
_Static_assert(sizeof(struct drm_mode_modeinfo) == 68, "DRM mode UAPI");
_Static_assert(sizeof(struct drm_mode_obj_get_properties) == 32, "DRM property UAPI");
_Static_assert(sizeof(struct drm_mode_get_property) == 64, "DRM property metadata UAPI");
_Static_assert(sizeof(struct drm_mode_atomic) == 56, "DRM atomic UAPI");
