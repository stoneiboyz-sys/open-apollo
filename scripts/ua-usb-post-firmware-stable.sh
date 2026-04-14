#!/usr/bin/env bash
set -euo pipefail

# Stable-mode root helper triggered by udev when Apollo live PID appears.
# Purpose: avoid full DSP replay while still re-applying minimal vendor state
# and ensuring snd_usb_audio is present after re-enumeration/hotplug.

USB_FULL_INIT="/usr/local/lib/ua-usb/usb-full-init.py"

if [ -f "$USB_FULL_INIT" ]; then
  python3 "$USB_FULL_INIT" --vendor-monitor-hp-only >/dev/null 2>&1 || true
fi

modprobe snd_usb_audio >/dev/null 2>&1 || true

exit 0
