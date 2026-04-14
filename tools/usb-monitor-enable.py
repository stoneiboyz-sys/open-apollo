#!/usr/bin/env python3
"""Activate hardware monitoring on Apollo Solo USB.

Hardware monitoring (mic → headphones) is enabled by the DSP firmware
by default on cold boot.  The only host-side requirement is:
  1. Vendor ctrl set[2] monitor level is non-zero and unmuted
  2. The seq counter written to 0x0602 is higher than the FPGA's
     internal counter — otherwise the settings write is silently ignored.

Root cause of "monitoring silent" after init:
  Older usb-full-init.py used seq=100 and only masked Monitor (0x00ff),
  not HP1.  If the FPGA's counter has already passed the written seq,
  the settings write is ignored and outputs stay at firmware defaults
  (often muted / -96 dB).  usb-full-init.py now mirrors this script's
  mask 0xffff + seq policy; use this tool if you still need a higher seq.

Fix: write settings with a seq value guaranteed to be higher than any
previous write.  This script uses a large starting value (5000) and
falls back to probing the current counter via 0x0A JKMK reads.

Usage: sudo python3 tools/usb-monitor-enable.py [--level DB] [--seq N]
"""

import argparse
import struct
import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:
    print("pip install pyusb")
    sys.exit(1)

UA_VID = 0x2B5A
SOLO_PID = 0x000D

# Vendor ctrl request 0x03 — mixer settings (host → device, no iface claim)
VREQ_SETTINGS  = 0x03
SETTINGS_SEQ   = 0x0602   # 4B: sequence counter (u32 LE)
SETTINGS_MASK  = 0x062D   # 128B: mask+value buffer
SETTINGS_EXT   = 0x0670   # 48B: extended settings

# setting[2] layout in the 128-byte mask buffer:
#   word A (+16):  (mask[15:0] << 16) | level[7:0]
#   word B (+20):  (mask[15:0] << 16) | flags[1:0]
#     flags: bit1=mute (1=muted, 0=live), bit0=mono
SETTING_MONITOR_WA = 16   # byte offset in 128B buffer (setting 2, word A)
SETTING_MONITOR_WB = 20   # byte offset in 128B buffer (setting 2, word B)

# set[2] wordA field layout (from register map rb_data[2]):
#   bits [7:0]   = Monitor volume (LINE output)
#   bits [15:8]  = HP1 volume    (headphone jack)
# Both are encoded as raw = 192 + dB * 2, range 0x00-0xC0 (−96 to 0 dB).
MASK_MONITOR = 0x00FF   # bits [7:0]  — Monitor/LINE output level
MASK_HP1     = 0xFF00   # bits [15:8] — HP1 headphone output level
MASK_MUTEMONO = 0x0003


def setting_word(mask, value):
    return ((mask & 0xFFFF) << 16) | (value & 0xFFFF)


def vendor_write(dev, wvalue, data):
    """Send vendor ctrl OUT (bmRequestType=0x41, bRequest=0x03)."""
    dev.ctrl_transfer(0x41, VREQ_SETTINGS, wvalue, 0, data, timeout=1000)


def probe_seq_via_jkmk(dev):
    """Try to read current monitor/HP state from JKMK register space.

    Vendor request 0x0A index 0 returns 48 bytes.  Bytes 12-15 of the
    payload often reflect the last written set[2] wordA (monitor+HP levels).
    Not 100% confirmed — treat as informational only.
    """
    try:
        data = bytes(dev.ctrl_transfer(0xC0, 0x0A, 0, 0, 48, timeout=300))
        if data[:4] == b"JKMK":
            return None  # JKMK data found but seq counter not parseable; use safe default
    except usb.core.USBError:
        pass
    return None


def decode_level(raw):
    """Convert raw 8-bit level to dB string."""
    if raw == 0:
        return "-inf dB (muted/silent)"
    db = (raw - 192) / 2.0
    return f"{db:.1f} dB (raw=0x{raw:02x})"


def write_monitor_settings(dev, level_db, muted, seq):
    """Write Monitor (LINE) + HP1 (headphone) level and mute state.

    Both outputs are set to the same level since:
      - set[2] wordA [7:0]  = Monitor/LINE output
      - set[2] wordA [15:8] = HP1 headphone output
    Writing both ensures whichever physical jack is in use gets signal.
    """
    raw = max(0, min(0xC0, int(192 + level_db * 2)))
    mute_flag = 0x0002 if muted else 0x0000

    mask_buf = bytearray(128)

    # Word A: Monitor bits[7:0] | HP1 bits[15:8] — set both simultaneously.
    # Combined mask covers both fields: 0xFFFF.
    # Value: HP1 raw in high byte, Monitor raw in low byte.
    combined_mask  = MASK_MONITOR | MASK_HP1          # 0xFFFF
    combined_value = (raw << 8) | raw                 # HP1=raw, Monitor=raw
    struct.pack_into("<I", mask_buf, SETTING_MONITOR_WA,
                     setting_word(combined_mask, combined_value))

    # Word B: clear mute, mono off
    struct.pack_into("<I", mask_buf, SETTING_MONITOR_WB,
                     setting_word(MASK_MUTEMONO, mute_flag))

    vendor_write(dev, SETTINGS_MASK, bytes(mask_buf))
    vendor_write(dev, SETTINGS_SEQ,  struct.pack("<I", seq))
    return raw


def read_protocol_version(dev):
    try:
        data = dev.ctrl_transfer(0xC0, 0x00, 0, 0, 4, timeout=300)
        return bytes(data).hex()
    except usb.core.USBError:
        return None


def read_sample_rate(dev):
    try:
        data = bytes(dev.ctrl_transfer(0xC0, 0x02, 0, 0, 4, timeout=300))
        if len(data) < 4:
            return None
        return struct.unpack("<I", data)[0]
    except usb.core.USBError:
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Activate Apollo Solo USB hardware monitoring")
    parser.add_argument("--level", type=float, default=-12.0,
                        help="Monitor level in dB (default: -12)")
    parser.add_argument("--seq", type=int, default=None,
                        help="Override seq counter (default: auto = 5000)")
    parser.add_argument("--mute", action="store_true",
                        help="Mute monitor instead of enabling it")
    args = parser.parse_args()

    dev = usb.core.find(idVendor=UA_VID, idProduct=SOLO_PID)
    if not dev:
        print("ERROR: Apollo Solo USB not found (VID 0x2B5A PID 0x000D)")
        print("  Is firmware loaded?  Run: sudo python3 tools/fx3-load.py")
        sys.exit(1)
    print(f"Found: {dev.manufacturer} {dev.product}")

    # === Health checks (no interface claim — uses EP0 only) ===
    proto = read_protocol_version(dev)
    if proto:
        print(f"Protocol version: {proto}")
    else:
        print("WARNING: protocol version unreadable (device may not be initialized)")

    rate = read_sample_rate(dev)
    if rate and 44100 <= rate <= 192000:
        print(f"Sample rate: {rate} Hz  (DSP is active)")
    else:
        print(f"Sample rate: {rate}  (DSP may not be initialized — "
              f"run usb-full-init.py first)")

    # === Determine seq counter to use ===
    probed_seq = probe_seq_via_jkmk(dev)
    if args.seq is not None:
        seq = args.seq
        print(f"Seq counter: {seq}  (from --seq argument)")
    elif probed_seq is not None:
        seq = probed_seq + 100
        print(f"Seq counter: {seq}  (probed FPGA counter={probed_seq}, +100)")
    else:
        # Safe default: use a large value unlikely to be exceeded by any
        # previous init run.  usb-full-init.py uses 5000 (10000 post-rebind pass).
        seq = 5000
        print(f"Seq counter: {seq}  (safe default — higher than any init run)")

    # === Write monitor settings ===
    #
    # Vendor ctrl 0x03 writes go directly to FPGA via EP0 — no interface
    # claim needed.  This is safe while snd-usb-audio is active on ifaces
    # 1-3 and does not interrupt audio streaming.
    print()
    action = "mute" if args.mute else f"unmute at {args.level:.1f} dB"
    print(f"Writing monitor settings: {action}, seq={seq}")

    raw = write_monitor_settings(dev, args.level, args.mute, seq)

    print(f"  set[2] word A: Monitor[7:0]=0x{raw:02x} + HP1[15:8]=0x{raw:02x} "
          f"({args.level:.1f} dB), mask=0xffff")
    print(f"  set[2] word B: mute={'1' if args.mute else '0'}, "
          f"mono=0, mask=0x{MASK_MUTEMONO:04x}")
    print(f"  seq={seq} → written to 0x0602")

    # Brief pause then write a second time at seq+1 to ensure the FPGA
    # processes even if seq was borderline.
    time.sleep(0.1)
    write_monitor_settings(dev, args.level, args.mute, seq + 1)
    print(f"  Confirmed at seq={seq + 1}")

    # === Read back JKMK to verify device is responsive ===
    print()
    print("JKMK register check (vendor 0x0A)...")
    for idx in [0, 1, 2]:
        try:
            data = bytes(dev.ctrl_transfer(0xC0, 0x0A, idx, 0, 48, timeout=300))
            payload = data[12:]
            has_data = any(b != 0 for b in payload)
            marker = " ← non-zero" if has_data else ""
            print(f"  [idx={idx}]: {data[:12].hex()}  payload={payload[:8].hex()}{marker}")
        except usb.core.USBError as e:
            print(f"  [idx={idx}]: error ({e})")

    print()
    if not args.mute:
        print("Done.  If monitoring is still silent:")
        print("  1. Verify usb-full-init.py ran:  sudo python3 tools/usb-full-init.py")
        print("  2. Try a higher seq:             sudo python3 tools/usb-monitor-enable.py --seq 50000")
        print("  3. Check preamp gain (must be > 0 dB for signal):  "
              "sudo python3 tools/usb-mixer-test.py")
    else:
        print("Done.  Monitor muted.")


if __name__ == "__main__":
    main()
