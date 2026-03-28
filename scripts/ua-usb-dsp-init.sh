#!/bin/bash
# Initialize DSP on UA Apollo USB after firmware load.
# Called by udev when post-firmware device (PID 000d/0002/000f) appears.
# Sends DSP init command + UAC2 SET_CUR sample rate.

set -euo pipefail

LOG_TAG="ua-usb-dsp-init"
log() { logger -t "$LOG_TAG" "$*"; }

# Small delay for USB enumeration to settle
sleep 2

log "Running DSP init"
python3 /usr/local/lib/ua-usb/usb-dsp-init.py 2>&1 | while read -r line; do
    log "$line"
done

# Rebind USB device so snd-usb-audio re-enumerates with DSP active
DEVPATH=$(find /sys/bus/usb/devices/ -maxdepth 1 -name '[0-9]*' -exec sh -c \
    'cat "$1/idVendor" 2>/dev/null | grep -q 2b5a && basename "$1"' _ {} \; | head -1)
if [ -n "$DEVPATH" ]; then
    log "Rebinding $DEVPATH for audio enumeration"
    echo "$DEVPATH" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true
    sleep 1
    echo "$DEVPATH" > /sys/bus/usb/drivers/usb/bind 2>/dev/null || true
fi

log "DSP init complete"
