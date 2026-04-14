#!/bin/bash
# Initialize DSP on UA Apollo USB after firmware load.
# Called by udev when post-firmware device (PID 000d/0002/000f) appears.
#
# Unloads snd_usb_audio so usb-full-init.py can set UAC2 clock and vendor
# mixer without EBUSY vs PipeWire, runs one full 38-packet DSP init, then
# loads snd_usb_audio so the kernel probes the device with DSP already up.
# No USB rebind — avoids extra enumeration churn and double-init timeouts.
# No daemon needed — one-shot init is sufficient.

set -euo pipefail

LOG_TAG="ua-usb-dsp-init"
log() { logger -t "$LOG_TAG" "$*"; }

# Small delay for USB enumeration to settle
sleep 8

# Kill any leftover daemon from previous installs
pkill -f "usb-dsp-init.py --daemon" 2>/dev/null || true

# Temporarily block snd_usb_audio autoload while DSP init is running.
MODPROBE_BLOCK_DIR="/run/modprobe.d"
MODPROBE_BLOCK_FILE="$MODPROBE_BLOCK_DIR/open-apollo-block-snd_usb_audio.conf"
cleanup_modprobe_block() {
    if [ -f "$MODPROBE_BLOCK_FILE" ]; then
        rm -f "$MODPROBE_BLOCK_FILE" 2>/dev/null || true
        log "Removed temporary snd_usb_audio autoload block"
    fi
}
trap cleanup_modprobe_block EXIT

mkdir -p "$MODPROBE_BLOCK_DIR"
printf "install snd_usb_audio /bin/false\n" > "$MODPROBE_BLOCK_FILE"
log "Temporary snd_usb_audio autoload block enabled"

# usb-full-init.py logs to syslog when stdout is not a TTY (no pipe).
log "Unloading snd_usb_audio before DSP init"
set +e
modprobe -r snd_usb_audio
if [ "$?" -ne 0 ]; then
    log "WARNING: modprobe -r snd_usb_audio failed (continuing)"
fi

log "Running full DSP init"
set +e
python3 -u /usr/local/lib/ua-usb/usb-full-init.py
FULL_EC=$?
set -e
if [ "$FULL_EC" -ne 0 ]; then
    log "WARNING: usb-full-init.py exited with code $FULL_EC (continuing)"
fi

# Remove block before manual modprobe.
cleanup_modprobe_block
trap - EXIT

log "Loading snd_usb_audio"
set +e
modprobe snd_usb_audio
if [ "$?" -ne 0 ]; then
    log "WARNING: modprobe snd_usb_audio failed"
fi
set -e

log "Waiting 3s for PipeWire/WirePlumber node opens"
sleep 3

log "Re-applying Monitor+HP1 after snd_usb_audio load"
set +e
python3 -u /usr/local/lib/ua-usb/usb-full-init.py --vendor-monitor-hp-only
POST_LOAD_VENDOR_EC=$?
set -e
if [ "$POST_LOAD_VENDOR_EC" -ne 0 ]; then
    log "WARNING: post-load vendor-monitor-hp-only exited with code $POST_LOAD_VENDOR_EC"
fi

log "DSP init complete"
