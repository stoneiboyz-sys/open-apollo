#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

USER_HOME="${HOME}"
USER_SYSTEMD_DIR="$USER_HOME/.config/systemd/user"

mkdir -p "$USER_SYSTEMD_DIR"

install -m 755 "$PROJECT_DIR/scripts/apollo-safe-start.sh" "$USER_HOME/apollo-safe-start.sh"
install -m 755 "$PROJECT_DIR/scripts/apollo-hotplug-watch.sh" "$USER_HOME/apollo-hotplug-watch.sh"
install -m 644 "$PROJECT_DIR/configs/systemd/user/apollo-audio-fix.service" \
  "$USER_SYSTEMD_DIR/apollo-audio-fix.service"
install -m 644 "$PROJECT_DIR/configs/systemd/user/apollo-hotplug-watch.service" \
  "$USER_SYSTEMD_DIR/apollo-hotplug-watch.service"

systemctl --user daemon-reload
systemctl --user enable --now apollo-audio-fix.service apollo-hotplug-watch.service

echo ""
echo "Apollo safe user services installed."
echo "Check status with:"
echo "  systemctl --user status apollo-audio-fix.service apollo-hotplug-watch.service --no-pager"
