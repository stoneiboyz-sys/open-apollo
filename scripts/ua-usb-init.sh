#!/bin/bash
# Upload firmware to UA Apollo USB FX3 stub.
# Called by udev when FX3 loader device appears.
# Usage: ua-usb-init <usb-device-name> <firmware-file>

set -euo pipefail

DEVICE="$1"
FIRMWARE="$2"
FW_DIR="/lib/firmware/universal-audio"
LOG_TAG="ua-usb-init"

log() { logger -t "$LOG_TAG" "$*"; }

FW_PATH="$FW_DIR/$FIRMWARE"
if [ ! -f "$FW_PATH" ]; then
    log "ERROR: Firmware not found: $FW_PATH"
    log "Download from UA Connect and place in $FW_DIR/"
    exit 1
fi

# Find the USB device bus/dev path
BUSNUM=$(cat "/sys/bus/usb/devices/$DEVICE/busnum" 2>/dev/null || echo "")
DEVNUM=$(cat "/sys/bus/usb/devices/$DEVICE/devnum" 2>/dev/null || echo "")

if [ -z "$BUSNUM" ] || [ -z "$DEVNUM" ]; then
    log "ERROR: Cannot find USB bus/dev for $DEVICE"
    exit 1
fi

log "Loading firmware $FIRMWARE to bus $BUSNUM dev $DEVNUM"

# Upload FX3 firmware using our loader script
python3 /usr/local/lib/ua-usb/fx3-load.py "$FW_PATH" 2>&1 | while read -r line; do
    log "$line"
done

log "Firmware uploaded, device will re-enumerate"
