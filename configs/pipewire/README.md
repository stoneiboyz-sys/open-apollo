# Open Apollo — PipeWire I/O

This folder defines **virtual I/O** (named PipeWire sources/sinks) built with
`libpipewire-module-loopback` on top of the **raw ALSA pro-audio / multichannel**
nodes.

Two stacks exist on purpose — **do not merge their configs**:

| Track | Hardware | Script | Generated config | When it runs |
|-------|----------|--------|------------------|--------------|
| **Base card (USB)** | Apollo Solo USB | `setup-apollo-solo-usb.sh` | `~/.config/pipewire/pipewire.conf.d/apollo-solo-usb-io.conf` | After firmware + `snd_usb_audio`; invoked by `apollo-safe-start.sh` and `install-usb.sh` (stable). |
| **Thunderbolt** | Apollo x4 (and `ua_apollo` driver) | `setup-apollo-io.sh` | `~/.config/pipewire/pipewire.conf.d/apollo-io-map.conf` | After driver load; often installed as `apollo-setup-io` (see `configs/deploy.sh`). |

## Single entry point (optional)

Use **`open-apollo-setup-io.sh`** to pick the right script automatically:

- Apollo Solo USB present → runs `setup-apollo-solo-usb.sh`
- `ua_apollo` Thunderbolt device present → runs `setup-apollo-io.sh`
- Neither → exits with a short message

```bash
bash configs/pipewire/open-apollo-setup-io.sh
```

Scope and priority (**base vs DSP**) are documented in the root [README.md](../../README.md) under **USB project scope**.

## Generated files

Regenerated on each successful run — **do not edit by hand**; fix the generator scripts instead.

## Display names (USB, Plasma / pavucontrol)

Friendly labels for the raw ALSA nodes (**Apollo Solo USB** instead of “Analog Surround 2.1”) are applied by WirePlumber:

- **Lua (0.4.x and up):** `configs/wireplumber/main.lua.d/52-apollo-solo-usb-names.lua` → `~/.config/wireplumber/main.lua.d/`
- **SPA-JSON merge (0.5+):** `configs/wireplumber/wireplumber.conf.d/98-apollo-solo-usb-display.conf` → `~/.config/wireplumber/wireplumber.conf.d/`

Restart WirePlumber after editing. If names do not change, check `journalctl --user -u wireplumber.service` for Lua errors and run `wpctl status` / `wpctl inspect <id>` to confirm `node.name` still contains `Universal_Audio_Inc_Apollo_Solo_USB`.

**Note:** `pactl list short sinks` shows the **sink Name** (the stable PipeWire id string) — it will stay long. Check the human label with `pactl list sinks` (look for `Description:`) or `wpctl inspect <id>` for `node.description` / `node.nick`.

## Buffer size (Apollo Solo USB)

**ALSA-side buffer** (what you usually tweak for latency vs xruns) is set in WirePlumber `alsa_monitor` rules on the USB card. Edit the three locals at the top of `configs/wireplumber/main.lua.d/53-apollo-solo-usb-performance.lua` (installed to `~/.config/wireplumber/main.lua.d/`), then:

`systemctl --user restart wireplumber pipewire`

Defaults: `period-size` 512, `period-num` 64, `headroom` 512. Smaller `PERIOD_SIZE` → lower latency, more risk of underruns; larger → the opposite. After `install-usb.sh`, the session tray (`tools/open-apollo-tray.py`) can change the USB period from the menu. Autostart is registered when AppIndicator is present at install time; if you installed `gir1.2-appindicator3-0.1` later, run **`bash scripts/install-open-apollo-tray-autostart.sh`** as your user (no sudo), then log out/in.

**Graph quantum** (PipeWire-wide processing buffer, not the same as ALSA period) lives in `~/.config/pipewire/pipewire.conf.d/*.conf` via `default.clock.*` — see [PipeWire clock docs](https://docs.pipewire.org/page_daemon_conf.html). Sample-rate notes (mostly Thunderbolt) are in [sample-rates](../docs/sample-rates/page.md).

Inspect what is applied on the sink:

```bash
wpctl status   # id for Apollo Solo USB sink
wpctl inspect ID
# e.g. api.alsa.period-size, api.alsa.period-num, api.alsa.headroom
```

## See also

- `filter-chain/apollo-io-map.conf` — static reference / alternate layout (Thunderbolt-oriented)
- `50-apollo-pulse-rules.conf` — PulseAudio bridge rules (system deploy)
