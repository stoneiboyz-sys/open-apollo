#!/usr/bin/env bash
# Dispatch to the correct PipeWire virtual-I/O generator.
#
# Base card (USB): Apollo Solo USB  → setup-apollo-solo-usb.sh
# Thunderbolt:      ua_apollo driver → setup-apollo-io.sh
#
# Usage:
#   bash configs/pipewire/open-apollo-setup-io.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOLO="$SCRIPT_DIR/setup-apollo-solo-usb.sh"
TB="$SCRIPT_DIR/setup-apollo-io.sh"

if ! command -v pw-dump >/dev/null 2>&1; then
    echo "[open-apollo-setup-io] pw-dump not found — is PipeWire installed?" >&2
    exit 1
fi

# shellcheck disable=SC2016
_devkind="$(pw-dump 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("none")
    raise SystemExit(0)
has_usb = False
has_tb = False
for obj in data:
    if obj.get("type") != "PipeWire:Interface:Device":
        continue
    props = obj.get("info", {}).get("props", {})
    card = props.get("alsa.card_name", "") or ""
    drv = props.get("alsa.driver_name", "") or ""
    if "Apollo Solo USB" in card:
        has_usb = True
    if drv == "ua_apollo":
        has_tb = True
if has_usb:
    print("solo-usb")
elif has_tb:
    print("thunderbolt")
else:
    print("none")
' 2>/dev/null || echo none)"

case "$_devkind" in
    solo-usb)
        exec bash "$SOLO" "$@"
        ;;
    thunderbolt)
        exec bash "$TB" "$@"
        ;;
    *)
        echo "[open-apollo-setup-io] No supported Apollo device in PipeWire yet (Solo USB or ua_apollo)." >&2
        echo "[open-apollo-setup-io] Plug in the interface, wait for PipeWire, then retry." >&2
        exit 1
        ;;
esac
