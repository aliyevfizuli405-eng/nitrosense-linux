#!/usr/bin/env bash
# Installs NitroSense for Linux for the current user (udev rule needs sudo).
set -euo pipefail

# Run a root shell snippet: sudo in a terminal, otherwise KDE's graphical pkexec prompt.
as_root() {
    if [ -t 0 ]; then sudo sh -c "$1"; else pkexec sh -c "$1"; fi
}
SRC="$(cd "$(dirname "$0")" && pwd)"
PREFIX="$HOME/.local/share/nitrosense"

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

echo ">> Installing launcher, icon and autostart entry"
install -Dm644 "$SRC/data/nitrosense.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/nitrosense.svg"
install -Dm644 "$SRC/data/nitrosense.desktop" "$HOME/.local/share/applications/nitrosense.desktop"
mkdir -p "$HOME/.config/autostart"
sed 's|^Exec=nitrosense$|Exec=nitrosense --tray|' "$SRC/data/nitrosense.desktop" > "$HOME/.config/autostart/nitrosense.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo ">> Installing PipeWire EQ (sound modes)"
install -Dm644 "$SRC/data/nitrosense-eq.conf" "$HOME/.config/pipewire/pipewire.conf.d/nitrosense-eq.conf"
systemctl --user restart pipewire pipewire-pulse wireplumber

echo ">> Installing udev rule for fan control (asks for your password)"
as_root "install -Dm644 '$SRC/data/99-nitrosense.rules' /etc/udev/rules.d/99-nitrosense.rules &&
         udevadm control --reload &&
         udevadm trigger --action=add --subsystem-match=platform-profile --subsystem-match=hwmon"

echo
echo "Done. Launch 'NitroSense' from the app menu or run: nitrosense"
