#!/system/bin/sh
# Opt-in off-mode diagnostics. One root-owned marker permits one bounded run.
set -u
DIR=/metadata/classic-charger-probe
[ "$(getprop ro.product.vendor.device)" = parrot ] || exit 2
board=$(od -An -tx1 -N8 /sys/firmware/devicetree/base/qcom,board-id | tr -d ' \n')
[ "$board" = 0000002200000000 ] || exit 2
case "$(getprop ro.bootmode):$(getprop ro.boot.mode)" in
    charger:*|*:charger) ;;
    *) exit 0;;
esac
[ ! -L "$DIR" ] && [ -d "$DIR" ] || exit 0
[ "$(stat -c %u:%g:%a "$DIR")" = 0:0:700 ] || exit 0
[ ! -L "$DIR/armed" ] && [ -f "$DIR/armed" ] || exit 0
[ "$(stat -c %u:%g:%a "$DIR/armed")" = 0:0:600 ] || exit 0
[ "$(cat "$DIR/armed")" = once ] || exit 0
rm "$DIR/armed" || exit 2
umask 077
sync

snapshot() {
    stage=$1
    {
        date
        cat /proc/sys/kernel/random/boot_id
        cat /proc/uptime
        getprop | grep -E 'ro.boot|init.svc.*(charger|health|light|servicemanager)|sys.usb|sys.boot_completed|sys.boot_from_charger'
        ps -A -o USER,PID,PPID,NAME,ARGS
        for pid in $(pidof charger charger-core); do
            cat "/proc/$pid/status"
            cat "/proc/$pid/wchan"
            ls -l "/proc/$pid/fd/1" "/proc/$pid/fd/2"
            tr '\000' '\n' < "/proc/$pid/environ" | grep '^CLASSIC_CHARGER_SERVICE='
        done
        ls -lZ /dev/kmsg_debug /dev/dri /dev/graphics /system/etc/res/images/charger 2>/dev/null
        ls -lZ /sys/class/backlight/panel0-backlight/brightness /sys/class/backlight/panel0-backlight/bl_power
        cat /sys/class/backlight/panel0-backlight/brightness
        cat /sys/class/power_supply/battery/capacity
    } > "$DIR/$stage-status.txt" 2>&1
    dmesg | tail -c 131072 > "$DIR/$stage-kernel.txt"
    sync
}

sleep 2
snapshot 02
sleep 4
snapshot 06
sleep 6
snapshot 12

# Exercise the charger's real KEY_POWER callback, not Android framework input.
power_node=
for path in /sys/class/input/event*/device/name; do
    if [ "$(cat "$path")" = pmic_pwrkey ]; then
        node=${path%/device/name}
        power_node=/dev/input/${node##*/}
        break
    fi
done
if [ -n "$power_node" ]; then
    echo "Short KEY_POWER via $power_node" > "$DIR/power-test.txt"
    sync
    sendevent "$power_node" 1 116 1
    sendevent "$power_node" 0 0 0
    sleep 0.08
    sendevent "$power_node" 1 116 0
    sendevent "$power_node" 0 0 0
    sleep 1
    snapshot 13
    sleep 6
    snapshot 19
    echo "Long KEY_POWER via $power_node" >> "$DIR/power-test.txt"
    sync
    sendevent "$power_node" 1 116 1
    sendevent "$power_node" 0 0 0
    sleep 2.5
    sendevent "$power_node" 1 116 0
    sendevent "$power_node" 0 0 0
fi
sleep 12
snapshot 34
if [ "$(getprop sys.boot_completed)" != 1 ] && [ "$(getprop sys.boot_from_charger_mode)" != 1 ]; then
    echo 'Power callback did not start Android; bounded fallback reboot' >> "$DIR/power-test.txt"
    sync
    setprop sys.powerctl reboot
fi
