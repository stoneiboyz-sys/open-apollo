#!/bin/bash
# Initialize DSP on UA Apollo USB after firmware load.
# Called by udev when post-firmware device (PID 000d/0002/000f) appears.
#
# Ordering: rebind device (snd-usb-audio probes + SET_INTERFACE) → THEN
# start DSP init daemon. DSP init must come AFTER SET_INTERFACE, otherwise
# the FPGA routing gets wiped. EP6 only floods after FPGA_ACTIVATE.

set -euo pipefail

LOG_TAG="ua-usb-dsp-init"
log() { logger -t "$LOG_TAG" "$*"; }

# Small delay for USB enumeration to settle
sleep 2

# Kill any previous EP6 drain daemon
pkill -f "usb-dsp-init.py --daemon" 2>/dev/null || true
sleep 0.5

# Step 1: Rebind USB device so snd-usb-audio probes interfaces 1-3
# This triggers SET_INTERFACE which configures the USB audio endpoints.
DEVPATH=$(find /sys/bus/usb/devices/ -maxdepth 1 -name '[0-9]*' -exec sh -c \
    'cat "$1/idVendor" 2>/dev/null | grep -q 2b5a && basename "$1"' _ {} \; | head -1)
if [ -n "$DEVPATH" ]; then
    log "Rebinding $DEVPATH for audio enumeration"
    echo "$DEVPATH" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true
    sleep 1
    echo "$DEVPATH" > /sys/bus/usb/drivers/usb/bind 2>/dev/null || true
    sleep 2
fi

# Step 2: Start DSP init + EP6 drain daemon AFTER snd-usb-audio has probed.
# DSP init sends FPGA_ACTIVATE which starts EP6 notifications — the daemon
# drains them to prevent Intel xHCI buffer overruns.
log "Running DSP init + EP6 drain (after module probe)"
python3 /usr/local/lib/ua-usb/usb-dsp-init.py --daemon </dev/null >/dev/null 2>&1 &
DRAIN_PID=$!

sleep 3

if kill -0 "$DRAIN_PID" 2>/dev/null; then
    log "EP6 drain running (PID $DRAIN_PID)"
else
    log "WARNING: EP6 drain exited early"
fi

log "DSP init complete"
