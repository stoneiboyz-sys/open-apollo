---
title: Initialization Sequence
---

How an Apollo Thunderbolt interface boots, connects, and becomes ready for audio. This document describes the complete initialization process as observed through DTrace captures of the macOS UAD2System.kext (v11.8.1) driving an Apollo x4 via Thunderbolt 3.

---

## Overview

Apollo initialization is a multi-phase process involving four processors:

| Processor | Role |
|---|---|
| **Host CPU** | Runs the driver. Orchestrates the entire init sequence via PCIe MMIO |
| **FPGA** | Manages DMA, transport clocks, PCIe BAR0 register interface |
| **SHARC DSP** (x4) | Runs mixer firmware. Processes audio, settings, bus coefficients |
| **ARM MCU** | Controls preamp hardware (PGA2500 relays), front panel, standalone mode |

The host driver must initialize these in the correct order. Skipping steps or reordering them can leave the hardware in a corrupted state where the monitor section (volume knob, dim, mono) stops working after the host disconnects.

---

## Phase 1: Device discovery and polling

Before any active initialization, the host establishes basic communication.

### PCI enumeration

The Apollo appears as a PCIe device on the Thunderbolt bus. The driver:

1. Enables the PCI device and sets bus master mode
2. Maps BAR0 (the entire register space)
3. Reads the FPGA revision at `0x2218` to identify the device type
4. Reads extended capabilities at `0x2234` for DSP count and device features
5. Disables interrupts and allocates MSI vectors

### Background polling

The host begins two continuous polling loops that run throughout the device's lifetime:

| Loop | macOS selector | Rate | Purpose |
|---|---|---|---|
| DSP service | SEL119 (ProcessPlugin) | ~300/sec | Drives DSP processing; delivers parameter updates and reads completions |
| Readback | SEL136 (GetMixerReadback) | ~33 Hz | Reads hardware state: monitor level, preamp flags, gain values, mute/dim/mono status |

These loops start **before** initialization and continue through all phases. The DSP service loop is how the firmware processes queued commands --- without it, settings writes and bus coefficients never take effect.

Additional status polling runs at lower rates:

- System info (SEL109): ~2/sec
- Device info (SEL111): ~2/sec
- DSP load (SEL112): ~8/sec (4 DSPs x 2/sec)
- Plugin readback (SEL120): ~20/sec

---

## Phase 2: DSP channel configuration

Once the device is discovered, the host configures the DSP channel topology.

### Channel configuration (SEL172)

The host sends **2,116 calls** of 64-byte per-channel DSP configuration data. This is the largest single phase by volume (~132 KB). Each call configures one channel's DSP routing parameters.

### Bus topology (SEL117)

47 calls query the bus topology --- how many buses exist and their types.

### BAR0 register probing (SEL100)

145 register reads probe the hardware state.

### Routing tables (SEL171)

8 calls send I/O routing table data (up to ~1200 bytes each). These define which physical inputs map to which DSP channels and which DSP outputs map to which physical outputs.

---

## Phase 3: Session and clock setup

The host establishes a session and configures clocking **before** any mixer parameters.

### Session format (SEL102)

194 calls configure per-channel session parameters. This establishes the audio format (sample size, channel count) for each path through the system.

### Clock and rate sequence

The clock must be configured in this exact order:

1. **Set sample rate** (SEL161) --- e.g., 48 kHz
2. **Set clock source** (SEL163) --- internal vs external, source ID
3. **Set clock master** (SEL162) --- which device is the master
4. **Query clock capabilities** (SEL159) --- available sources and modes
5. **Set latency** (SEL157) --- per-channel latency compensation (130 calls)

{% callout type="warning" title="Order matters" %}
The clock/rate sequence must complete before mixer parameters are sent. If the DSP receives mixer settings before the clock is configured, the internal processing state may be undefined.
{% /callout %}

---

## Phase 4: Mixer parameter initialization

With the session and clock established, the host sends all mixer parameters. This is the core of what makes the monitor section work.

### SetMixerParam (SEL131) --- 278 calls

SEL131 is a 24-byte struct:

```
{session_id: u32, reserved: u32, channel_type: u32, channel_idx: u32, param_id: u32, value: u32}
```

Parameters are sent in this strict order:

#### 4a. Input routing bitmasks (ch_type=1, param 0x13)

**Must be first.** Each input channel needs a routing bitmask that tells the DSP mixer which output buses it can route to.

| Channel range | Description | Value |
|---|---|---|
| 0--3 | Analog inputs 1--4 | `0x0001FFFF` |
| 8--9 | S/PDIF L/R | `0x0001FFFF` (L gets `0x0003FFFF`) |
| 10 | Talkback | `0x0001FFFF` |
| 12--15 | ADAT 1--4 | `0x0001FFFF` |
| 20--23 | ADAT 5--8 | `0x0001FFFF` |
| 24--27 | Virtual 1--4 | `0x0001FFFF` |

The bitmask `0x0001FFFF` enables routing to buses 0--16 (MIX, CUE1, CUE2, AUX, and virtual outputs). Without this bitmask, inputs cannot reach the monitor output.

#### 4b. DSP path routing (ch_type=0)

Four writes enable audio routing paths through the DSP fabric:

| ch_idx | param | value | Purpose |
|---|---|---|---|
| 1 | 0x01 | 1 | Enable digital output path (S/PDIF) |
| 2 | 0x01 | 1 | Enable digital output path (ADAT) |
| 5 | 0x00 | 1 | Enable CUE bus routing path |
| 6 | 0x00 | 1 | Enable CUE bus routing path |

These are system-level routing enables. The monitor section listens to MIX/CUE1/CUE2 buses --- if the CUE bus paths are not enabled, there may be no audio path to the monitor output.

#### 4c. Channel levels (ch_type=1, param 0x16)

Default DSP processing level for all 32 channels:

- Value `0xA0` = -16 dB
- Sent to ch_idx 0--15 and 20--31

#### 4d. Per-channel preamp initialization (ch_type=1)

For each of the 4 physical preamp channels, macOS sends 13 parameters in order:

| # | Param | Name | Default |
|---|---|---|---|
| 1 | 0x13 | Route bitmask | `0x0001FFFF` |
| 2 | 0x16 | Level | `0xA0` (-16 dB) |
| 3 | 0x04 | LowCut filter | 0 (off) |
| 4 | 0x00 | Mic/Line select | 0 (mic) |
| 5--6 | 0x08 | Unknown (sent 2x) | 0 |
| 7 | 0x06 | GainC | 1 (10 dB) |
| 8 | 0x05 | Phase | `0x3F800000` (+1.0f, normal) |
| 9 | 0x07 | Unknown | 0 |
| 10 | 0x11 | Unknown (ch 0--1 only) | 1 |
| 11 | 0x01 | PAD | 0 (off) |
| 12 | 0x03 | 48V phantom | 0 (off) |
| 13 | 0x02 | Link | 0 (unlinked) |
| 14 | 0x13 | Route bitmask (again) | `0x0001FFFF` |

Note: Param 0x11 is only sent for channels 0 and 1, which have HiZ jacks on the Apollo x4.

#### 4e. Monitor section initialization (ch_type=2)

The monitor init sends ~50 unique parameters across three sub-phases. The ch_idx field varies:

- **ch_idx=0**: Global monitor controls (mute, mono, talkback config)
- **ch_idx=1**: Per-output controls (volume, source, HP routing, dim)
- **ch_idx=10**: Mirror/alt-monitor configuration

Key monitor parameters:

| Param | ch_idx | Name | Init value |
|---|---|---|---|
| 0x6a | 0 | Channel config count | 5 (sent 3x as bookend) |
| 0x21 | 1 | Digital output mode | 0 (S/PDIF) |
| 0x13 | 1 | Unknown config | 2 |
| 0x14 | 1 | Unknown config | 2 |
| 0x47 | 0 | Talkback config | 1 (enabled, talkback itself off) |
| 0x46 | 1 | Talkback on/off | 0 (off) |
| 0x43 | 1 | Dim level | 7 (max attenuation) |
| 0x1f | 1 | Sample rate convert | 1 (on) |
| 0x04 | 1 | Monitor source | 0 (MIX bus) |
| 0x01 | 1 | Monitor volume | 172 (-10 dB) |
| 0x03 | 0 | Mute | 0 (unmuted) |
| 0x44 | 1 | Dim | 0 (off) |
| 0x3f | 1 | HP1 source | 0 (CUE1) |
| 0x40 | 1 | HP2 source | 1 (CUE2) |
| 0x2e | 10 | Mirror A destination | `0xFFFFFFFF` (none) |
| 0x2f | 10 | Mirror B destination | `0xFFFFFFFF` (none) |
| 0x48 | 0 | Unknown (transitions 0 to 1) | 0 then 1 |

Param 0x6a (value=5) acts as a bookend signal --- it is sent at the start and end of monitor init. It may trigger the DSP to configure channel group processing slots.

#### 4f. Sample rate (ch_type=3)

A single call: `{session_id, 0, 3, 48000, 0, 0}`. The ch_idx field carries the rate.

### SetMixerChannelCount (SEL164) --- 4 calls

Tells the DSP mixer how many channels are active. Without this, the mixer may not know the channel topology.

### SetMixerSessionConfig (SEL189) --- 6 calls

Loads a complete session configuration. Each call is 144 bytes containing 52 mixer settings as a batch. This is distinct from the per-setting SEL132 writes --- it loads an entire session preset.

The 52-setting count matches the SRAM register space (settings 0--51). The first 38 are flushed per batch cycle; settings 38--51 may contain session metadata that the DSP uses for standalone operation.

{% callout title="SEL189 is macOS CoreAudio software delay compensation" %}
Despite appearing in the session config phase, SEL189 (`SetDeviceOutputDelayComp`) is a CoreAudio software mechanism for compensating for output latency. It is not part of the DSP session configuration and does not affect hardware state.
{% /callout %}

### SetMixerBusParam (SEL130) --- 713 calls

Bus coefficients control fader levels, pan, sends, and mute state. Each call is a 136-byte struct:

```
{session_id: u32, 0: u32, bus_id: u32, 0x02: u32, sub_param: u32, 0: u32, value_f32: u32, ...}
```

Seven sub-parameters per bus:

| Sub | Name | Purpose |
|---|---|---|
| 0 | Main | Mix bus coefficient (fader x pan) |
| 1 | CUE1 | CUE 1 send level |
| 2 | CUE2 | CUE 2 send level |
| 3 | Gain L | Left gain / AUX1 send |
| 4 | Gain R | Right gain / AUX2 send |
| 5 | Mute L | Left channel mute coefficient |
| 6 | Mute R | Right channel mute coefficient |

Bus coefficients are sent to 21 buses:

| Bus range | Description |
|---|---|
| `0x0000`--`0x0003` | Analog inputs 1--4 |
| `0x0008`--`0x0009` | S/PDIF L/R |
| `0x000a` | Talkback 1 |
| `0x000c`--`0x000f` | ADAT 1--4 |
| `0x0010`, `0x0012` | AUX 1/2 return |
| `0x0014`--`0x0017` | ADAT 5--8 |
| `0x0018`--`0x001b` | Virtual 1--4 |

Values are IEEE 754 float. Unity gain is `1.0` for AUX returns, `0.707` (1/sqrt(2), -3 dB) for input faders, and `3.976` for talkback (the talkback reference level). During a fresh init with faders down, most values are `0.0`.

Bus coefficients are interleaved with SEL131 mixer params across 24 sub-phases.

---

## Phase 5: Firmware loading and DSP connection

With all mixer state configured, the host loads DSP firmware and activates DSP modules.

### Firmware loading (SEL127) --- 145 blocks

Each firmware block is loaded through a DMA triplet:

```
SEL115 (AllocSharedDMABuffer) -> SEL127 (SendBlock) -> SEL116 (FreeSharedDMABuffer)
```

Six program types are loaded:

| Module ID | Size | Count | Purpose |
|---|---|---|---|
| `0xEB` | 716 B | 16 | Input routing |
| `0xDA` | 3044 B | 16 | Mixer bus routing |
| `0xA5` | 1940 B | 47 | Mixer core |
| `0xC2` | 184 B | 47 | Output routing |
| `0xDB` | 452 B | 16 | Capture routing |
| `0x12B` | 728 B | 3 | Talkback / monitor special |

Total: 145 blocks, 169,404 bytes.

{% callout title="Key insight" %}
Mixer parameters and bus coefficients are sent **before** firmware loading. The DSP stores them in SRAM and applies them when modules activate. This means the routing and level state must be valid before any DSP program runs.
{% /callout %}

### Per-module activation

Modules are not loaded in bulk. Each module follows this sequence:

1. **Load programs**: N x (SEL115 + SEL127 + SEL116)
2. **Register module**: SEL170 (GetPluginDSPLoad)
3. **Allocate chain**: SEL128 (4 bytes --- allocates an in-memory chain object)
4. **Add to chain**: SEL129 (2800 bytes --- I/O descriptor describing module inputs/outputs)
5. **Activate**: SEL113 (2800 bytes --- commits the chain, triggers DSP resource allocation)
6. **Finalize**: SEL170 + SEL118 (SetPluginLatency)

This repeats 47 times for all modules across all 4 DSPs.

### Module types

The 47 modules fall into three configurations:

| Type | Programs | Count | Role |
|---|---|---|---|
| Full chain | EB + DA + A5 + C2 + DB | 16 (4/DSP) | Complete preamp input processing with capture routing |
| Output only | A5 + C2 | 28 | Digital I/O, virtual channels, auxiliary paths |
| Master mixer | A5 + C2 + DB | 3 (1/DSP 0--2) | Master mixer with capture routing (is_master=1) |

DSP 3 has no master mixer module (no capture routing) --- it handles playback-only virtual channels.

### SEL128/129/113 are kext-internal

These three selectors manage the macOS kext's in-memory C++ plugin graph (CSession, CChain, CPluginInstance objects). They perform:

- `malloc` + `memcpy` + linked-list operations
- Zero BAR0 register writes
- Zero ring buffer submissions
- Zero DMA transfers

The actual hardware delivery happens later through the DSP service loop (SEL119) when `CDSPResourceManager::LoadPlugin` transmits memory-spec updates via ring buffer command `0x00150000`.

A Linux driver does not need these selectors. The equivalent functionality is achieved through:

1. Ring buffer firmware loading (command `0x00020180`)
2. Plugin chain activation via ring buffer (SRAM_CFG, ROUTING, MODULE_ACTIVATE, BUS_COEFF, SYNCH commands)
3. ACEFACE connect handshake

---

## Phase 6: Post-connect finalization

After all modules are activated, the host writes final configuration.

### WriteMixerSetting (SEL132) --- 24 calls

Direct DSP setting writes. These appear ~7 seconds after connect (after ~2000 ProcessPlugin cycles), suggesting the DSP needs time to stabilize before accepting direct setting writes.

The struct is `{setting_index: u32, value: u32, ...}`. Settings 0--11 receive value=1 with mask=0, which ORs bit 0 into each setting while preserving the DSP firmware's internal defaults.

### DSP buffer configuration (SEL108) --- 4 calls

Configures DSP buffer sizes (one per DSP).

---

## Mixer settings batch protocol

The DSP reads mixer parameters through a shared SRAM window using a sequence-counter handshake.

### SRAM layout

52 settings at BAR0 `0x3800`+offset, each setting is 8 bytes (two 32-bit words):

```
Word A: (mask[15:0] << 16) | val[15:0]
Word B: (mask[31:16] << 16) | val[31:16]
```

Settings 0--31 store active data in Word B. Settings 32--51 use Word A.

### Sequence counter handshake

1. Host writes all dirty settings to SRAM
2. Host increments `SEQ_WR` at `0x3808`
3. DSP detects `SEQ_WR != SEQ_RD`
4. DSP reads all settings atomically
5. DSP writes `SEQ_RD` at `0x380C` to match `SEQ_WR`

{% callout type="warning" title="Batch writes only" %}
The DSP reads ALL settings on each SEQ_WR advance. Individual per-setting SEQ_WR bumps corrupt the DSP state --- all settings must be cached and flushed as a single atomic batch.
{% /callout %}

The host flushes at ~10--33 Hz (macOS flushes from the GetMixerReadback handler at 33 Hz).

### Setting index map (partial)

Key settings that control monitor and preamp behavior:

| Index | Contents |
|---|---|
| 0 | Preamp flags ch 0--3 (6-bit stride: Mic/Line, PAD, Link, 48V, LowCut, Phase) + output pads |
| 1 | Sample rate convert, unknown 3-bit config fields |
| 2 | **Monitor core**: volume[7:0], HP1 vol[15:8], mute[17:16], source[19:18], CUE mono/mix, dim |
| 3 | GainC values for ch 0--3 (6-bit packed with gaps) |
| 6 | Mirror A destination, identify, digital mirror |
| 7 | Mirror B destination, talkback config, unknown flags |
| 8 | Digital output mode, CUE alt mix |
| 11 | Mirror config, output reference level |
| 12 | Preamp flags ch 4--7, HP cue source selection |
| 13 | Talkback on/off, DIM level config |
| 14 | DIM level, unknown config |
| 15 | Mirror enables, HP routing values |

---

## Standalone operation

When the host disconnects, the Apollo transitions to standalone mode. The ARM MCU reads front panel controls (volume knob, dim button, mono button) and sends them to the DSP. For this to work:

1. The DSP must have a valid session configuration (from SEL189 or equivalent)
2. Input routing bitmasks must be set (param 0x13)
3. The monitor section settings must be initialized (setting[2] and related)
4. DSP path routing must be enabled (ch_type=0 params)

If any of these are missing or corrupted during the host's init sequence, the monitor section will not function after disconnect. The DSP has no way to reconstruct missing state --- it relies entirely on what the host programmed before disconnecting.

{% callout type="warning" title="Critical: do not overwrite firmware defaults during init" %}
The DSP firmware initializes `setting[2]` (the monitor core register) with valid defaults on cold boot: it contains volume, mute, source, and dim state that the ARM MCU depends on for standalone operation. Writing `setting[2]` with a non-zero mask during driver connect overwrites these defaults and breaks the ARM MCU's ability to control the monitor after host disconnect.

The macOS driver avoids this by sending `mask=0` ("preserve firmware defaults") for settings it has not explicitly configured. The flush function correctly skips settings whose mask is zero. A Linux driver must follow the same convention — only write mixer settings with non-zero masks for fields that have been explicitly set by the host.
{% /callout %}

---

## ACEFACE connect handshake

ACEFACE is the Apollo's PCIe audio extension connect protocol. It establishes the DMA audio streaming connection between the host and the FPGA.

### Sequence

1. Write `0xACEFACE` to the notification ACEFACE register (`0xC02C`)
2. Write connect doorbell to AX_CONNECT register
3. Poll notification status register (`0xC030`) for bit 21 (connect response)
4. On success: read I/O descriptors, rate info, clock info, transport info
5. Clear notification status by writing 0

The kext retries up to 20 times with 9 polls each (100 ms per poll) = ~18 seconds max.

### Post-connect reads

After ACEFACE succeeds, the firmware expects the host to read several registers as acknowledgment:

- **Bit 0**: Output I/O descriptors (72 dwords from `0xC2C4`)
- **Bit 1**: Input I/O descriptors (72 dwords from `0xC1A4`)
- **Bit 22**: Rate info (`0xC07C`) + clock info (`0xC084`)
- **Bit 4**: Transport info (`0xC080`)

Without these reads, the DSP may not advance to active audio routing.

---

## Complete init timeline

Summary of the full sequence with approximate call numbers from a 9,748-call DTrace capture:

| Call # | Selector | Phase | Description |
|---|---|---|---|
| 0--1506 | SEL136/119/109/111/112/120 | Polling | Background service loops |
| 1507 | SEL153/158 | Discovery | Device capability queries |
| 1542 | SEL172 x2116 | Channel config | Per-channel DSP configuration |
| 1588 | SEL117/100/171 | Topology | Bus info, register probe, routing tables |
| 1781 | SEL102 x194 | Session | Per-channel session format |
| 2627 | SEL195 | Audio engine | Unknown pre-audio setup |
| 2628 | SEL161/163/162/159 | Clock | Rate, source, master, capabilities |
| 2651 | SEL157 x130 | Latency | Per-channel latency compensation |
| 2655 | **SEL131 x278** | **Mixer params** | **Route, level, preamp, monitor init** |
| 2715 | SEL164 x4 | Channel count | Mixer channel topology |
| 2717 | SEL189 x6 | Session config | 52-setting session preset load |
| 2734 | **SEL130 x713** | **Bus coefficients** | **Fader, pan, send, mute levels** |
| 2927 | SEL115/127/116 x145 | Firmware | DSP program loading |
| 2943 | SEL170 x129 | I/O routing | Driver I/O assignments |
| 2945 | SEL128/129/113 x47 | Module connect | Per-module chain setup (kext-internal) |
| 2951 | SEL118 x82 | Latency | Plugin chain latency setup |
| 4920 | **SEL132 x24** | **Settings** | **Direct mixer setting writes (after ~7s)** |
| 4948 | SEL108 x4 | DSP config | Buffer size configuration |
| 5436 | SEL196 x2 | Finalize | Unknown late-init |

---

## Selectors that do not touch hardware

Several high-call-count selectors visible in DTrace captures perform no BAR0 register writes and require no Linux equivalent:

| Selector | Name | Call count | What it actually does |
|---|---|---|---|
| SEL172 | `DispatchGetDriverIoRoutings` | 2,116 | READ operation only — copies the kext's internal routing array into the output buffer. No hardware writes. |
| SEL189 | `SetDeviceOutputDelayComp` | 6 | macOS CoreAudio software output delay compensation. Not session config. No hardware writes. |
| SEL128 | `DispatchAllocateChain` | 47 | `malloc` + linked-list insert for a `CChain` C++ object. Zero hardware writes. |
| SEL129 | `DispatchAddSubPluginToChain` | 47 | `memcpy` of a 2,800-byte I/O descriptor into the `CChain` object. Zero hardware writes. |
| SEL113 | `DispatchAllocatePlugin` | 47 | `malloc` + linked-list insert for a `CPluginInstance` C++ object. Zero hardware writes. |

SEL128, SEL129, and SEL113 manage the macOS kext's in-memory C++ plugin graph (CSession, CChain, CPluginInstance). The actual hardware delivery of plugin data happens later through the DSP service loop (SEL119) via ring buffer command `0x00150000`. This was proven by kext binary disassembly: none of these functions access BAR0.
