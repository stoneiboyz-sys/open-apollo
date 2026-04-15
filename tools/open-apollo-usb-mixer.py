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

from __future__ import annotations

import sys

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk, Pango

try:
    import usb.core
except ImportError:
    print('Install pyusb: pip install pyusb', file=sys.stderr)
    sys.exit(1)

from open_apollo import APP_ID_USB_MIXER
from open_apollo.solo_usb_vendor_mixer import VendorEp0Mixer


class SoloUsbMixerWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title('Open Apollo — Solo USB mixer')
        self.set_default_size(480, 680)
        self.mix = VendorEp0Mixer()
        self._connected = False

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_vexpand(True)
        self._toast_overlay.set_hexpand(True)

        toolbar = Adw.ToolbarView()
        toolbar.set_vexpand(True)
        toolbar.set_hexpand(True)
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_vexpand(True)
        outer.set_hexpand(True)

        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status_box.set_margin_start(18)
        status_box.set_margin_end(18)
        status_box.set_margin_top(14)
        self.status = Gtk.Label(
            label='Non connecté — branche l’Apollo Solo USB (USB 3).',
            xalign=0.0,
        )
        self.status.set_wrap(True)
        self.status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
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
            sc.set_size_request(200, -1)
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
        msc.set_size_request(200, -1)
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
        scroll.set_hexpand(True)
        scroll.set_kinetic_scrolling(True)
        scroll.set_propagate_natural_height(False)
        scroll.set_child(clamp)
        outer.append(scroll)

        note = Gtk.Label(
            label='Le bus master du DAW (là où tout le mix part à la fin) ne se règle pas ici.\n'
            'Cette fenêtre ne fait que le monitor Apollo (casque / retour micro + lecture).',
            xalign=0.0,
        )
        note.set_wrap(True)
        note.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        note.add_css_class('dim-label')
        note.set_margin_start(18)
        note.set_margin_end(18)
        note.set_margin_top(10)
        note.set_margin_bottom(14)
        outer.append(note)

        toolbar.set_content(outer)
        self._toast_overlay.set_child(toolbar)
        self.set_content(self._toast_overlay)

        GLib.idle_add(self.on_reconnect, None)

    def _toast_usb_error(self, message: str) -> None:
        text = f'USB : {message}'
        if len(text) > 200:
            text = text[:197] + '…'
        toast = Adw.Toast.new(text)
        toast.set_timeout(6)
        self._toast_overlay.add_toast(toast)

    def _guard(self) -> bool:
        return self._connected

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
            self._toast_usb_error(str(e))

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
            application_id=APP_ID_USB_MIXER,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._win: SoloUsbMixerWindow | None = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)

    def do_activate(self):
        if self._win is None:
            self._win = SoloUsbMixerWindow(application=self)
        self._win.present()


def main():
    return OpenApolloUsbMixerApp().run(sys.argv)


if __name__ == '__main__':
    raise SystemExit(main())
