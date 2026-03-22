#!/usr/bin/env python3
"""Replay DSP firmware blocks captured from macOS to Apollo hardware via Linux driver.

This script replays the 145+ firmware blocks captured via DTrace during Apollo
boot on macOS. Each block is sent to DSP 0 via the ua_dsp_send_block() ioctl,
which uses the DSP ring buffer DMA protocol.

Protocol (from SEL127 DTrace captures):
  - dsp_index: always 0 (mixer DSP)
  - cmd: SRAM address (e.g., 0x0e8cc000)
  - param: always 0x00000001
  - payload: binary firmware data (sizes vary: 184-3044 bytes per block)

The capture log shows 291 SEL127 calls, but many are duplicates to the same
SRAM addresses. The unique SRAM addresses have been extracted to binary files
in fw-payloads-v3/.

Usage:
  ./replay-fw-blocks.py                  # Replay all blocks in order
  ./replay-fw-blocks.py --dry-run        # Parse and print without sending
  ./replay-fw-blocks.py --verbose        # Print each block
  ./replay-fw-blocks.py --pause 10       # Wait 10ms between blocks
"""

import os
import sys
import struct
import fcntl
import time
import argparse
import re
import ctypes
from pathlib import Path

# ----------------------------------------------------------------
# Ioctl definitions (from driver/ua_ioctl.h)
# ----------------------------------------------------------------

UA_IOCTL_MAGIC = ord('U')

def _IOC(dir, type, nr, size):
    return (dir << 30) | (type << 8) | nr | (size << 16)

def _IOR(type, nr, size):
    return _IOC(2, type, nr, size)  # 2 = _IOC_READ

def _IOW(type, nr, size):
    return _IOC(1, type, nr, size)  # 1 = _IOC_WRITE

def _IOWR(type, nr, size):
    return _IOC(3, type, nr, size)  # 3 = _IOC_READ | _IOC_WRITE

def _IO(type, nr):
    return _IOC(0, type, nr, 0)     # 0 = no direction

# Device info
UA_IOCTL_GET_DEVICE_INFO = _IOR(UA_IOCTL_MAGIC, 0x01, 64)

# Register access
UA_IOCTL_READ_REG  = _IOWR(UA_IOCTL_MAGIC, 0x10, 8)
UA_IOCTL_WRITE_REG = _IOW(UA_IOCTL_MAGIC, 0x11, 8)

# HW readback
UA_IOCTL_GET_HW_READBACK = _IOR(UA_IOCTL_MAGIC, 0x41, 164)

# DSP operations
UA_IOCTL_DSP_SEND_BLOCK = _IOW(UA_IOCTL_MAGIC, 0x54, 24)  # struct ua_dsp_block

# ----------------------------------------------------------------
# Register definitions (from driver/ua_apollo.h)
# ----------------------------------------------------------------

REG_MIXER_BASE    = 0x3800
REG_MIXER_SEQ_WR  = 0x3808
REG_MIXER_SEQ_RD  = 0x380C
REG_MIXER_RB_STATUS = 0x3810
REG_MIXER_RB_DATA   = 0x3814

DSP_BANK_LOW    = 0x2000
DSP_BANK_STRIDE = 0x80
RING_CMD_OFFSET = 0x00
RING_POSITION   = 0x28

# ----------------------------------------------------------------
# Block data structure
# ----------------------------------------------------------------

class FirmwareBlock:
    """Represents a single SEL127 firmware block."""
    def __init__(self, seq, timestamp, dsp_idx, sram_addr, param, payload):
        self.seq = seq              # Sequence number in capture
        self.timestamp = timestamp  # ms from capture start
        self.dsp_idx = dsp_idx      # DSP index (always 0)
        self.sram_addr = sram_addr  # SRAM address (cmd parameter)
        self.param = param          # param (always 0x00000001)
        self.payload = payload      # Binary payload data

    def __repr__(self):
        return (f"Block(seq={self.seq}, t={self.timestamp}ms, "
                f"sram=0x{self.sram_addr:08x}, size={len(self.payload)})")

# ----------------------------------------------------------------
# Ioctl wrappers
# ----------------------------------------------------------------

def read_reg(fd, offset):
    """Read a BAR0 register via ioctl."""
    buf = struct.pack("II", offset, 0)
    result = fcntl.ioctl(fd, UA_IOCTL_READ_REG, buf)
    return struct.unpack("II", result)[1]

def write_reg(fd, offset, value):
    """Write a BAR0 register via ioctl."""
    buf = struct.pack("II", offset, value & 0xFFFFFFFF)
    fcntl.ioctl(fd, UA_IOCTL_WRITE_REG, buf)

def get_device_info(fd):
    """Get device info via ioctl."""
    buf = bytes(64)
    result = fcntl.ioctl(fd, UA_IOCTL_GET_DEVICE_INFO, buf)
    fields = struct.unpack("I" * 16, result)
    return {
        'fpga_rev': fields[0],
        'device_type': fields[1],
        'subsystem_id': fields[2],
        'num_dsps': fields[3],
        'fw_version': fields[4],
        'fw_v2': fields[5],
        'serial': fields[6],
    }

def get_hw_readback(fd):
    """Read 40-word HW readback register."""
    buf = bytes(164)  # 1 status + 40 data words
    result = fcntl.ioctl(fd, UA_IOCTL_GET_HW_READBACK, buf)
    words = struct.unpack("I" * 41, result)
    return words[0], words[1:]  # (status, data[40])

# ----------------------------------------------------------------
# DSP state checking
# ----------------------------------------------------------------

def dump_dsp_state(fd, label=""):
    """Print current DSP and mixer state."""
    seq_wr = read_reg(fd, REG_MIXER_SEQ_WR)
    seq_rd = read_reg(fd, REG_MIXER_SEQ_RD)
    rb_status = read_reg(fd, REG_MIXER_RB_STATUS)
    mixer_state = read_reg(fd, REG_MIXER_BASE)

    print(f"[{label}] Mixer: state=0x{mixer_state:08x} "
          f"SEQ_WR={seq_wr} SEQ_RD={seq_rd} rb={rb_status}")

    # DSP 0 ring buffer registers (at BAR0+0x2000)
    dsp0_base = DSP_BANK_LOW  # 0x2000
    cmd_base = dsp0_base + RING_CMD_OFFSET  # 0x2000
    resp_base = dsp0_base + 0x40            # 0x2040

    cmd_pos = read_reg(fd, cmd_base + RING_POSITION)
    resp_pos = read_reg(fd, resp_base + RING_POSITION)

    # Read page addresses (cmd ring)
    cmd_pg0_lo = read_reg(fd, cmd_base + 0x00)
    cmd_pg0_hi = read_reg(fd, cmd_base + 0x04)
    cmd_pg1_lo = read_reg(fd, cmd_base + 0x08)
    cmd_wr_ptr = read_reg(fd, cmd_base + 0x20)

    # DMA control
    dma_ctrl = read_reg(fd, 0x2200)
    ax_ctrl = read_reg(fd, 0x2248)

    print(f"[{label}] DSP 0 ring: cmd_pos={cmd_pos} resp_pos={resp_pos} "
          f"cmd_wr_ptr=0x{cmd_wr_ptr:08x}")
    print(f"[{label}] cmd page0=0x{cmd_pg0_hi:08x}:{cmd_pg0_lo:08x} "
          f"page1_lo=0x{cmd_pg1_lo:08x}")
    print(f"[{label}] DMA_CTRL=0x{dma_ctrl:08x} AX_CTRL=0x{ax_ctrl:08x}")

    if cmd_pg0_lo == 0 and cmd_pg0_hi == 0:
        print(f"[{label}] WARNING: cmd ring page0 address is ZERO - "
              f"ring not programmed or registers not readable")

    return seq_wr == seq_rd

# ----------------------------------------------------------------
# Block parsing from DTrace log
# ----------------------------------------------------------------

def parse_dtrace_log(log_path):
    """Parse the DTrace capture log and extract block metadata.

    Returns list of FirmwareBlock objects in capture order.
    Each SEL127 line has: dsp=N payload_size=M sram=0xXXXXXXXX param=0xYYYYYYYY
    """
    blocks = []
    seq = 0

    with open(log_path, 'r') as f:
        for line in f:
            if '=== FW_PAYLOAD SEL127' not in line:
                continue

            # Parse: T+79766ms dsp=0 insize=16 payload_size=716 sram=0x0e8cc000 param=0x00000001
            m = re.search(r'T\+(\d+)ms.*dsp=(\d+).*payload_size=(\d+).*sram=(0x[0-9a-f]+).*param=(0x[0-9a-f]+)', line)
            if not m:
                continue

            timestamp = int(m.group(1))
            dsp_idx = int(m.group(2))
            payload_size = int(m.group(3))
            sram_addr = int(m.group(4), 16)
            param = int(m.group(5), 16)

            # Payload will be loaded separately
            blocks.append(FirmwareBlock(seq, timestamp, dsp_idx, sram_addr, param, None))
            seq += 1

    return blocks

def load_block_payload(block, payloads_dir):
    """Load binary payload data for a block from the parsed directory.

    The payloads_dir contains files like fw-payload-0e8cc000.bin which are
    the concatenated payloads for all blocks sent to that SRAM address.

    For replay, we need the FIRST block sent to each SRAM address. The DTrace
    capture shows multiple blocks to the same address, but we can't split them
    reliably from the concatenated file.

    Workaround: read the entire file and assume it's ONE logical block.
    The kext may have split it into multiple DMA transfers, but we'll send
    it as one (or chunk it ourselves if > 4KB).
    """
    bin_path = Path(payloads_dir) / f"fw-payload-{block.sram_addr:08x}.bin"

    if not bin_path.exists():
        print(f"WARNING: Payload file not found: {bin_path}")
        return None

    with open(bin_path, 'rb') as f:
        data = f.read()

    return data

# ----------------------------------------------------------------
# Block replay via ioctl
# ----------------------------------------------------------------

def send_block_via_ioctl(fd, block, verbose=False):
    """Send a firmware block to the DSP via UA_IOCTL_DSP_SEND_BLOCK.

    Struct ua_dsp_block (24 bytes):
      u32 dsp_index
      u32 cmd (SRAM address)
      u32 param
      u32 data_size
      u64 data (userspace pointer)
    """
    if verbose:
        print(f"  → send_block: sram=0x{block.sram_addr:08x} param=0x{block.param:08x} "
              f"size={len(block.payload)} bytes")

    # Create a ctypes buffer from the payload bytes
    # This gives us a stable memory address that the kernel can read from
    if len(block.payload) > 0:
        payload_buf = ctypes.create_string_buffer(block.payload)
        data_ptr = ctypes.addressof(payload_buf)
    else:
        data_ptr = 0

    # Pack struct ua_dsp_block
    # Layout: dsp_index(u32), cmd(u32), param(u32), data_size(u32), data(u64)
    blk_struct = struct.pack("IIIIQ",
                             block.dsp_idx,
                             block.sram_addr,
                             block.param,
                             len(block.payload),
                             data_ptr)

    try:
        fcntl.ioctl(fd, UA_IOCTL_DSP_SEND_BLOCK, blk_struct)
        return True
    except OSError as e:
        print(f"  ERROR: ioctl failed: {e}")
        return False

# ----------------------------------------------------------------
# Main replay logic
# ----------------------------------------------------------------

def replay_firmware_blocks(device_path, log_path, payloads_dir,
                          dry_run=False, verbose=False, pause_ms=0):
    """Main replay routine."""

    # Parse the DTrace log
    print(f"Parsing DTrace log: {log_path}")
    blocks = parse_dtrace_log(log_path)
    print(f"Found {len(blocks)} firmware blocks")

    if len(blocks) == 0:
        print("ERROR: No SEL127 blocks found in log")
        return 1

    # Load payload data for each block
    print(f"Loading payloads from: {payloads_dir}")
    unique_sram = set()
    total_bytes = 0

    for block in blocks:
        if block.sram_addr not in unique_sram:
            payload = load_block_payload(block, payloads_dir)
            if payload:
                block.payload = payload
                total_bytes += len(payload)
                unique_sram.add(block.sram_addr)
            else:
                # No payload found, skip this block
                block.payload = b''
        else:
            # Duplicate SRAM address — the payload was already loaded by
            # the first block to this address. For replay, skip duplicates.
            block.payload = None  # Mark as skip

    # Filter out blocks without payloads
    blocks = [b for b in blocks if b.payload is not None and len(b.payload) > 0]

    print(f"Filtered to {len(blocks)} unique SRAM addresses")
    print(f"Total payload size: {total_bytes} bytes ({total_bytes/1024:.1f} KB)")

    if dry_run:
        print("\n=== DRY RUN: Block list ===")
        for i, block in enumerate(blocks):
            print(f"  [{i:3d}] t={block.timestamp:6d}ms sram=0x{block.sram_addr:08x} "
                  f"param=0x{block.param:08x} size={len(block.payload):5d}")
        return 0

    # Open device
    print(f"\nOpening device: {device_path}")
    if not os.path.exists(device_path):
        print(f"ERROR: Device not found: {device_path}")
        return 1

    fd = os.open(device_path, os.O_RDWR)

    try:
        # Get device info
        info = get_device_info(fd)
        print(f"Device: type=0x{info['device_type']:02x} "
              f"DSPs={info['num_dsps']} fw_v2={info['fw_v2']}")

        # Check initial state
        print("\n=== Initial DSP state ===")
        mixer_alive_before = dump_dsp_state(fd, "before")

        if mixer_alive_before:
            print("WARNING: Mixer DSP is already alive (SEQ_WR == SEQ_RD)")
            print("         Firmware replay may interfere with running DSP")

        # Replay blocks
        print(f"\n=== Replaying {len(blocks)} blocks ===")
        start_time = time.time()

        for i, block in enumerate(blocks):
            if verbose or (i % 10 == 0):
                print(f"[{i+1}/{len(blocks)}] {block}")

            success = send_block_via_ioctl(fd, block, verbose=verbose)
            if not success:
                print(f"ERROR: Failed to send block {i}")
                return 1

            if pause_ms > 0:
                time.sleep(pause_ms / 1000.0)

        elapsed = time.time() - start_time
        print(f"Replay complete in {elapsed:.2f}s "
              f"({len(blocks)/elapsed:.1f} blocks/s)")

        # Check final state
        print("\n=== Final DSP state ===")
        time.sleep(0.1)  # Let DSP settle
        mixer_alive_after = dump_dsp_state(fd, "after")

        # Try HW readback
        rb_status, rb_data = get_hw_readback(fd)
        print(f"HW readback status: {rb_status}")
        if rb_status == 1:
            print(f"  rb[0] (preamp flags) = 0x{rb_data[0]:08x}")
            print(f"  rb[2] (monitor)      = 0x{rb_data[2]:08x}")
            print(f"  rb[3] (preamp gain)  = 0x{rb_data[3]:08x}")

        # Summary
        print("\n" + "="*60)
        if mixer_alive_after and not mixer_alive_before:
            print("SUCCESS: Mixer DSP came alive after firmware replay!")
        elif mixer_alive_after:
            print("INFO: Mixer DSP still alive (was already running)")
        else:
            print("FAILED: Mixer DSP not responding")
            print("\nNext steps:")
            print("  - Check dmesg for kernel driver messages")
            print("  - Verify DSP ring buffer programming (page addrs, write_ptr)")
            print("  - Check if DMA engines are enabled (DMA_CTRL register)")
            print("  - May need firmware connect sequence after blocks")
        print("="*60)

    finally:
        os.close(fd)

    return 0

# ----------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Replay DSP firmware blocks captured from macOS',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)

    parser.add_argument('--device', default='/dev/ua_apollo0',
                       help='Device path (default: /dev/ua_apollo0)')
    parser.add_argument('--log', default='tools/captures/fw-payload-3.log',
                       help='DTrace capture log path')
    parser.add_argument('--payloads', default='tools/captures/fw-payloads-v3',
                       help='Directory containing parsed binary payloads')
    parser.add_argument('--dry-run', action='store_true',
                       help='Parse and print blocks without sending')
    parser.add_argument('--verbose', action='store_true',
                       help='Print each block as it is sent')
    parser.add_argument('--pause', type=int, default=0, metavar='MS',
                       help='Pause MS milliseconds between blocks')

    args = parser.parse_args()

    # Resolve relative paths
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent

    log_path = Path(args.log)
    if not log_path.is_absolute():
        log_path = repo_root / log_path

    payloads_dir = Path(args.payloads)
    if not payloads_dir.is_absolute():
        payloads_dir = repo_root / payloads_dir

    if not log_path.exists():
        print(f"ERROR: Log file not found: {log_path}")
        return 1

    if not payloads_dir.is_dir():
        print(f"ERROR: Payloads directory not found: {payloads_dir}")
        return 1

    return replay_firmware_blocks(
        args.device, log_path, payloads_dir,
        dry_run=args.dry_run, verbose=args.verbose, pause_ms=args.pause)

if __name__ == '__main__':
    sys.exit(main())
