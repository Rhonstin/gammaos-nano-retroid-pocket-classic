#!/system/bin/sh
# Nano's native power action bypasses ShutdownThread. Flush the latest CE save
# to the DE resume cache after Nano has gracefully closed RetroArch.
set -u
case "${1:-}" in reboot|shutdown) action=$1;; *) exit 2;; esac
[ "$(getprop ro.product.vendor.device)" = parrot ] || exit 2
board=$(od -An -tx1 -N8 /sys/firmware/devicetree/base/qcom,board-id | tr -d ' \n')
[ "$board" = 0000002200000000 ] || exit 2

if [ "$(getprop persist.gammaos.nano.qr_prepared)" = 1 ] &&
        [ "$(getprop persist.gammaos.nano.quick_resume)" != 0 ]; then
    # A launch-time populate must finish before starting a second cache writer.
    tries=0
    while [ "$(getprop init.svc.nano_cache_populate)" = running ] ||
            [ "$(getprop init.svc.nano_cache_sync_to_cache)" = running ]; do
        [ "$tries" -lt 100 ] || {
            log -p e -t ClassicPower 'Cache writer did not finish; cancelling power action'
            exit 1
        }
        sleep .1
        tries=$((tries+1))
    done
    /system/bin/sh /system/bin/nano_cache.sh sync_to_cache || {
        log -p e -t ClassicPower 'Resume cache sync failed; cancelling power action'
        exit 1
    }
    log -t ClassicPower "Latest resume cache synchronized before $action"
fi
sync
setprop sys.powerctl "$action"
