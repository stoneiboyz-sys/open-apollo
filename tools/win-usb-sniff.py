"""Sniff Apollo Solo USB DSP endpoints from Windows via libusb.

Tries to claim DSP interface 0 and read from bulk/interrupt endpoints.
Requires: pip install pyusb libusb-package

Usage: python win-usb-sniff.py
"""
import struct, sys, time
import usb.core, usb.util, usb.backend.libusb1
import libusb_package

backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
dev = usb.core.find(idVendor=0x2b5a, idProduct=0x000d, backend=backend)
if not dev:
    print("Not found"); sys.exit(1)
print(f"Found device VID={dev.idVendor:#06x} PID={dev.idProduct:#06x}")

try:
    dev.set_configuration()
except Exception as e:
    print(f"Config: {e}")

try:
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
        print("Detached kernel driver")
except:
    pass

try:
    usb.util.claim_interface(dev, 0)
    print("Claimed DSP interface 0")
except Exception as e:
    print(f"Claim failed: {e}")
    sys.exit(1)

# Read bulk IN
print("\n--- BULK IN (EP 0x81) ---")
for i in range(5):
    try:
        data = dev.read(0x81, 1024, timeout=500)
        print(f"  [{len(data)}B] {bytes(data)[:48].hex()}")
    except usb.core.USBTimeoutError:
        print(f"  timeout ({i+1})")
        if i >= 1: break
    except Exception as e:
        print(f"  error: {e}"); break

# Read interrupt IN
print("\n--- INTR IN (EP 0x86) ---")
for i in range(5):
    try:
        data = dev.read(0x86, 512, timeout=500)
        print(f"  [{len(data)}B] {bytes(data)[:48].hex()}")
    except usb.core.USBTimeoutError:
        print(f"  timeout ({i+1})")
        if i >= 1: break
    except Exception as e:
        print(f"  error: {e}"); break

# Try vendor control requests
print("\n--- Vendor control reads ---")
for req in [0x00, 0x02, 0x0A, 0x10]:
    try:
        data = dev.ctrl_transfer(0xC0, req, 0, 0, 64, timeout=300)
        print(f"  req={req:#04x}: [{len(data)}B] {bytes(data)[:24].hex()}")
    except:
        pass

usb.util.release_interface(dev, 0)
print("\nDone")
