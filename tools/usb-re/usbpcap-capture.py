#!/usr/bin/env python3
r"""Capture USB traffic from USBPcap device on Windows.

Reads raw USB packets from \\.\USBPcapX device handle using ctypes/Win32.
USBPcap outputs a pcap-formatted stream (header + records) directly from
the device handle after SETUP_BUFFER + START_FILTERING IOCTLs.

Usage:
    python usbpcap-capture.py --filter 2 -o capture.pcap --duration 60

Requires: Windows, USBPcap driver installed.
"""

import argparse
import ctypes
import ctypes.wintypes
import os
import struct
import sys
import time
import threading

kernel32 = ctypes.windll.kernel32

# USBPcap IOCTLs (from source + brute-force verification)
IOCTL_SETUP_BUFFER = 0x00226000    # CTL_CODE(0x22, 0x800, 0, FILE_READ_DATA)
IOCTL_START_FILTER = 0x0022E008    # CTL_CODE(0x22, 0x802, 0, FILE_READ|FILE_WRITE)


def capture(filter_num, outfile, duration=None):
    """Open USBPcap, start filtering, and write pcap stream to file."""
    path = f"\\\\.\\USBPcap{filter_num}"
    h = kernel32.CreateFileW(path, 0xC0000000, 0, None, 3, 0, None)
    if h in (-1, 0xFFFFFFFF):
        print(f"Cannot open {path}")
        sys.exit(1)

    br = ctypes.wintypes.DWORD()

    # Setup 1MB capture buffer
    buf = ctypes.c_ulong(1048576)
    kernel32.DeviceIoControl(h, IOCTL_SETUP_BUFFER,
                             ctypes.byref(buf), 4, None, 0,
                             ctypes.byref(br), None)

    # Start filtering (16-byte bitmap all-ones + 4-byte filterAll=1)
    fdata = b"\xff" * 16 + struct.pack("<I", 1)
    fbuf = (ctypes.c_ubyte * len(fdata))(*fdata)
    ok = kernel32.DeviceIoControl(h, IOCTL_START_FILTER,
                                  fbuf, len(fdata), None, 0,
                                  ctypes.byref(br), None)
    if not ok:
        print(f"START_FILTER failed: err={ctypes.GetLastError()}")
        kernel32.CloseHandle(h)
        sys.exit(1)

    # USBPcap streams pcap data — first read is the 24-byte global header
    rbuf = ctypes.create_string_buffer(65536)
    bread = ctypes.wintypes.DWORD()

    with open(outfile, "wb") as f:
        count = 0
        start = time.time()

        while True:
            if duration and (time.time() - start) > duration:
                break

            res = [None]
            def rf():
                rok = kernel32.ReadFile(h, rbuf, 65536,
                                        ctypes.byref(bread), None)
                res[0] = (rok, bread.value)

            t = threading.Thread(target=rf, daemon=True)
            t.start()
            t.join(timeout=1.0)

            if t.is_alive():
                kernel32.CancelIo(h)
                t.join(timeout=0.5)
                continue

            if res[0] and res[0][1] > 0:
                f.write(bytes(rbuf[:res[0][1]]))
                f.flush()
                count += 1
                if count % 50 == 0:
                    elapsed = time.time() - start
                    sz = os.path.getsize(outfile)
                    print(f"\r  {count} reads, {sz/1024:.0f}KB, "
                          f"{elapsed:.0f}s", end="", flush=True)

    kernel32.CloseHandle(h)
    sz = os.path.getsize(outfile)
    print(f"\n  Done: {count} reads, {sz/1024:.1f}KB -> {outfile}")


def main():
    p = argparse.ArgumentParser(description="USBPcap capture via Python")
    p.add_argument("--filter", type=int, default=2,
                   help="USBPcap filter number (default: 2)")
    p.add_argument("-o", "--output", required=True, help="Output .pcap")
    p.add_argument("--duration", type=float, default=None,
                   help="Capture duration in seconds")
    args = p.parse_args()

    print(f"Capturing from USBPcap{args.filter} -> {args.output}")
    if args.duration:
        print(f"  Duration: {args.duration}s")

    capture(args.filter, args.output, args.duration)


if __name__ == "__main__":
    main()
