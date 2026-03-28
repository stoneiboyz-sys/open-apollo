#!/usr/bin/env python3
"""Binary patch snd-usb-audio.ko to add UA Apollo Solo USB quirk.

Replaces the Line6 Helix USB ID (0x0e414241) with UA Apollo Solo USB
ID (0x2b5a000d) in the fixed-rate quirk function, so snd-usb-audio
falls back to 48kHz when GET_RANGE fails.

Usage: python3 patch-snd-usb.py /tmp/snd-usb-audio.ko /tmp/snd-usb-audio-patched.ko
"""
import struct
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/snd-usb-audio.ko"
dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/snd-usb-audio-patched.ko"

data = bytearray(open(src, "rb").read())

old_id = struct.pack("<I", 0x0E414241)  # Line6 Helix
new_id = struct.pack("<I", 0x2B5A000D)  # UA Apollo Solo USB

offset = data.find(old_id)
if offset == -1:
    print("Line6 Helix ID not found in module")
    sys.exit(1)

print(f"Patching at offset {offset:#x}")
print(f"  Before: {data[offset:offset+4].hex()} (Line6 Helix)")
data[offset:offset+4] = new_id
print(f"  After:  {data[offset:offset+4].hex()} (UA Apollo Solo USB)")

open(dst, "wb").write(data)
print(f"Written to {dst}")
