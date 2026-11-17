#!/system/bin/sh
# Hardware adapter for the original SG4250P Classic, using stock frequency bounds.

set -u
FAN=/sys/class/gpio5_pwm2
GPU=/sys/class/kgsl/kgsl-3d0/devfreq
CPU=/sys/devices/system/cpu/cpufreq

guard() {
    [ "$(getprop ro.product.vendor.device)" = parrot ] || return 1
    board=$(od -An -tx1 -N8 /sys/firmware/devicetree/base/qcom,board-id | tr -d ' \n')
    [ "$board" = 0000002200000000 ] || return 1
    [ -r "$FAN/period" ] && [ -d "$CPU/policy6" ]
}

write_value() {
    printf '%s\n' "$2" >"$1"
}

set_fan() {
    period=$(cat "$FAN/period") || return 1
    case "$period" in ''|*[!0-9]*) return 1;; esac
    [ "$period" -gt 0 ] && [ "$period" -le 100000000 ] || return 1
    case "$1" in
        off)
            write_value "$FAN/state" 0 || return 1
            write_value "$FAN/duty" "$((period / 5))" || return 1;;
        cool|max)
            duty=$period
            [ "$1" = cool ] && duty=$((period / 2))
            write_value "$FAN/duty" "$duty" || return 1
            write_value "$FAN/state" 1 || return 1;;
        *) return 1;;
    esac
    setprop sys.gammaos.classic.fan_applied "$1"
}

set_cpu_range() {
    policy=$1 lower=$2 upper=$3 governor=$4
    grep -qw "$lower" "$CPU/$policy/scaling_available_frequencies" || return 1
    grep -qw "$upper" "$CPU/$policy/scaling_available_frequencies" || return 1
    grep -qw "$governor" "$CPU/$policy/scaling_available_governors" || return 1
    # Widen before narrowing: this also works when switching from powersave to max.
    ceiling=$(cat "$CPU/$policy/cpuinfo_max_freq") || return 1
    write_value "$CPU/$policy/scaling_max_freq" "$ceiling" || return 1
    write_value "$CPU/$policy/scaling_min_freq" "$lower" || return 1
    write_value "$CPU/$policy/scaling_max_freq" "$upper" || return 1
    write_value "$CPU/$policy/scaling_governor" "$governor"
}

set_profile() {
    case "$1" in
        stock) lmin=672000; lmax=1958400; bmin=691200; bmax=2400000
               gmin=340000000; gmax=1010000000; governor=walt; interval=200;;
        max) lmin=1958400; lmax=1958400; bmin=2400000; bmax=2400000
             gmin=1010000000; gmax=1010000000; governor=performance; interval=0;;
        powersave) lmin=499200; lmax=499200; bmin=691200; bmax=691200
                   gmin=340000000; gmax=340000000; governor=powersave; interval=0;;
        *) return 1;;
    esac
    grep -qw "$gmin" "$GPU/available_frequencies" || return 1
    grep -qw "$gmax" "$GPU/available_frequencies" || return 1
    set_cpu_range policy0 "$lmin" "$lmax" "$governor" || return 1
    set_cpu_range policy6 "$bmin" "$bmax" "$governor" || return 1
    write_value "$GPU/max_freq" 1010000000 || return 1
    write_value "$GPU/min_freq" "$gmin" || return 1
    write_value "$GPU/max_freq" "$gmax" || return 1
    write_value "$GPU/governor" msm-adreno-tz || return 1
    write_value "$GPU/polling_interval" "$interval" || return 1
    setprop sys.gammaos.classic.profile_applied "$1"
}

temperature() {
    value=$(cat "/sys/class/thermal/$1/temp" 2>/dev/null) || return 1
    case "$value" in ''|*[!0-9]*) return 1;; esac
    [ "$value" -le 150000 ] || return 1
    echo "$value"
}

automatic_fan() {
    little=$(temperature thermal_zone22) || { echo max; return; }
    big=$(temperature thermal_zone23) || { echo max; return; }
    gpu=$(temperature thermal_zone28) || { echo max; return; }
    cpu=$little; [ "$big" -gt "$cpu" ] && cpu=$big
    # CPU and GPU thresholds from the Classic reference, with 3 C hysteresis.
    if [ "$cpu" -gt 65000 ] || [ "$gpu" -gt 55000 ]; then echo max
    elif [ "$last_fan" = max ] && { [ "$cpu" -gt 62000 ] || [ "$gpu" -gt 52000 ]; }; then echo max
    elif [ "$cpu" -gt 55000 ] || [ "$gpu" -gt 45000 ]; then echo cool
    elif [ "$last_fan" = cool ] && { [ "$cpu" -gt 52000 ] || [ "$gpu" -gt 42000 ]; }; then echo cool
    else echo off; fi
}

guard || exit 2
case "${1:-daemon}" in
    --fan) set_fan "${2:-}"; exit $?;;
    --profile) set_profile "${2:-}"; exit $?;;
    daemon) ;;
    *) exit 2;;
esac

last_fan=unknown
last_profile=unknown
while true; do
    profile=$(getprop persist.gammaos.performance_mode)
    [ -n "$profile" ] || profile=stock
    # Retain the user's preference, but lower the hardware bounds while asleep.
    # Nano's generic setclock scripts do not know this stock vendor layout.
    [ "$(getprop sys.screen.state)" = off ] && profile=powersave
    if [ "$profile" != "$last_profile" ]; then
        if set_profile "$profile"; then
            last_profile=$profile
            log -t ClassicHardware "Applied profile $profile"
        else
            log -t ClassicHardware "Could not apply profile $profile"
        fi
    fi
    mode=$(getprop persist.gammaos.fan_mode)
    case "$mode" in
        off|cool|max) requested=$mode;;
        *) requested=$(automatic_fan);;
    esac
    [ "$(getprop sys.screen.state)" = off ] && requested=off
    if [ "$requested" != "$last_fan" ]; then
        if set_fan "$requested"; then last_fan=$requested; fi
    fi
    sleep 3
done
