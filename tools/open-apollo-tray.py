#!/usr/bin/env python3
"""Open Apollo system tray indicator.

Thunderbolt: hardware + daemon status, init, PipeWire profile reload.
USB (Apollo Solo USB): plug-in / PipeWire readiness + ALSA period (buffer)
from the WirePlumber drop-in (53-apollo-solo-usb-performance.lua).

Dependencies: gir1.2-appindicator3-0.1 (Ubuntu) or libappindicator-gtk3 (Fedora)
"""

import json
import os
import re
import shutil
import signal
import struct
import fcntl
import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
from gi.repository import Gtk, GLib, AppIndicator3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ICON_DIR = os.path.join(SCRIPT_DIR, 'icons')
DEVICE_PATH = '/dev/ua_apollo0'
DAEMON_LOG = '/tmp/ua-mixer-daemon.log'
POLL_INTERVAL = 5  # seconds

WP_PERF_BASENAME = '53-apollo-solo-usb-performance.lua'
# Powers of two; 16–32 are very aggressive on USB (xruns / dropouts) but useful for min latency experiments.
BUFFER_PRESETS = (16, 32, 64, 128, 256, 512, 1024, 2048)
PERIOD_SIZE_RE = re.compile(r'^(local PERIOD_SIZE = )(\d+)(\s*)$', re.MULTILINE)

# Ioctl numbers for BAR0 register read (Thunderbolt)
IOCTL_REG_READ = (3 << 30) | (ord('U') << 8) | 0x10 | (8 << 16)


def xdg_config_home():
    return os.environ.get('XDG_CONFIG_HOME') or os.path.join(
        os.path.expanduser('~'), '.config'
    )


def wireplumber_perf_lua_path():
    return os.path.join(
        xdg_config_home(), 'wireplumber', 'main.lua.d', WP_PERF_BASENAME
    )


def bundled_perf_lua_path():
    return os.path.join(
        REPO_ROOT, 'configs', 'wireplumber', 'main.lua.d', WP_PERF_BASENAME
    )


class ApolloState:
    """Snapshot of Apollo Thunderbolt hardware + daemon state."""

    def __init__(self):
        self.driver_loaded = False
        self.device_exists = False
        self.pcie_alive = False
        self.dsp_alive = False
        self.seq_wr = 0
        self.seq_rd = 0
        self.daemon_running = False
        self.daemon_pid = None
        self.device_name = 'Apollo'

    @property
    def icon_name(self):
        if not self.driver_loaded or not self.device_exists:
            return 'apollo-gray'
        if not self.pcie_alive:
            return 'apollo-red'
        if not self.dsp_alive or not self.daemon_running:
            return 'apollo-yellow'
        return 'apollo-green'


class UsbAudioState:
    """Apollo Solo USB: ALSA card + PipeWire device visibility."""

    def __init__(self):
        self.card_present = False
        self.pipewire_ready = False

    @property
    def stable(self):
        return self.card_present and self.pipewire_ready

    @property
    def icon_name(self):
        if not self.card_present:
            return 'apollo-gray'
        if not self.pipewire_ready:
            return 'apollo-yellow'
        return 'apollo-green'


def read_register(fd, offset):
    """Read a BAR0 register via ioctl."""
    buf = struct.pack('II', offset, 0)
    result = fcntl.ioctl(fd, IOCTL_REG_READ, buf)
    return struct.unpack('II', result)[1]


def poll_usb_audio_state():
    """Detect Apollo Solo USB ALSA card and PipeWire enumeration."""
    st = UsbAudioState()
    try:
        with open('/proc/asound/cards') as f:
            st.card_present = 'Apollo Solo USB' in f.read()
    except OSError:
        pass

    if st.card_present:
        st.pipewire_ready = _usb_pipewire_ready()
    return st


def _usb_pipewire_ready():
    """True if PipeWire lists the Solo USB ALSA device (same idea as apollo-safe-start.sh)."""
    try:
        r = subprocess.run(
            ['wpctl', 'status'],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if 'Apollo Solo USB' in line and '[alsa]' in line:
                    return True
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        r = subprocess.run(
            ['pw-dump'],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if r.returncode != 0:
            return False
        objs = json.loads(r.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False

    for obj in objs:
        if obj.get('type') != 'PipeWire:Interface:Device':
            continue
        props = obj.get('info', {}).get('props', {})
        name = props.get('alsa.card_name', '') or props.get('api.alsa.card.name', '')
        if 'Apollo Solo USB' in str(name):
            return True
    return False


def poll_state():
    """Check Apollo Thunderbolt hardware and daemon state."""
    state = ApolloState()

    try:
        with open('/proc/modules') as f:
            state.driver_loaded = 'ua_apollo' in f.read()
    except OSError:
        pass

    state.device_exists = os.path.exists(DEVICE_PATH)

    if state.device_exists:
        try:
            fd = os.open(DEVICE_PATH, os.O_RDWR)
            try:
                reg0 = read_register(fd, 0x0000)
                state.pcie_alive = reg0 != 0xFFFFFFFF

                if state.pcie_alive:
                    dev_type = read_register(fd, 0x000C)
                    state.seq_wr = read_register(fd, 0x3808)
                    state.seq_rd = read_register(fd, 0x380C)
                    state.dsp_alive = (
                        state.seq_wr == state.seq_rd and state.seq_wr > 0
                    )
                    names = {
                        0x1F: 'Apollo x4', 0x1E: 'Apollo x6',
                        0x14: 'Apollo x8', 0x15: 'Apollo x8p',
                        0x10: 'Apollo x16', 0x20: 'Apollo Twin X',
                        0x21: 'Apollo Solo',
                    }
                    state.device_name = names.get(dev_type, f'Apollo (0x{dev_type:02X})')
            finally:
                os.close(fd)
        except OSError:
            pass

    try:
        result = subprocess.run(
            ['pgrep', '-f', 'ua_mixer_daemon'], capture_output=True
        )
        if result.returncode == 0:
            state.daemon_running = True
            state.daemon_pid = result.stdout.decode().strip().split('\n')[0]
    except OSError:
        pass

    return state


def read_usb_period_size():
    """Return configured PERIOD_SIZE from the WirePlumber Lua drop-in, or None."""
    path = wireplumber_perf_lua_path()
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return None
    m = PERIOD_SIZE_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(2))
    except ValueError:
        return None


def ensure_perf_lua_file():
    """Ensure ~/.config/.../53-*.lua exists (copy from repo if missing)."""
    dst = wireplumber_perf_lua_path()
    if os.path.isfile(dst):
        return dst
    src = bundled_perf_lua_path()
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isfile(src):
        shutil.copy2(src, dst)
        return dst
    raise FileNotFoundError(
        f'Missing {WP_PERF_BASENAME}: install USB configs or run install-usb.sh'
    )


def write_usb_period_size(new_size: int):
    """Set PERIOD_SIZE in the Lua file and restart PipeWire + WirePlumber."""
    if new_size not in BUFFER_PRESETS:
        raise ValueError('Unsupported period size')
    path = ensure_perf_lua_file()
    with open(path, encoding='utf-8') as f:
        text = f.read()
    if not PERIOD_SIZE_RE.search(text):
        raise ValueError('Could not find local PERIOD_SIZE line to replace')
    new_text, n = PERIOD_SIZE_RE.subn(
        lambda m: f'{m.group(1)}{new_size}{m.group(3)}',
        text,
        count=1,
    )
    if n != 1:
        raise ValueError('PERIOD_SIZE replace failed')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(new_text)
    os.replace(tmp, path)

    r = subprocess.run(
        ['systemctl', '--user', 'restart', 'pipewire', 'wireplumber'],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            (r.stderr or r.stdout or '') or 'systemctl --user restart pipewire wireplumber failed'
        )

    subprocess.run(
        [
            'notify-send', '-a', 'Open Apollo', 'ALSA buffer',
            f'Period size set to {new_size} frames (PipeWire restarted).',
        ],
        capture_output=True,
    )


class ApolloTray:
    """System tray indicator for Open Apollo."""

    def __init__(self):
        self.state = ApolloState()
        self.usb_state = UsbAudioState()
        self._ignoring_buffer_toggle = False
        self.indicator = AppIndicator3.Indicator.new(
            'open-apollo',
            os.path.join(ICON_DIR, 'apollo-gray'),
            AppIndicator3.IndicatorCategory.HARDWARE
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_icon_theme_path(ICON_DIR)
        self.indicator.set_title('Open Apollo')
        self.build_menu()
        self.update()
        GLib.timeout_add_seconds(POLL_INTERVAL, self.update)

    def build_menu(self):
        """Build the GTK menu."""
        self.menu = Gtk.Menu()

        self.lbl_device = Gtk.MenuItem(label='Apollo: checking...')
        self.lbl_device.set_sensitive(False)
        self.menu.append(self.lbl_device)

        self.lbl_dsp = Gtk.MenuItem(label='DSP: checking...')
        self.lbl_dsp.set_sensitive(False)
        self.menu.append(self.lbl_dsp)

        self.lbl_daemon = Gtk.MenuItem(label='Daemon: checking...')
        self.lbl_daemon.set_sensitive(False)
        self.menu.append(self.lbl_daemon)

        self.menu.append(Gtk.SeparatorMenuItem())

        # USB buffer submenu
        self.item_buffer = Gtk.MenuItem(label='Buffer size (USB)…')
        self.buffer_submenu = Gtk.Menu()
        self.buffer_radios = {}
        leader = None
        for sz in BUFFER_PRESETS:
            label = f'{sz} frames'
            if sz < 64:
                label += ' — may xrun'
            elif sz == 512:
                label += ' — default'
            if leader is None:
                mi = Gtk.RadioMenuItem(label=label)
                leader = mi
            else:
                mi = Gtk.RadioMenuItem.new_with_label_from_widget(leader, label)
            mi.connect('toggled', self.on_usb_buffer_toggled, sz)
            self.buffer_submenu.append(mi)
            self.buffer_radios[sz] = mi
        self.item_buffer.set_submenu(self.buffer_submenu)
        self.menu.append(self.item_buffer)

        self.menu.append(Gtk.SeparatorMenuItem())

        item_init = Gtk.MenuItem(label='Initialize Apollo…')
        item_init.connect('activate', self.on_init)
        self.item_init = item_init
        self.menu.append(item_init)

        item_restart = Gtk.MenuItem(label='Restart Daemon')
        item_restart.connect('activate', self.on_restart_daemon)
        self.item_restart = item_restart
        self.menu.append(item_restart)

        item_stop = Gtk.MenuItem(label='Stop Daemon')
        item_stop.connect('activate', self.on_stop_daemon)
        self.item_stop = item_stop
        self.menu.append(item_stop)

        item_pipewire = Gtk.MenuItem(label='Reload PipeWire profile')
        item_pipewire.connect('activate', self.on_reload_pipewire)
        self.menu.append(item_pipewire)

        self.menu.append(Gtk.SeparatorMenuItem())

        item_log = Gtk.MenuItem(label='Open daemon log')
        item_log.connect('activate', self.on_open_log)
        self.item_log = item_log
        self.menu.append(item_log)

        item_quit = Gtk.MenuItem(label='Quit')
        item_quit.connect('activate', self.on_quit)
        self.menu.append(item_quit)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def _tb_active(self):
        return self.state.driver_loaded and self.state.device_exists

    def _usb_menu_relevant(self):
        return self.usb_state.card_present or os.path.isfile(wireplumber_perf_lua_path())

    def sync_buffer_radios(self):
        cur = read_usb_period_size()
        if cur is None:
            cur = 512
        if cur not in self.buffer_radios:
            cur = min(self.buffer_radios.keys(), key=lambda x: abs(x - cur))
        self._ignoring_buffer_toggle = True
        try:
            for sz, w in self.buffer_radios.items():
                w.set_active(sz == cur)
        finally:
            self._ignoring_buffer_toggle = False

    def update(self):
        """Poll state and update UI."""
        self.state = poll_state()
        self.usb_state = poll_usb_audio_state()
        tb = self._tb_active()
        usb = self.usb_state

        if tb:
            self.indicator.set_icon(self.state.icon_name)
        else:
            self.indicator.set_icon(usb.icon_name)

        if tb:
            s = self.state
            if not s.driver_loaded:
                self.lbl_device.set_label('Driver: not loaded')
            elif not s.device_exists:
                self.lbl_device.set_label(f'{s.device_name}: disconnected')
            elif not s.pcie_alive:
                self.lbl_device.set_label(f'{s.device_name}: PCIe dead — power cycle')
            else:
                self.lbl_device.set_label(f'{s.device_name}: connected')

            if not s.device_exists:
                self.lbl_dsp.set_label('DSP: —')
            elif not s.pcie_alive:
                self.lbl_dsp.set_label('DSP: PCIe link down')
            elif s.dsp_alive:
                self.lbl_dsp.set_label(f'DSP: alive (SEQ: {s.seq_wr})')
            elif s.seq_wr == 0:
                self.lbl_dsp.set_label('DSP: not initialized')
            else:
                self.lbl_dsp.set_label(f'DSP: stalled (WR={s.seq_wr} RD={s.seq_rd})')

            if s.daemon_running:
                self.lbl_daemon.set_label(f'Daemon: running (PID {s.daemon_pid})')
            else:
                self.lbl_daemon.set_label('Daemon: stopped')

            for w in (
                self.lbl_dsp, self.lbl_daemon, self.item_init,
                self.item_restart, self.item_stop, self.item_log,
            ):
                w.set_visible(True)
        else:
            if usb.card_present and usb.pipewire_ready:
                ps = read_usb_period_size()
                extra = f' — buffer {ps} frames' if ps else ''
                self.lbl_device.set_label(f'Apollo Solo USB: ready{extra}')
            elif usb.card_present:
                self.lbl_device.set_label('Apollo Solo USB: card seen, waiting for PipeWire…')
            else:
                self.lbl_device.set_label('Apollo Solo USB: not connected')

            for w in (
                self.lbl_dsp, self.lbl_daemon, self.item_init,
                self.item_restart, self.item_stop, self.item_log,
            ):
                w.set_visible(False)

        show_usb_buffer = self._usb_menu_relevant()
        self.item_buffer.set_visible(show_usb_buffer)
        self.item_buffer.set_sensitive(show_usb_buffer)
        if show_usb_buffer:
            self.sync_buffer_radios()

        return True  # Keep timer alive

    def run_sudo(self, cmd):
        """Run a command with pkexec for graphical sudo."""
        try:
            subprocess.Popen(['pkexec'] + cmd)
        except OSError as e:
            self.show_error(f'Failed to run command: {e}')

    def show_error(self, msg):
        """Show a simple error dialog."""
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=msg
        )
        dialog.run()
        dialog.destroy()

    def on_usb_buffer_toggled(self, widget, size):
        if self._ignoring_buffer_toggle:
            return
        if not widget.get_active():
            return
        cur = read_usb_period_size()
        if cur == size:
            return
        try:
            write_usb_period_size(size)
        except Exception as e:
            self.show_error(f'Could not set buffer size: {e}')
            self.sync_buffer_radios()

    def on_init(self, _):
        init_script = os.path.join(REPO_ROOT, 'tools', 'apollo-init.sh')
        if os.path.exists(init_script):
            self.run_sudo(['bash', init_script])
        else:
            self.show_error(f'Init script not found: {init_script}')

    def on_restart_daemon(self, _):
        self.run_sudo([
            'bash', '-c',
            'pkill -f ua_mixer_daemon 2>/dev/null; sleep 1; '
            f'cd {REPO_ROOT}/mixer-engine && '
            f'nohup python3 ua_mixer_daemon.py > {DAEMON_LOG} 2>&1 &'
        ])

    def on_stop_daemon(self, _):
        self.run_sudo(['pkill', '-f', 'ua_mixer_daemon'])

    def on_reload_pipewire(self, _):
        """Re-run apollo-setup-io to recreate virtual devices."""
        subprocess.Popen(['apollo-setup-io'])

    def on_open_log(self, _):
        if os.path.exists(DAEMON_LOG):
            subprocess.Popen(['xdg-open', DAEMON_LOG])
        else:
            self.show_error(f'Log not found: {DAEMON_LOG}')

    def on_quit(self, _):
        Gtk.main_quit()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Allow Ctrl+C
    ApolloTray()
    Gtk.main()


if __name__ == '__main__':
    main()
