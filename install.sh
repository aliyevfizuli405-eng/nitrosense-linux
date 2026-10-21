#!/usr/bin/env bash
# Installs NitroSense for Linux for the current user (udev rule needs sudo).
set -euo pipefail

# Run a root shell snippet: sudo in a terminal, otherwise the graphical pkexec prompt.
as_root() {
    if [ -t 0 ]; then sudo sh -c "$1"; else pkexec sh -c "$1"; fi
}
SRC="$(cd "$(dirname "$0")" && pwd)"
PREFIX="$HOME/.local/share/nitrosense"

echo ">> Checking the laptop"
product="$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo unknown)"
vendor="$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo unknown)"
echo "   $vendor $product"
case "$vendor $product" in
    *Acer*|*acer*) ;;
    *) echo "   Warning: this is not an Acer laptop - fan control will not work (sound modes will)." ;;
esac
if [ ! -d /sys/devices/platform/acer-wmi ]; then
    echo "   Warning: the acer_wmi driver is not loaded - fan control will not work (sound modes will)."
elif ! ls /sys/class/platform-profile/*/name >/dev/null 2>&1 && [ ! -e /sys/firmware/acpi/platform_profile ]; then
    echo "   Note: no fan profiles exposed yet. Run ./enable-manual-fan.sh after installing to turn them on."
fi

echo ">> Checking requirements"
missing=()
python3 -c 'import PySide6.QtWidgets, PySide6.QtNetwork' 2>/dev/null || missing+=(pyside6)
command -v pw-cli >/dev/null && command -v pw-dump >/dev/null || missing+=(pipewire-tools)
if [ ${#missing[@]} -gt 0 ]; then
    echo "   Missing: ${missing[*]}. Install them with:"
    if command -v dnf >/dev/null; then
        echo "     sudo dnf install python3-pyside6 pipewire-utils"
    elif command -v apt-get >/dev/null; then
        echo "     sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtnetwork python3-pyside6.qtgui pipewire-bin"
    elif command -v pacman >/dev/null; then
        echo "     sudo pacman -S pyside6 pipewire"
    elif command -v zypper >/dev/null; then
        echo "     sudo zypper install python3-PySide6 pipewire-tools"
    fi
    echo "     (or: pip install --user -r requirements.txt for PySide6)"
    exit 1
fi

echo ">> Copying app to $PREFIX"
rm -rf "$PREFIX"
mkdir -p "$PREFIX" "$HOME/.local/bin"
cp -r "$SRC/nitrosense" "$SRC/data" "$PREFIX/"
find "$PREFIX" -name __pycache__ -prune -exec rm -rf {} +

cat > "$HOME/.local/bin/nitrosense" <<LAUNCH
#!/bin/sh
PYTHONPATH="$PREFIX" exec python3 -m nitrosense "\$@"
LAUNCH
chmod +x "$HOME/.local/bin/nitrosense"
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) echo "   Note: add ~/.local/bin to your PATH to use the 'nitrosense' command." ;;
esac

echo ">> Installing launcher, icon and autostart entry"
install -Dm644 "$SRC/data/nitrosense.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/nitrosense.svg"
install -Dm644 "$SRC/data/nitrosense.desktop" "$HOME/.local/share/applications/nitrosense.desktop"
mkdir -p "$HOME/.config/autostart"
sed 's|^Exec=nitrosense$|Exec=nitrosense --tray|' "$SRC/data/nitrosense.desktop" > "$HOME/.config/autostart/nitrosense.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo ">> Installing PipeWire EQ (sound modes)"
install -Dm644 "$SRC/data/nitrosense-eq.conf" "$HOME/.config/pipewire/pipewire.conf.d/nitrosense-eq.conf"
systemctl --user restart pipewire 2>/dev/null || true
systemctl --user restart pipewire-pulse wireplumber 2>/dev/null || true

# The group allowed to change fan settings: the admin group this user is in.
group=""
for g in wheel sudo admin; do
    if id -nG | tr ' ' '\n' | grep -qx "$g"; then group=$g; break; fi
done
if [ -z "$group" ]; then
    group=nitrosense
    echo ">> Creating group '$group' for fan control (log out and back in afterwards)"
    as_root "getent group $group >/dev/null || groupadd -r $group; usermod -aG $group '$USER'"
fi

echo ">> Installing udev rule for fan control, group '$group' (asks for your password)"
rules="$(mktemp)"
sed "s/@GROUP@/$group/g" "$SRC/data/99-nitrosense.rules" > "$rules"
as_root "install -Dm644 '$rules' /etc/udev/rules.d/99-nitrosense.rules &&
         udevadm control --reload &&
         udevadm trigger --action=add --subsystem-match=platform-profile --subsystem-match=hwmon"
rm -f "$rules"

echo
echo "Done. Launch 'NitroSense' from the app menu or run: nitrosense"
