#!/usr/bin/env python3
"""GTK mixer for Apollo Solo USB (vendor control on EP0 — no USB interface claim).

Controls preamp / monitor paths using the same 0x03 batch protocol as
tools/usb-mixer-test.py and mixer-engine/hardware_usb.py. PipeWire keeps working.

PAD / Low-cut use bit positions inferred from internal docs (stride order vs bits
may differ); if toggles do the wrong thing on your unit, file an issue with a USB
capture — 48V / Mic-Line / monitor level are the best-tested paths.

Usage:
  python3 tools/open-apollo-usb-mixer.py

Requires: pyusb, python3-gi (GTK 3). USB access: plugdev/udev or run with sudo if needed.
"""

import struct
import sys

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

try:
    import usb.core
    import usb.util
except ImportError:
    print('Install pyusb: pip install pyusb', file=sys.stderr)
    sys.exit(1)

UA_VID = 0x2B5A
SOLO_PID = 0x000D

SETTINGS_SEQ = 0x0602
SETTINGS_MASK = 0x062D
SETTINGS_VALUES = 0x064F

SETTING_PREAMP_CH0 = 0
SETTING_PREAMP_CH1 = 1
SETTING_MONITOR = 2
SETTING_GAIN_C = 3


def setting_word(mask, value):
    return ((mask & 0xFFFF) << 16) | (value & 0xFFFF)


class VendorMixer:
    """EP0-only mixer writes (do not claim interface 0 — snd_usb_audio stays attached)."""

    def __init__(self):
        self.dev = None
        self.seq = 7

    def find(self):
        self.dev = usb.core.find(idVendor=UA_VID, idProduct=SOLO_PID)
        return self.dev is not None

    def _vendor_write(self, request, wvalue, data=b''):
        self.dev.ctrl_transfer(0x41, request, wvalue, 0, data, timeout=1000)

    def write_settings(self, mask_buf, value_buf=None):
        self._vendor_write(0x03, SETTINGS_MASK, mask_buf)
        if value_buf and any(b != 0 for b in value_buf):
            self._vendor_write(0x03, SETTINGS_VALUES, value_buf)
        self._vendor_write(0x03, SETTINGS_SEQ, struct.pack('<I', self.seq))
        self.seq += 1

    def set_phantom(self, channel, enabled):
        off = (SETTING_PREAMP_CH0 + channel) * 8
        mask_buf = bytearray(128)
        val = 0x0008 if enabled else 0x0000
        struct.pack_into('<I', mask_buf, off, setting_word(0x0008, val))
        self.write_settings(mask_buf)

    def set_mic_line(self, channel, line_mode):
        off = (SETTING_PREAMP_CH0 + channel) * 8
        mask_buf = bytearray(128)
        val = 0x0001 if line_mode else 0x0000
        struct.pack_into('<I', mask_buf, off, setting_word(0x0001, val))
        self.write_settings(mask_buf)

    def set_pad(self, channel, enabled):
        """Inferred PAD on bit1 (mask 0x0002) — verify on hardware."""
        off = (SETTING_PREAMP_CH0 + channel) * 8
        mask_buf = bytearray(128)
        val = 0x0002 if enabled else 0x0000
        struct.pack_into('<I', mask_buf, off, setting_word(0x0002, val))
        self.write_settings(mask_buf)

    def set_low_cut(self, channel, enabled):
        """Inferred low-cut on bit4 (mask 0x0010) — verify on hardware."""
        off = (SETTING_PREAMP_CH0 + channel) * 8
        mask_buf = bytearray(128)
        val = 0x0010 if enabled else 0x0000
        struct.pack_into('<I', mask_buf, off, setting_word(0x0010, val))
        self.write_settings(mask_buf)

    def set_monitor_db(self, level_db):
        raw = max(0, min(0xC0, int(192 + float(level_db) * 2)))
        mask_buf = bytearray(128)
        struct.pack_into('<I', mask_buf, SETTING_MONITOR * 8, setting_word(0x00FF, raw))
        self.write_settings(mask_buf)

    def set_monitor_flags(self, muted, mono):
        """Mute (bit1) and mono (bit0) share wordB — must be written in one shot."""
        mask_buf = bytearray(128)
        val = (0x0002 if muted else 0) | (0x0001 if mono else 0)
        struct.pack_into(
            '<I', mask_buf, SETTING_MONITOR * 8 + 4, setting_word(0x0003, val)
        )
        self.write_settings(mask_buf)

    def set_preamp_gain_db(self, channel, gain_db):
        gain_db = int(round(float(gain_db)))
        val_a = max(0, min(54, gain_db - 10))
        val_c = val_a + 0x41
        mask_buf = bytearray(128)
        value_buf = bytearray(128)
        off = (SETTING_PREAMP_CH0 + channel) * 8
        struct.pack_into('<I', value_buf, off, setting_word(0x00FF, val_a))
        struct.pack_into('<I', mask_buf, SETTING_GAIN_C * 8, setting_word(0x003F, val_c))
        self.write_settings(mask_buf, value_buf)


class SoloUsbMixerWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title='Open Apollo — Solo USB mixer')
        self.set_default_size(420, 520)
        self.mix = VendorMixer()
        self._connected = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_start(12)
        root.set_margin_end(12)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        self.add(root)

        self.status = Gtk.Label(label='Non connecté — branche l’Apollo Solo USB (USB 3).')
        self.status.set_line_wrap(True)
        root.pack_start(self.status, False, False, 0)

        btn = Gtk.Button(label='Reconnecter')
        btn.connect('clicked', self.on_reconnect)
        root.pack_start(btn, False, False, 0)

        # --- Preamps ---
        for ch in (0, 1):
            f = Gtk.Frame(label=f'Entrée {ch + 1}')
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            f.add(vb)

            g48 = Gtk.CheckButton(label='48 V phantom')
            g48.connect('toggled', self._mk_phantom, ch)
            vb.pack_start(g48, False, False, 0)
            setattr(self, f'phantom_{ch}', g48)

            gml = Gtk.CheckButton(label='Entrée ligne (sinon micro)')
            gml.connect('toggled', self._mk_line, ch)
            vb.pack_start(gml, False, False, 0)
            setattr(self, f'line_{ch}', gml)

            gpad = Gtk.CheckButton(label='PAD (atténuation) — bit expérimental')
            gpad.connect('toggled', self._mk_pad, ch)
            vb.pack_start(gpad, False, False, 0)
            setattr(self, f'pad_{ch}', gpad)

            glc = Gtk.CheckButton(label='Low-cut (passe-haut) — bit expérimental')
            glc.connect('toggled', self._mk_lowcut, ch)
            vb.pack_start(glc, False, False, 0)
            setattr(self, f'lowcut_{ch}', glc)

            adj = Gtk.Adjustment(value=30, lower=10, upper=60, step_increment=1, page_increment=5, page_size=0)
            sc = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
            sc.set_digits(0)
            sc.add_mark(10, Gtk.PositionType.BOTTOM, '10')
            sc.add_mark(60, Gtk.PositionType.BOTTOM, '60')
            sc.connect('value-changed', self._mk_gain, ch)
            vb.pack_start(Gtk.Label(label='Gain preamp (dB)'), False, False, 0)
            vb.pack_start(sc, False, False, 0)
            setattr(self, f'gain_{ch}', sc)

            root.pack_start(f, False, False, 0)

        # --- Monitor (casque / mix micro + lecture) ---
        mon = Gtk.Frame(label='Monitor (casque — niveau matériel USB)')
        mv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        mon.add(mv)

        madj = Gtk.Adjustment(value=-12, lower=-96, upper=0, step_increment=1, page_increment=6, page_size=0)
        msc = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=madj)
        msc.set_digits(0)
        msc.connect('value-changed', self._on_monitor_db)
        mv.pack_start(Gtk.Label(label='Niveau (dB)'), False, False, 0)
        mv.pack_start(msc, False, False, 0)
        self.monitor_scale = msc

        gmute = Gtk.CheckButton(label='Muet')
        gmute.connect('toggled', self._on_monitor_mute_mono)
        mv.pack_start(gmute, False, False, 0)
        self.monitor_mute = gmute

        gmono = Gtk.CheckButton(label='Mono')
        gmono.connect('toggled', self._on_monitor_mute_mono)
        mv.pack_start(gmono, False, False, 0)
        self.monitor_mono = gmono

        root.pack_start(mon, False, False, 0)

        note = Gtk.Label(
            label='Le « master » logiciel (DAW / volume OS) est séparé : ici c’est le\n'
            'monitor USB hardware. Le son système passe encore par PipeWire.'
        )
        note.set_line_wrap(True)
        note.get_style_context().add_class('dim-label')
        root.pack_start(note, False, False, 0)

        GLib.idle_add(self.on_reconnect, None)

    def _guard(self):
        if not self._connected:
            return False
        return True

    def on_reconnect(self, _widget=None):
        try:
            if self.mix.find():
                self._connected = True
                self.status.set_label('Connecté — Apollo Solo USB (contrôles vendor EP0).')
                self.set_sensitive(True)
            else:
                self._connected = False
                self.status.set_label(
                    'Apollo Solo USB introuvable (VID 2B5A / PID 000D). USB branché ?'
                )
        except usb.core.USBError as e:
            self._connected = False
            self.status.set_label(f'USB: {e}\n(Essaye sudo ou règles udev plugdev.)')
        return False

    def _apply(self, fn, *args):
        if not self._guard():
            return
        try:
            fn(*args)
        except usb.core.USBError as e:
            dlg = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=str(e),
            )
            dlg.run()
            dlg.destroy()

    def _mk_phantom(self, w, ch):
        self._apply(self.mix.set_phantom, ch, w.get_active())

    def _mk_line(self, w, ch):
        self._apply(self.mix.set_mic_line, ch, w.get_active())

    def _mk_pad(self, w, ch):
        self._apply(self.mix.set_pad, ch, w.get_active())

    def _mk_lowcut(self, w, ch):
        self._apply(self.mix.set_low_cut, ch, w.get_active())

    def _mk_gain(self, w, ch):
        self._apply(self.mix.set_preamp_gain_db, ch, w.get_value())

    def _on_monitor_db(self, w):
        self._apply(self.mix.set_monitor_db, w.get_value())

    def _on_monitor_mute_mono(self, _w=None):
        self._apply(
            self.mix.set_monitor_flags,
            self.monitor_mute.get_active(),
            self.monitor_mono.get_active(),
        )


def main():
    w = SoloUsbMixerWindow()
    w.connect('destroy', Gtk.main_quit)
    w.show_all()
    Gtk.main()


if __name__ == '__main__':
    main()
