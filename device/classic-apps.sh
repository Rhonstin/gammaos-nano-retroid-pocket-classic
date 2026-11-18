#!/system/bin/sh
# Install or upgrade the port's bundled applications after GammaOS setup, refresh an
# existing RetroArch installation from the rebuilt payload once, add the extra Nano game
# systems and apply first-run defaults. Called by classic-provision.sh; every step is
# idempotent and keeps what the user changed.
set -u
STATE=/data/misc/classic
LIST=/system/etc/classic-apps.list
mkdir -p "$STATE"
log_line() { log -t ClassicApps "$*"; }

installed_code() {
    dumpsys package "$1" 2>/dev/null | sed -n 's/^ *versionCode=\([0-9][0-9]*\).*/\1/p' | head -n 1
}

app_uid() { stat -c %u "/data/user/0/$1" 2>/dev/null; }

grant() {
    pkg=$1; kinds=$2
    case ",$kinds," in *,storage,*)
        appops set --uid "$pkg" MANAGE_EXTERNAL_STORAGE allow 2>/dev/null
        pm grant "$pkg" android.permission.READ_EXTERNAL_STORAGE 2>/dev/null
        pm grant "$pkg" android.permission.WRITE_EXTERNAL_STORAGE 2>/dev/null;;
    esac
    case ",$kinds," in *,notifications,*)
        pm grant "$pkg" android.permission.POST_NOTIFICATIONS 2>/dev/null;;
    esac
    return 0
}

# 1. Applications: install when missing, upgrade only when ours is newer. A newer or
# differently signed copy the user installed is left alone.
pending=0
while IFS='|' read -r id pkg code apk grants; do
    case "$id" in ''|\#*) continue;; esac
    [ -f "$apk" ] || { log_line "$id: $apk missing"; continue; }
    have=$(installed_code "$pkg")
    if [ -z "$have" ] || [ "$have" -lt "$code" ]; then
        result=$(pm install -r "$apk" 2>&1)
        case "$result" in
            *Success*) log_line "$id: installed $code (was ${have:-none})";;
            *) log_line "$id: install failed: $result"; pending=1; continue;;
        esac
    fi
    grant "$pkg" "$grants"
done < "$LIST"

# 2. RetroArch: setup.sh extracts the payload only on first boot. An installation that
# predates this image gets the payload's cores, info, assets, autoconfig, databases,
# overlays and shaders once; configuration, saves and states are never touched.
payload=/system/etc/retroarch.tar.xz
stamp=$(cat /system/etc/classic-retroarch-payload.sha256 2>/dev/null)
ra=/data/user/0/com.retroarch.aarch64
if [ -n "$stamp" ] && [ -d "$ra" ] && [ "$(cat "$STATE/retroarch-payload" 2>/dev/null)" != "$stamp" ]; then
    owner=$(stat -c %u:%g "$ra")
    am force-stop com.retroarch.aarch64
    members=""
    for dir in cores info assets autoconfig database overlays shaders; do
        members="$members data/data/com.retroarch.aarch64/$dir"
    done
    # shellcheck disable=SC2086 # members is a fixed list of archive paths
    if tar -xJf "$payload" -C / $members; then
        for dir in cores info assets autoconfig database overlays shaders; do
            chown -R "$owner" "$ra/$dir"
        done
        restorecon -R "$ra" >/dev/null 2>&1
        echo "$stamp" > "$STATE/retroarch-payload"
        log_line "RetroArch payload refreshed ($stamp)"
    else
        log_line "RetroArch payload refresh failed; retrying next boot"
        pending=1
    fi
fi

# 3. Nano game systems (Steam, PS2, GameCube, Wii, 3DS, Switch, Saturn) and the
# conditional PlayStation core migration. Exit 3: Nano has not seeded its config yet.
# Create folders through the emulated-storage view so MediaProvider owns them.
for dir in steam ps2 gc wii n3ds switch saturn psvita; do
    [ -d "/data/media/0/ROMs/$dir" ] || mkdir -p "/storage/emulated/0/ROMs/$dir"
done
CLASSPATH=/system/framework/classic-systems.jar app_process /system/bin ClassicSystems \
    /system/etc/classic-systems.json /data/system/nano_systems.json \
    "$STATE/nano-systems.json" /data/system/packages.list "$ra/cores" 2>&1 |
    while IFS= read -r line; do log_line "$line"; done
restorecon /data/system/nano_systems.json >/dev/null 2>&1

# 4. First-run defaults that need no user decision.
# DroidDeck: Android 14 child-process limit off, and export the Steam library as
# Nano-launchable .steam files into ROMs/steam (written once; the user may change it).
if pm path com.droiddeck.launcher >/dev/null 2>&1; then
    settings put global settings_enable_monitor_phantom_procs false
    prefs=/data/user/0/com.droiddeck.launcher/shared_prefs
    uid=$(app_uid com.droiddeck.launcher)
    if [ -n "$uid" ] && [ ! -f "$STATE/droiddeck-gamefiles" ] && [ ! -f "$prefs/game_files.xml" ]; then
        am force-stop com.droiddeck.launcher
        mkdir -p "$prefs"
        printf '%s\n' "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>" '<map>' \
            '    <string name="folder">/storage/emulated/0/ROMs/steam</string>' '</map>' > "$prefs/game_files.xml"
        chown "$uid:$uid" "$prefs" "$prefs/game_files.xml"
        chmod 0771 "$prefs"; chmod 0660 "$prefs/game_files.xml"
        restorecon -R "$prefs" >/dev/null 2>&1
        touch "$STATE/droiddeck-gamefiles"
        log_line "DroidDeck game files folder: ROMs/steam"
    fi
fi

# Emulator profiles captured on a configured Classic (controller mapping for the GammaPad
# "Xbox Wireless Controller", touch overlay hidden, Classic screen layout). A profile is
# applied once, only while its marker file is absent (the emulator was never configured).
# profile.list: "marker|<path>" then "<target path>|<file in the profile directory>".
place() {
    target=$1 source=$2 uid=$3
    case "$target" in
        /data/user/0/*) group=$uid dmode=0771;;
        /data/media/0/Android/data/*) group=ext_data_rw dmode=2770;;
        /data/media/0/*) group=media_rw dmode=2770;;
        *) return 1;;
    esac
    # Create missing ancestors below the app's own directory with the app's ownership.
    dir=${target%/*} missing=""
    while [ ! -d "$dir" ]; do missing="$dir $missing"; dir=${dir%/*}; done
    for dir in $missing; do
        mkdir "$dir" && chown "$uid:$group" "$dir" && chmod "$dmode" "$dir" || return 1
    done
    cat "$source" > "$target.classic" && chown "$uid:$group" "$target.classic" &&
        chmod 0660 "$target.classic" && mv -f "$target.classic" "$target" || return 1
    restorecon -R "${missing%% *}" "$target" >/dev/null 2>&1
    return 0
}
for profile in /system/etc/classic-profiles/*/profile.list; do
    [ -f "$profile" ] || continue
    root=${profile%/profile.list}
    pkg=${root##*/}
    [ -f "$STATE/profile-$pkg" ] && continue
    pm path "$pkg" >/dev/null 2>&1 || continue
    uid=$(app_uid "$pkg")
    [ -n "$uid" ] || continue
    marker=$(sed -n 's/^marker|//p' "$profile")
    if [ -n "$marker" ] && [ ! -e "$marker" ]; then
        am force-stop "$pkg"
        ok=1
        while IFS='|' read -r target source; do
            case "$target" in ''|marker) continue;; esac
            place "$target" "$root/$source" "$uid" || { ok=0; log_line "$pkg: cannot place $target"; }
        done < "$profile"
        [ "$ok" = 1 ] || continue
        log_line "$pkg: Classic profile applied"
    fi
    touch "$STATE/profile-$pkg"
done

# Debug counters off: Flycast's FPS readout (enabled by GammaOS's flycast.tar.xz) and
# Eden's performance bar. Each single key is rewritten once, in place (owner and label
# kept), as soon as the emulator's own config exists; the owner may re-enable it later.
tweak() {
    name=$1 file=$2 expr=$3
    [ -f "$STATE/tweak-$name" ] && return 0
    [ -f "$file" ] || return 0
    sed "$expr" "$file" > "$STATE/tweak.tmp" && cat "$STATE/tweak.tmp" > "$file" || {
        rm -f "$STATE/tweak.tmp"; log_line "$name: cannot rewrite $file"; return 0; }
    rm -f "$STATE/tweak.tmp"
    touch "$STATE/tweak-$name"
    log_line "$name: applied"
}
tweak flycast-fps /data/media/0/Android/data/com.flycast.emulator/files/emu.cfg \
    's/^rend\.ShowFPS = yes$/rend.ShowFPS = no/'
tweak eden-perf-overlay /data/media/0/Android/data/dev.legacy.eden_emulator/files/config/config.ini \
    's/^show_performance_overlay\\default=true$/show_performance_overlay\\default=false/;s/^show_performance_overlay=true$/show_performance_overlay=false/'

# Eden on the Adreno 613: the stock Vulkan driver crashes its VulkanWorker and NCE
# crashes commercial titles. Once Eden has written its config, select the bundled Mesa
# Turnip package and the Dynarmic CPU backend, but only where the setting is still the
# default (a choice the owner made is kept). The driver zip gets the app's own owner and
# SELinux category label, as files root writes elsewhere are unreadable to the app.
eden_defaults() {
    eden=/data/media/0/Android/data/dev.legacy.eden_emulator/files
    driver=/system/etc/classic-drivers/turnip-axfl3-003-android.zip
    config=$eden/config/config.ini
    [ -f "$STATE/tweak-eden-defaults" ] && return 0
    [ -f "$config" ] && [ -f "$driver" ] || return 0
    owner=$(stat -c %u:%g "$eden") label=$(ls -Zd "$eden" | cut -d' ' -f1)
    mkdir -p "$eden/gpu_drivers" && chown "$owner" "$eden/gpu_drivers" && chcon "$label" "$eden/gpu_drivers"
    target=$eden/gpu_drivers/${driver##*/}
    cat "$driver" > "$target.classic" && chown "$owner" "$target.classic" && chmod 0660 "$target.classic" &&
        chcon "$label" "$target.classic" && mv -f "$target.classic" "$target" || {
        log_line "eden-defaults: cannot place driver"; return 0; }
    app_path=/storage/emulated/0/Android/data/dev.legacy.eden_emulator/files/gpu_drivers/${driver##*/}
    am force-stop dev.legacy.eden_emulator
    tweak eden-defaults "$config" \
        "/^driver_path\\\\default=true\$/{s//driver_path\\\\default=false/;n;s#^driver_path=\$#driver_path=$app_path#;}
/^cpu_backend\\\\default=true\$/{s//cpu_backend\\\\default=false/;n;s/^cpu_backend=1\$/cpu_backend=0/;}"
}
eden_defaults

[ "$pending" = 0 ] && touch "$STATE/apps-v1"
exit 0
