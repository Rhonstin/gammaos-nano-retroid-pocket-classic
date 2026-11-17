#!/system/bin/sh
# No resident Java VM: synchronize after connectivity, then once per half hour.
[ "$(getprop ro.product.vendor.device)" = parrot ] || exit 2
export CLASSPATH=/system/framework/classic-time.jar
while true; do
    if app_process /system/bin ClassicTimeSync; then
        setprop sys.gammaos.classic.time_sync "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        sleep 1800
    else
        sleep 30
    fi
done
