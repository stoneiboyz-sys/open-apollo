-- Open Apollo — Apollo Solo USB (snd_usb_audio)
-- Install to: ~/.config/wireplumber/main.lua.d/99-apollo-solo-usb.lua
--
-- WirePlumber applies ALSA monitor rules from Lua (see /usr/share/wireplumber/main.lua.d/50-alsa-config.lua).
-- JSON snippets in wireplumber.conf.d are NOT used for alsa_monitor.rules on modern setups.
-- This file runs after 50-alsa-config.lua and appends rules so node.nick / node.description
-- override the default "Analog Surround 2.1" profile label in Plasma / pavucontrol.

if not alsa_monitor or not alsa_monitor.rules then
  return
end

table.insert(alsa_monitor.rules, {
  matches = {
    {
      { "device.name", "matches", "alsa_card.*Apollo_Solo_USB.*" },
    },
  },
  apply_properties = {
    ["device.profile"] = "output:analog-surround-21+input:analog-surround-21",
    ["device.nick"] = "Apollo Solo USB",
    ["device.description"] = "Apollo Solo USB",
  },
})

table.insert(alsa_monitor.rules, {
  matches = {
    {
      { "node.name", "matches", "alsa_output.*Apollo_Solo_USB.*" },
    },
  },
  apply_properties = {
    ["session.suspend-timeout-seconds"] = 0,
    ["node.pause-on-idle"] = false,
    ["node.nick"] = "Apollo Solo USB",
    ["node.description"] = "Apollo Solo USB",
  },
})

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
  },
})
