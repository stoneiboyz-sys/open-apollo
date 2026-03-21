#!/bin/bash
# check-deps.sh — Check for required build dependencies
#
# Verifies that all tools needed to build and run Open Apollo are present.
# Reports missing dependencies with distribution-specific install commands.

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

MISSING=0

check() {
    local name="$1"
    local check_cmd="$2"
    local fedora_pkg="$3"
    local debian_pkg="$4"
    local arch_pkg="$5"

    if eval "$check_cmd" > /dev/null 2>&1; then
        printf "  ${GREEN}[OK]${NC}  %s\n" "$name"
    else
        printf "  ${RED}[  ]${NC}  %s — not found\n" "$name"
        printf "        Fedora:       sudo dnf install %s\n" "$fedora_pkg"
        printf "        Ubuntu/Debian: sudo apt install %s\n" "$debian_pkg"
        printf "        Arch:         sudo pacman -S %s\n" "$arch_pkg"
        echo ""
        MISSING=$((MISSING + 1))
    fi
}

echo ""
echo "Open Apollo — Dependency Check"
echo "==============================="
echo ""

# Build tools
echo "Build tools:"
check "gcc" "command -v gcc" "gcc" "gcc" "gcc"
check "make" "command -v make" "make" "make" "make"
check "kernel headers" "test -d /lib/modules/\$(uname -r)/build" \
    "kernel-devel" "linux-headers-\$(uname -r)" "linux-headers"

echo ""

# Runtime
echo "Runtime:"
check "python3 (>= 3.8)" \
    "python3 -c 'import sys; assert sys.version_info >= (3,8)'" \
    "python3" "python3" "python3"

echo ""

# Optional (informational only)
echo "Optional (for PipeWire integration):"
if command -v wpctl > /dev/null 2>&1; then
    printf "  ${GREEN}[OK]${NC}  wireplumber\n"
else
    printf "  ${YELLOW}[--]${NC}  wireplumber — not found (optional, for PipeWire integration)\n"
fi

if command -v pw-cli > /dev/null 2>&1; then
    printf "  ${GREEN}[OK]${NC}  pipewire\n"
else
    printf "  ${YELLOW}[--]${NC}  pipewire — not found (optional, for audio routing)\n"
fi

echo ""

if [ "$MISSING" -gt 0 ]; then
    printf "${RED}%d required dependency(ies) missing.${NC}\n" "$MISSING"
    echo "Install them and re-run this script."
    exit 1
else
    printf "${GREEN}All required dependencies found.${NC}\n"
    exit 0
fi
