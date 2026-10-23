"""Dev settings for tools/deploy.py and tools/logviewer.py."""
from __future__ import annotations

import getpass, glob, os, sys
from typing import List, Optional

# Your RuneScape-BETA folder (the one holding *.jcache files), e.g. r"C:\ProgramData\Jagex\RuneScape-BETA".
# Empty: the first default folder for this OS that exists (see candidates()).
JAGEX_DIR: str = ""

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8766
SERVER_URL = "http://127.0.0.1:%d" % PORT


def candidates() -> List[str]:
    """Default RuneScape-BETA folders for this OS, most likely first."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        return [r"C:\ProgramData\Jagex\RuneScape-BETA"]
    if sys.platform == "darwin":
        return [os.path.join(home, "Jagex", "RuneScape-BETA")]
    return [
        os.path.join(home, ".var/app/com.adamcake.Bolt/data/bolt-launcher/Jagex/RuneScape-BETA"),
        os.path.join(home, ".local/share/bolt-launcher/Jagex/RuneScape-BETA"),
        os.path.join(home, ".var/app/com.jagex.Launcher/data/wine/drive_c/users", getpass.getuser(),
                     "AppData/Local/Jagex/RuneScape-BETA"),
    ]


def jagex_dir() -> Optional[str]:
    """JAGEX_DIR if set, else the first default folder holding *.jcache files; None if none found."""
    if JAGEX_DIR:
        return os.path.normpath(os.path.expanduser(JAGEX_DIR))
    for d in candidates():
        if glob.glob(os.path.join(glob.escape(d), "*.jcache")):
            return d
    return None


def require_jagex_dir() -> str:
    """jagex_dir(), or exit with what to set if there isn't a usable one."""
    d = jagex_dir()
    if not d or not os.path.isdir(d):
        sys.exit("RuneScape-BETA folder not found (%s). Set JAGEX_DIR in tools/devconfig.py." % (d or "tried " + ", ".join(candidates())))
    return d
