#!/bin/bash
# Initialize DSP on UA Apollo USB after firmware load.
# Called by udev when post-firmware device (PID 000d/0002/000f) appears.
#
# Runs the full 38-packet DSP init (including program load needed for
# capture), then rebinds so snd-usb-audio probes with DSP active.
# The DSP program persists in FPGA memory across SET_INTERFACE.
# No daemon needed — one-shot init is sufficient.

set -euo pipefail

LOG_TAG="ua-usb-dsp-init"
log() { logger -t "$LOG_TAG" "$*"; }

# Small delay for USB enumeration to settle
sleep 2

# Kill any leftover daemon from previous installs
pkill -f "usb-dsp-init.py --daemon" 2>/dev/null || true

# Run full DSP init (38 packets including DSP program load for capture)
log "Running full DSP init"
python3 /usr/local/lib/ua-usb/usb-full-init.py 2>&1 | while read -r line; do
    log "$line"
done

# Rebind USB device so snd-usb-audio probes interfaces 1-3
DEVPATH=$(find /sys/bus/usb/devices/ -maxdepth 1 -name '[0-9]*' -exec sh -c \
    'cat "$1/idVendor" 2>/dev/null | grep -q 2b5a && basename "$1"' _ {} \; | head -1)
if [ -n "$DEVPATH" ]; then
    log "Rebinding $DEVPATH for audio enumeration"
    echo "$DEVPATH" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true
    sleep 1
    echo "$DEVPATH" > /sys/bus/usb/drivers/usb/bind 2>/dev/null || true
fi

log "DSP init complete"
