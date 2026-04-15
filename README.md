[![Release](https://img.shields.io/github/v/release/rolotrealanis98/open-apollo?style=flat-square)](https://github.com/rolotrealanis98/open-apollo/releases)
[![License: GPL v2](https://img.shields.io/badge/License-GPL_v2-blue.svg?style=flat-square)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)
[![Ubuntu 24.04](https://img.shields.io/badge/Ubuntu-24.04-E95420?style=flat-square&logo=ubuntu&logoColor=white)](https://github.com/rolotrealanis98/open-apollo/wiki/Hardware-Compatibility)
[![Docs](https://img.shields.io/badge/docs-open--apollo-blue?style=flat-square)](https://open-apollo-docs.pages.dev)
[![Issues](https://img.shields.io/github/issues/rolotrealanis98/open-apollo?style=flat-square)](https://github.com/rolotrealanis98/open-apollo/issues)

# Open Apollo

**Open-source Linux driver and tools for Universal Audio Apollo Thunderbolt and USB interfaces**

Open Apollo brings Linux support to Universal Audio's Apollo audio interfaces.
Built through clean-room reverse engineering, this community-driven project
provides a native kernel driver for Thunderbolt models and a pure-userspace
stack for USB models, along with a mixer daemon and system tray indicator.

> **⚠️ Experimental** — This project is under active development and not yet ready
> for production use. Expect rough edges, kernel stability issues on some
> configurations, and incomplete features. We're shipping early to get community
> feedback and testing across different Apollo models.

## What Works (Apollo x4 — Thunderbolt, Ubuntu 24.04)

- **Full duplex audio** — 4 analog inputs + 6 analog outputs verified (24/22 total ALSA channels exposed; S/PDIF, ADAT, and virtual channels are unverified)
- **All sample rates** — 44.1, 48, 88.2, 96, 176.4, 192 kHz
- **Preamp control** — gain, 48V phantom power, PAD, low cut, phase invert, mic/line switching
- **Monitor control** — volume, mute, dim, mono, talkback, headphone routing
- **DSP mixer** — input faders, pan, sends (AUX1/AUX2, CUE1/CUE2), solo, mute
- **PipeWire virtual I/O** — named Mic 1-4, Line In 3+4, Monitor L/R, Line Out devices
- **Desktop audio** — YouTube, system sounds, GNOME volume control all work through Apollo Monitor
- **WebRTC capture** — clean audio in Chromium-based browsers (webcam mic tests, Discord web)
- **pw-record/pw-play** — zero-dropout capture and playback verified
- **Guided installer** — `sudo bash scripts/install.sh` with hardware validation gates + audio test
- **System tray indicator** — real-time hardware status

## What Works (Apollo Solo USB)

Confirmed working on Ubuntu Studio 24.04 / Intel Tiger Lake-H by contributor @stoneiboyz-sys:

- **6ch playback** — S32_LE 48kHz, confirmed on Ubuntu Studio 24.04 (Intel) and CachyOS (AMD)
- **10ch capture** — confirmed working; one-shot `usb-full-init.py` (38 packets, includes DSP program load), then `modprobe snd_usb_audio`
- **PipeWire capture** — mic input working end-to-end; Discord voice calls, `pw-record`, browser tabs confirmed
- **Hardware monitoring** — mic → headphones simultaneous with active PipeWire streams
- **Preamp control** — gain, 48V phantom power, mic/line switching via vendor control
- **Monitor control** — level, mute, mono
- **PipeWire playback** — browser audio, system audio, DAWs all work
- **Patched snd-usb-audio** — four out-of-tree patches (fixed-rate quirk, implicit feedback skip, endpoint compat bypass, IFACE_SKIP_CLOSE)
- **Automatic init via udev** — firmware upload + full DSP init on device plug-in; no daemon required
- **Session tray** — `install-usb.sh` tries to install GTK/AppIndicator packages on **apt** / **dnf** systems, then registers session autostart for `tools/open-apollo-tray.py` (icon = Solo USB + PipeWire readiness; menu **Buffer size (USB)** + **USB mixer…**). If packages are unavailable, run **`bash scripts/install-open-apollo-tray-autostart.sh`** after installing them, then log out/in. Standalone mixer: **`python3 tools/open-apollo-usb-mixer.py`** (48V, mic/line, PAD/low-cut expérimental, gain, monitor casque).

### USB project scope — base card vs DSP (do not mix the two)

**Base sound card (current focus)** — What we optimize for first: the Apollo shows up as a **normal USB audio device** on Linux (firmware, `snd-usb-audio`, ALSA visible, PipeWire sinks/sources), with **playback, capture, headphones, and stable hotplug/login**. The recommended path is **`--stable-default`**. This is *not* the same goal as full Universal Audio Console / DSP parity.

**DSP & console-class features (later in the project)** — Full **DSP replay** on plug-in, legacy **udev auto-init**, deeper on-device mixer behavior, and tooling that chases UA Console semantics. That track exists (e.g. **`--legacy-dsp`**, `usb-full-init.py`, mixer work) but is **explicitly secondary**: we document and harden **base-card behavior** first so users are not forced to depend on the heavy DSP path for everyday audio.

Issues and PRs should state which track they target (**base card** vs **DSP / legacy**).

**PipeWire I/O** (which script generates which virtual devices): [`configs/pipewire/README.md`](configs/pipewire/README.md).

### USB Known Issues

| Issue | Status | Notes |
|-------|--------|-------|
| **Full init crash at packet 28** | Known | Some firmware builds crash on IIR biquad SRAM write (address mismatch); observed on CachyOS/AMD (@ariahello) with a different Cauldron build. Playback still works |
| **Intel xHCI EP6 flood** | Resolved | One-shot `usb-full-init.py` stabilizes device; EP6 drain daemon removed from stack |
| **PipeWire capture zeros** | Fixed | Resolved by `QUIRK_FLAG_IFACE_SKIP_CLOSE` patch (quirks.c, patch 4) — prevents snd-usb-audio from resetting Interface 3 on stream close |
| **DSP init ordering** | Documented | `usb-full-init.py` runs before `modprobe snd_usb_audio`; reversed from previous documentation |

{% callout type="note" %}
USB support uses `sudo bash scripts/install-usb.sh`. See [USB Quick Start](#usb-quick-start-apollo-solo-usb) below.
{% /callout %}

## Known Issues

| Issue | Severity | Workaround |
|-------|----------|------------|
| **Firefox Snap crashes** — kernel `hrtimer` lockup when using WebRTC capture | Critical | Use Chromium or Firefox .deb instead of Snap |
| **Raw pro-audio node crash** — apps selecting "Apollo x4 Pro" (22ch) as input can hang the system | Critical | Default source is set to Mic 1; avoid selecting the raw multichannel device |
| **WebRTC capture pitch drift** — brief pitch wobble (~1-3s) when browser capture starts; stabilizes automatically. This is normal PipeWire DLL lock-in behavior affecting all pro-audio interfaces through the PulseAudio bridge. | Minor | Normal — wait for it to stabilize. Native PipeWire apps (`pw-record`, Ardour, OBS) have zero drift. |
| **Apollo hot-unplug** — powering off Apollo while driver is loaded | Fixed | Shutdown guards prevent crash; system stays stable ([#22](https://github.com/rolotrealanis98/open-apollo/issues/22)) |
| **Ardour JACK routing** — Ardour via JACK can steal ALSA device from PipeWire | Moderate | Launch with `pw-jack ardour7`; restart PipeWire if audio stops |
| **Audacity ALSA-only** — Ubuntu's Audacity package lacks PipeWire backend | Minor | Install Audacity via Flatpak for PipeWire support |
| **GNOME Sound Settings** — input level meter may not show activity | Cosmetic | Audio works; meter is a GNOME UI limitation with pro-audio devices |
| **Warm reboot requires Apollo power cycle** — rebooting Linux while Apollo stays powered leaves firmware in a stale state; audio won't work until Apollo is power-cycled | Moderate | After reboot: turn Apollo off, wait 5s, turn back on. Hot-replug auto-recovers within ~7s. Cold boot (Apollo powered on after Linux) works without issues. |

## App Compatibility

| App | Status | Notes |
|-----|--------|-------|
| **Chromium / Chrome** | Verified | Recommended browser for WebRTC capture |
| **Firefox .deb** | Untested | Should work; Snap version crashes (see Known Issues) |
| **Discord .deb** | Verified (USB) | Voice calls with mic input confirmed on Apollo Solo USB (Ubuntu Studio 24.04) |
| **OBS Studio** | Untested | Should work natively with PipeWire |
| **Ardour** | Partial | Use `pw-jack ardour7`; don't let it grab ALSA directly |
| **Audacity** | Partial | Flatpak version only (Ubuntu .deb lacks PipeWire backend) |
| **pw-record / pw-play** | Verified | Zero-drift, cleanest capture path |
| **REAPER** | Untested | Expected to work via `pw-jack` |

**Recommendation:** Use Chromium-based browsers for WebRTC. Use native PipeWire apps (`pw-record`, Ardour, OBS) for studio-quality recording with zero clock drift.

## Not Yet Implemented

Virtual/monitor loopback, console UI, multi-device support, plugin chain (UAD plugins require PACE licensing — not planned)

## Supported Devices

### Thunderbolt Models

| Device | Status |
|--------|--------|
| Apollo x4 | **Partially Verified** — analog I/O (Mic 1-4, Monitor, Line Out), preamps, gain, DSP settings. S/PDIF, ADAT, virtual channels untested. |
| Apollo x4 Gen 2 | Needs Testing |
| Apollo x6 / Gen 2 | Needs Testing |
| Apollo x8 / Gen 2 | Needs Testing |
| Apollo x8p / Gen 2 | Needs Testing |
| Apollo x16 / Gen 2 | Needs Testing |
| Apollo x16D | Needs Testing |
| Apollo Twin X / Gen 2 | Needs Testing |
| Apollo Solo (Thunderbolt) | Needs Testing |
| Apollo 8P (original) | Needs Testing |
| Arrow | Needs Testing |

All Thunderbolt Apollo models share the same register map and protocol — the driver
includes device detection and channel configuration for every model listed above.
We need community testers to verify each one.

### USB Models

| Device | Status |
|--------|--------|
| Apollo Solo USB | **Verified** — USB, playback + capture, preamp control, PipeWire integration |
| Apollo Twin USB | Needs Testing |
| Apollo Twin X USB | Needs Testing |

### Thunderbolt 2 Devices (Not Supported)

Older Apollo models with **Thunderbolt 2** connections (Apollo Twin, Apollo 8, Apollo 16, Apollo Duo, Apollo Quad) are **not expected to work**, even with an Apple Thunderbolt 2 → 3 adapter.

The issue is not the driver — it's that **Linux does not enumerate Thunderbolt 2 PCIe devices** in most configurations. The Apollo will not appear in `lspci` output, so the driver has nothing to bind to. This has been confirmed by a community member testing an Apollo Twin (TB2) with an Apple adapter on a Linux laptop with Thunderbolt 3 ports — the install completed successfully but the device was never detected.

If your Apollo uses a Thunderbolt 2 connector (Mini DisplayPort-shaped, not USB-C), you will likely hit this limitation. This project targets **Thunderbolt 3/4 Apollo models** (USB-C connector) on systems with native Thunderbolt 3 or 4 ports.

## Quick Start

### Prerequisites

- Ubuntu 24.04+, Fedora 40+, Arch, openSUSE Tumbleweed, Linux Mint 22, Pop!_OS 24.04, Manjaro
- Linux kernel 6.8+ with headers installed (required — uses `hrtimer_types.h` introduced in 6.8)
- Thunderbolt 3 or 4 connection (see [Thunderbolt 2 note](#thunderbolt-2-devices-not-supported) below)
- GCC, Make
- Python 3.10+ (for mixer daemon)
- `iommu=pt` kernel parameter required on most systems (see below)

### Install

```bash
git clone https://github.com/rolotrealanis98/open-apollo.git
cd open-apollo
sudo bash scripts/install.sh
```

The installer is a guided walkthrough that:
1. Installs dependencies, builds the driver, sets up DKMS
2. Deploys PipeWire/WirePlumber/UCM2 configs
3. Guides you through an Apollo power cycle for clean Thunderbolt initialization
4. Loads the driver, verifies DSP handshake, sets up virtual I/O devices
5. Starts the mixer daemon and tray indicator
6. Plays a test tone so you can verify audio output

### NixOS (Thunderbolt)

Add to your `flake.nix` inputs:

```nix
inputs.open-apollo.url = "github:rolotrealanis98/open-apollo";
```

Then in your `configuration.nix`:

```nix
imports = [ inputs.open-apollo.nixosModules.default ];
hardware.ua-apollo.enable = true;
```

Run `nixos-rebuild switch` — the module handles the kernel module build, `iommu=pt`, Thunderbolt (bolt), PipeWire, and required packages.

### Uninstall

```bash
sudo bash scripts/uninstall.sh
```

Removes driver, DKMS, all configs, services, and guides you through Apollo power-off for clean module unload.

### Troubleshooting

If audio stops working after using a JACK app (Ardour, etc):
```bash
systemctl --user restart pipewire wireplumber pipewire-pulse
apollo-setup-io
```

### Virtual I/O devices (Apollo x4)

After running `apollo-setup-io`, these devices are available in PipeWire:

| Device | Type | Channels |
|--------|------|----------|
| Apollo Mic 1 | Source (capture) | Mono |
| Apollo Mic 2 | Source (capture) | Mono |
| Apollo Mic 1+2 | Source (capture) | Stereo |
| Apollo Mic 3 | Source (capture) | Mono |
| Apollo Mic 4 | Source (capture) | Mono |
| Apollo Line In 3+4 | Source (capture) | Stereo |
| Apollo Monitor L/R | Sink (playback) | Stereo |
| Apollo Line Out 1+2 | Sink (playback) | Stereo |
| Apollo Line Out 3+4 | Sink (playback) | Stereo |

### USB Quick Start (Apollo Solo USB)

```bash
git clone https://github.com/rolotrealanis98/open-apollo.git
cd open-apollo
sudo bash scripts/install-usb.sh
```

Optional install mode flags:

```bash
# Recommended default (stable startup/hotplug behavior)
sudo bash scripts/install-usb.sh --stable-default

# Legacy behavior (full DSP auto-init via udev)
sudo bash scripts/install-usb.sh --legacy-dsp
```

Non-interactive installs (no “press Enter” prompts): `OPEN_APOLLO_ASSUME_YES=1 sudo -E bash scripts/install-usb.sh --stable-default` — note that **this also skips the guided Apollo power-cycle step**; omit `OPEN_APOLLO_ASSUME_YES` if you want that assistant.

Preview the installer UI only (no install): `bash scripts/install-usb.sh --demo-ui`

**Clean uninstall → reinstall (full assistant, hot-plug + reboot test):** run `sudo bash scripts/uninstall-usb.sh` (add `--purge` only if you intend to remove firmware too). The uninstaller removes udev, patched `snd-usb-audio`, WirePlumber drops, **user systemd units** (`apollo-*`, `open-apollo-install-resume`), **`~/apollo-safe-start.sh`** / **`~/apollo-hotplug-watch.sh`**, generated **`apollo-solo-usb-io.conf`**, **`~/.config/open-apollo/`**, and tray autostart where tagged by install-usb. To see what is still on disk, run **`bash scripts/check-open-apollo-artifacts.sh`** (USB + Thunderbolt paths; no sudo). Thunderbolt-only leftovers need **`sudo bash scripts/uninstall.sh`** instead. Then, from a **normal terminal** (not piped stdin), run `sudo bash scripts/install-usb.sh --stable-default` **without** `OPEN_APOLLO_ASSUME_YES` and **without** `--no-guided-verify`. Follow the on-screen power-cycle prompt, finish the install, **reboot** when suggested, then after login check the notification / `~/.config/open-apollo/last-verify.txt` and test hot-plug (unplug/replug Apollo, run `~/apollo-safe-start.sh` if needed).

In **stable** mode, an interactive install also walks you through a short **Apollo power-cycle** check (USB + ALSA), then schedules a **one-shot post-reboot verification** (user systemd at next login). After login you should get a **desktop notification** (and a text recap in `~/.config/open-apollo/last-verify.txt`); full logs: `journalctl --user -u open-apollo-install-resume.service -e`. Skip that handoff with `--no-guided-verify` or `OPEN_APOLLO_SKIP_GUIDED_VERIFY=1`. After reboot you can always run `bash scripts/install-usb.sh --resume-verify` manually.

The installer handles dependencies, firmware setup, kernel module build, PipeWire configuration, and (depending on mode) **light vendor init** or **full legacy DSP init**. You'll need the Apollo firmware file from UA's website — the installer will prompt you if it's missing. With GTK/AppIndicator Python bindings available, it also drops a **tray autostart** (`~/.config/autostart/open-apollo-tray.desktop`) so you can see plug-in status and change the USB ALSA buffer from the menu; otherwise install those packages and run `python3 tools/open-apollo-tray.py` once manually.

### USB Stable Mode (Recommended)

If your system is sensitive to full DSP replay timeouts or startup crackle, use the
stable userspace recovery flow:

1. Keep the heavy udev DSP replay script disabled (`ua-usb-dsp-init.disabled`).
2. Use vendor-only monitor recovery + PipeWire sink auto-fix via user services.

Install the stable user services:

```bash
cd open-apollo
bash scripts/install-apollo-safe-user.sh
```

What this enables:

- `apollo-safe-start.sh` — vendor-only monitor restore (`--vendor-monitor-hp-only`), ensures `snd_usb_audio` is loaded, restarts PipeWire/WirePlumber, and selects Apollo sink.
- `apollo-audio-fix.service` — runs once at login.
- `apollo-hotplug-watch.service` — reruns the fix when sound devices hotplug/change.
- `ua-usb-post-firmware-stable` (udev root helper) — runs automatically on live Apollo USB enumeration to apply lightweight post-firmware recovery without full DSP replay.

Disable later if needed:

```bash
systemctl --user disable --now apollo-hotplug-watch.service apollo-audio-fix.service
```

### USB Stable Mode Validation (2-Min)

Run this quick checklist after install:

1. Reboot Linux with Apollo powered on.
2. Confirm both services are active:
   ```bash
   systemctl --user status apollo-audio-fix.service apollo-hotplug-watch.service --no-pager
   ```
3. Confirm Apollo sink is default:
   ```bash
   pactl get-default-sink
   pactl list short sinks
   ```
4. Play system audio and verify output in Apollo headphones/monitors.
5. Test mic direct monitor and capture:
   ```bash
   arecord -D plughw:USB -f S32_LE -r 48000 -c 2 -d 3 /tmp/apollo-test.wav
   ```
6. Hotplug test: unplug/replug Apollo USB and wait ~5-10s; verify system audio auto-recovers without manual commands.

If sink is not selected after reboot/hotplug, run:

```bash
~/apollo-safe-start.sh
```

After install, the following PipeWire devices are available:

| Device | Type | Channels |
|--------|------|----------|
| Apollo Solo USB Mic 1 | Source (capture) | Mono |
| Apollo Solo USB Mic 2 | Source (capture) | Mono |
| Apollo Solo USB Mic 1+2 | Source (capture) | Stereo |
| Apollo Solo USB Monitor | Sink (playback) | Stereo |
| Apollo Solo USB Headphone | Sink (playback) | Stereo |

### Start the Mixer Daemon

```bash
cd mixer-engine
python3 ua_mixer_daemon.py -v
```

The daemon exposes TCP:4710, TCP:4720, and WS:4721 for mixer control from any client application.

## Architecture

```
┌──────────────┐   ┌──────────────┐
│ Control App  │   │ Control App  │
│ (TCP:4710)   │   │ (TCP:4720)   │
└──────┬───────┘   └──────┬───────┘
       │                  │
       └────────┬─────────┘
                │
       ┌────────▼────────┐
       │  Mixer Daemon   │
       │  (Python)       │
       └────────┬────────┘
                │ ioctl
       ┌────────▼────────┐
       │  Kernel Driver  │
       │  (ua_apollo.ko) │
       └────────┬────────┘
                │ MMIO
       ┌────────▼────────┐
       │  Apollo Hardware │
       │  (BAR0 regs)    │
       └─────────────────┘
```

## Components

| Component | Path | Description |
|-----------|------|-------------|
| **Driver** | `driver/` | Linux PCIe kernel module — DMA, ALSA, DSP ring buffer, preamp control |
| **Mixer Daemon** | `mixer-engine/` | TCP:4710 + TCP:4720 + WS:4721 daemon — state tree, hardware routing, metering |
| **Configs** | `configs/` | PipeWire, WirePlumber, and UCM2 configuration profiles |
| **Tools** | `tools/contribute/` | Device probe and capture scripts for community contributions |

## Documentation

Full documentation at **[open-apollo-docs.pages.dev](https://open-apollo-docs.pages.dev/)**, including:

- [Installation guide](https://open-apollo-docs.pages.dev/docs/installation) — build, install, configure
- [Supported devices](https://open-apollo-docs.pages.dev/docs/supported-devices) — model compatibility table
- [Architecture overview](https://open-apollo-docs.pages.dev/docs/architecture-overview) — how the pieces fit together
- [Register map](https://open-apollo-docs.pages.dev/docs/register-map) — BAR0 hardware register documentation
- [DSP protocol](https://open-apollo-docs.pages.dev/docs/dsp-protocol) — ring buffer commands and settings batch protocol
- [How to contribute](https://open-apollo-docs.pages.dev/docs/how-to-contribute) — testing, device captures, code contributions

Documentation content lives in the [`docs/`](docs/) directory of this repo. Edit the
Markdown files there and submit a PR — changes are automatically deployed to the
docs site.

## Contributing

We welcome contributions of all kinds — from device testing reports to driver
code. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

**The most impactful thing you can do right now is test on your hardware.** If you
own any Apollo model besides the x4, your testing report directly enables support
for that device.

### Quick contribution path

1. Build and load the driver
2. Run `./tools/contribute/device-probe.sh`
3. [Submit a device report](https://github.com/open-apollo/open-apollo/issues/new?template=device-report.yml)

## License

This project is licensed under the [GNU General Public License v2.0](LICENSE).

See [NOTICE.md](NOTICE.md) for information about trademarks and intellectual
property.
