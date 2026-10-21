#!/usr/bin/env bash
set -uo pipefail

# Run a root shell snippet: sudo in a terminal, otherwise KDE's graphical pkexec prompt.
as_root() {
    if [ -t 0 ]; then sudo sh -c "$1"; else pkexec sh -c "$1"; fi
}
pkill -f "python3 -m nitrosense" 2>/dev/null
rm -rf "$HOME/.local/share/nitrosense" "$HOME/.local/bin/nitrosense" \
       "$HOME/.local/share/applications/nitrosense.desktop" \
       "$HOME/.local/share/icons/hicolor/scalable/apps/nitrosense.svg" \
       "$HOME/.config/autostart/nitrosense.desktop" \
       "$HOME/.config/pipewire/pipewire.conf.d/nitrosense-eq.conf"
systemctl --user restart pipewire pipewire-pulse wireplumber
as_root "rm -f /etc/udev/rules.d/99-nitrosense.rules /etc/modprobe.d/nitrosense-fan.conf && udevadm control --reload"
echo "Removed. Settings kept in ~/.config/nitrosense (delete manually if wanted)."
