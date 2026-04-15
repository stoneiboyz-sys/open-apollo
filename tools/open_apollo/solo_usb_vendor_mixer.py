"""Vendor EP0 mixer writes for Apollo Solo USB (no interface claim — PipeWire stays up).

Same 0x03 batch protocol as tools/usb-mixer-test.py; constants align with
mixer-engine/hardware_usb.py (SETTINGS_* / SETTING_*).
"""

from __future__ import annotations

import struct
from typing import Optional

import usb.core

UA_VID = 0x2B5A
SOLO_USB_PID = 0x000D

SETTINGS_SEQ = 0x0602
SETTINGS_MASK = 0x062D
SETTINGS_VALUES = 0x064F

SETTING_PREAMP_CH0 = 0
SETTING_PREAMP_CH1 = 1
SETTING_MONITOR = 2
SETTING_GAIN_C = 3


def setting_word(mask: int, value: int) -> int:
    return ((mask & 0xFFFF) << 16) | (value & 0xFFFF)


class VendorEp0Mixer:
    """EP0-only mixer (bmRequestType 0x41); do not claim interface 0."""

    __slots__ = ('dev', 'seq')

    def __init__(self) -> None:
        self.dev: Optional[usb.core.Device] = None
        self.seq = 7

    def find(self) -> bool:
        self.dev = usb.core.find(idVendor=UA_VID, idProduct=SOLO_USB_PID)
        return self.dev is not None

    def _vendor_write(self, request: int, wvalue: int, data: bytes = b'') -> None:
        assert self.dev is not None
        self.dev.ctrl_transfer(0x41, request, wvalue, 0, data, timeout=1000)

    def write_settings(
        self, mask_buf: bytearray, value_buf: Optional[bytearray] = None
    ) -> None:
        self._vendor_write(0x03, SETTINGS_MASK, mask_buf)
        if value_buf and any(b != 0 for b in value_buf):
            self._vendor_write(0x03, SETTINGS_VALUES, value_buf)
        self._vendor_write(0x03, SETTINGS_SEQ, struct.pack('<I', self.seq))
        self.seq += 1

    def set_phantom(self, channel: int, enabled: bool) -> None:
        off = (SETTING_PREAMP_CH0 + channel) * 8
        mask_buf = bytearray(128)
        val = 0x0008 if enabled else 0x0000
        struct.pack_into('<I', mask_buf, off, setting_word(0x0008, val))
        self.write_settings(mask_buf)

    def set_mic_line(self, channel: int, line_mode: bool) -> None:
        off = (SETTING_PREAMP_CH0 + channel) * 8
        mask_buf = bytearray(128)
        val = 0x0001 if line_mode else 0x0000
        struct.pack_into('<I', mask_buf, off, setting_word(0x0001, val))
        self.write_settings(mask_buf)

    def set_pad(self, channel: int, enabled: bool) -> None:
        """Inferred PAD on bit1 (mask 0x0002) — verify on hardware."""
        off = (SETTING_PREAMP_CH0 + channel) * 8
        mask_buf = bytearray(128)
        val = 0x0002 if enabled else 0x0000
        struct.pack_into('<I', mask_buf, off, setting_word(0x0002, val))
        self.write_settings(mask_buf)

    def set_low_cut(self, channel: int, enabled: bool) -> None:
        """Inferred low-cut on bit4 (mask 0x0010) — verify on hardware."""
        off = (SETTING_PREAMP_CH0 + channel) * 8
        mask_buf = bytearray(128)
        val = 0x0010 if enabled else 0x0000
        struct.pack_into('<I', mask_buf, off, setting_word(0x0010, val))
        self.write_settings(mask_buf)

    def set_monitor_db(self, level_db: float) -> None:
        raw = max(0, min(0xC0, int(192 + float(level_db) * 2)))
        mask_buf = bytearray(128)
        struct.pack_into(
            '<I', mask_buf, SETTING_MONITOR * 8, setting_word(0x00FF, raw)
        )
        self.write_settings(mask_buf)

    def set_monitor_flags(self, muted: bool, mono: bool) -> None:
        """Mute (bit1) and mono (bit0) share wordB — must be written in one shot."""
        mask_buf = bytearray(128)
        val = (0x0002 if muted else 0) | (0x0001 if mono else 0)
        struct.pack_into(
            '<I', mask_buf, SETTING_MONITOR * 8 + 4, setting_word(0x0003, val)
        )
        self.write_settings(mask_buf)

    def set_preamp_gain_db(self, channel: int, gain_db: float) -> None:
        gain_i = int(round(float(gain_db)))
        val_a = max(0, min(54, gain_i - 10))
        val_c = val_a + 0x41
        mask_buf = bytearray(128)
        value_buf = bytearray(128)
        off = (SETTING_PREAMP_CH0 + channel) * 8
        struct.pack_into('<I', value_buf, off, setting_word(0x00FF, val_a))
        struct.pack_into(
            '<I', mask_buf, SETTING_GAIN_C * 8, setting_word(0x003F, val_c)
        )
        self.write_settings(mask_buf, value_buf)
