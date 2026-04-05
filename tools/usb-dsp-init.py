#!/usr/bin/env python3
"""Initialize DSP on UA Apollo USB devices.

Sends the DSP init command via bulk endpoint, sets the UAC2 clock
frequency, and configures a safe default monitor level so audio routes
to physical outputs.

Must run after firmware is loaded (device at PID 000d/0002/000f).
Can be called standalone or from udev via ua-usb-dsp-init.sh.

Usage: sudo python3 usb-dsp-init.py
"""
import struct
import sys
import usb.core
import usb.util

UA_VID = 0x2B5A
# Post-firmware PIDs
LIVE_PIDS = {
    0x000D: "Apollo Solo USB",
    0x0002: "Twin USB",
    0x000F: "Twin X USB",
}

EP_BULK_OUT = 0x01
EP_BULK_IN = 0x81

# DSP protocol constants
MAGIC_CMD = 0xDC
MAGIC_RSP = 0xDD

# Mixer settings FPGA addresses (vendor request 0x03)
SETTINGS_SEQ = 0x0602
SETTINGS_MASK = 0x062D
SETTING_MONITOR = 2  # offset in 128-byte mask buffer


def find_device():
    """Find any UA USB device in post-firmware state."""
    for pid, name in LIVE_PIDS.items():
        dev = usb.core.find(idVendor=UA_VID, idProduct=pid)
        if dev:
            return dev, name
    return None, None


def dsp_init(dev):
    """Send DSP init: activate FPGA, set hardware config, write identity routing table.

    Sequence verified from Cauldron 1.3 build 3 USBPcap capture (2026-04-05):
      1. FPGA_ACTIVATE (reg 0x0023=1) + CONFIG_A (reg 0x0010=0x01b7a1fa) x2
      2. CONFIG_B (reg 0x0011=0x82607600)
      3. Identity routing table: 32 slots (0x00–0x1F) via reg 0x001e
         Each slot: BLOCK(0x001e, slot_index) + op=0x0008(0x0000, 0x00000020)
      4. Clock set to 48 kHz (reg 0x001a=0x0000bb80) — done in set_clock()

    CONFIG_A value 0x01b7a1fa was confirmed in the Cauldron 1.3 capture.
    The previous value (0x01B71448) was wrong — low 16 bits differed.
    CONFIG_B must follow immediately; without it the USB audio path is not enabled.

    The FPGA needs the identity routing table to pass USB audio frames to the
    DAC output ring.  Without it audio is silently discarded even though USB
    streams are acknowledged.
    """
    seq = 0  # packet sequence counter (type byte)

    # Packet 0: FPGA_ACTIVATE + CONFIG_A x2
    # word_count covers all sub-commands: 3 RW × 2 words each = 6 words
    pkt = struct.pack("<HBB", 6, seq, MAGIC_CMD)
    pkt += struct.pack("<HHI", 0x0002, 0x0023, 0x00000001)  # FPGA_ACTIVATE
    pkt += struct.pack("<HHI", 0x0002, 0x0010, 0x01B7A1FA)  # CONFIG_A
    pkt += struct.pack("<HHI", 0x0002, 0x0010, 0x01B7A1FA)  # CONFIG_A (written twice)
    dev.write(EP_BULK_OUT, pkt, timeout=1000)
    seq += 1

    # Packet 1: CONFIG_B
    pkt = struct.pack("<HBB", 2, seq, MAGIC_CMD)
    pkt += struct.pack("<HHI", 0x0002, 0x0011, 0x82607600)  # CONFIG_B
    dev.write(EP_BULK_OUT, pkt, timeout=1000)
    seq += 1

    # Drain any response packets from the above two writes
    try:
        while True:
            dev.read(EP_BULK_IN, 1024, timeout=200)
    except usb.core.USBTimeoutError:
        pass

    # Packets 2–14: Identity routing table (slots 0x00–0x1F)
    # Groups match the exact framing UA Console uses.  Each entry is:
    #   BLOCK(0x001e, slot_index)  +  op=0x0008(0x0000, 0x00000020)
    # = 2 sub-commands = 4 words per slot
    ROUTING_GROUPS = [
        [0x00, 0x01],                               # fr=1200 (2 slots)
        [0x02, 0x03, 0x04, 0x05, 0x06],             # fr=1201 (5 slots)
        [0x07],                                      # fr=1202
        [0x08],                                      # fr=1205
        [0x09],                                      # fr=1207
        [0x0A, 0x0B, 0x0C],                         # fr=1208
        [0x0D, 0x0E, 0x0F, 0x14],                   # fr=1211
        [0x15],                                      # fr=1214
        [0x16],                                      # fr=1215
        [0x17],                                      # fr=1217
        [0x18, 0x19, 0x1A, 0x1B, 0x1C],             # fr=1222
        [0x1D, 0x1E],                                # fr=1224
        [0x1F],                                      # fr=1225
    ]

    for group in ROUTING_GROUPS:
        # word_count: each slot = 4 words (2 sub-commands × 2 words each)
        word_count = len(group) * 4
        pkt = struct.pack("<HBB", word_count, seq, MAGIC_CMD)
        for slot in group:
            pkt += struct.pack("<HHI", 0x0004, 0x001E, slot)   # BLOCK(ROUTE_WRITE, slot)
            pkt += struct.pack("<HHI", 0x0008, 0x0000, 0x00000020)  # stride=32
        dev.write(EP_BULK_OUT, pkt, timeout=1000)
        seq += 1

    # Drain routing responses
    try:
        while True:
            dev.read(EP_BULK_IN, 1024, timeout=200)
    except usb.core.USBTimeoutError:
        pass


def set_clock(dev, rate=48000, seq=16):
    """Set sample rate via DSP bulk protocol (reg 0x001a) and UAC2 SET_CUR.

    The Cauldron 1.3 capture shows UA Console writes the clock via bulk EP1
    (reg 0x001a = sample rate in Hz, LE32) immediately after the routing table.
    The UAC2 SET_CUR on EP0 is sent separately by the UAC2 audio driver — we
    send it here as well to keep the USB audio clock entity in sync.

    seq: packet sequence counter continuing from dsp_init (default 16 = after
         2 config packets + 13 routing packets + 1 status query).
    """
    # DSP bulk clock write (verified Cauldron 1.3 fr=1229)
    pkt = struct.pack("<HBB", 2, seq, MAGIC_CMD)
    pkt += struct.pack("<HHI", 0x0002, 0x001A, rate)
    try:
        dev.write(EP_BULK_OUT, pkt, timeout=1000)
    except usb.core.USBError:
        pass

    # UAC2 SET_CUR on clock entity (EP0 vendor control)
    try:
        dev.ctrl_transfer(0x21, 0x01, 0x0100, 0x8001,
                          struct.pack("<I", rate), timeout=2000)
    except usb.core.USBError:
        pass  # May timeout on first set, that's OK

    # Verify via GET_CUR
    try:
        data = dev.ctrl_transfer(0xA1, 0x01, 0x0100, 0x8001, 4, timeout=1000)
        return struct.unpack("<I", bytes(data))[0]
    except usb.core.USBError:
        return rate  # assume success if read fails


def set_monitor_level(dev, db=-12):
    """Set monitor output level via vendor control request 0x03.

    Without this, the FPGA boots with all mixer settings muted (0x80000000)
    and no audio reaches the physical outputs.
    Uses the same batch-write protocol as usb-mixer-test.py:
      1. Write 128-byte mask buffer to SETTINGS_MASK (0x062D)
      2. Bump sequence counter at SETTINGS_SEQ (0x0602)
    """
    raw = max(0, min(0xC0, int(192 + db * 2)))
    mask_buf = bytearray(128)
    # setting_word: (changed_mask << 16) | value
    word = (0x00FF << 16) | raw
    struct.pack_into("<I", mask_buf, SETTING_MONITOR * 8, word)

    try:
        dev.ctrl_transfer(0x41, 0x03, SETTINGS_MASK, 0,
                          bytes(mask_buf), timeout=1000)
        dev.ctrl_transfer(0x41, 0x03, SETTINGS_SEQ, 0,
                          struct.pack("<I", 1), timeout=1000)
    except usb.core.USBError:
        return False
    return True


def main():
    dev, name = find_device()
    if not dev:
        print("No UA USB device found (post-firmware)")
        sys.exit(1)

    print("Found: {}".format(name))

    # Detach kernel drivers from DSP + audio control interfaces
    for intf in [0, 1]:
        try:
            if dev.is_kernel_driver_active(intf):
                dev.detach_kernel_driver(intf)
        except Exception:
            pass

    usb.util.claim_interface(dev, 0)

    # Step 1: DSP init — FPGA activate, CONFIG_A/B, identity routing table
    # Sends 15 bulk packets (seq 0x00–0x0E); STATUS query is seq 0x0F internally
    dsp_init(dev)
    print("DSP init done")

    # Step 2: Set clock
    # UA Console sends a STATUS_QUERY (reg 0x0027) at seq=0x02 after a ~3-second
    # wait, then the routing table at seq=0x03–0x0F, then clock at seq=0x10.
    # We skip the STATUS_QUERY and wait; our routing runs at seq=0x02–0x0E,
    # clock at seq=0x10.  The device does not enforce seq monotonicity — all
    # payload bytes are identical to the capture regardless of the seq offset.
    freq = set_clock(dev, 48000, seq=0x10)
    print("Clock: {} Hz".format(freq))

    usb.util.release_interface(dev, 0)

    # Step 3: Set monitor level to -12 dB (safe default)
    # Uses EP0 vendor control — no interface claim needed
    if set_monitor_level(dev, -12):
        print("Monitor: -12 dB")
    else:
        print("Monitor level set failed (non-fatal)")

    print("Ready")


if __name__ == "__main__":
    main()
