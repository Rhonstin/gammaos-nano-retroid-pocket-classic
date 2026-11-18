#!/system/bin/sh
# Repair optional split-APK installation only after the main installer settles.
set -u
PACKAGE=com.magneticchen.daijishou
[ "$(getprop ro.product.vendor.device)" = parrot ] || exit 2
[ "$(getprop persist.gammaos.setupwizard_done)" = 1 ] ||
    [ "$(getprop persist.gammaos.nano.setup_done)" = 1 ] || exit 0
STATE=/data/misc/classic
mkdir -p "$STATE" || exit 1

# Configs copied through root ADB/FUSE can acquire storage_file and root ownership.
# RetroArch then cannot read its profile and silently starts with defaults.
retro=/data/user/0/com.retroarch.aarch64
cfg=/data/media/0/Android/data/com.retroarch.aarch64/files/retroarch.cfg
if [ -d "$retro" ] && [ -f "$cfg" ]; then
    uid=$(stat -c '%u' "$retro") || exit 1
    chown "$uid:1078" "$cfg" || exit 1
    chmod 0660 "$cfg" || exit 1
    restorecon "$cfg" || exit 1
fi

/system/bin/sh /system/bin/classic-apps.sh || log -t ClassicProvision "Application setup will retry on next boot"
/system/bin/sh /system/bin/classic-shaders.sh || log -t ClassicProvision "Shader setup will retry on next boot"

if ! pm path "$PACKAGE" | grep -q '^package:'; then
    setprop sys.gammaos.classic.launcher_ready installing
    session=$(pm install-create -r | sed -n 's/.*\[\([0-9][0-9]*\)\].*/\1/p')
    case "$session" in ''|*[!0-9]*) exit 1;; esac
    for split in base.apk split_config.en.apk split_config.xxxhdpi.apk; do
        result=$(pm install-write "$session" "$split" "/system/etc/daijisho/$split" 2>&1)
        case "$result" in Success*) ;; *) pm install-abandon "$session"; exit 1;; esac
    done
    result=$(pm install-commit "$session" 2>&1)
    case "$result" in Success*) ;; *) exit 1;; esac
fi

if [ ! -f "$STATE/launcher_ready" ]; then
    appdir=/data/user/0/$PACKAGE
    # Restore the release's launcher profile once; retain any existing user profile.
    if [ ! -f "$appdir/shared_prefs/${PACKAGE}_preferences.xml" ]; then
        owner=$(stat -c '%u:%g' "$appdir") || exit 1
        am force-stop "$PACKAGE"
        tar -xJf /system/etc/daijisho.tar.xz -P -C / || exit 1
        chown -R "$owner" "$appdir" || exit 1
        restorecon -RF "$appdir" || exit 1
    fi
    appops set "$PACKAGE" MANAGE_EXTERNAL_STORAGE allow || exit 1
    home=$(cmd package query-activities --components -a android.intent.action.MAIN \
        -c android.intent.category.HOME -p "$PACKAGE" | grep -oE "$PACKAGE/[A-Za-z0-9_.]+" | head -n1)
    [ -n "$home" ] || exit 1
    cmd package set-home-activity "$home" || exit 1
    touch "$STATE/launcher_ready" || exit 1
fi
setprop sys.gammaos.classic.launcher_ready 1
log -t ClassicProvision 'Android launcher installed and provisioned'
