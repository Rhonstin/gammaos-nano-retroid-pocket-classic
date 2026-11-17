#!/system/bin/sh
# Called after Nano's setup restores the bundled emulator profiles.
set -eu
umask 077
[ "$(getprop ro.product.vendor.device)" = parrot ] || exit 2
[ "$(od -An -tx1 -N8 /sys/firmware/devicetree/base/qcom,board-id | tr -d ' \n')" = 0000002200000000 ] || exit 2
[ "$(getprop persist.gammaos.setupwizard_done)" = 1 ] ||
    [ "$(getprop persist.gammaos.nano.setup_done)" = 1 ] || exit 0

state=/data/misc/classic
mkdir -p "$state"
ra=/data/user/0/com.retroarch.aarch64
media=/data/media/0
config="$media/RetroArch/config"
cfg="$media/Android/data/com.retroarch.aarch64/files/retroarch.cfg"
psp="$media/PSP/SYSTEM/ppsspp.ini"
tmp=
trap '[ -z "$tmp" ] || rm -f "$tmp"' EXIT

copy_context() {
    context=$(ls -Zd "$1" | awk 'NR == 1 {print $1}')
    case "$context" in u:object_r:*) chcon "$context" "$2";; *) return 1;; esac
}

config_value() {
    sed -n 's/^'"$1"' = "\([^"]*\)"$/\1/p' "$2" | tail -n 1
}

ra_ready() {
    [ -d "$config" ] && [ ! -L "$config" ] && [ -f "$cfg" ] &&
        [ -d "$ra/shaders/shaders_slang" ] &&
        ! pidof com.retroarch.aarch64 >/dev/null &&
        [ "$(config_value rgui_config_directory "$cfg")" = /storage/emulated/0/RetroArch/config ] &&
        [ "$(config_value auto_shaders_enable "$cfg")" = true ]
}

# Filter names and paths come from this fixed table, not from user settings.
if [ ! -f "$state/shaders-ra-v2" ] && ra_ready; then
default_driver=$(config_value video_driver "$cfg")
while IFS='|' read -r core preset; do
    [ -n "$core" ] || continue
    # On a dev.24 installation only migrate GBA presets we previously wrote.
    if [ -f "$state/shaders-ra-v1" ] && [ "$preset" != handheld/lcd-grid-v2-gba-color ]; then
        continue
    fi
    folder="$config/$core"
    [ ! -L "$folder" ] || continue
    override="$folder/$core.cfg"
    driver=$default_driver
    if [ -f "$override" ]; then
        local_driver=$(sed -n 's/^video_driver = "\([^"]*\)"$/\1/p' "$override" | tail -n 1)
        driver=${local_driver:-$driver}
        grep -q '^video_shader_enable = "false"' "$override" && continue
    fi
    case "$driver" in
        vulkan|glcore) format=slang;;
        gl) format=glsl;;
        *) continue;;
    esac
    target="$ra/shaders/shaders_$format/$preset.${format}p"
    [ -f "$target" ] || continue
    file="$folder/$core.${format}p"
    [ ! -L "$file" ] || continue
    repair=0
    if [ -f "$file" ]; then
        previous="#reference \"$ra/shaders/shaders_$format/handheld/lcd-grid-v2.${format}p\""
        if [ "$preset" = handheld/lcd-grid-v2-gba-color ] && [ "$(cat "$file")" = "$previous" ]; then
            repair=1
        else
        case "$core:$format" in
            mGBA:slang|SwanStation:slang)
                broken='#reference "/data/user/0/com.retroarch.aarch64/shaders/SHARP_SHIMMERLESS.slangp"'
                [ ! -e "$ra/shaders/SHARP_SHIMMERLESS.slangp" ] &&
                    [ "$(cat "$file")" = "$broken" ] || continue
                repair=1;;
            *) continue;;
        esac
        fi
    elif [ -f "$state/shaders-ra-v1" ]; then
        # A deleted preset on an already configured device is intentional.
        continue
    elif [ -e "$folder/$core.slangp" ] || [ -e "$folder/$core.glslp" ]; then
        continue
    fi
    # Do not overshadow a user's global preset with new core-specific defaults.
    if [ "$repair" = 0 ]; then
        [ ! -e "$config/global.slangp" ] && [ ! -e "$config/global.glslp" ] || continue
        grep -q '^video_shader_enable = "true"' "$cfg" || continue
    fi
    owner=$(stat -c %u "$ra")
    if [ ! -d "$folder" ]; then
        mkdir -m 0770 "$folder"
        chown "$owner:$(stat -c %g "$config")" "$folder"
        copy_context "$config" "$folder"
    fi
    tmp=$(mktemp "$folder/.classic-shader-XXXXXX")
    printf '#reference "%s"\n' "$target" > "$tmp"
    chown "$owner:$(stat -c %g "$folder")" "$tmp"
    chmod 0660 "$tmp"
    if [ "$repair" = 1 ]; then
        copy_context "$file" "$tmp"
        # Rename via the emulated-storage view so open/stat do not retain
        # the old preset's length in Android's FUSE cache.
        mv -f "/storage/emulated/0/${tmp#"$media/"}" "/storage/emulated/0/${file#"$media/"}"
    else
        copy_context "$folder" "$tmp"
        ln "$tmp" "$file"
        rm -f "$tmp"
    fi
    tmp=
    log -t ClassicShaders "$core: $preset ($format)"
done <<'PRESETS'
Gambatte|handheld/lcd-grid-v2
SameBoy|handheld/lcd-grid-v2
Gearboy|handheld/lcd-grid-v2
TGB Dual|handheld/lcd-grid-v2
mGBA|handheld/lcd-grid-v2-gba-color
gpSP|handheld/lcd-grid-v2-gba-color
VBA-M|handheld/lcd-grid-v2-gba-color
VBA Next|handheld/lcd-grid-v2-gba-color
Gearsystem|interpolation/sharp-bilinear
Beetle Lynx|handheld/lcd-grid-v2
Handy|handheld/lcd-grid-v2
Beetle NeoPop|handheld/lcd-grid-v2
Beetle WonderSwan|handheld/lcd-grid-v2
DeSmuME|interpolation/sharp-bilinear
DeSmuME 2015|interpolation/sharp-bilinear
melonDS|interpolation/sharp-bilinear
melonDS DS|interpolation/sharp-bilinear
FCEUmm|crt/crt-easymode
Nestopia|crt/crt-easymode
QuickNES|crt/crt-easymode
Mesen|crt/crt-easymode
Snes9x|crt/crt-easymode
Snes9x 2002|crt/crt-easymode
Snes9x 2005|crt/crt-easymode
Snes9x 2005 Plus|crt/crt-easymode
Snes9x 2010|crt/crt-easymode
bsnes|crt/crt-easymode
bsnes 2014 Accuracy|crt/crt-easymode
bsnes 2014 Balanced|crt/crt-easymode
bsnes 2014 Performance|crt/crt-easymode
Genesis Plus GX|crt/crt-easymode
Genesis Plus GX Wide|interpolation/sharp-bilinear
PicoDrive|crt/crt-easymode
SMS Plus GX|crt/crt-easymode
Beetle PCE Fast|crt/crt-easymode
Beetle PCE|crt/crt-easymode
Beetle SuperGrafx|crt/crt-easymode
FinalBurn Neo|crt/crt-easymode
MAME 2003-Plus|crt/crt-easymode
PCSX-ReARMed|interpolation/sharp-bilinear
Beetle PSX|interpolation/sharp-bilinear
SwanStation|interpolation/sharp-bilinear
FAKE-08|interpolation/sharp-bilinear
PRESETS
    touch "$state/shaders-ra-v1" "$state/shaders-ra-v2"
fi

# PPSSPP 1.20.3 has a built-in output-resolution scaler. Leave customized
# chains, game overrides, renderer and internal resolution intact.
if [ ! -f "$state/shaders-ppsspp-v1" ] && [ -f "$psp" ] && [ ! -L "$psp" ] &&
    ! pidof org.ppsspp.ppsspp >/dev/null; then
    if ! grep -Eq '^[[:space:]]*\[PostShader(List|Setting)\]' "$psp" &&
        grep -Eq '^InternalResolution[[:space:]]*=[[:space:]]*1[[:space:]]*$' "$psp"; then
        tmp=$(mktemp "${psp%/*}/.classic-shader-XXXXXX")
        cat "$psp" > "$tmp"
        printf '\n[PostShaderList]\nPostShader1 = UpscaleSharpBilinear\n' >> "$tmp"
        chown "$(stat -c %u:%g "$psp")" "$tmp"
        chmod "$(stat -c %a "$psp")" "$tmp"
        copy_context "$psp" "$tmp"
        mv -f "/storage/emulated/0/${tmp#"$media/"}" "/storage/emulated/0/${psp#"$media/"}"
        tmp=
        log -t ClassicShaders 'PPSSPP: UpscaleSharpBilinear'
    fi
    touch "$state/shaders-ppsspp-v1"
fi
