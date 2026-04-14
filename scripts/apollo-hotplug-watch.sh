#!/usr/bin/env bash
set -euo pipefail

# Run the safe-start fixer whenever ALSA devices are added/changed.

SAFE_SCRIPT="${SAFE_SCRIPT:-$HOME/apollo-safe-start.sh}"

udevadm monitor --udev --subsystem-match=sound | while read -r line; do
  if echo "$line" | grep -Eiq 'add|change'; then
    sleep 1
    "$SAFE_SCRIPT" || true
  fi
done
