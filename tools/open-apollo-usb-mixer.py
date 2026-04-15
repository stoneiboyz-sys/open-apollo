#!/usr/bin/env python3
"""GTK 4 / Libadwaita mixer for Apollo Solo USB (vendor control on EP0 — no USB interface claim).

Controls preamp / monitor paths using the same 0x03 batch protocol as
tools/usb-mixer-test.py and mixer-engine/hardware_usb.py. PipeWire keeps working.

PAD / Low-cut use bit positions inferred from internal docs (stride order vs bits
may differ); if toggles do the wrong thing on your unit, file an issue with a USB
capture — 48V / Mic-Line / monitor level are the best-tested paths.

Usage:
  python3 tools/open-apollo-usb-mixer.py

Requires: pyusb, python3-gi, GTK 4, Libadwaita (gir1.2-gtk-4.0, gir1.2-adw-1).
USB access: plugdev/udev or run with sudo if needed.
"""

import struct
import sys

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk

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


class SoloUsbMixerWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title('Open Apollo — Solo USB mixer')
        self.set_default_size(480, 620)
        self.mix = VendorMixer()
        self._connected = False

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status_box.set_margin_start(18)
        status_box.set_margin_end(18)
        status_box.set_margin_top(14)
        self.status = Gtk.Label(
            label='Non connecté — branche l’Apollo Solo USB (USB 3).',
            xalign=0.0,
        )
        self.status.set_wrap(True)
        self.status.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        btn = Gtk.Button(label='Reconnecter')
        btn.connect('clicked', self.on_reconnect)
        status_box.append(self.status)
        status_box.append(btn)
        outer.append(status_box)

        page = Adw.PreferencesPage()

        for ch in (0, 1):
            grp = Adw.PreferencesGroup(title=f'Entrée {ch + 1}')
            sw48 = Adw.SwitchRow(title='48 V phantom')
            sw48.connect('notify::active', self._mk_phantom_sw, ch)
            grp.add(sw48)
            setattr(self, f'phantom_{ch}', sw48)

            swline = Adw.SwitchRow(title='Entrée ligne (sinon micro)')
            swline.connect('notify::active', self._mk_line_sw, ch)
            grp.add(swline)
            setattr(self, f'line_{ch}', swline)

            swpad = Adw.SwitchRow(
                title='PAD (atténuation)',
                subtitle='Bit expérimental — à valider sur ta carte',
            )
            swpad.connect('notify::active', self._mk_pad_sw, ch)
            grp.add(swpad)
            setattr(self, f'pad_{ch}', swpad)

            swlc = Adw.SwitchRow(
                title='Low-cut (passe-haut)',
                subtitle='Bit expérimental — à valider sur ta carte',
            )
            swlc.connect('notify::active', self._mk_lowcut_sw, ch)
            grp.add(swlc)
            setattr(self, f'lowcut_{ch}', swlc)

            adj = Gtk.Adjustment(
                value=30,
                lower=10,
                upper=60,
                step_increment=1,
                page_increment=5,
                page_size=0,
            )
            sc = Gtk.Scale(
                orientation=Gtk.Orientation.HORIZONTAL,
                adjustment=adj,
            )
            sc.set_digits(0)
            sc.set_draw_value(True)
            sc.set_hexpand(True)
            sc.set_width_request(200)
            sc.add_mark(10, Gtk.PositionType.BOTTOM, '10')
            sc.add_mark(60, Gtk.PositionType.BOTTOM, '60')
            sc.connect('value-changed', self._mk_gain, ch)
            gain_row = Adw.ActionRow(title='Gain preamp (dB)')
            gain_row.add_suffix(sc)
            gain_row.set_activatable(False)
            grp.add(gain_row)
            setattr(self, f'gain_{ch}', sc)

            page.add(grp)

        mon_grp = Adw.PreferencesGroup(
            title='Monitor — casque',
            description='Volume du retour Apollo (pas le master DAW).',
        )
        madj = Gtk.Adjustment(
            value=-12,
            lower=-96,
            upper=0,
            step_increment=1,
            page_increment=6,
            page_size=0,
        )
        msc = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=madj)
        msc.set_digits(0)
        msc.set_draw_value(True)
        msc.set_hexpand(True)
        msc.set_width_request(200)
        msc.connect('value-changed', self._on_monitor_db)
        mon_row = Adw.ActionRow(title='Niveau monitor (dB)')
        mon_row.add_suffix(msc)
        mon_row.set_activatable(False)
        mon_grp.add(mon_row)
        self.monitor_scale = msc

        sw_mute = Adw.SwitchRow(title='Muet')
        sw_mute.connect('notify::active', self._on_monitor_mute_mono)
        mon_grp.add(sw_mute)
        self.monitor_mute = sw_mute

        sw_mono = Adw.SwitchRow(title='Mono')
        sw_mono.connect('notify::active', self._on_monitor_mute_mono)
        mon_grp.add(sw_mono)
        self.monitor_mono = sw_mono

        page.add(mon_grp)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(560)
        clamp.set_child(page)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(clamp)
        outer.append(scroll)

        note = Gtk.Label(
            label='Le bus master du DAW (là où tout le mix part à la fin) ne se règle pas ici.\n'
            'Cette fenêtre ne fait que le monitor Apollo (casque / retour micro + lecture).',
            xalign=0.0,
        )
        note.set_wrap(True)
        note.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        note.add_css_class('dim-label')
        note.set_margin_start(18)
        note.set_margin_end(18)
        note.set_margin_top(10)
        note.set_margin_bottom(14)
        outer.append(note)

        toolbar.set_content(outer)
        self.set_content(toolbar)

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

    def _show_usb_error(self, message: str):
        dlg = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        dlg.connect('response', lambda d, *_: d.destroy())
        dlg.present()

    def _apply(self, fn, *args):
        if not self._guard():
            return
        try:
            fn(*args)
        except usb.core.USBError as e:
            self._show_usb_error(str(e))

    def _mk_phantom_sw(self, row, _pspec, ch):
        self._apply(self.mix.set_phantom, ch, row.get_active())

    def _mk_line_sw(self, row, _pspec, ch):
        self._apply(self.mix.set_mic_line, ch, row.get_active())

    def _mk_pad_sw(self, row, _pspec, ch):
        self._apply(self.mix.set_pad, ch, row.get_active())

    def _mk_lowcut_sw(self, row, _pspec, ch):
        self._apply(self.mix.set_low_cut, ch, row.get_active())

    def _mk_gain(self, w, ch):
        self._apply(self.mix.set_preamp_gain_db, ch, w.get_value())

    def _on_monitor_db(self, w):
        self._apply(self.mix.set_monitor_db, w.get_value())

    def _on_monitor_mute_mono(self, *_args):
        self._apply(
            self.mix.set_monitor_flags,
            self.monitor_mute.get_active(),
            self.monitor_mono.get_active(),
        )


class OpenApolloUsbMixerApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id='org.openapollo.UsbMixer',
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._win = None

    def do_activate(self):
        if self._win is None:
            self._win = SoloUsbMixerWindow(application=self)
        self._win.present()


def main():
    return OpenApolloUsbMixerApp().run(sys.argv)


if __name__ == '__main__':
    raise SystemExit(main())
