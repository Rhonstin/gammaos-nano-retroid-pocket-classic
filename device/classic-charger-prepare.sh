#!/system/bin/sh
# Run before the native charger without granting it root or generic proc write.
[ "$(getprop ro.product.vendor.device)" = parrot ] || exit 2
board=$(od -An -tx1 -N8 /sys/firmware/devicetree/base/qcom,board-id | tr -d ' \n')
[ "$board" = 0000002200000000 ] || exit 2
node=/sys/class/backlight/panel0-backlight/brightness
attempt=0
while [ ! -e "$node" ] && [ "$attempt" -lt 50 ]; do
    sleep 0.1
    attempt=$((attempt + 1))
done
before=$(stat -c %u:%g:%a "$node" 2>/dev/null)
# The vendor performs this chown only in "on boot", which charger skips.
# Match those normal-boot permissions before starting the unprivileged client.
chown 1000:1000 "$node" && chmod 0644 "$node" || exit 2
echo "<6>ClassicChargerPrepare: backlight $before -> $(stat -c %u:%g:%a "$node")" > /dev/kmsg
dir=/metadata/classic-charger-probe
if [ ! -L "$dir" ] && [ ! -L "$dir/armed" ] &&
   [ "$(stat -c %u:%g:%a "$dir" 2>/dev/null)" = 0:0:700 ] &&
   [ "$(stat -c %u:%g:%a "$dir/armed" 2>/dev/null)" = 0:0:600 ] &&
   [ "$(cat "$dir/armed" 2>/dev/null)" = once ]; then
    echo on > /proc/sys/kernel/printk_devkmsg
    echo '<6>ClassicChargerPrepare: one-use diagnostic logging enabled' > /dev/kmsg
fi
