-- main.lua: a bare plugin that only logs, to show and test devlog.lua.
local Log = require("log")

-- Event.Logic runs at a fixed 50 ticks per second, so this is 10 seconds.
local HEARTBEAT_TICKS = 500
local ticks, beats = 0, 0

-- Logs whether httpAccess is granted now and whenever a grant changes. The event's `enabled` has
-- been seen reading true on revokes, so HasPermission is logged next to it.
Log.log("startup", "httpAccess=%s", tostring(Plugin.HasPermission(PluginPermissions.httpAccess)))

Event.OptionalPermissionChanged.Subscribe("devlog-example", function(e)
  Log.log("startup", "permission %s changed: enabled=%s, HasPermission=%s", tostring(e.permissionName),
    tostring(e.enabled), tostring(Plugin.HasPermission(PluginPermissions.httpAccess)))
end)

-- A line every 10 seconds, so there is always something arriving to check a sink with.
Event.Logic.Subscribe("devlog-example", function()
  ticks = ticks + 1
  if ticks < HEARTBEAT_TICKS then return end
  ticks, beats = 0, beats + 1
  Log.log("heartbeat", "beat %d, httpAccess=%s", beats, tostring(Plugin.HasPermission(PluginPermissions.httpAccess)))
end)

-- Global on purpose: the client looks this function up by name.
function PluginShutdown()
  Event.OptionalPermissionChanged.Unsubscribe("devlog-example")
  Event.Logic.Unsubscribe("devlog-example")
end
