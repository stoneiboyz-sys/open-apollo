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

Friendly labels for the raw ALSA nodes (**Apollo Solo USB** instead of “Analog Surround 2.1”) are set by **WirePlumber Lua** rules that extend `alsa_monitor.rules`: `configs/wireplumber/main.lua.d/99-apollo-solo-usb.lua` → installed to `~/.config/wireplumber/main.lua.d/`. Older JSON snippets under `wireplumber.conf.d/` are **not** used by modern WirePlumber for ALSA matching — use the Lua file. Restart WirePlumber after editing.

## See also

- `filter-chain/apollo-io-map.conf` — static reference / alternate layout (Thunderbolt-oriented)
- `50-apollo-pulse-rules.conf` — PulseAudio bridge rules (system deploy)
