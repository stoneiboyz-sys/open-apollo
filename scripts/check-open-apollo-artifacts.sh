#!/usr/bin/env bash
# check-open-apollo-artifacts.sh — Read-only audit: what Open Apollo files/services remain
#
# Two uninstallers cover different stacks:
#   • scripts/uninstall-usb.sh   — USB (patched snd-usb-audio, ua-usb, user stable stack)
#   • scripts/uninstall.sh       — Thunderbolt (ua_apollo DKMS, /etc/wireplumber, apollo-setup-io)
#
# Usage (no root required for most checks):
#   bash scripts/check-open-apollo-artifacts.sh
#   TARGET_USER=alice bash scripts/check-open-apollo-artifacts.sh

set -uo pipefail

TARGET_USER="${TARGET_USER:-${SUDO_USER:-$USER}}"
TARGET_HOME=$(eval echo "~$TARGET_USER" 2>/dev/null || echo "$HOME")
KERN=$(uname -r)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

FOUND=0

note() { echo -e "${CYAN}$*${NC}"; }
ok_line() { echo -e "${GREEN}[ clean ]${NC} $*"; }
hit() { echo -e "${RED}[ found ]${NC} $*"; FOUND=1; }

check_f() {
    if [ -e "$1" ]; then hit "$1"; else ok_line "$1"; fi
}

check_glob() {
    # $1 = glob pattern, e.g. "/lib/modules/foo/updates/snd-usb-audio.ko*"
    local -a _files
    local _pat=$1
    shopt -s nullglob
    _files=( $_pat )
    shopt -u nullglob
    if [ "${#_files[@]}" -eq 0 ]; then
        ok_line "(none) $1"
    else
        local f
        for f in "${_files[@]}"; do hit "$f"; done
    fi
}

echo ""
echo -e "${BOLD}Open Apollo — artifact audit${NC} (user home: $TARGET_HOME)"
echo "=============================================================="
note "Kernel: $KERN | login user for paths: $TARGET_USER"
echo ""

echo -e "${BOLD}USB stack (uninstall: sudo bash scripts/uninstall-usb.sh)${NC}"
check_f "/etc/udev/rules.d/99-apollo-usb.rules"
check_f "/usr/local/bin/ua-usb-init"
check_f "/usr/local/bin/ua-usb-dsp-init"
check_f "/usr/local/lib/ua-usb"
check_glob "/lib/modules/${KERN}/updates/snd-usb-audio.ko*"
check_f "$TARGET_HOME/.config/wireplumber/main.lua.d/52-apollo-solo-usb-names.lua"
check_f "$TARGET_HOME/.config/wireplumber/main.lua.d/53-apollo-solo-usb-performance.lua"
check_f "$TARGET_HOME/.config/wireplumber/main.lua.d/99-apollo-solo-usb.lua"
check_f "$TARGET_HOME/.config/wireplumber/wireplumber.conf.d/98-apollo-solo-usb-display.conf"
check_f "$TARGET_HOME/.config/wireplumber/wireplumber.conf.d/50-apollo-solo-usb.conf"
check_f "$TARGET_HOME/.config/pipewire/pipewire.conf.d/apollo-solo-usb-io.conf"
check_f "$TARGET_HOME/apollo-safe-start.sh"
check_f "$TARGET_HOME/apollo-hotplug-watch.sh"
check_f "$TARGET_HOME/.config/systemd/user/apollo-audio-fix.service"
check_f "$TARGET_HOME/.config/systemd/user/apollo-hotplug-watch.service"
check_f "$TARGET_HOME/.config/systemd/user/open-apollo-install-resume.service"
check_f "$TARGET_HOME/.config/open-apollo"
check_f "$TARGET_HOME/.cache/open-apollo-snd-usb-build"
if [ -f "$TARGET_HOME/.config/autostart/open-apollo-tray.desktop" ]; then
    if grep -q 'open-apollo-tray\|X-Open-Apollo-Installer=usb-tray' "$TARGET_HOME/.config/autostart/open-apollo-tray.desktop" 2>/dev/null; then
        hit "$TARGET_HOME/.config/autostart/open-apollo-tray.desktop (Open Apollo tray)"
    else
        ok_line "$TARGET_HOME/.config/autostart/open-apollo-tray.desktop (unrelated — different Exec)"
    fi
else
    ok_line "$TARGET_HOME/.config/autostart/open-apollo-tray.desktop"
fi

if command -v modinfo >/dev/null 2>&1; then
    _fn=$(modinfo -F filename snd_usb_audio 2>/dev/null || true)
    if [ -n "$_fn" ]; then
        case "$_fn" in
            */updates/*) hit "snd_usb_audio on disk still under .../updates/ (patched path): $_fn" ;;
            *) ok_line "snd_usb_audio module file (expected stock path): $_fn" ;;
        esac
    else
        note "modinfo snd_usb_audio: (no module — optional package or wrong kernel)"
    fi
else
    note "modinfo not installed — skipped module path check"
fi

if lsmod 2>/dev/null | grep -q '^snd_usb_audio'; then
    ok_line "lsmod: snd_usb_audio loaded (normal after stock modprobe)"
else
    note "lsmod: snd_usb_audio not loaded (run: sudo modprobe snd_usb_audio if you need USB audio)"
fi

echo ""
echo -e "${BOLD}Thunderbolt stack (uninstall: sudo bash scripts/uninstall.sh)${NC}"
check_f "/etc/udev/rules.d/91-ua-apollo.rules"
check_f "/etc/wireplumber/main.lua.d/51-ua-apollo.lua"
check_f "/etc/wireplumber/wireplumber.conf.d/51-ua-apollo.conf"
check_f "/etc/pipewire/pipewire-pulse.conf.d/50-apollo-pulse-rules.conf"
check_f "/etc/pipewire/pipewire.conf.d/10-apollo.conf"
check_f "$TARGET_HOME/.config/pipewire/pipewire.conf.d/apollo-io-map.conf"
check_f "$TARGET_HOME/.config/systemd/user/apollo-setup-io.service"
check_f "/usr/local/bin/apollo-setup-io"
check_f "/usr/share/applications/open-apollo.desktop"
if [ -d /usr/src ]; then
    check_glob /usr/src/ua_apollo-*
else
    ok_line "/usr/src/ua_apollo-*"
fi
if lsmod 2>/dev/null | grep -q '^ua_apollo'; then
    hit "lsmod: ua_apollo kernel module still loaded"
else
    ok_line "lsmod: ua_apollo not loaded"
fi

echo ""
if [ "$FOUND" = "1" ]; then
    echo -e "${YELLOW}Summary:${NC} at least one path above still exists — run the matching uninstaller, then this script again."
    exit 1
fi
echo -e "${GREEN}Summary:${NC} no tracked Open Apollo install files found for this user/kernel."
echo "Firmware (USB) is intentionally kept unless you use: sudo bash scripts/uninstall-usb.sh --purge"
exit 0
