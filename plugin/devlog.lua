-- rs3-devlog managed file: keep this line. tools/deploy.py --upgrade only replaces files that start with it.
-- devlog.lua: Local logging. Do not ship this code in your final released zip file.
-- Set up with the below variables (TO_CONSOLE, TO_DB, TO_SERVER). Any combination of the three should work.
-- If using TO_SERVER, httpAccess will be needed. TO_DB and TO_SERVER both work best with ../tools/logviewer.py running
-- (TO_SERVER explicitly won't work without it)
--
-- Never ship this file: leave it out of the release zip, and log.lua falls back to no-ops without it.

---@class DevLog
local DevLog = {}

-- This plugin's dev name: the console prefix and the name the log server files lines under.
-- tools/deploy.py sets it to the plugin's dev_plugins folder name.
DevLog.NAME = "devlog-example"

-- Where lines go. Each can be on or off. Log server status messages always print to the console.
---@type boolean
DevLog.TO_CONSOLE = true
---@type boolean
DevLog.TO_DB = true
-- Needs `python3 tools/logviewer.py` running and httpAccess granted (README "Server route").
-- The server also appends every line to logs/plugin.log. A line that can't be sent goes nowhere else.
---@type boolean
DevLog.TO_SERVER = true

-- Per-topic switches: a topic logs only when set to true here (or at runtime).
DevLog.TOPICS = { startup = true, heartbeat = true }

-- Keep only the last MAX_LINES lines: every line is a DB row, and plugins may iterate their entries.
local MAX_LINES = 2000
local seq = PersistentDB:GetInt("log:next") or 0
local pending = {} -- in-flight requests, kept referenced until they finish
local serverStatus

-- Stores line number n, deleting the row MAX_LINES older.
local function toDB(n, line)
  PersistentDB:SetString(string.format("log:%06d", n), line)
  if n - MAX_LINES >= 0 then PersistentDB:Delete(string.format("log:%06d", n - MAX_LINES)) end
end

-- Prints the log server's state when it changes, so a missing grant or a down server shows once.
local function setServerStatus(status)
  if status == serverStatus then return end
  serverStatus = status
  print(DevLog.NAME .. ": log server " .. status)
end

-- Posts line number n to the log server, if it can.
local function toServer(n, line)
  local url = Plugin.urls and Plugin.urls.logserver
  if not url then
    setServerStatus("URL missing from plugin.json: tools/deploy.py <folder> --edit-plugin-json, then prf")
    return
  end
  if not Plugin.HasPermission(PluginPermissions.httpAccess) then
    setServerStatus("needs httpAccess: turn it on for this plugin in the Plugin Hub")
    return
  end
  local ok, err = pcall(function()
    local request = HTTPRequest.new(url, "/log/" .. DevLog.NAME)
    pending[request] = true
    request:Post(string.format("%06d %s", n, line), function(r)
      pending[r] = nil
      if r.successful then
        setServerStatus("connected")
      else
        setServerStatus("unreachable (" .. tostring(r.errorCode) .. " " .. tostring(r.errorInfo) .. ")")
      end
    end)
  end)
  if not ok then setServerStatus("error: " .. tostring(err)) end
end

-- Sends the line to the enabled sinks, if the topic is enabled.
---@param topic string
---@param fmt string
---@param ... any
function DevLog.log(topic, fmt, ...)
  if DevLog.TOPICS[topic] ~= true then return end
  local text = string.format(fmt, ...)
  if DevLog.TO_CONSOLE == true then print(DevLog.NAME .. "[" .. topic .. "] " .. text) end
  local line = topic .. " " .. text
  if DevLog.TO_DB == true then toDB(seq, line) end
  if DevLog.TO_SERVER == true then toServer(seq, line) end
  seq = seq + 1
  PersistentDB:SetInt("log:next", seq)
end

DevLog.log("startup", "dev build loaded")

return DevLog
