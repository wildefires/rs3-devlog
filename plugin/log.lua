-- rs3-devlog managed file: keep this line. tools/deploy.py --upgrade only replaces files that start with it.
-- log.lua: debug logging for development, which does nothing in the released plugin.
--
-- The developer keeps a second file, devlog.lua, in their local development copy only. It is NOT
-- part of the released plugin (not in the zip submitted for moderation), so in every release the
-- `require` below fails and this file hands back a logger whose `log` does nothing at all.
--
-- When devlog.lua is present (development only) it prints debug lines to the in-game console and
-- can keep them in this plugin's own PersistentDB or send them to a local log server, as io and os
-- aren't present in the RuneScape Lua interpreter.
--
-- Nothing is downloaded or loaded from outside the plugin: `require` only looks for a file in this
-- plugin's own folder. `pcall` is used only so that the missing file in a release is not an error.
---@class Log
---@field log fun(topic: string, fmt: string, ...: any)
local ok, DevLog = pcall(require, "devlog")

-- Development copy: devlog.lua was found, so other modules log through it.
if ok and DevLog then return DevLog --[[@as Log]] end

-- devlog.lua exists but failed to load (a bug in the development copy): say so, rather than
-- silently losing the debug output. In a release the file is simply missing ("not found"),
-- which is expected, so nothing is printed.
if not ok and not tostring(DevLog):find("not found", 1, true) then
  print("devlog failed to load: " .. tostring(DevLog))
end

-- Release (and the fallback above): a logger whose calls do nothing.
return { log = function() end } --[[@as Log]]
