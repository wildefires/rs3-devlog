"""The log server. Run: python3 -m unittest discover tests (from the repo root)."""
from __future__ import annotations

import json, os, sqlite3, sys, tempfile, threading, unittest, urllib.error, urllib.request
from typing import Any, List, Tuple
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import logviewer  # after the sys.path entry above, which makes tools/ importable


class Server(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        logviewer.LOG = os.path.join(self.dir.name, "logs", "plugin.log")
        logviewer.MAX_BYTES = 200
        logviewer.DB = os.path.join(self.dir.name, "PluginData.db")
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), logviewer.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        self.dir.cleanup()

    def post(self, path: str, body: str) -> None:
        urllib.request.urlopen(urllib.request.Request(self.base + path, data=body.encode())).close()

    def test_posts_show_in_viewer_and_rotate(self) -> None:
        for i in range(10):
            self.post("/log/demo", "%06d x line %d" % (i, i))
        self.assertIn("demo (http)", json.load(urllib.request.urlopen(self.base + "/api/plugins")))
        logs = json.load(urllib.request.urlopen(self.base + "/api/logs?plugin=demo%20(http)&after=0"))
        self.assertEqual(logs[-1]["line"], "x line 9")
        size = os.path.getsize(logviewer.LOG) + os.path.getsize(logviewer.LOG + ".1")
        self.assertLessEqual(size, logviewer.MAX_BYTES + 50)  # each file stops growing once past half
        with open(logviewer.LOG, encoding="utf-8") as f:
            self.assertTrue(f.read().endswith("demo #000009 x line 9\n"))

    def get(self, path: str) -> object:
        with urllib.request.urlopen(self.base + path) as r:
            return json.load(r)

    def test_db_source_is_labelled_and_readable(self) -> None:
        con = sqlite3.connect(logviewer.DB)
        con.execute("CREATE TABLE DataStore (PluginID, Key, Type, Value)")
        # The client stores some keys and values as NUL-padded blobs.
        con.executemany("INSERT INTO DataStore VALUES (?, ?, 3, ?)", [
            ("demo", "log:000002", b"x second\x00"),
            ("demo", "log:000001", "x first"),
            ("demo", "log:next", 3),
            ("other", "setting", "not a log line"),
        ])
        con.commit()
        con.close()
        self.post("/log/demo", "000001 x sent")
        self.assertEqual(self.get("/api/plugins"), ["demo (db)", "demo (http)"])
        self.assertEqual(self.get("/api/logs?plugin=demo%20(db)&after=0"),
                         [{"n": 1, "line": "x first"}, {"n": 2, "line": "x second"}])
        self.assertEqual(self.get("/api/logs?plugin=demo%20(db)&after=1"), [{"n": 2, "line": "x second"}])

    def make_db(self, rows: List[Tuple[str, str, str]]) -> None:
        con = sqlite3.connect(logviewer.DB)
        con.execute("CREATE TABLE IF NOT EXISTS DataStore (PluginID, Key, Type, Value)")
        con.executemany("INSERT INTO DataStore VALUES (?, ?, 3, ?)", rows)
        con.commit()
        con.close()

    def test_db_is_copied_only_when_it_changes(self) -> None:
        self.make_db([("demo", "log:000001", "x first")])
        copies: List[str] = []
        real_copy = logviewer.shutil.copy

        def counting_copy(src: str, dst: str) -> Any:
            copies.append(src)
            return real_copy(src, dst)

        logviewer.shutil.copy = counting_copy
        try:
            self.assertEqual(len(logviewer.query("SELECT * FROM DataStore")), 1)
            first = len(copies)
            self.assertEqual(len(logviewer.query("SELECT * FROM DataStore")), 1)
            self.assertEqual(len(copies), first, "unchanged DB was copied again")
            self.make_db([("demo", "log:000002", "x second")])
            self.assertEqual(len(logviewer.query("SELECT * FROM DataStore")), 2)
            self.assertGreater(len(copies), first, "changed DB was not copied")
        finally:
            logviewer.shutil.copy = real_copy

    def test_bad_path_rejected(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/nope", "x")
        cm.exception.close()


if __name__ == "__main__":
    unittest.main()
