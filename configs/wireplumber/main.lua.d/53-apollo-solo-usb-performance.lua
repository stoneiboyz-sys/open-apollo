-- Open Apollo — Apollo Solo USB: ALSA buffer (period + headroom)
-- Install: ~/.config/wireplumber/main.lua.d/53-apollo-solo-usb-performance.lua
--
-- Change these when you need lower latency (smaller period) or fewer xruns (larger).
-- Very small PERIOD_SIZE (e.g. 16–32) can cause USB xruns; raise if audio glitches.
-- This is separate from PipeWire graph quantum (default.clock.*); see configs/pipewire/README.md
--
-- After editing: systemctl --user restart wireplumber pipewire

local PERIOD_SIZE = 512
local PERIOD_NUM = 64
local HEADROOM = 512

if alsa_monitor == nil or alsa_monitor.rules == nil then
  Log.warning("open-apollo: 53-apollo-solo-usb-performance.lua skipped (alsa_monitor not ready)")
  return
end

table.insert(alsa_monitor.rules, {
  matches = {
    {
      { "device.name", "matches", "alsa_card.*Apollo_Solo_USB.*" },
    },
  },
  apply_properties = {
    ["api.alsa.period-size"] = PERIOD_SIZE,
    ["api.alsa.period-num"] = PERIOD_NUM,
    ["api.alsa.headroom"] = HEADROOM,
  },
})
