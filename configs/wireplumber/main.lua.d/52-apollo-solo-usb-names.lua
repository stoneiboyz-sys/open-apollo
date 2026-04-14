-- Open Apollo — Apollo Solo USB: friendly names in Plasma / pavucontrol
-- Install: ~/.config/wireplumber/main.lua.d/52-apollo-solo-usb-names.lua
--
-- Same pattern as a working user rule (table.insert + apply_properties).
-- Match on the stable part of node.name (USB path varies: Undefined-01, etc.).

if alsa_monitor == nil or alsa_monitor.rules == nil then
  -- If this ever prints, main.lua.d ran before 50-alsa-config.lua (unlikely).
  Log.warning("open-apollo: 52-apollo-solo-usb-names.lua skipped (alsa_monitor not ready)")
else
  -- Playback: raw ALSA sink (analog-surround-21 profile)
  table.insert(alsa_monitor.rules, {
    matches = {
      {
        -- Same style as stock rules: "matches" is a regex; avoid over-escaping.
        { "node.name", "matches", "alsa_output.*Apollo_Solo_USB.*" },
      },
    },
    apply_properties = {
      ["session.suspend-timeout-seconds"] = 0,
      ["node.pause-on-idle"] = false,
      ["node.nick"] = "Apollo Solo USB",
      ["node.description"] = "Apollo Solo USB",
      ["media.name"] = "Apollo Solo USB",
    },
  })

  -- Capture
  table.insert(alsa_monitor.rules, {
    matches = {
      {
        { "node.name", "matches", "alsa_input.*Apollo_Solo_USB.*" },
      },
    },
    apply_properties = {
      ["session.suspend-timeout-seconds"] = 0,
      ["node.pause-on-idle"] = false,
      ["node.nick"] = "Apollo Solo USB",
      ["node.description"] = "Apollo Solo USB",
      ["media.name"] = "Apollo Solo USB",
    },
  })

  -- ALSA card (labels in some UIs)
  table.insert(alsa_monitor.rules, {
    matches = {
      {
        { "device.name", "matches", "alsa_card.*Apollo_Solo_USB.*" },
      },
    },
    apply_properties = {
      ["device.nick"] = "Apollo Solo USB",
      ["device.description"] = "Apollo Solo USB",
    },
  })
end
