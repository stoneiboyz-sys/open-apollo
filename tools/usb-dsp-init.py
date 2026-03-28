#!/usr/bin/env python3
"""Initialize DSP on UA Apollo USB devices.

Sends the DSP init command via bulk endpoint and sets the UAC2 clock
frequency. Must run after firmware is loaded (device at PID 000d/0002/000f).

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


def find_device():
    """Find any UA USB device in post-firmware state."""
    for pid, name in LIVE_PIDS.items():
        dev = usb.core.find(idVendor=UA_VID, idProduct=pid)
        if dev:
            return dev, name
    return None, None


def dsp_init(dev):
    """Send DSP init command: register 0x23=1 (activate FPGA)."""
    cmd = struct.pack("<HBB", 4, 0, MAGIC_CMD)
    cmd += struct.pack("<HHI", 0x0002, 0x0023, 0x00000001)
    cmd += struct.pack("<HHI", 0x0002, 0x0010, 0x01B71448)
    dev.write(EP_BULK_OUT, cmd, timeout=1000)

    # Drain response packets
    try:
        while True:
            dev.read(EP_BULK_IN, 1024, timeout=500)
    except usb.core.USBTimeoutError:
        pass


def set_clock(dev, rate=48000):
    """Set UAC2 clock frequency via SET_CUR."""
    # bmRequestType=0x21 (host-to-device, class, interface)
    # bRequest=0x01 (SET_CUR)
    # wValue=0x0100 (CS_SAM_FREQ_CONTROL)
    # wIndex=0x8001 (clock_id=128, interface=1)
    try:
        dev.ctrl_transfer(0x21, 0x01, 0x0100, 0x8001,
                          struct.pack("<I", rate), timeout=2000)
    except usb.core.USBError:
        pass  # May timeout on first set, that's OK

    # Verify
    try:
        data = dev.ctrl_transfer(0xA1, 0x01, 0x0100, 0x8001, 4, timeout=1000)
        return struct.unpack("<I", bytes(data))[0]
    except usb.core.USBError:
        return 0


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

    # Step 1: DSP init
    dsp_init(dev)
    print("DSP init done")

    # Step 2: Set clock
    freq = set_clock(dev, 48000)
    print("Clock: {} Hz".format(freq))

    usb.util.release_interface(dev, 0)
    print("Ready")


if __name__ == "__main__":
    main()
