---
title: Installation
---

Complete guide to building and installing the Open Apollo Linux driver for Universal Audio Apollo Thunderbolt interfaces.

---

## Prerequisites

You need a Linux system with:

- **Kernel headers** for your running kernel
- **GCC** (or compatible C compiler)
- **Make**
- **Python 3.10+** (for the mixer daemon)
- A **Thunderbolt 3/4** port (USB-C Thunderbolt)

### Fedora / RHEL

```bash
sudo dnf install kernel-devel gcc make python3
```

### Ubuntu / Debian

```bash
sudo apt install linux-headers-$(uname -r) build-essential python3
```

### Arch Linux

```bash
sudo pacman -S linux-headers gcc make python
```

---

## Build the driver

> **Automated installer:** The repository includes `scripts/install.sh`, which checks dependencies, builds the kernel module, optionally loads it, and deploys PipeWire/WirePlumber configs interactively. Run `bash scripts/install.sh` from the repo root to use it instead of the manual steps below.

Clone the repository and build the kernel module:

```bash
git clone https://github.com/open-apollo/open-apollo.git
cd open-apollo/driver
make
```

This produces `ua_apollo.ko` — the kernel module.

---

## Load the driver

Make sure your Apollo is connected via Thunderbolt and powered on, then load the module:

```bash
sudo insmod ua_apollo.ko
```

### Verify it loaded

Check kernel messages:

```bash
dmesg | tail -20
```

You should see output like:

```
ua_apollo: Apollo x4 detected (device_type=0x1F)
ua_apollo: Firmware version: ...
ua_apollo: Registered ALSA card ...
```

Check that ALSA sees the device:

```bash
aplay -l
```

You should see an entry for your Apollo interface.

---

## PipeWire / WirePlumber configuration

The repository includes recommended PipeWire and WirePlumber configuration files in the `configs/` directory. These configure:

- S32LE sample format at 48 kHz
- MMAP disabled (required for stability)
- Suspend disabled (keeps the device active)

Deploy the configurations:

```bash
sudo bash configs/deploy.sh
```

This copies the WirePlumber policy and UCM2 profiles to the correct system directories. Restart PipeWire and WirePlumber afterward:

```bash
systemctl --user restart pipewire wireplumber
```

---

## Initialize the Apollo

After loading the driver and deploying configs, use the initialization script to bring the Apollo fully online:

```bash
sudo bash tools/apollo-init.sh
```

This script handles everything needed for a working Apollo:

1. **Loads the driver** (if not already loaded)
2. **Diagnoses DSP state** (cold boot, warm restart, or stalled)
3. **Loads firmware** (on cold boot — replays 15 firmware blocks)
4. **Triggers ACEFACE connect** (activates DSP routing tables)
5. **Starts the mixer daemon** (TCP:4710 + TCP:4720 + WS:4721)
6. **Sets the PipeWire pro-audio profile** (makes Apollo visible in desktop sound settings)

After running, the Apollo should appear in your desktop sound settings and in `wpctl status`.

### Options

```bash
sudo bash tools/apollo-init.sh --no-daemon  # Init only, don't start daemon
sudo bash tools/apollo-init.sh --force       # Force firmware replay
sudo bash tools/apollo-init.sh --status      # Print current Apollo state
```

### Troubleshooting init

If the script reports **DSP STALLED** or **PCIe DEAD**, power cycle the Apollo (unplug power cable, wait 5 seconds, replug) and run the script again.

---

## DKMS setup (persist across kernel updates)

Without DKMS, you need to rebuild and reload the module every time your kernel updates. DKMS automates this.

### Install DKMS

```bash
# Fedora
sudo dnf install dkms

# Ubuntu / Debian
sudo apt install dkms

# Arch
sudo pacman -S dkms
```

### Register the module

From the repository root:

```bash
sudo cp -r driver /usr/src/ua_apollo-0.1.0
sudo dkms add ua_apollo/0.1.0
sudo dkms build ua_apollo/0.1.0
sudo dkms install ua_apollo/0.1.0
```

The module will now rebuild automatically when you install a new kernel.

### Load on boot

Create a module load configuration:

```bash
echo "ua_apollo" | sudo tee /etc/modules-load.d/ua_apollo.conf
```

---

## Next steps

- [Supported Devices](/docs/supported-devices) — check your Apollo model's status
- [Daemon Setup](/docs/daemon-setup) — configure the mixer daemon for full mixer control
- [Troubleshooting](/docs/troubleshooting) — common issues and solutions
