"""Local viewer and log server for the plugin's dev log lines (see plugin/devlog.lua).

    python3 tools/logviewer.py    then open http://127.0.0.1:8766

Shows two kinds of source in the plugin dropdown:
- "<plugin> (db)": PersistentDB rows (DevLog.TO_DB), read from a temp copy of the client's PluginData.db,
  never the real one.
- "<plugin> (http)": lines POSTed to /log/<plugin> (DevLog.TO_SERVER). Each is also appended to
  logs/plugin.log; when that reaches 25 MB it becomes logs/plugin.log.1 (replacing the old one),
  so the two never take more than 50 MB.
"""
from __future__ import annotations

import collections, json, os, re, shutil, sqlite3, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, DefaultDict, Deque, List, Tuple, TypedDict, Union
from urllib.parse import parse_qs, unquote, urlparse
import devconfig

JAGEX = devconfig.jagex_dir()
DB = os.path.join(JAGEX, "plugins", "PluginData.db") if JAGEX else ""
LINE = re.compile(r"log:(\d+)$")
LOG = os.path.join(devconfig.ROOT, "logs", "plugin.log")
MAX_BYTES = 50 * 1024 * 1024
# Dropdown labels: which source a plugin entry reads from.
HTTP = " (http)"
STORED = " (db)"



class Line(TypedDict):
    """One log line as the page gets it: its number and "<topic> <text>"."""
    n: int
    line: str


lock = threading.Lock()
# Lines POSTed since the server started, newest last, per plugin name.
posted: DefaultDict[str, Deque[Line]] = collections.defaultdict(lambda: collections.deque(maxlen=2000))
received = 0

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logviewer.html")


def append(line: str) -> None:
    """Appends to logs/plugin.log, rotating it to plugin.log.1 at half of MAX_BYTES."""
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    if os.path.exists(LOG) and os.path.getsize(LOG) >= MAX_BYTES // 2:
        os.replace(LOG, LOG + ".1")
    with open(LOG, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def text(blob: Union[str, bytes]) -> str:
    """A DB column as text: the client stores some keys and values as NUL-padded blobs."""
    if isinstance(blob, str):
        blob = blob.encode()
    return blob.decode("utf-8", errors="replace").rstrip("\x00")


def query(sql: str, args: Tuple[str, ...] = ()) -> List[Any]:
    """Rows from a temp copy of PluginData.db (with its WAL files), or [] if there's no DB."""
    if not os.path.exists(DB):
        return []
    with tempfile.TemporaryDirectory() as d:
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(DB + ext):
                shutil.copy(DB + ext, os.path.join(d, "db" + ext))
        con = sqlite3.connect(os.path.join(d, "db"))
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        """Quiet: no line per request on the console."""

    def send(self, body: str, ctype: str) -> None:
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/api/plugins":
            rows = query("SELECT DISTINCT PluginID, Key FROM DataStore WHERE Key LIKE 'log:%'")
            names = {text(p) + STORED for p, k in rows if LINE.match(text(k))}
            with lock:
                names |= {p + HTTP for p in posted}
            self.send(json.dumps(sorted(names)), "application/json")
        elif url.path == "/api/logs":
            plugin, after = q.get("plugin", [""])[0], int(q.get("after", ["0"])[0])
            if plugin.endswith(HTTP):
                with lock:
                    out = [o for o in posted.get(plugin[:-len(HTTP)], ()) if o["n"] > after]
                self.send(json.dumps(out), "application/json")
                return
            plugin = plugin[:-len(STORED)] if plugin.endswith(STORED) else plugin
            rows = query("SELECT Key, Value FROM DataStore WHERE PluginID = ? AND Key LIKE 'log:%'", (plugin,))
            stored: List[Line] = [{"n": int(m.group(1)), "line": text(v)}
                                   for k, v in rows if (m := LINE.match(text(k)))]
            stored = sorted((o for o in stored if o["n"] > after), key=lambda o: o["n"])[:2000]
            self.send(json.dumps(stored), "application/json")
        elif url.path == "/":
            with open(PAGE, encoding="utf-8") as f:  # read per request, so page edits show on reload
                self.send(f.read(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        """POST /log/<plugin> with body "<seq> <topic> <text>", from devlog.lua."""
        global received
        path = urlparse(self.path).path
        size = int(self.headers.get("Content-Length") or 0)
        if not path.startswith("/log/") or not 0 < size <= 65536:
            self.send_error(400)
            return
        plugin = unquote(path[len("/log/"):])
        body = self.rfile.read(size).decode("utf-8", errors="replace").rstrip("\n")
        seq, _, line = body.partition(" ")
        with lock:
            append("%s #%s %s" % (plugin, seq, line))
            received += 1
            posted[plugin].append({"n": received, "line": line})
        self.send("", "text/plain")


if __name__ == "__main__":
    print("RuneScape-BETA: %s\nLog file: %s\nOpen %s" % (JAGEX or "not found (set JAGEX_DIR in tools/devconfig.py)", LOG, devconfig.SERVER_URL))
    ThreadingHTTPServer(("127.0.0.1", devconfig.PORT), Handler).serve_forever()
