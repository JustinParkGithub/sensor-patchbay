"""Where things live: the code, and the files a user adds or edits.

From a checkout both are the repo, exactly as before: ``sources/``, ``sinks/``,
``presets/``, ``patchbay.toml`` and ``patchbay.lock`` sit next to ``run.py``.

From the packaged app (PyInstaller, ``sys.frozen``) the code is read-only inside
the bundle and ships no modules or presets at all, so everything user-owned
moves to a per-user data folder:

    Linux    ~/.local/share/sensor-patchbay/      ($XDG_DATA_HOME)
    macOS    ~/Library/Application Support/sensor-patchbay/
    Windows  %APPDATA%\\sensor-patchbay\\

      sources/<type>/      uploaded source modules
      sinks/<type>/        uploaded sink modules
      presets/*.json
      patchbay.toml        the same config as the repo's
      patchbay.lock
      site-packages/       the Python packages those modules declare

``PATCHBAY_HOME`` overrides the data folder in either mode, which is also how
to try the app's layout from a checkout.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

# The code: the repo, or the unpacked bundle.
APP = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def _user_data() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "sensor-patchbay"


_home = os.environ.get("PATCHBAY_HOME", "").strip()
DATA = Path(_home).expanduser() if _home else (_user_data() if FROZEN else APP)

PRESETS = DATA / "presets"
CONFIG = DATA / "patchbay.toml"
LOCK = DATA / "patchbay.lock"
SITE = DATA / "site-packages"       # only used by the packaged app (see engine/modules.py)
KINDS = {"sources": "source", "sinks": "sink"}

_DEFAULT_CONFIG = """\
# patchbay.toml - which modules run, and what starts with the app.
# Same format as the repo's patchbay.toml (see the README).

# Extra Python packages to install beside the ones modules declare.
python = []

# Module types to leave out entirely, e.g. disable = ["cv"]
disable = []

# Module catalog (index.json URL or local path); empty means the default on GitHub.
# catalog = ""

# Modules to add on start, e.g. autostart = ["controller", "hid"]
autostart = []
"""


def module_dirs() -> list[tuple[Path, str]]:
    """``(folder, kind)`` for every folder whose subfolders are modules."""
    out = []
    for parent, kind in KINDS.items():
        for root in dict.fromkeys((APP, DATA)):   # once each, in order, if they're the same
            out.append((root / parent, kind))
    return out


def upload_dir(kind: str) -> Path:
    """Where an uploaded module of *kind* is written."""
    return DATA / f"{kind}s"


def ensure_layout():
    """Create the data folder's skeleton (a no-op for a plain checkout)."""
    PRESETS.mkdir(parents=True, exist_ok=True)
    if DATA == APP:
        return
    for parent in KINDS:
        (DATA / parent).mkdir(parents=True, exist_ok=True)
    if not CONFIG.is_file():
        CONFIG.write_text(_DEFAULT_CONFIG)


def extend_packages():
    """Let ``sources.<type>`` / ``sinks.<type>`` import from the data folder too,
    so a module uploaded there is a normal package. Its ``depends`` imports
    (``from sources.<other> import ...``) then work as they do in the repo."""
    import sinks
    import sources

    for pkg, parent in ((sources, "sources"), (sinks, "sinks")):
        extra = str(DATA / parent)
        if extra not in pkg.__path__:
            pkg.__path__.append(extra)
