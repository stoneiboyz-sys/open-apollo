#!/usr/bin/env python3
"""Full DSP + routing init for Apollo Solo USB.

Replays the complete 38-packet bulk init sequence captured from Windows
UA Console, then sets the UAC2 clock and initial monitor level.
This configures the FPGA routing matrix so capture channels receive signal.

Logs to stdout when connected to a TTY; otherwise to syslog via
SysLogHandler(/dev/log, LOG_USER) with messages prefixed ``ua-usb-dsp-init:``
in the formatter (no ident= kwarg — portable across Python builds).

Usage:
  sudo python3 tools/usb-full-init.py
  sudo python3 tools/usb-full-init.py --vendor-monitor-hp-only

After full init, reload snd-usb-audio:
    sudo rmmod snd_usb_audio; sudo insmod /tmp/sound/usb/snd-usb-audio.ko
"""
import argparse
import logging
import logging.handlers
import os
import struct
import sys
import time

import usb.core
import usb.util

UA_VID = 0x2B5A
SOLO_PID = 0x000D
EP_BULK_OUT = 0x01
EP_BULK_IN = 0x81

# Same facility/tag as scripts/ua-usb-dsp-init.sh (logger -t ua-usb-dsp-init)
_SYSLOG_IDENT = "ua-usb-dsp-init:"

LOG = logging.getLogger("usb_full_init")

# Vendor ctrl 0x03 — mixer settings (same layout as tools/usb-monitor-enable.py)
SETTINGS_SEQ = 0x0602
SETTINGS_MASK = 0x062D
SETTING_MONITOR_WA = 16
SETTING_MONITOR_WB = 20
MASK_MONITOR = 0x00FF
MASK_HP1 = 0xFF00
MASK_MUTEMONO = 0x0003

# After full init uses seq 5000/5001, post-rebind vendor-only pass must stay higher
# if the FPGA retains its counter across re-enumeration.
SEQ_VENDOR_POST_REBIND = 10000

_script_dir = os.path.dirname(os.path.abspath(__file__))
INIT_BIN = os.path.join(_script_dir, "usb-re", "init-bulk-sequence.bin")
if not os.path.exists(INIT_BIN):
    INIT_BIN = os.path.join(_script_dir, "init-bulk-sequence.bin")


def _drain_bulk_in_until_idle(dev, timeout_ms):
    """Drain EP BULK IN until two consecutive read timeouts (endpoint idle).

    Avoids stopping early when the DSP pauses longer than *timeout_ms* between
    IN chunks (single-timeout drain can leave stale data).
    """
    consecutive_timeouts = 0
    while consecutive_timeouts < 2:
        try:
            dev.read(EP_BULK_IN, 1024, timeout=timeout_ms)
            consecutive_timeouts = 0
        except usb.core.USBTimeoutError:
            consecutive_timeouts += 1


def configure_logging():
    """TTY → stdout; else syslog (non-blocking vs pipe-to-logger)."""
    LOG.setLevel(logging.INFO)
    LOG.handlers.clear()
    LOG.propagate = False
    fmt_tty = logging.Formatter("%(message)s")
    fmt_syslog = logging.Formatter(_SYSLOG_IDENT + " %(message)s")
    if sys.stdout.isatty():
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(fmt_tty)
        LOG.addHandler(h)
    else:
        try:
            h = logging.handlers.SysLogHandler(
                address="/dev/log",
                facility=logging.handlers.SysLogHandler.LOG_USER,
            )
            h.setFormatter(fmt_syslog)
            LOG.addHandler(h)
        except OSError:
            h = logging.StreamHandler(sys.stderr)
            h.setFormatter(fmt_syslog)
            LOG.addHandler(h)


def _setting_word(mask, value):
    return ((mask & 0xFFFF) << 16) | (value & 0xFFFF)


def _probe_seq_via_jkmk(dev):
    """Optional seq hint from vendor 0x0A; often returns None (see usb-monitor-enable)."""
    try:
        data = bytes(dev.ctrl_transfer(0xC0, 0x0A, 0, 0, 48, timeout=300))
        if data[:4] == b"JKMK":
            return None
    except usb.core.USBError:
        pass
    return None


def _write_monitor_and_hp(dev, level_db, muted, seq):
    """Write set[2] Monitor (LINE) + HP1 together (mask 0xffff) and seq; returns raw level byte."""
    raw = max(0, min(0xC0, int(192 + level_db * 2)))
    mute_flag = 0x0002 if muted else 0x0000
    mask_buf = bytearray(128)
    combined_mask = MASK_MONITOR | MASK_HP1
    combined_value = (raw << 8) | raw
    struct.pack_into(
        "<I", mask_buf, SETTING_MONITOR_WA,
        _setting_word(combined_mask, combined_value),
    )
    struct.pack_into(
        "<I", mask_buf, SETTING_MONITOR_WB,
        _setting_word(MASK_MUTEMONO, mute_flag),
    )
    dev.ctrl_transfer(0x41, 0x03, SETTINGS_MASK, 0, bytes(mask_buf), timeout=1000)
    dev.ctrl_transfer(0x41, 0x03, SETTINGS_SEQ, 0, struct.pack("<I", seq), timeout=1000)
    return raw


def apply_vendor_monitor_hp(
    dev,
    level_db=-12.0,
    *,
    post_rebind=False,
    seq_min=0,
):
    """EP0-only: Monitor (LINE) + HP1 levels and unmute (two-step seq like usb-monitor-enable).

    post_rebind: use SEQ_VENDOR_POST_REBIND so writes beat a prior full init's 5000/5001
    if the FPGA counter survives USB re-enumeration.

    seq_min: raise the chosen seq to at least this value (FPGA ignores writes when seq is
    not strictly above its internal counter; after a long bulk init the counter may be high).
    """
    probed_seq = _probe_seq_via_jkmk(dev)
    if post_rebind:
        seq = SEQ_VENDOR_POST_REBIND
        LOG.info("Settings seq: %s (post-rebind vendor pass)", seq)
    elif probed_seq is not None:
        seq = probed_seq + 100
        LOG.info("Settings seq: %s (probed base=%s)", seq, probed_seq)
    else:
        seq = 5000
        LOG.info("Settings seq: %s (safe default, above stale init counters)", seq)
    if seq_min and not post_rebind and seq < seq_min:
        LOG.info("  bumping seq %s -> %s (seq_min after bulk init)", seq, seq_min)
        seq = seq_min

    raw = _write_monitor_and_hp(dev, level_db, False, seq)
    LOG.info(
        "Monitor+HP1: %.0f dB — Monitor[7:0]=HP1[15:8]=0x%02x, mask=0xffff, seq=%s",
        level_db, raw, seq,
    )
    time.sleep(0.1)
    _write_monitor_and_hp(dev, level_db, False, seq + 1)
    LOG.info("Monitor+HP1: confirmed seq=%s", seq + 1)


def replay_init_sequence(dev, bin_path, skip_indices=None):
    """Replay the captured init bulk sequence.

    The 38-packet sequence has three phases:
      0-9:   FPGA config + clock setup
      10-23: DSP program loads (large packets)
      24-37: Routing table + monitor config

    The DSP needs time to process program loads before accepting routing
    writes.  Windows UA Console leaves 1+ second gaps between phases.
    """
    ROUTING_START = 24        # first routing config packet
    ROUTING_INTERPACKET_DELAY_SEC = 0.2
    ROUTING_PREWRITE_DRAIN_MS = 150
    RETRY_BACKOFF_SEC = (1.0, 2.0, 4.0)
    SPECIAL_INDEX_28 = 28
    SPECIAL_28_INTERPACKET_DELAY_SEC = 0.5
    SPECIAL_28_WRITE_TIMEOUT_MS = 5000
    SPECIAL_28_POST_SETTLE_SEC = 0.5
    SPECIAL_28_POST_DRAIN_MS = 2000

    if skip_indices is None:
        skip_indices = set()

    with open(bin_path, "rb") as f:
        count = struct.unpack("<I", f.read(4))[0]
        LOG.info("Replaying %s bulk OUT packets...", count)
        if skip_indices:
            LOG.info("  Skip list enabled: %s", sorted(skip_indices))
        packet_stats = []
        for i in range(count):
            start_ts = time.monotonic()
            pkt_len = struct.unpack("<I", f.read(4))[0]
            pkt_data = f.read(pkt_len)
            retries = 0
            success = False

            wc, cmd_type, magic = struct.unpack_from("<HBB", pkt_data, 0)

            if i in skip_indices:
                elapsed_ms = (time.monotonic() - start_ts) * 1000.0
                packet_stats.append({
                    "index": i,
                    "cmd_type": cmd_type,
                    "words": wc,
                    "len": pkt_len,
                    "retries": 0,
                    "elapsed_ms": elapsed_ms,
                    "success": True,
                    "skipped": True,
                })
                LOG.info("  [%2d] SKIP type=%3d words=%3d len=%s", i, cmd_type, wc, pkt_len)
                continue

            # Phase transition delay — let DSP finish processing programs
            if i == ROUTING_START:
                LOG.info("  -- waiting for DSP to process program loads --")
                time.sleep(5.0)

            # All packets get generous timeout (AMD xHCI can be slow)
            timeout = 10000
            if i == SPECIAL_INDEX_28:
                timeout = SPECIAL_28_WRITE_TIMEOUT_MS

            # Inter-packet pacing: small delay between all packets,
            # longer delay after large ones (DSP program uploads)
            if i > 0:
                if i == SPECIAL_INDEX_28:
                    time.sleep(SPECIAL_28_INTERPACKET_DELAY_SEC)
                elif i >= ROUTING_START:
                    time.sleep(ROUTING_INTERPACKET_DELAY_SEC)
                elif pkt_len > 512:
                    time.sleep(0.2)
                else:
                    time.sleep(0.05)

            for attempt in range(3):
                try:
                    if i >= ROUTING_START:
                        _drain_bulk_in_until_idle(dev, ROUTING_PREWRITE_DRAIN_MS)
                    dev.write(EP_BULK_OUT, pkt_data, timeout=timeout)
                    success = True
                    break
                except usb.core.USBTimeoutError:
                    retries += 1
                    wait = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)]
                    LOG.info(
                        "  [%2d] timeout, retrying (%d/3) after %.0fs...",
                        i, attempt + 1, wait,
                    )
                    time.sleep(wait)
                    # Drain any stale responses before retry
                    _drain_bulk_in_until_idle(dev, 100)
                    if attempt == 2:
                        break

            elapsed_ms = (time.monotonic() - start_ts) * 1000.0
            packet_stats.append({
                "index": i,
                "cmd_type": cmd_type,
                "words": wc,
                "len": pkt_len,
                "retries": retries,
                "elapsed_ms": elapsed_ms,
                "success": success,
                "skipped": False,
            })
            if not success:
                LOG.error("  [%2d] FAILED after %d retries (%.1fms)", i, retries, elapsed_ms)
                break

            LOG.info("  [%2d] type=%3d words=%3d len=%s", i, cmd_type, wc, pkt_len)

            # Drain responses — wait longer after big packets
            drain_timeout = 1000 if pkt_len > 512 else 500
            if i == SPECIAL_INDEX_28:
                time.sleep(SPECIAL_28_POST_SETTLE_SEC)
                drain_timeout = SPECIAL_28_POST_DRAIN_MS
            _drain_bulk_in_until_idle(dev, drain_timeout)

    skipped_count = sum(1 for s in packet_stats if s.get("skipped"))
    ok_count = sum(1 for s in packet_stats if s["success"] and not s.get("skipped"))
    fail_count = len(packet_stats) - ok_count - skipped_count
    total_ms = sum(s["elapsed_ms"] for s in packet_stats)
    LOG.info(
        "  Replay summary: ok=%s skipped=%s failed=%s total_time=%.1fms",
        ok_count, skipped_count, fail_count, total_ms,
    )
    LOG.info("  Packet stats (idx type len retries elapsed_ms status):")
    for s in packet_stats:
        if s.get("skipped"):
            status = "SKIP"
        else:
            status = "OK" if s["success"] else "FAIL"
        LOG.info(
            "    [%2d] t=%3d len=%4d retries=%d elapsed=%.1fms %s",
            s["index"], s["cmd_type"], s["len"], s["retries"], s["elapsed_ms"], status,
        )
    if fail_count:
        raise RuntimeError(f"Init bulk replay failed on packet index {packet_stats[-1]['index']}")
    LOG.info("  Sent all %s packets", count)


def run_full_dsp_init(dev, skip_indices=None):
    if not os.path.exists(INIT_BIN):
        LOG.error("Missing: %s", INIT_BIN)
        sys.exit(1)

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except Exception:
        pass
    usb.util.claim_interface(dev, 0)

    replay_init_sequence(dev, INIT_BIN, skip_indices=skip_indices)

    LOG.info("Writing mic->monitor routing...")
    pkt_a = bytes([0x04, 0x00, 0x25, 0xdc, 0x04, 0x00, 0x1d, 0x00, 0x19, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00])
    pkt_b = bytes([0x08, 0x00, 0x26, 0xdc, 0x04, 0x00, 0x1d, 0x00, 0x18, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x04, 0x00, 0x1d, 0x00, 0x18, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00])
    dev.write(EP_BULK_OUT, pkt_a, timeout=1000)
    dev.write(EP_BULK_OUT, pkt_b, timeout=1000)
    # Extra DSP OUT from monitor-toggle.pcapng (not in init-bulk-sequence.bin); UA sends
    # these after routing; float words in pkt_toggle_3 match the capture (gain).
    pkt_toggle_1 = bytes.fromhex(
        "08002fdc04001d0000000000000000000000000004001d00000000000000000100000000"
    )
    pkt_toggle_2 = bytes.fromhex(
        "100030dc04001d0000000000030000000000000004001d00000000000300000100000000"
        "04001d0000000000040000000000000004001d00000000000400000100000000"
    )
    pkt_toggle_3 = bytes.fromhex(
        "180031dc04001d000000000000000000d63c263f04001d000000000000000001d63c263f"
        "04001d0000000000030000000000000004001d00000000000300000100000000"
        "04001d0000000000040000000000000004001d00000000000400000100000000"
    )
    dev.write(EP_BULK_OUT, pkt_toggle_1, timeout=1000)
    dev.write(EP_BULK_OUT, pkt_toggle_2, timeout=1000)
    time.sleep(0.006)
    dev.write(EP_BULK_OUT, pkt_toggle_3, timeout=1000)
    LOG.info("Mic->monitor routing + monitor-toggle DSP burst: done")
    _drain_bulk_in_until_idle(dev, 500)

    try:
        dev.ctrl_transfer(0x21, 0x01, 0x0100, 0x8001,
                          struct.pack("<I", 48000), timeout=2000)
        data = dev.ctrl_transfer(0xA1, 0x01, 0x0100, 0x8001, 4, timeout=1000)
        freq = struct.unpack("<I", bytes(data))[0]
        LOG.info("Clock: %s Hz", freq)
    except usb.core.USBError as e:
        LOG.warning("Clock ctrl_transfer failed (continuing): %s", e)

    # Vendor 0x41 (recipient = interface) while iface 0 is still claimed — releasing first
    # can race udev/snd_usb_audio and leave monitor/HP writes ignored (hardware silent).
    apply_vendor_monitor_hp(dev, post_rebind=False, seq_min=50000)
    usb.util.release_interface(dev, 0)
    LOG.info("Ready — run 'sudo modprobe snd_usb_audio' to get ALSA card")
    LOG.info("If hardware monitor is still silent: sudo python3 tools/usb-monitor-enable.py --seq 100000")


def run_post_interface_routing(dev):
    """Post-interface recovery pass after snd_usb_audio SET_INTERFACE.

    Do NOT replay routing packets 24..37 here: they can override/disable the
    native Apollo direct-monitor path in this post-interface context.
    Apply only vendor Monitor+HP1 with a high seq counter.
    """
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except Exception:
        pass
    usb.util.claim_interface(dev, 0)

    LOG.info("Post-interface: vendor-only Monitor+HP1 (seq_min=100000)")
    apply_vendor_monitor_hp(dev, post_rebind=False, seq_min=100000)
    usb.util.release_interface(dev, 0)
    LOG.info("Ready (post-interface vendor-only pass).")


def main():
    configure_logging()

    parser = argparse.ArgumentParser(
        description="Apollo Solo USB DSP init (bulk + vendor) or vendor-only pass.",
    )
    parser.add_argument(
        "--vendor-monitor-hp-only",
        action="store_true",
        help="Only apply Monitor+HP1 vendor settings (no bulk DSP init). "
        "Use after USB rebind when full init already ran.",
    )
    parser.add_argument(
        "--post-interface",
        action="store_true",
        help="Replay only routing/toggle bulk DSP packets + vendor monitor pass. "
        "Use after snd_usb_audio SET_INTERFACE without full 38-packet init.",
    )
    parser.add_argument(
        "--skip-index",
        action="append",
        type=int,
        default=[],
        help="Skip one init-bulk packet index (repeatable). Example: --skip-index 28",
    )
    args = parser.parse_args()

    dev = usb.core.find(idVendor=UA_VID, idProduct=SOLO_PID)
    if not dev:
        LOG.error("Apollo Solo USB not found")
        sys.exit(1)
    LOG.info("Found: %s", dev.product)

    if args.vendor_monitor_hp_only:
        apply_vendor_monitor_hp(dev, post_rebind=True)
        LOG.info("Ready (vendor-only).")
        return
    if args.post_interface:
        run_post_interface_routing(dev)
        return

    skip_indices = set(args.skip_index)
    if skip_indices:
        LOG.info("Using --skip-index: %s", sorted(skip_indices))
    run_full_dsp_init(dev, skip_indices=skip_indices)


if __name__ == "__main__":
    main()
