---
title: Installation
---

Complete guide to building and installing the Open Apollo Linux driver for Universal Audio Apollo Thunderbolt interfaces.

---

## Before you begin

{% callout type="warning" title="Turn OFF the Apollo before installing" %}
If your Apollo is powered on and connected via Thunderbolt, DKMS module auto-loading during installation can cause the system to hang. **Power off the Apollo first.** You do not need to unplug the Thunderbolt cable — just turn the unit off. Power it back on after the install completes.
{% /callout %}

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

## Build and install

The repository includes an interactive installer that handles everything: dependency checks, kernel module build, DKMS registration, IOMMU detection, PipeWire/WirePlumber config deployment, and tray indicator setup.

```bash
git clone https://github.com/open-apollo/open-apollo.git
cd open-apollo
sudo bash scripts/install.sh
```

The installer will walk you through each step interactively. Options:

```bash
sudo bash scripts/install.sh --skip-init   # Skip hardware init
sudo bash scripts/install.sh --no-dkms     # Skip DKMS setup
sudo bash scripts/install.sh --help        # Show all options
```

### Manual build (alternative)

If you prefer to build manually instead of using the installer:

```bash
cd open-apollo/driver
make
```

This produces `ua_apollo.ko` — the kernel module. Load it with:

```bash
sudo insmod ua_apollo.ko
```

### Verify the driver loaded

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

## IOMMU / Intel VT-d

Ubuntu and many other distributions enable IOMMU (Intel VT-d or AMD-Vi) by default. Without passthrough mode, the driver cannot communicate with the Apollo — BAR0 register reads return `0xFFFFFFFF` and the device is unusable.

The install script detects this automatically and offers to add `iommu=pt` to your GRUB configuration. If you need to do it manually:

1. Edit `/etc/default/grub`
2. Add `iommu=pt` to `GRUB_CMDLINE_LINUX_DEFAULT`:
   ```
   GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt"
   ```
3. Update GRUB:
   ```bash
   sudo update-grub          # Ubuntu/Debian
   sudo grub2-mkconfig -o /boot/grub2/grub.cfg  # Fedora
   ```
4. Reboot

This is safe and does not affect other devices. It simply tells the kernel to use passthrough mode for DMA, which is required for the Apollo's PCIe BAR0 registers to be accessible.

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

The install script handles this automatically if you use `scripts/install.sh`.

---

## Post-install: powering on the Apollo

After the install completes:

1. **Power on the Apollo** using its rear power switch
2. **Wait approximately 20 seconds** for Thunderbolt enumeration to complete
3. The driver auto-loads via DKMS — no manual `insmod` needed
4. The WirePlumber rule automatically sets the pro-audio profile
5. The Apollo should appear in your desktop Sound Settings as **"Apollo x4 Pro"** (or your model name)

You can verify with:

```bash
wpctl status          # Apollo should appear under Audio devices
aplay -l              # ALSA card listing
```

---

## Initialize the Apollo

After loading the driver and deploying configs, the Apollo needs initialization to load firmware and activate the DSP. This is required after every cold boot (powering the Apollo from off).

### Using the tray indicator

Click the Open Apollo tray icon and select **"Initialize Apollo..."** — this runs the init script with a graphical progress dialog.

### Using the command line

```bash
sudo bash tools/apollo-init.sh
```

The init script handles:

1. **Loads the driver** (if not already loaded)
2. **Diagnoses DSP state** (cold boot, warm restart, or stalled)
3. **Loads firmware** (on cold boot — replays 15 firmware blocks)
4. **Triggers ACEFACE connect** (activates DSP routing tables)
5. **Starts the mixer daemon** (TCP:4710 + TCP:4720 + WS:4721)
6. **Sets the PipeWire pro-audio profile** (makes Apollo visible in desktop sound settings)

On a warm boot (Apollo was already powered on), the DSP may already be alive. The init script detects this and skips firmware loading automatically.

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

## System tray indicator

The Open Apollo tray indicator is installed automatically by the install script and auto-starts on login.

### Icon colors

| Color | Meaning |
|-------|---------|
| **Green** | Everything is working — driver loaded, DSP alive, daemon running |
| **Yellow** | Needs attention — Apollo needs initialization, or daemon is stopped |
| **Red** | Apollo disconnected or PCIe link dead |
| **Gray** | Driver not loaded |

### Menu actions

- **Initialize Apollo...** — runs `apollo-init.sh` (firmware load + DSP connect + daemon start)
- **Restart Daemon** — restarts the mixer daemon
- **Stop Daemon** — stops the mixer daemon
- **Reload PipeWire Profile** — re-applies the pro-audio profile
- **Open Daemon Log** — opens `/tmp/ua-mixer-daemon.log` in your default text editor

You can also launch the tray indicator manually from Activities by searching **"Open Apollo"**.

---

## DKMS setup (persist across kernel updates)

The install script sets up DKMS automatically. If you installed manually, you can configure DKMS separately so the module rebuilds when your kernel updates.

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

## Known limitations

- **Apollo must be powered off during installation** — DKMS auto-loading while the Apollo is connected can cause system hangs
- **`apollo-init.sh` must be run after each cold boot** — a systemd service for automatic initialization is planned for a future release
- **`iommu=pt` kernel parameter is required** on systems with Intel VT-d or AMD-Vi enabled (most modern systems, including Ubuntu defaults)
- **Audacity and raw-ALSA apps may freeze the desktop** — these apps probe ALSA devices directly, bypassing PipeWire, which can lock up the audio subsystem. Use PipeWire-native applications instead: `pw-record`, `pw-play`, REAPER, Ardour, or any JACK-compatible DAW
- **PCIe address varies** between Thunderbolt connections — the driver handles this automatically, but don't hardcode addresses in scripts

---

## Verified configurations

| Distro | Kernel | CPU | Thunderbolt | Status |
|--------|--------|-----|-------------|--------|
| Ubuntu 24.04.4 LTS | 6.17.0-19-generic | Intel i9-14900K | Thunderbolt 4 (Maple Ridge) | Fully working |
| Fedora 43 | 6.18.16-200.fc43.x86_64 | — | Thunderbolt 3 | Fully working |

---

## Next steps

- [Supported Devices](/docs/supported-devices) — check your Apollo model's status
- [Daemon Setup](/docs/daemon-setup) — configure the mixer daemon for full mixer control
- [Troubleshooting](/docs/troubleshooting) — common issues and solutions
