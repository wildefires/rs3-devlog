"""tools/deploy.py, run as a script on a temp copy of the repo whose JAGEX_DIR points at a temp folder.

Run: python3 -m unittest discover tests (from the repo root).
"""
from __future__ import annotations

import json, os, re, shutil, subprocess, sys, tempfile, unittest
from typing import Any, Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER = "-- rs3-devlog managed file"


class Deploy(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        jagex = os.path.join(self.tmp.name, "RuneScape-BETA")
        self.dev = os.path.join(jagex, "dev_plugins")
        os.makedirs(self.dev)
        shutil.copytree(os.path.join(ROOT, "plugin"), os.path.join(self.repo, "plugin"))
        shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(self.repo, "tools"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        config = os.path.join(self.repo, "tools", "devconfig.py")
        text, n = re.subn(r'^JAGEX_DIR: str = ""$', "JAGEX_DIR: str = %r" % jagex, self.read(config), flags=re.M)
        self.assertEqual(n, 1, "devconfig.py has no empty JAGEX_DIR line to point at the temp folder")
        self.write(config, text)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def read(path: str) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def write(path: str, text: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def run_deploy(self, *args: str, ok: bool = True) -> str:
        p = subprocess.run([sys.executable, os.path.join(self.repo, "tools", "deploy.py"), *args],
                           capture_output=True, text=True)
        out = (p.stdout + p.stderr).replace(self.dev + os.sep, "")
        self.assertEqual(p.returncode == 0, ok, out)
        return out

    def manifest(self, folder: str) -> Any:
        return json.loads(self.read(os.path.join(folder, "plugin.json")))

    def other(self, name: str, devlog: Optional[str] = None) -> str:
        """A dev plugin named `name`, optionally with an existing devlog.lua."""
        folder = os.path.join(self.dev, name)
        self.write(os.path.join(folder, "plugin.json"), '{"name": "Other"}')
        if devlog is not None:
            self.write(os.path.join(folder, "devlog.lua"), devlog)
        return folder

    def snapshot(self) -> Dict[str, str]:
        files: Dict[str, str] = {}
        for d, _, names in os.walk(self.dev):
            for n in names:
                files[os.path.join(d, n)] = self.read(os.path.join(d, n))
        return files

    # Choosing plugins

    def test_never_deploys_the_example_plugin(self) -> None:
        self.run_deploy("--all")
        self.assertEqual(os.listdir(self.dev), [])

    def test_named_plugins_get_the_files(self) -> None:
        one, two = self.other("one"), self.other("two")
        self.other("untouched")
        out = self.run_deploy("one", "two")
        self.assertIn('DevLog.NAME = "one"', self.read(os.path.join(one, "devlog.lua")))
        self.assertIn('DevLog.NAME = "two"', self.read(os.path.join(two, "devlog.lua")))
        self.assertTrue(self.read(os.path.join(one, "log.lua")).startswith(MARKER))
        self.assertEqual(os.listdir(os.path.join(self.dev, "untouched")), ["plugin.json"])
        self.assertIn("Not updated one/plugin.json", out)

    def test_a_named_numbered_folder_is_allowed(self) -> None:
        numbered = self.other("6398181")
        self.run_deploy("6398181")
        self.assertIn('DevLog.NAME = "6398181"', self.read(os.path.join(numbered, "devlog.lua")))

    def test_any_bad_name_stops_before_anything_is_written(self) -> None:
        self.other("good")
        before = self.snapshot()
        self.assertIn("missing: no plugin.json", self.run_deploy("good", "missing", ok=False))
        self.assertIn("folder name must be", self.run_deploy("good", "../good", ok=False))
        self.assertEqual(self.snapshot(), before)

    def test_needs_names_or_all_but_not_both(self) -> None:
        self.other("one")
        self.assertIn("or pass --all", self.run_deploy(ok=False))
        self.assertIn("or pass --all", self.run_deploy("one", "--all", ok=False))

    def test_include_downloaded_needs_all(self) -> None:
        self.other("one")
        self.assertIn("only applies with --all", self.run_deploy("one", "--include-downloaded", ok=False))

    def test_refuses_source_without_marker(self) -> None:
        self.other("one")
        path = os.path.join(self.repo, "plugin", "log.lua")
        self.write(path, self.read(path).split("\n", 1)[1])
        self.assertIn("must start with the line", self.run_deploy("one", ok=False))
        self.assertEqual(os.listdir(os.path.join(self.dev, "one")), ["plugin.json"])

    # --all

    def test_all_adds_files_with_folder_name_and_leaves_manifest(self) -> None:
        other = self.other("other")
        out = self.run_deploy("--all")
        self.assertIn('DevLog.NAME = "other"', self.read(os.path.join(other, "devlog.lua")))
        self.assertTrue(self.read(os.path.join(other, "log.lua")).startswith(MARKER))
        self.assertEqual(self.manifest(other), {"name": "Other"})
        self.assertIn("Not updated other/plugin.json", out)

    def test_all_skips_numbered_bad_named_and_manifestless_folders(self) -> None:
        self.other("6398181")
        self.other("bad name")
        os.makedirs(os.path.join(self.dev, "nojson"))
        out = self.run_deploy("--all")
        self.assertIn("Skipped 6398181: downloaded from mod.io (--include-downloaded covers it)", out)
        self.assertIn("Skipped bad name: folder name", out)
        self.assertIn("Skipped nojson: no plugin.json", out)
        for name in ("6398181", "bad name", "nojson"):
            self.assertNotIn("devlog.lua", os.listdir(os.path.join(self.dev, name)))

    def test_include_downloaded_adds_to_downloaded_folders_with_the_same_rules(self) -> None:
        numbered = self.other("6398181")
        kept = self.other("6398193", "return {}\n")
        out = self.run_deploy("--all", "--include-downloaded")
        self.assertIn('DevLog.NAME = "6398181"', self.read(os.path.join(numbered, "devlog.lua")))
        self.assertEqual(self.manifest(numbered), {"name": "Other"})
        self.assertEqual(self.read(os.path.join(kept, "devlog.lua")), "return {}\n")
        self.assertIn("Not updated 6398193/devlog.lua: not an rs3-devlog file", out)

    def test_all_keeps_existing_files_without_upgrade(self) -> None:
        other = self.other("other", MARKER + " (old copy)\n")
        out = self.run_deploy("--all")
        self.assertEqual(self.read(os.path.join(other, "devlog.lua")), MARKER + " (old copy)\n")
        self.assertIn("Not updated other/devlog.lua: already exists (use --upgrade to replace it)", out)

    def test_upgrade_replaces_only_marked_files(self) -> None:
        mine = self.other("mine", MARKER + " (old copy)\n")
        theirs = self.other("theirs", "return {}\n")
        out = self.run_deploy("--all", "--upgrade")
        self.assertIn('DevLog.NAME = "mine"', self.read(os.path.join(mine, "devlog.lua")))
        self.assertEqual(self.read(os.path.join(theirs, "devlog.lua")), "return {}\n")
        self.assertIn("Replaced mine/devlog.lua", out)
        self.assertIn("Not updated theirs/devlog.lua: not an rs3-devlog file", out)

    def source_devlog(self) -> str:
        return self.read(os.path.join(self.repo, "plugin", "devlog.lua"))

    def test_upgrade_keeps_settings_and_resets_name(self) -> None:
        old = (self.source_devlog()
               .replace("DevLog.NAME = \"devlog-example\"", "DevLog.NAME = \"stale\"")
               .replace("DevLog.TO_DB = true", "DevLog.TO_DB = false")
               .replace("DevLog.TOPICS = { startup = true, heartbeat = true }", "DevLog.TOPICS = { combat = true }")
               .replace("\n", "\r\n"))  # as saved by a Windows editor
        mine = self.other("mine")
        with open(os.path.join(mine, "devlog.lua"), "w", encoding="utf-8", newline="") as f:
            f.write(old)
        out = self.run_deploy("mine", "--upgrade")
        new = self.read(os.path.join(mine, "devlog.lua"))
        self.assertIn("Kept settings TO_DB, TOPICS in mine/devlog.lua", out)
        self.assertIn("DevLog.TO_DB = false\n", new)
        self.assertIn("DevLog.TOPICS = { combat = true }\n", new)
        self.assertIn("DevLog.TO_SERVER = true\n", new)
        self.assertIn('DevLog.NAME = "mine"\n', new)
        self.assertNotIn("\r", new)

    def test_upgrade_reports_a_multiline_setting_it_cannot_keep(self) -> None:
        old = self.source_devlog().replace("DevLog.TOPICS = { startup = true, heartbeat = true }",
                                           "DevLog.TOPICS = {\n  combat = true,\n}")
        mine = self.other("mine", old)
        out = self.run_deploy("mine", "--upgrade")
        self.assertIn("Not kept mine/devlog.lua: DevLog.TOPICS spans several lines", out)
        self.assertIn("DevLog.TOPICS = { startup = true, heartbeat = true }", self.read(os.path.join(mine, "devlog.lua")))

    def test_settings_untouched_without_upgrade(self) -> None:
        old = self.source_devlog().replace("DevLog.TO_DB = true", "DevLog.TO_DB = false")
        mine = self.other("mine", old)
        out = self.run_deploy("mine")
        self.assertEqual(self.read(os.path.join(mine, "devlog.lua")), old)
        self.assertNotIn("Kept settings", out)

    # Backups

    def backups(self, plugin: str) -> Dict[str, str]:
        folder = os.path.join(self.repo, "backup", plugin)
        if not os.path.isdir(folder):
            return {}
        return {n: self.read(os.path.join(folder, n)) for n in sorted(os.listdir(folder))}

    def test_upgrade_backs_up_each_replaced_file_first(self) -> None:
        old = MARKER + " (old copy)\n"
        mine = self.other("mine", old)
        self.write(os.path.join(mine, "log.lua"), old)
        out = self.run_deploy("mine", "--upgrade")
        saved = self.backups("mine")
        self.assertEqual(len(saved), 2, saved)
        for name, text in saved.items():
            self.assertRegex(name, r"^(log|devlog)-backup-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.lua$")
            self.assertEqual(text, old)
        self.assertIn("Backed up mine/devlog.lua to", out)
        self.assertNotEqual(self.read(os.path.join(mine, "devlog.lua")), old)

    def test_no_backup_for_added_files_or_dry_runs(self) -> None:
        self.other("fresh")
        self.other("mine", MARKER + " (old copy)\n")
        self.run_deploy("mine", "--upgrade", "--dry-run")
        self.run_deploy("fresh", "--upgrade")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "backup")))

    def test_a_failed_backup_leaves_the_file_alone(self) -> None:
        mine = self.other("mine", MARKER + " (old copy)\n")
        self.write(os.path.join(self.repo, "backup"), "a file where the backup folder should be")
        self.run_deploy("mine", "--upgrade", ok=False)
        self.assertEqual(self.read(os.path.join(mine, "devlog.lua")), MARKER + " (old copy)\n")

    def test_upgrade_leaves_up_to_date_files_alone(self) -> None:
        mine = self.other("mine")
        self.run_deploy("mine")
        before = self.snapshot()
        out = self.run_deploy("mine", "--upgrade")
        self.assertEqual(self.snapshot(), before)
        self.assertIn("Not updated mine/log.lua: already up to date", out)
        self.assertIn("Not updated mine/devlog.lua: already up to date", out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "backup")))
        self.assertTrue(os.path.exists(os.path.join(mine, "devlog.lua")))

    def test_edit_plugin_json_leaves_a_complete_manifest_alone(self) -> None:
        other = self.other("other")
        self.run_deploy("other", "--edit-plugin-json")
        before = self.read(os.path.join(other, "plugin.json"))
        out = self.run_deploy("other", "--edit-plugin-json")
        self.assertIn("Not updated other/plugin.json: already has httpAccess and the log server URL", out)
        self.assertEqual(self.read(os.path.join(other, "plugin.json")), before)

    def test_edit_plugin_json_skips_plugins_with_their_own_devlog(self) -> None:
        theirs = self.other("theirs", "return {}\n")
        out = self.run_deploy("theirs", "--edit-plugin-json")
        self.assertEqual(self.manifest(theirs), {"name": "Other"})
        self.assertIn("Not updated theirs/plugin.json: its devlog.lua isn't an rs3-devlog file", out)

    def test_edit_plugin_json_adds_logserver_and_keeps_fields(self) -> None:
        other = self.other("other")
        self.run_deploy("--all", "--edit-plugin-json")
        m = self.manifest(other)
        self.assertEqual(m["name"], "Other")
        self.assertEqual(m["optionalPermissions"], ["httpAccess"])
        self.assertEqual(m["urls"], {"logserver": "http://127.0.0.1:8766"})

    def test_dry_run_writes_nothing(self) -> None:
        self.other("fresh")
        self.other("mine", MARKER + " (old copy)\n")
        before = self.snapshot()
        out = self.run_deploy("--all", "--upgrade", "--edit-plugin-json", "--dry-run")
        self.assertEqual(self.snapshot(), before)
        self.assertIn("Would have added fresh/devlog.lua", out)
        self.assertIn("Would have replaced mine/devlog.lua", out)
        self.assertIn("Would have edited fresh/plugin.json", out)


if __name__ == "__main__":
    unittest.main()
