#!/usr/bin/env python3
"""
Test talkback by sending bus 0x0A coefficients + enabling talkback switch.
Then record 5s from raw 22ch capture and check AUX20-21 for signal.

Usage: sudo python3 test-talkback-bus.py
"""
import struct
import fcntl
import time
import subprocess
import sys
import os

DEV = "/dev/ua_apollo0"

# ioctl numbers (from ua_ioctl.h)
# _IOW('U', 0x30, 16 bytes) = SET_MIXER_BUS_PARAM
IOCTL_MAGIC = ord('U')
SET_BUS_PARAM = (1 << 30) | (16 << 16) | (IOCTL_MAGIC << 8) | 0x30
# _IOW('U', 0x31, 24 bytes) = SET_MIXER_PARAM
SET_MIXER_PARAM = (1 << 30) | (24 << 16) | (IOCTL_MAGIC << 8) | 0x31
# _IOW('U', 0x70, 20 bytes) = RING_SEND
RING_SEND = (1 << 30) | (20 << 16) | (IOCTL_MAGIC << 8) | 0x70

def float_to_u32(f):
    return struct.unpack('<I', struct.pack('<f', f))[0]

def set_bus_param(fd, bus_id, sub_param, value_f32):
    """Send BUS_COEFF via SET_MIXER_BUS_PARAM ioctl."""
    data = struct.pack('<IIII', bus_id, sub_param, float_to_u32(value_f32), 0x02)
    fcntl.ioctl(fd, SET_BUS_PARAM, data)

def ring_send(fd, dsp, w0, w1, w2, w3):
    """Send raw ring buffer command."""
    data = struct.pack('<IIIII', dsp, w0, w1, w2, w3)
    fcntl.ioctl(fd, RING_SEND, data)

def set_mixer_param(fd, chan_type, chan_idx, param_id, value):
    """Send SetMixerParam (SEL131 equivalent)."""
    data = struct.pack('<IIIIII', 0, 0, chan_type, chan_idx, param_id, value)
    fcntl.ioctl(fd, SET_MIXER_PARAM, data)

def main():
    if not os.path.exists(DEV):
        print(f"ERROR: {DEV} not found")
        sys.exit(1)

    fd = os.open(DEV, os.O_RDWR)

    print("=== Talkback Bus Test ===")
    print()

    # Step 1: Send ROUTING commands for bus 0x0A
    print("[1] Sending ROUTING for bus 0x0A...")
    ring_send(fd, 0, 0x001E0004, 0x000A, 0x0008, 0x0020)      # flush
    ring_send(fd, 0, 0x001E0004, 0x000A, 0x0005, 0x3F800000)  # gain = 1.0
    ring_send(fd, 0, 0x001E0004, 0x000A, 0x0007, 0x0000FFFF)  # 16ch mask

    # Step 2: Send BUS_COEFF for bus 0x0A (talkback coefficients)
    # Value ~1.993 (0x3FFF1743) from Windows capture
    TB_COEFF = 1.993
    print(f"[2] Sending BUS_COEFF for bus 0x0A (coeff={TB_COEFF})...")
    for sub in range(7):  # sub 0-6
        for side in range(2):  # L=0, R=1
            sub_param = (side << 24) | sub
            # sub 3,4 (AUX1/2) stay at 0
            if sub in (3, 4):
                set_bus_param(fd, 0x0A, sub_param, 0.0)
            else:
                set_bus_param(fd, 0x0A, sub_param, TB_COEFF)

    # Step 3: Enable talkback via mixer param
    print("[3] Enabling talkback (SEL131 param 0x46 = 1)...")
    set_mixer_param(fd, 2, 1, 0x46, 1)  # ch_type=2, ch_idx=1, param=0x46, value=1

    os.close(fd)

    print("[4] Waiting 1s for DSP to process...")
    time.sleep(1)

    # Step 4: Record 5s from raw 22ch via ALSA and check channels 20-21
    print("[5] Recording 5s from Apollo (22ch)...")
    wav = "/tmp/tb_test_22ch.wav"
    try:
        os.unlink(wav)
    except FileNotFoundError:
        pass

    # Use pw-record targeting the pro-audio source
    proc = subprocess.run(
        ["timeout", "6", "pw-record", "--target",
         "alsa_input.pci-0000_10_00.0.pro-input-0",
         "--channels", "22", "--rate", "48000", "--format", "s32",
         wav],
        capture_output=True, text=True, timeout=10
    )

    if not os.path.exists(wav):
        print("ERROR: no wav file produced. Try tapping the talkback mic.")
        print("  pw-record stderr:", proc.stderr[:200] if proc.stderr else "(none)")
        sys.exit(1)

    # Analyze
    import wave
    w = wave.open(wav, 'r')
    n = w.getnframes()
    ch = w.getnchannels()
    sw = w.getsampwidth()
    print(f"  Recorded: {n} frames, {ch} channels, {sw} bytes/sample")

    if n < 100:
        print("ERROR: too few frames recorded")
        sys.exit(1)

    # Read middle section
    w.setpos(n // 2)
    nf = min(2000, n - n // 2)
    data = w.readframes(nf)
    actual = len(data) // (ch * sw)
    samples = struct.unpack('<' + 'i' * (actual * ch), data[:actual * ch * sw])

    print()
    print("Channel analysis (middle 2000 frames):")
    print(f"  {'Ch':>3} {'Name':>12} {'Peak':>12}  {'Status'}")
    print(f"  {'---':>3} {'----':>12} {'----':>12}  {'------'}")

    names = {0: "Mic 1", 1: "Mic 2", 2: "Mic 3", 3: "Mic 4",
             4: "SPDIF L", 5: "SPDIF R", 14: "Mon L", 15: "Mon R",
             20: "TB 1", 21: "TB 2"}

    for c in [0, 1, 2, 3, 4, 5, 14, 15, 20, 21]:
        cs = [samples[i * ch + c] for i in range(actual)]
        peak = max(abs(s) for s in cs) if cs else 0
        status = "SIGNAL" if peak > 10000 else "silent"
        name = names.get(c, f"ch{c}")
        print(f"  {c:3d} {name:>12} {peak:12d}  {status}")

    w.close()

    # Step 5: Disable talkback
    print()
    print("[6] Disabling talkback...")
    fd = os.open(DEV, os.O_RDWR)
    set_mixer_param(fd, 2, 9, 0x46, 0)  # OFF uses ch_idx=9
    os.close(fd)

    print("Done.")

if __name__ == "__main__":
    main()
