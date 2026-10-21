#!/usr/bin/env bash
# Turns on the manual fan (PWM) support that already exists in the kernel's acer_wmi
# driver but is only enabled for a few listed models (e.g. Nitro AN515-58).
# It keeps every capability the driver currently detects and adds ACER_CAP_PWM.
# On Nitro models the driver doesn't list at all, it also sets predator_v4=1, which
# turns on the fan profiles (Eco ... Turbo) and the fan RPM sensors.
# Undo:  sudo rm /etc/modprobe.d/nitrosense-fan.conf && reboot
# Usage: ./enable-manual-fan.sh [--dry-run]
set -euo pipefail

# Run a root shell snippet: sudo in a terminal, otherwise KDE's graphical pkexec prompt.
as_root() {
    if [ -t 0 ]; then sudo sh -c "$1"; else pkexec sh -c "$1"; fi
}

CONF=/etc/modprobe.d/nitrosense-fan.conf
DEV=/sys/devices/platform/acer-wmi

has_pwm() {
    for h in /sys/class/hwmon/hwmon*; do
        [ "$(cat "$h/name")" = acer ] && [ -e "$h/pwm1_enable" ] && return 0
    done
    return 1
}

[ -d "$DEV" ] || { echo "acer_wmi is not loaded - unsupported laptop."; exit 1; }
has_pwm && { echo "Manual fan control is already enabled."; exit 0; }
opts=""
if [ ! -d "$DEV/platform-profile" ]; then
    echo "This model is not in acer_wmi's list yet; predator_v4=1 will be added to enable fan profiles."
    opts="predator_v4=1 "
fi

caps=0
cap() { caps=$(( caps | $1 )); }
for r in "$DEV"/rfkill/*/name; do
    case "$(cat "$r")" in
        acer-wireless)  cap 0x2 ;;    # ACER_CAP_WIRELESS
        acer-bluetooth) cap 0x4 ;;    # ACER_CAP_BLUETOOTH
        acer-threeg)    cap 0x10 ;;   # ACER_CAP_THREEG
    esac
done
[ -e /sys/class/leds/acer-wmi::mail ] && cap 0x1         # ACER_CAP_MAILLED
[ -e /sys/class/backlight/acer-wmi ] && cap 0x8          # ACER_CAP_BRIGHTNESS
ls /sys/bus/wmi/devices/ | grep -qi '^61EF69EA-865C-4BC3-A502-A0DEBA0CB531' && cap 0x20  # SET_FUNCTION_MODE (WMID_GUID3)
cap 0x400   # ACER_CAP_PLATFORM_PROFILE
cap 0x800   # ACER_CAP_HWMON
cap 0x1000  # ACER_CAP_PWM

printf 'Laptop: %s\nacer_wmi options: %sforce_caps=%d (0x%X)\n' "$(cat /sys/class/dmi/id/product_name)" "$opts" "$caps" "$caps"
[ "${1:-}" = --dry-run ] && exit 0
echo "Writing $CONF and reloading acer_wmi (asks for your password)..."
if as_root "echo 'options acer_wmi ${opts}force_caps=$caps' > '$CONF' && modprobe -r acer_wmi && modprobe acer_wmi"; then
    sleep 1
    has_pwm && { echo "OK: manual fan control is available."; exit 0; }
    echo "Driver reloaded but no pwm files appeared (your kernel may be too old for manual fan"
    echo "control, or the firmware doesn't support it). Remove $CONF to undo."
    exit 1
elif [ -f "$CONF" ]; then
    echo "Could not reload the driver now; reboot to apply."
else
    echo "Cancelled - nothing was changed."; exit 1
fi
