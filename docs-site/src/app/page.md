---
title: Open Apollo
---

Open-source Linux driver and mixer engine for Universal Audio Apollo Thunderbolt audio interfaces. Built through clean-room reverse engineering, Open Apollo brings full hardware support to Linux — playback, recording, mixer control, preamp gain, and DSP routing.

---

## Quick links

- [Installation](/docs/installation) — build and load the driver in minutes
- [Supported Devices](/docs/supported-devices) — check your Apollo model's status
- [How to Contribute](/docs/how-to-contribute) — help us support more devices
- [Architecture Overview](/docs/architecture-overview) — understand how the pieces fit together

---

## Current status

Verified working on **Apollo x4** with full feature coverage:

- **Full duplex audio** — 24 playback and 22 record channels via ALSA
- **All sample rates** — 44.1, 48, 88.2, 96, 176.4, and 192 kHz
- **Preamp control** — gain, 48V phantom power, PAD, low cut, phase invert, mic/line switching
- **Monitor control** — volume, mute, dim, mono
- **DSP mixer routing** — all input buses, aux sends, cue mixes, panning, faders
- **50+ ALSA mixer controls** — integrated with standard Linux audio tools
- **Protocol-compatible daemon** — existing UA Console and UA Connect applications can connect

The driver recognizes all 15 Apollo Thunderbolt models. Models beyond the x4 need community testing — if you own one, [your help is valuable](/docs/how-to-contribute).
