#!/usr/bin/env bash
set -euo pipefail

# Stable USB path: avoid full DSP replay, apply only vendor monitor pass,
# ensure snd_usb_audio is present, then re-point PipeWire playback to Apollo.

UA_USB_FULL_INIT="${UA_USB_FULL_INIT:-/usr/local/lib/ua-usb/usb-full-init.py}"
# Prefer repo root next to this script when run from a git checkout (not only ~/open-apollo).
_script="$(readlink -f "${BASH_SOURCE[0]:-$0}" 2>/dev/null || echo "${BASH_SOURCE[0]:-$0}")"
_script_dir="$(dirname "$_script")"
if [ -f "$_script_dir/../configs/pipewire/setup-apollo-solo-usb.sh" ]; then
  OPEN_APOLLO_DIR="${OPEN_APOLLO_DIR:-$(cd "$_script_dir/.." && pwd)}"
else
  OPEN_APOLLO_DIR="${OPEN_APOLLO_DIR:-$HOME/open-apollo}"
fi
SETUP_APOLLO_SCRIPT="${SETUP_APOLLO_SCRIPT:-$OPEN_APOLLO_DIR/configs/pipewire/setup-apollo-solo-usb.sh}"

if [ ! -f "$UA_USB_FULL_INIT" ] && [ -f "$OPEN_APOLLO_DIR/tools/usb-full-init.py" ]; then
  UA_USB_FULL_INIT="$OPEN_APOLLO_DIR/tools/usb-full-init.py"
fi

# In user services, interactive sudo is unavailable.
# Behavior:
# - Interactive terminal: try normal sudo (can prompt once).
# - Service/non-interactive: skip root steps unless ALLOW_ROOT_STEPS=1.
run_root() {
  if [ "${ALLOW_ROOT_STEPS:-0}" = "1" ]; then
    sudo -n "$@" >/dev/null 2>&1 || true
    return 0
  fi

  # Manual run from terminal: allow interactive sudo prompt.
  if [ -t 0 ] && [ -t 1 ]; then
    sudo "$@" || true
    return 0
  fi
}

if [ -f "$UA_USB_FULL_INIT" ]; then
  run_root python3 "$UA_USB_FULL_INIT" --vendor-monitor-hp-only
fi

run_root modprobe snd_usb_audio

systemctl --user unmask wireplumber pipewire pipewire-pulse || true
systemctl --user restart pipewire pipewire-pulse wireplumber || true

# Force Apollo card profile when visible (mirrors setup script behavior).
apollo_dev_id="$(
  pw-dump 2>/dev/null | python3 -c '
import json, sys
try:
    objs = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
for obj in objs:
    props = obj.get("info", {}).get("props", {})
    if obj.get("type") == "PipeWire:Interface:Device" and "Apollo Solo USB" in props.get("alsa.card_name", ""):
        print(obj.get("id", ""))
        break
' 2>/dev/null || true
)"
if [ -n "${apollo_dev_id:-}" ]; then
  wpctl set-profile "$apollo_dev_id" 1 2>/dev/null || true
fi

# Rebuild Apollo loopback mapping when available (keeps apollo_monitor
# routed to Apollo output instead of falling back to built-in audio).
if [ -x "$SETUP_APOLLO_SCRIPT" ]; then
  bash "$SETUP_APOLLO_SCRIPT" >/dev/null 2>&1 || true
fi

# Wait for PipeWire/Apollo nodes to appear and choose the best sink.
# Prefer the real USB playback sink, fallback to virtual apollo_monitor.
for _ in {1..180}; do
  sink="$(
    pactl list short sinks 2>/dev/null | awk '
      $2 ~ /^alsa_output\.usb-Universal_Audio_Inc_Apollo_Solo_USB/ {print $2; found=1; exit}
      END {if (!found) exit 1}
    ' || true
  )"
  if [ -z "${sink:-}" ]; then
    # Only use apollo_monitor if Apollo USB device is actually present.
    if ! wpctl status 2>/dev/null | awk '/Apollo Solo USB[[:space:]]+\[alsa\]/{found=1} END{exit(found?0:1)}'; then
      sleep 1
      continue
    fi
    sink="$(
      pactl list short sinks 2>/dev/null | awk '
        $2 == "apollo_monitor" {print $2; exit}
      ' || true
    )"
  fi
  if [ -n "${sink:-}" ]; then
    pactl set-default-sink "$sink" || true
    for i in $(pactl list short sink-inputs 2>/dev/null | awk '{print $1}'); do
      pactl move-sink-input "$i" "$sink" || true
    done
    pactl set-sink-mute "$sink" 0 || true
    pactl set-sink-volume "$sink" 80% || true
    break
  fi
  sleep 1
done

exit 0
