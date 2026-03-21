#!/bin/bash
# install.sh — Build and install the Open Apollo driver and configs
#
# Steps:
#   1. Check dependencies
#   2. Build the kernel module
#   3. Optionally load the driver
#   4. Optionally deploy PipeWire/WirePlumber configs
#   5. Print verification steps

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "Open Apollo — Install"
echo "====================="
echo ""

# --- Step 1: Check dependencies ---
echo "Checking dependencies..."
if ! bash "$SCRIPT_DIR/check-deps.sh"; then
    echo ""
    printf "${RED}Cannot proceed — missing dependencies.${NC}\n"
    exit 1
fi
echo ""

# --- Step 2: Build the driver ---
echo "Building kernel module..."
if make -C "$PROJECT_DIR/driver" clean > /dev/null 2>&1; then
    true  # clean is best-effort
fi

if make -C "$PROJECT_DIR/driver"; then
    printf "${GREEN}Build successful.${NC}\n"
else
    printf "${RED}Build failed. Check the output above for errors.${NC}\n"
    exit 1
fi
echo ""

# --- Step 3: Load the driver ---
read -rp "Load the driver now? (requires sudo) [y/N] " load_answer
if [[ "$load_answer" =~ ^[Yy]$ ]]; then
    # Unload existing module if present
    if lsmod | grep -q ua_apollo; then
        echo "Unloading existing ua_apollo module..."
        sudo rmmod ua_apollo
    fi

    echo "Loading ua_apollo module..."
    if sudo insmod "$PROJECT_DIR/driver/ua_apollo.ko"; then
        printf "${GREEN}Driver loaded successfully.${NC}\n"
    else
        printf "${RED}Failed to load driver. Check dmesg for details.${NC}\n"
    fi
else
    echo "Skipped. Load manually with:"
    echo "  sudo insmod $PROJECT_DIR/driver/ua_apollo.ko"
fi
echo ""

# --- Step 4: Deploy PipeWire/WirePlumber configs ---
read -rp "Install PipeWire/WirePlumber/UCM2 configs? (requires sudo) [y/N] " config_answer
if [[ "$config_answer" =~ ^[Yy]$ ]]; then
    if [ -f "$PROJECT_DIR/configs/deploy.sh" ]; then
        sudo bash "$PROJECT_DIR/configs/deploy.sh"
    else
        printf "${YELLOW}configs/deploy.sh not found — skipping.${NC}\n"
    fi
else
    echo "Skipped. Deploy configs manually with:"
    echo "  sudo bash $PROJECT_DIR/configs/deploy.sh"
fi
echo ""

# --- Step 5: Verification ---
echo "==============================="
echo "Verification steps:"
echo ""
echo "  1. Check driver loaded:   lsmod | grep ua_apollo"
echo "  2. Check kernel log:      sudo dmesg | tail -20"
echo "  3. List ALSA devices:     aplay -l"
echo "  4. List capture devices:  arecord -l"
echo ""
echo "  If using PipeWire:"
echo "  5. Restart PipeWire:      systemctl --user restart pipewire wireplumber"
echo "  6. Check status:          wpctl status"
echo ""
printf "${GREEN}Done.${NC}\n"
