-- devlog.lua with stubbed client globals. Run: lua5.4 tests/test_devlog.lua (from the repo root).
package.path = "plugin/?.lua;" .. package.path

local printed = {} ---@type any
local db = {} ---@type any
local perms = {} ---@type any
local posts = {} ---@type any
local failed, total = 0, 0

-- Fresh stubs and a fresh devlog; finish(i, ok) runs post i's completion callback.
local function load(opts)
  opts = opts or {}
  printed, db, perms, posts = {}, { ["log:next"] = opts.next }, { httpAccess = opts.granted }, {}
  print = function(s) printed[#printed + 1] = s end
  PersistentDB = {
    GetInt = function(_, k) return db[k] end,
    SetInt = function(_, k, v) db[k] = v end,
    SetString = function(_, k, v) db[k] = v end,
    Delete = function(_, k) db[k] = nil end,
  }
  PluginPermissions = { httpAccess = "httpAccess" }
  Plugin = { HasPermission = function(p) return perms[p] == true end, urls = opts.urls }
  HTTPRequest = { new = function(url, path)
    local r = { url = url .. path }
    function r:Post(body, cb) posts[#posts + 1] = { req = self, body = body, cb = cb } end
    return r
  end }
  package.loaded.devlog = nil
  return require("devlog")
end

local function finish(i, ok)
  local p = posts[i]
  p.req.successful, p.req.errorCode, p.req.errorInfo = ok, ok and 0 or 7, ok and "" or "refused"
  p.cb(p.req)
end

local function check(v, msg) if not v then error(msg or "check failed", 2) end end

local function count(pattern)
  local n = 0
  for _, l in ipairs(printed) do if l:find(pattern, 1, true) then n = n + 1 end end
  return n
end

local function rows()
  local n = 0
  for k in pairs(db) do if k:match("^log:%d+$") then n = n + 1 end end
  return n
end

local function test(name, fn)
  total = total + 1
  local ok, err = pcall(fn)
  if not ok then failed = failed + 1 end
  io.write(ok and "  ok   " or "  FAIL ", name, ok and "" or ("\n    " .. tostring(err)), "\n")
end

local URLS = { logserver = "http://127.0.0.1:8766" }

test("every line prints, and goes to the DB and the server", function()
  local DevLog = load({ granted = true, urls = URLS })
  DevLog.TOPICS.x = true
  DevLog.log("x", "n=%d", 5)
  check(printed[#printed] == "devlog-example[x] n=5", printed[#printed])
  check(db["log:000001"] == "x n=5")
  check(posts[2].body == "000001 x n=5", posts[2].body)
  check(posts[2].req.url == "http://127.0.0.1:8766/log/devlog-example")
  check(db["log:next"] == 2)
  finish(2, true)
  check(count("log server connected") == 1)
end)

test("TO_CONSOLE off: lines don't print, server status still does", function()
  local DevLog = load({ granted = false, urls = URLS })
  DevLog.TO_CONSOLE, DevLog.TOPICS.x = false, true
  printed = {}
  DevLog.log("x", "a")
  check(count("devlog-example[x]") == 0 and db["log:000001"] == "x a")
  check(load({ granted = false, urls = URLS }) and count("needs httpAccess") == 1)
end)

test("disabled topics print and send nothing", function()
  local DevLog = load({ granted = true, urls = URLS })
  DevLog.log("nope", "x")
  check(#printed == 1 and #posts == 1 and rows() == 1)
end)

test("TO_DB off: nothing stored, still printed and sent", function()
  local DevLog = load({ granted = true, urls = URLS })
  DevLog.TO_DB, DevLog.TOPICS.x = false, true
  DevLog.log("x", "a")
  check(db["log:000001"] == nil and posts[2] and count("devlog-example[x] a") == 1)
end)

test("a failed post is only printed, not stored, and the reason shows once", function()
  local DevLog = load({ granted = true, urls = URLS })
  DevLog.TO_DB, DevLog.TOPICS.x = false, true
  DevLog.log("x", "a")
  DevLog.log("x", "b")
  finish(2, false)
  finish(3, false)
  check(rows() == 1, "only the startup row, stored before TO_DB was switched off")
  check(count("unreachable (7 refused)") == 1)
end)

test("without httpAccess: nothing sent, the reason shows once", function()
  local DevLog = load({ granted = false, urls = URLS })
  DevLog.TOPICS.x = true
  DevLog.log("x", "a")
  check(#posts == 0 and count("needs httpAccess: turn it on for this plugin in the Plugin Hub") == 1)
end)

test("without the manifest URL: nothing sent", function()
  load({ granted = true })
  check(#posts == 0 and count("URL missing") == 1)
end)

test("keeps the last 2000 rows, across a reload", function()
  local DevLog = load({ next = 1999 })
  DevLog.TO_SERVER = false
  for _ = 1, 3 do DevLog.log("startup", "x") end -- rows 1999..2002 now
  check(rows() == 4 and db["log:002002"] and db["log:next"] == 2003)
  for i = 3, 1998 do db[string.format("log:%06d", i)] = "old" end
  DevLog.log("startup", "y") -- row 2003 replaces row 3
  check(db["log:000003"] == nil and rows() == 2000)
end)

io.write(string.format("%d/%d passed\n", total - failed, total))
os.exit(failed == 0 and 0 or 1)
