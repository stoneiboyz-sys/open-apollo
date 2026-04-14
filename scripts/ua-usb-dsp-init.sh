#!/bin/bash
# Initialize DSP on UA Apollo USB after firmware load.
# Called by udev when post-firmware device (PID 000d/0002/000f) appears.
#
# Runs the full 38-packet DSP init (including program load needed for
# capture), then rebinds so snd-usb-audio probes with DSP active.
# Vendor Monitor+HP1 settings may not survive re-enumeration — a second
# EP0-only pass re-applies them after bind (usb-full-init.py flag).
# No daemon needed — one-shot init is sufficient.

set -euo pipefail

LOG_TAG="ua-usb-dsp-init"
log() { logger -t "$LOG_TAG" "$*"; }

# Small delay for USB enumeration to settle
sleep 2

# Kill any leftover daemon from previous installs
pkill -f "usb-dsp-init.py --daemon" 2>/dev/null || true

# Run full DSP init (38 packets including DSP program load for capture).
# usb-full-init.py logs to syslog itself when stdout is not a TTY (no pipe).
log "Running full DSP init"
set +e
python3 -u /usr/local/lib/ua-usb/usb-full-init.py
FULL_EC=$?
set -e
if [ "$FULL_EC" -ne 0 ]; then
    log "WARNING: usb-full-init.py exited with code $FULL_EC (continuing)"
fi

# Rebind USB device so snd-usb-audio probes interfaces 1-3
DEVPATH=$(find /sys/bus/usb/devices/ -maxdepth 1 -name '[0-9]*' -exec sh -c \
    'cat "$1/idVendor" 2>/dev/null | grep -q 2b5a && basename "$1"' _ {} \; | head -1)
if [ -n "$DEVPATH" ]; then
    log "Rebinding $DEVPATH for audio enumeration"
    echo "$DEVPATH" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true
    sleep 1
    echo "$DEVPATH" > /sys/bus/usb/drivers/usb/bind 2>/dev/null || true
    sleep 2
    log "Re-applying Monitor+HP1 vendor settings after rebind"
    set +e
    python3 -u /usr/local/lib/ua-usb/usb-full-init.py --vendor-monitor-hp-only
    VENDOR_EC=$?
    set -e
    if [ "$VENDOR_EC" -ne 0 ]; then
        log "WARNING: usb-full-init.py --vendor-monitor-hp-only exited with code $VENDOR_EC (continuing)"
    fi
fi

log "DSP init complete"
