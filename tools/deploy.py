"""Adds log.lua and devlog.lua to plugins in <RuneScape-BETA>/dev_plugins/, on Windows, macOS and Linux.

    python3 tools/deploy.py <plugin folder>... [--upgrade] [--edit-plugin-json] [--dry-run]
    python3 tools/deploy.py --all [--include-downloaded] [--upgrade] [--edit-plugin-json] [--dry-run]

The files come from plugin/ in this repo, and each copy of devlog.lua gets DevLog.NAME set to the
plugin's folder name. Copies the files directly, because the client can't read plugin files
through symlinks (at least on Linux). It never changes an existing file unless:
- --upgrade: replace log.lua and devlog.lua, but only copies that start with MARKER (ours),
  keeping devlog.lua's one-line `DevLog.<KEY> = <value>` settings;
- --edit-plugin-json: add httpAccess and the log server URL to each plugin.json.
Every file it leaves alone is printed, with the reason. Before --upgrade replaces a file, the old one
is copied to backup/<plugin folder>/<file>-backup-<Y-m-d-H-M-S>.lua in this repo. Then `prl <folder>` in the console
(`prf` first if plugin.json changed).

--all covers every plugin in dev_plugins/, except numbered folders (plugins downloaded from mod.io);
--include-downloaded covers those too, with the same rules.

--dry-run runs every check and prints what would be written, without writing anything.
"""
from __future__ import annotations

import argparse, json, os, re, shutil, time
from typing import List, Tuple
import devconfig  # JAGEX_DIR, the repo root and the log server URL, shared with logviewer.py

# --- Command line -------------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Add log.lua and devlog.lua to plugins in the client's dev_plugins folder.")
parser.add_argument("plugins", nargs="*", metavar="plugin folder",
                    help="dev_plugins folder names to add the files to")
parser.add_argument("--all", action="store_true",
                    help="every plugin in dev_plugins (skipping ones downloaded from mod.io)")
parser.add_argument("--include-downloaded", action="store_true",
                    help="with --all: also numbered folders (downloaded from mod.io)")
parser.add_argument("--upgrade", action="store_true",
                    help="replace existing log.lua/devlog.lua that carry the rs3-devlog marker")
parser.add_argument("--edit-plugin-json", action="store_true",
                    help="add httpAccess and the log server URL to each plugin's plugin.json")
parser.add_argument("--dry-run", action="store_true", help="print what would be written, write nothing")
args = parser.parse_args()
# Exactly one way of choosing plugins, so a missing name never turns into "all of them".
if bool(args.plugins) == args.all:
    parser.error("name the plugin folders, or pass --all (not both)")
if args.include_downloaded and not args.all:
    parser.error("--include-downloaded only applies with --all; name a numbered folder to target it directly")

# Line 1 of log.lua and devlog.lua: marks a copy as ours, so --upgrade may replace it.
MARKER = "-- rs3-devlog managed file"
# Where --upgrade keeps the files it replaces, and the timestamp shared by every backup in this run.
BACKUP_DIR = os.path.join(devconfig.ROOT, "backup")
STAMP = time.strftime("%Y-%m-%d-%H-%M-%S")
# The line in devlog.lua that each copy gets its plugin's folder name on.
NAME_LINE = re.compile(r'^DevLog\.NAME = ".*"$', re.M)
# A setting in devlog.lua: a top-level `DevLog.<KEY> = <value>` line. --upgrade carries these over.
SETTING_LINE = re.compile(r'^DevLog\.(\w+) = (.*?)\r?$', re.M)


# --- Helpers ------------------------------------------------------------------------------------

def is_dev_name(name: str) -> bool:
    """Letters, digits, - and _: safe as a folder name and inside a Lua string."""
    return name.replace("-", "").replace("_", "").isalnum()


def add_logserver(folder: str) -> bool:
    """Adds httpAccess and the log server URL to folder/plugin.json (unless --dry-run).

    Returns whether the manifest needed them; one that already has both is left as it is.
    """
    manifest = os.path.join(folder, "plugin.json")
    with open(manifest, encoding="utf-8") as f:
        m = json.load(f)
    before = json.dumps(m, sort_keys=True)

    # Add optional httpAccess
    if "httpAccess" not in m.setdefault("optionalPermissions", []):
        m["optionalPermissions"].append("httpAccess")

    # devlog.lua posts to Plugin.urls.logserver; the client only allows URLs listed here.
    m.setdefault("urls", {})["logserver"] = devconfig.SERVER_URL
    if json.dumps(m, sort_keys=True) == before:
        return False
    if not args.dry_run:
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2)
    return True


def is_ours(path: str) -> bool:
    """True if path starts with MARKER, i.e. it's a copy deploy.py may replace."""
    # Only line 1 matters, and a file that isn't valid UTF-8 is still someone else's file.
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.readline().startswith(MARKER)


def keep_settings(path: str, text: str) -> Tuple[str, List[str]]:
    """With --upgrade, puts the settings from the existing devlog.lua at path into the new text.

    Each `DevLog.<KEY> = <value>` line of the new text gets the old copy's value, so upgrading keeps
    the plugin's settings. NAME is left alone (it's always the folder name); settings only in one
    of the two versions keep the new text's line. Returns the text and the settings it kept.
    """
    if not (args.upgrade and os.path.exists(path) and is_ours(path)):
        return text, []
    with open(path, encoding="utf-8", errors="replace") as f:
        old = dict(SETTING_LINE.findall(f.read()))
    kept: List[str] = []

    def swap(m: re.Match[str]) -> str:
        key, value = m.group(1), old.get(m.group(1))
        if key == "NAME" or value is None or value == m.group(2):
            return m.group(0)
        # A value spread over several lines (a TOPICS table split across lines) can't be copied
        # from its first line alone, so the new default stays.
        if value.count("{") != value.count("}"):
            print("Not kept %s: DevLog.%s spans several lines; set it again by hand" % (path, key))
            return m.group(0)
        kept.append(key)
        return "DevLog.%s = %s" % (key, value)

    return SETTING_LINE.sub(swap, text), kept


def back_up(path: str) -> str:
    """Copies path to backup/<plugin folder>/<file>-backup-<STAMP>.lua and returns the copy's path."""
    stem, ext = os.path.splitext(os.path.basename(path))
    folder = os.path.join(BACKUP_DIR, os.path.basename(os.path.dirname(path)))
    os.makedirs(folder, exist_ok=True)
    backup = os.path.join(folder, "%s-backup-%s%s" % (stem, STAMP, ext))
    shutil.copy2(path, backup)
    return backup


def place_file(path: str, text: str) -> bool:
    """Writes text to path if it's new, or ours and --upgrade is on; otherwise says why not.

    Returns whether it wrote the file (or, with --dry-run, would have).
    """
    verb = "Added"
    if os.path.exists(path):
        if not is_ours(path):
            print("Not updated %s: not an rs3-devlog file (no marker on line 1)" % path)
            return False
        # Rewriting an identical file would only leave a backup of nothing.
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            if f.read() == text:
                print("Not updated %s: already up to date" % path)
                return False
        if not args.upgrade:
            print("Not updated %s: already exists (use --upgrade to replace it)" % path)
            return False
        verb = "Replaced"
    if args.dry_run:
        print("Would have %s %s" % (verb.lower(), path))
        return True
    if verb == "Replaced":
        # Failsafe: keep the old copy. If the backup fails, the error stops the run before the replace.
        print("Backed up %s to %s" % (path, back_up(path)))
    # newline="": write the text exactly as read, keeping its line endings on every OS.
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print("%s %s" % (verb, path))
    return True


def install(folder: str) -> None:
    """Adds the log files (and, with --edit-plugin-json, the manifest entries) to one plugin."""
    name = os.path.basename(folder)
    place_file(os.path.join(folder, "log.lua"), LOG)

    # Each plugin logs under its own folder name, which is also the name the log server files it under.
    devlog = NAME_LINE.sub('DevLog.NAME = "%s"' % name, DEVLOG, count=1)
    target = os.path.join(folder, "devlog.lua")
    # A plugin with its own devlog.lua doesn't use this logger, so it shouldn't gain the permission.
    uses_ours = not os.path.exists(target) or is_ours(target)
    devlog, kept = keep_settings(target, devlog)
    if place_file(target, devlog) and kept:
        print("Kept settings %s in %s" % (", ".join(kept), target))
    manifest = os.path.join(folder, "plugin.json")
    if not args.edit_plugin_json:
        print("Not updated %s: --edit-plugin-json adds httpAccess and the log server URL" % manifest)
    elif not uses_ours:
        print("Not updated %s: its devlog.lua isn't an rs3-devlog file" % manifest)
    elif not add_logserver(folder):
        print("Not updated %s: already has httpAccess and the log server URL" % manifest)
    else:
        print(("Would have edited " if args.dry_run else "Edited ") + manifest)


def read_source(filename: str) -> str:
    """A file from plugin/, read without newline translation so the copies match it byte for byte."""
    with open(os.path.join(SRC, filename), encoding="utf-8", newline="") as f:
        return f.read()


# --- Checks: all of these run before anything is written, also with --dry-run ---------------------

SRC = os.path.join(devconfig.ROOT, "plugin")
LOG = read_source("log.lua")
DEVLOG = read_source("devlog.lua")
# Copies without the marker could never be upgraded later, so don't hand any out.
if not (LOG.startswith(MARKER) and DEVLOG.startswith(MARKER)):
    raise SystemExit("plugin/log.lua and plugin/devlog.lua must start with the line '%s ...'." % MARKER)
if not NAME_LINE.search(DEVLOG):
    raise SystemExit('plugin/devlog.lua needs a line DevLog.NAME = "..." for each copy\'s name.')

DEV_PLUGINS = os.path.join(devconfig.require_jagex_dir(), "dev_plugins")
if not os.path.isdir(DEV_PLUGINS):
    raise SystemExit("No dev_plugins folder in %s: create it and put your plugin in it first." % os.path.dirname(DEV_PLUGINS))


# --- Install ------------------------------------------------------------------------------------

def main() -> None:
    """Checks the named plugins, then installs into them, or into every plugin with --all."""
    # Named plugins must all be real before any of them is touched.
    for name in args.plugins:
        if not is_dev_name(name):
            parser.error("%s: folder name must be letters, digits, - and _ (it goes into a Lua string)" % name)
        if not os.path.isfile(os.path.join(DEV_PLUGINS, name, "plugin.json")):
            parser.error("%s: no plugin.json in %s" % (name, os.path.join(DEV_PLUGINS, name)))

    for name in args.plugins:
        install(os.path.join(DEV_PLUGINS, name))

    if not args.all:
        return
    for name in sorted(os.listdir(DEV_PLUGINS)):
        folder = os.path.join(DEV_PLUGINS, name)
        # Loose files aren't plugins.
        if not os.path.isdir(folder):
            continue
        if name.isdigit() and not args.include_downloaded:
            print("Skipped %s: downloaded from mod.io (--include-downloaded covers it)" % folder)
            continue
        # The client needs a plugin.json to load a folder, so without one it isn't a plugin.
        if not os.path.isfile(os.path.join(folder, "plugin.json")):
            print("Skipped %s: no plugin.json" % folder)
            continue
        # The folder name goes into a Lua string, so it must not be able to break out of it.
        if not is_dev_name(name):
            print("Skipped %s: folder name must be letters, digits, - and _" % folder)
            continue
        install(folder)


main()
