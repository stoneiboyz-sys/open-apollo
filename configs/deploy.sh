#!/bin/bash
# Deploy PipeWire/WirePlumber/UCM2 configs for Universal Audio Apollo
# Run on Ubuntu: sudo bash ~/apollo-linux/configs/deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Deploying Apollo PipeWire integration configs ==="

# Step 1: Remove broken PipeWire config that causes crash
BROKEN_CONF="/etc/pipewire/pipewire.conf.d/90-disable-apollo.conf"
if [ -f "$BROKEN_CONF" ]; then
    echo "Removing broken config: $BROKEN_CONF"
    rm -f "$BROKEN_CONF"
else
    echo "No broken config to remove (OK)"
fi

# Step 2: Deploy WirePlumber rules
echo "Installing WirePlumber rules..."
mkdir -p /etc/wireplumber/main.lua.d
cp "$SCRIPT_DIR/wireplumber/51-ua-apollo.lua" /etc/wireplumber/main.lua.d/
echo "  -> /etc/wireplumber/main.lua.d/51-ua-apollo.lua"

# Step 3: Deploy UCM2 profile
echo "Installing UCM2 profile..."
mkdir -p /usr/share/alsa/ucm2/ua_apollo
mkdir -p /usr/share/alsa/ucm2/conf.d/ua_apollo
cp "$SCRIPT_DIR/ucm2/ua_apollo/ua_apollo.conf" /usr/share/alsa/ucm2/ua_apollo/
cp "$SCRIPT_DIR/ucm2/ua_apollo/HiFi.conf" /usr/share/alsa/ucm2/ua_apollo/
echo "  -> /usr/share/alsa/ucm2/ua_apollo/ua_apollo.conf"
echo "  -> /usr/share/alsa/ucm2/ua_apollo/HiFi.conf"

# Create symlink for driver name match (UCM2 looks up conf.d/${CardDriver}/${CardDriver}.conf)
ln -sf ../../ua_apollo/ua_apollo.conf /usr/share/alsa/ucm2/conf.d/ua_apollo/ua_apollo.conf
echo "  -> /usr/share/alsa/ucm2/conf.d/ua_apollo/ua_apollo.conf (symlink)"

# Step 4: Install PipeWire I/O mapping setup script
echo "Installing PipeWire I/O setup script..."
SETUP_SCRIPT="$SCRIPT_DIR/pipewire/setup-apollo-io.sh"
if [ -f "$SETUP_SCRIPT" ]; then
    cp "$SETUP_SCRIPT" /usr/local/bin/apollo-setup-io
    chmod +x /usr/local/bin/apollo-setup-io
    echo "  -> /usr/local/bin/apollo-setup-io"
else
    echo "  Warning: $SETUP_SCRIPT not found, skipping"
fi

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Next steps:"
echo "  1. Restart PipeWire:  systemctl --user restart pipewire wireplumber"
echo "  2. Set up I/O map:    apollo-setup-io"
echo "  3. Verify:            wpctl status"
echo "  4. Test playback:     pw-play /usr/share/sounds/freedesktop/stereo/complete.oga"
echo "  5. Test capture:      pw-record --rate 48000 --channels 2 --format s32 /tmp/test.wav"
