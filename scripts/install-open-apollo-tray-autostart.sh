#!/usr/bin/env bash
# install-open-apollo-tray-autostart.sh — Register GNOME/KDE session autostart for the tray (no sudo)
#
# Use when AppIndicator was installed *after* install-usb.sh (tray was skipped),
# or to repair a missing ~/.config/autostart entry.
#
# Requires: python3-gi, gir1.2-gtk-3.0, gir1.2-appindicator3-0.1 (Ubuntu) for the tray.
# USB mixer window: gir1.2-gtk-4.0 + gir1.2-adw-1 (optional here; install-usb.sh pulls them).
#
# Usage:
#   bash scripts/install-open-apollo-tray-autostart.sh
#   HOME=/home/alice bash scripts/install-open-apollo-tray-autostart.sh   # unusual; default is $HOME

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TRAY_SCRIPT="$PROJECT_DIR/tools/open-apollo-tray.py"
ICON_FILE="$PROJECT_DIR/tools/icons/apollo-green.svg"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
DESKTOP_FILE="$AUTOSTART_DIR/open-apollo-tray.desktop"

if [ ! -f "$TRAY_SCRIPT" ]; then
    echo "ERROR: tray script not found: $TRAY_SCRIPT" >&2
    exit 1
fi

if ! python3 -c "import gi; gi.require_version('Gtk','3.0'); gi.require_version('AppIndicator3','0.1')" 2>/dev/null; then
    echo "ERROR: GTK / AppIndicator Python bindings missing." >&2
    echo "  Ubuntu: sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-appindicator3-0.1" >&2
    exit 1
fi

if ! python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')" 2>/dev/null; then
    echo "NOTE: GTK 4 / Libadwaita not found — menu « USB mixer… » may fail until you install:" >&2
    echo "  Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1" >&2
    echo "  Fedora: sudo dnf install gtk4 libadwaita python3-gobject" >&2
fi

mkdir -p "$AUTOSTART_DIR"
cat >"$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Open Apollo
Comment=Apollo tray: USB status and buffer size
Exec=python3 $TRAY_SCRIPT
Icon=$ICON_FILE
Terminal=false
Categories=AudioVideo;Audio;
X-GNOME-Autostart-enabled=true
X-Open-Apollo-Installer=usb-tray
EOF
chmod 644 "$DESKTOP_FILE"

echo "Installed: $DESKTOP_FILE"
echo "Log out and back in (or reboot) so the tray starts automatically with your session."
