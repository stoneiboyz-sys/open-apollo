#!/usr/bin/env python3
"""Parse USBPcap captures and extract Apollo Solo USB DSP bulk commands.

Reads classic .pcap or .pcapng (Wireshark) from USBPcap (Windows) and extracts:
  - Bulk OUT commands (EP1 OUT, 0xDC magic) — host → device writes
  - Bulk IN responses (EP1 IN, 0xDD magic) — device → host responses
  - Optionally correlates with mixer-sweep.py CSV timestamps

Output: human-readable decoded commands + mapping table.

Usage:
    # Basic decode — show all bulk commands
    python pcap-mixer-decode.py capture.pcap

    # Correlate with sweep log to build parameter mapping
    python pcap-mixer-decode.py capture.pcap --sweep-log sweep-log.csv

    # Filter by time window (epoch seconds)
    python pcap-mixer-decode.py capture.pcap --after 1711561200 --before 1711561300

    # Export mapping table as JSON
    python pcap-mixer-decode.py capture.pcap --sweep-log sweep-log.csv --json mapping.json

Requires: pip install dpkt  (or scapy, but dpkt is lighter)

USBPcap pcap format:
    Each packet has a USBPcap pseudo-header (27 bytes) followed by payload.
    Header fields (little-endian):
        u16 headerLen, u64 irpId, u32 irpStatus, u16 urbFunction,
        u8  irpInfo (direction: 0=OUT, 1=IN), u16 bus, u16 device,
        u8  endpoint, u8  transfer, u32 dataLength
"""

import argparse
import csv
import json
import os
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass, field

# USBPcap header size (standard)
USBPCAP_HEADER_LEN = 27

# Apollo DSP protocol constants
MAGIC_CMD = 0xDC
MAGIC_RSP = 0xDD

# Mic→monitor routing bulk (tools/usb-full-init.py) — for pcap comparison
PKT_MIC_MONITOR_A = bytes([
    0x04, 0x00, 0x25, 0xDC, 0x04, 0x00, 0x0C, 0x00, 0xA8, 0x6B, 0x0C, 0x00,
    0x01, 0x00, 0x00, 0x00, 0x0A, 0x00, 0x00, 0x19,
])
PKT_MIC_MONITOR_B = bytes([
    0x04, 0x00, 0x26, 0xDC, 0x04, 0x00, 0x0C, 0x00, 0xC4, 0x6A, 0x0C, 0x00,
    0x01, 0x00, 0x00, 0x00, 0x1A, 0x00, 0x00, 0x04,
])

# Substrings for mic→monitor-style DSP headers (any bulk OUT / any EP)
SEARCH_PAT_25DC = bytes([0x04, 0x00, 0x25, 0xDC])
SEARCH_PAT_26DC = bytes([0x04, 0x00, 0x26, 0xDC])
OP_QUERY = 0x0001
OP_READWRITE = 0x0002
OP_BLOCK_WRITE = 0x0004

OP_NAMES = {
    OP_QUERY: "QUERY",
    OP_READWRITE: "RW",
    OP_BLOCK_WRITE: "BLOCK",
}

# Known register names (from RE findings)
REG_NAMES = {
    0x0010: "CONFIG_A",
    0x0011: "CONFIG_B",
    0x0023: "INIT",
    0x0027: "STATUS",
}


@dataclass
class UsbPacket:
    """Parsed USB packet from USBPcap."""
    timestamp: float        # pcap timestamp (seconds)
    direction: str          # "OUT" or "IN"
    endpoint: int           # endpoint address (without direction bit)
    transfer_type: int      # 0=isoc, 1=intr, 2=ctrl, 3=bulk
    data: bytes             # payload after USBPcap header
    irp_id: int = 0


@dataclass
class DspCommand:
    """Decoded DSP bulk command/response."""
    timestamp: float
    direction: str          # "OUT" or "IN"
    word_count: int
    cmd_type: int           # sub-type byte
    magic: int              # 0xDC or 0xDD
    subcmds: list = field(default_factory=list)  # [(opcode, param, value), ...]
    raw: bytes = b""


@dataclass
class SweepEntry:
    """One entry from the sweep CSV log."""
    timestamp: float
    group: str
    path: str
    value: str


def _parse_usbpcap_record(pkt_data, timestamp):
    """Parse one USBPcap link-layer record into UsbPacket or None."""
    if len(pkt_data) < 28:
        return None

    hdr_len = struct.unpack_from("<H", pkt_data, 0)[0]
    if hdr_len < 27 or hdr_len > len(pkt_data):
        return None

    irp_id = struct.unpack_from("<Q", pkt_data, 2)[0]
    irp_info = pkt_data[16]  # 0=OUT, 1=IN
    endpoint = pkt_data[21]
    transfer_type = pkt_data[22]

    direction = "IN" if irp_info & 1 else "OUT"
    payload = pkt_data[hdr_len:]

    return UsbPacket(
        timestamp=timestamp,
        direction=direction,
        endpoint=endpoint & 0x7F,
        transfer_type=transfer_type,
        data=payload,
        irp_id=irp_id,
    )


def read_pcap(filepath):
    """Read classic pcap (not pcapng) and return UsbPacket list.

    Supports standard pcap format with USBPcap link type (249).
    """
    with open(filepath, "rb") as f:
        # pcap global header (24 bytes)
        ghdr = f.read(24)
        if len(ghdr) < 24:
            raise ValueError("Not a valid pcap file")

        magic = struct.unpack_from("<I", ghdr, 0)[0]
        if magic == 0xA1B2C3D4:
            endian = "<"
        elif magic == 0xD4C3B2A1:
            endian = ">"
        else:
            raise ValueError(f"Unknown pcap magic: {magic:#010x}")

        link_type = struct.unpack_from(f"{endian}I", ghdr, 20)[0]
        if link_type != 249:
            print(f"Warning: link type {link_type} (expected 249 for USBPcap)")

        packets = []
        while True:
            # pcap record header (16 bytes)
            rhdr = f.read(16)
            if len(rhdr) < 16:
                break

            ts_sec, ts_usec, incl_len, orig_len = struct.unpack(f"{endian}IIII", rhdr)
            timestamp = ts_sec + ts_usec / 1_000_000.0

            pkt_data = f.read(incl_len)
            if len(pkt_data) < incl_len:
                break

            pkt = _parse_usbpcap_record(pkt_data, timestamp)
            if pkt:
                packets.append(pkt)

        return packets


PCAPNG_SHB = 0x0A0D0D0A
PCAPNG_EPB = 0x00000006


def read_pcapng(filepath):
    """Read pcapng (Wireshark) with Enhanced Packet Blocks; link 249 = USBPcap."""
    packets = []
    with open(filepath, "rb") as f:
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            block_type, block_len = struct.unpack("<II", hdr)
            if block_len < 12:
                break
            body = f.read(block_len - 8)
            if len(body) != block_len - 8:
                break

            if block_type != PCAPNG_EPB:
                continue
            if len(body) < 20:
                continue

            iface, tsh, tsl, caplen, pktlen = struct.unpack_from("<IIIII", body, 0)
            ts_ns = (tsh << 32) | tsl
            timestamp = ts_ns / 1e9

            capdata = body[20 : 20 + caplen]
            pkt = _parse_usbpcap_record(capdata, timestamp)
            if pkt:
                packets.append(pkt)

    return packets


def read_pcap_auto(filepath):
    """Detect pcap vs pcapng and read USBPcap packets."""
    with open(filepath, "rb") as f:
        magic = f.read(4)
    if len(magic) < 4:
        raise ValueError("Empty file")
    if struct.unpack("<I", magic)[0] == PCAPNG_SHB:
        return read_pcapng(filepath)
    return read_pcap(filepath)


def decode_dsp_packet(pkt):
    """Decode a bulk endpoint packet into a DspCommand, or None."""
    if len(pkt.data) < 4:
        return None

    word_count, cmd_type, magic = struct.unpack_from("<HBB", pkt.data, 0)

    if magic not in (MAGIC_CMD, MAGIC_RSP):
        return None

    cmd = DspCommand(
        timestamp=pkt.timestamp,
        direction=pkt.direction,
        word_count=word_count,
        cmd_type=cmd_type,
        magic=magic,
        raw=pkt.data,
    )

    # Parse sub-commands (8 bytes each: opcode:u16 param:u16 value:u32)
    payload = pkt.data[4:]
    # For queries (opcode 0x01), sub-command is only 4 bytes: opcode:u16 param:u16
    offset = 0
    while offset < len(payload):
        if offset + 4 > len(payload):
            break
        opcode, param = struct.unpack_from("<HH", payload, offset)
        if opcode == OP_QUERY:
            cmd.subcmds.append((opcode, param, 0))
            offset += 4
        elif offset + 8 <= len(payload):
            value = struct.unpack_from("<I", payload, offset + 4)[0]
            cmd.subcmds.append((opcode, param, value))
            offset += 8
        else:
            break

    return cmd


def read_sweep_log(filepath):
    """Read sweep-log.csv and return list of SweepEntry."""
    entries = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(SweepEntry(
                timestamp=float(row["timestamp"]),
                group=row["group"],
                path=row["path"],
                value=row["value"],
            ))
    return entries


def format_subcmd(opcode, param, value):
    """Format a sub-command for display."""
    op_name = OP_NAMES.get(opcode, f"0x{opcode:04x}")
    reg_name = REG_NAMES.get(param, f"0x{param:04x}")
    if opcode == OP_QUERY:
        return f"{op_name}({reg_name})"
    return f"{op_name}({reg_name}, 0x{value:08x})"


def correlate(dsp_cmds, sweep_entries, window_sec=2.0):
    """Correlate DSP commands with sweep entries by timestamp.

    For each sweep entry, find DSP OUT commands that occurred within
    window_sec after the sweep SET was sent. These are the USB commands
    that UA Console sent in response to the TCP SET.

    Returns list of (sweep_entry, [dsp_commands]) tuples.
    """
    # We need to align clocks. The sweep log uses the host clock,
    # and the pcap uses the Windows VM clock. We'll try to find a
    # time offset by looking at the sync markers.
    #
    # Strategy: the first sweep entry is a "marker" SET. Look for
    # the first DSP OUT command and compute offset.

    if not sweep_entries or not dsp_cmds:
        return []

    # Find OUT commands only
    out_cmds = [c for c in dsp_cmds if c.direction == "OUT"]
    if not out_cmds:
        return []

    # Auto-detect clock offset from first marker
    markers = [e for e in sweep_entries if e.group == "marker"]
    if markers:
        first_marker_ts = markers[0].timestamp
        # Find first OUT command near the beginning
        first_out_ts = out_cmds[0].timestamp
        clock_offset = first_out_ts - first_marker_ts
        print(f"\n  Clock offset: {clock_offset:+.3f}s "
              f"(sweep={first_marker_ts:.3f}, pcap={first_out_ts:.3f})")
    else:
        clock_offset = 0.0
        print("\n  No sync markers found — assuming clocks are aligned")

    correlations = []
    out_idx = 0
    for entry in sweep_entries:
        adjusted_ts = entry.timestamp + clock_offset
        matched = []
        # Find OUT commands within [adjusted_ts, adjusted_ts + window_sec]
        for cmd in out_cmds:
            if cmd.timestamp < adjusted_ts - 0.1:
                continue
            if cmd.timestamp > adjusted_ts + window_sec:
                break
            matched.append(cmd)
        correlations.append((entry, matched))

    return correlations


def build_mapping(correlations):
    """Build parameter → USB command mapping from correlations.

    Groups by sweep group and extracts unique (param, value) pairs
    for each control path + value combination.
    """
    mapping = defaultdict(list)

    for entry, cmds in correlations:
        if entry.group == "marker":
            continue
        if not cmds:
            continue

        key = f"{entry.group}:{entry.path}={entry.value}"
        for cmd in cmds:
            for opcode, param, value in cmd.subcmds:
                mapping[key].append({
                    "opcode": opcode,
                    "param": param,
                    "value": value,
                    "param_hex": f"0x{param:04x}",
                    "value_hex": f"0x{value:08x}",
                    "cmd_type": cmd.cmd_type,
                })

    return dict(mapping)


def print_commands(dsp_cmds, limit=None):
    """Print decoded DSP commands."""
    count = 0
    for cmd in dsp_cmds:
        if limit and count >= limit:
            print(f"  ... ({len(dsp_cmds) - limit} more)")
            break
        magic_name = "CMD" if cmd.magic == MAGIC_CMD else "RSP"
        dir_arrow = "→" if cmd.direction == "OUT" else "←"
        subcmd_strs = [format_subcmd(o, p, v) for o, p, v in cmd.subcmds]
        print(f"  {cmd.timestamp:.6f} {dir_arrow} {magic_name} "
              f"type={cmd.cmd_type} words={cmd.word_count} "
              f"[{', '.join(subcmd_strs)}]")
        count += 1


def main():
    parser = argparse.ArgumentParser(
        description="Decode Apollo USB DSP commands from USBPcap pcap files")
    parser.add_argument("pcap", help="USBPcap .pcap or .pcapng file")
    parser.add_argument("--sweep-log", type=str, default=None,
                        help="Sweep CSV log for correlation")
    parser.add_argument("--after", type=float, default=None,
                        help="Only show packets after this epoch timestamp")
    parser.add_argument("--before", type=float, default=None,
                        help="Only show packets before this epoch timestamp")
    parser.add_argument("--json", type=str, default=None,
                        help="Export mapping table as JSON")
    parser.add_argument("--endpoint", type=int, default=1,
                        help="Bulk endpoint number (default: 1)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit output to N commands")
    parser.add_argument("--out-only", action="store_true",
                        help="Show only OUT (host→device) commands")
    parser.add_argument(
        "--dump-raw-bulk-out",
        action="store_true",
        help="Print timestamp + raw hex for each BULK transfer_type OUT on "
        "--endpoint (includes non-DSP payloads).",
    )
    parser.add_argument(
        "--search-mic-pkts",
        action="store_true",
        help="Search PKT_MIC_MONITOR_A/B on any BULK OUT endpoint and print hits.",
    )
    parser.add_argument(
        "--search-dc-patterns",
        action="store_true",
        help="Search any BULK OUT for payload containing 040025dc or 040026dc; "
        "print ep + raw hex (respects --after / --before).",
    )
    args = parser.parse_args()

    def _aux_modes():
        return (
            args.dump_raw_bulk_out
            or args.search_mic_pkts
            or args.search_dc_patterns
        )

    print(f"Reading {args.pcap}...")
    packets = read_pcap_auto(args.pcap)
    print(f"  {len(packets)} USB packets total")

    # Filter to bulk endpoint
    bulk_pkts = [p for p in packets
                 if p.transfer_type == 3 and p.endpoint == args.endpoint]
    print(f"  {len(bulk_pkts)} bulk EP{args.endpoint} packets")

    # Time filter
    if args.after:
        bulk_pkts = [p for p in bulk_pkts if p.timestamp >= args.after]
    if args.before:
        bulk_pkts = [p for p in bulk_pkts if p.timestamp <= args.before]

    # Decode DSP commands
    dsp_cmds = []
    for pkt in bulk_pkts:
        cmd = decode_dsp_packet(pkt)
        if cmd:
            dsp_cmds.append(cmd)

    if args.out_only:
        dsp_cmds = [c for c in dsp_cmds if c.direction == "OUT"]

    out_count = sum(1 for c in dsp_cmds if c.direction == "OUT")
    in_count = sum(1 for c in dsp_cmds if c.direction == "IN")
    print(f"  {len(dsp_cmds)} DSP commands ({out_count} OUT, {in_count} IN)")

    if args.dump_raw_bulk_out:
        print("\n=== Raw BULK OUT (filtered endpoint + time window) ===")
        for p in bulk_pkts:
            if p.direction == "OUT" and len(p.data) > 0:
                note = ""
                if p.data == PKT_MIC_MONITOR_A:
                    note = "  # MATCH usb-full-init pkt_a (mic→monitor)"
                elif p.data == PKT_MIC_MONITOR_B:
                    note = "  # MATCH usb-full-init pkt_b (mic→monitor)"
                print(
                    f"  {p.timestamp:.9f}  ep={p.endpoint}  len={len(p.data)}  "
                    f"hex={p.data.hex()}{note}",
                )

    if args.search_mic_pkts:
        print("\n=== Search pkt_a / pkt_b on any BULK OUT ===")
        hits = 0
        for p in packets:
            if p.transfer_type != 3 or p.direction != "OUT" or len(p.data) == 0:
                continue
            if p.data == PKT_MIC_MONITOR_A:
                print(
                    f"  HIT_A  {p.timestamp:.9f}  ep={p.endpoint}  "
                    f"len={len(p.data)}  hex={p.data.hex()}",
                )
                hits += 1
            elif p.data == PKT_MIC_MONITOR_B:
                print(
                    f"  HIT_B  {p.timestamp:.9f}  ep={p.endpoint}  "
                    f"len={len(p.data)}  hex={p.data.hex()}",
                )
                hits += 1
        if hits == 0:
            print("  (no exact matches for pkt_a or pkt_b on any BULK OUT)")

    if args.search_dc_patterns:
        print(
            "\n=== BULK OUT containing 040025dc or 040026dc "
            "(any endpoint, --after/--before apply) ===",
        )
        hits_dc = 0
        for p in packets:
            if args.after is not None and p.timestamp < args.after:
                continue
            if args.before is not None and p.timestamp > args.before:
                continue
            if p.transfer_type != 3 or p.direction != "OUT" or len(p.data) == 0:
                continue
            tags = []
            if SEARCH_PAT_25DC in p.data:
                tags.append("040025dc")
            if SEARCH_PAT_26DC in p.data:
                tags.append("040026dc")
            if not tags:
                continue
            hits_dc += 1
            tag_s = "+".join(tags)
            print(
                f"  match={tag_s}  {p.timestamp:.9f}  ep={p.endpoint}  "
                f"len={len(p.data)}  hex={p.data.hex()}",
            )
        if hits_dc == 0:
            print("  (no bulk OUT payloads contain those substrings)")

    if not dsp_cmds:
        print("No DSP commands found.")
        if not _aux_modes():
            print(
                "Tip: try --dump-raw-bulk-out, --search-mic-pkts, or "
                "--search-dc-patterns for raw payloads.",
            )
        if not _aux_modes():
            return
        if args.sweep_log:
            print("Skipping sweep correlation (no DSP commands).")
        return

    # Collect unique params seen in OUT commands
    params_seen = set()
    for cmd in dsp_cmds:
        if cmd.direction == "OUT":
            for opcode, param, value in cmd.subcmds:
                params_seen.add((opcode, param))

    print(f"\n  Unique (opcode, param) pairs in OUT commands:")
    for opcode, param in sorted(params_seen):
        op_name = OP_NAMES.get(opcode, f"0x{opcode:04x}")
        reg_name = REG_NAMES.get(param, f"0x{param:04x}")
        print(f"    {op_name} {reg_name}")

    # Show commands
    print(f"\n=== DSP Commands ===")
    print_commands(dsp_cmds, args.limit)

    # Correlate with sweep log
    if args.sweep_log:
        print(f"\n=== Correlation with {args.sweep_log} ===")
        sweep_entries = read_sweep_log(args.sweep_log)
        print(f"  {len(sweep_entries)} sweep entries")

        correlations = correlate(dsp_cmds, sweep_entries)

        # Print correlations
        for entry, cmds in correlations:
            if entry.group == "marker":
                continue
            status = f"{len(cmds)} USB cmd(s)" if cmds else "NO USB TRAFFIC"
            print(f"\n  [{entry.group}] {entry.path} = {entry.value}  "
                  f"→ {status}")
            for cmd in cmds:
                subcmd_strs = [format_subcmd(o, p, v)
                               for o, p, v in cmd.subcmds]
                delta = cmd.timestamp - (entry.timestamp)
                print(f"    +{delta*1000:.1f}ms: [{', '.join(subcmd_strs)}]")

        # Build mapping
        mapping = build_mapping(correlations)
        if mapping:
            print(f"\n=== Parameter Mapping ({len(mapping)} entries) ===")
            for key, cmds in sorted(mapping.items()):
                print(f"\n  {key}:")
                for c in cmds:
                    print(f"    op=0x{c['opcode']:04x} "
                          f"param={c['param_hex']} "
                          f"value={c['value_hex']} "
                          f"type={c['cmd_type']}")

            if args.json:
                with open(args.json, "w") as f:
                    json.dump(mapping, f, indent=2)
                print(f"\n  Mapping exported to {args.json}")


if __name__ == "__main__":
    main()
