# PyInstaller spec for the desktop app.  Build from the repo root:
#
#     pip install -r packaging/requirements.txt
#     pyinstaller packaging/sensor-patchbay.spec
#
# Output (one folder, two executables over the same files):
#
#     dist/sensor-patchbay/SensorPatchbay[.exe]   the app: window + tray (no console on Windows)
#     dist/sensor-patchbay/patchbay[.exe]         the same, as a console program: --cli, --no-ui, ...
#     dist/Sensor Patchbay.app                    macOS only, wrapping both
#
# What's in the bundle is the core only: the engine, the server, the console,
# the built UI (ui/dist) and the Source/Sink base classes. No module folder and
# no preset is bundled; they're installed from the catalog into the
# user's data folder (engine/paths.py). Modules can import anything in the
# standard library, which is bundled whole for that reason, plus whatever
# their module.toml installs.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
NAME = "sensor-patchbay"

# ---- the standard library, all of it ------------------------------------
# PyInstaller bundles only what the core imports; an uploaded module could
# import anything else. Leave out the parts no plugin should want.
_SKIP = {"tkinter", "turtle", "turtledemo", "idlelib", "test", "lib2to3", "ensurepip",
         "venv", "pydoc_data", "this", "antigravity", "__phello__", "_pyrepl"}
stdlib = []
for name in sorted(sys.stdlib_module_names):
    if name in _SKIP or name.startswith("_test"):
        continue
    try:
        __import__(name)
    except Exception:
        continue        # other platform, or not built into this interpreter
    stdlib += collect_submodules(name, filter=lambda m: not any(
        part in _SKIP or part == "tests" for part in m.split(".")))

# ---- the core ------------------------------------------------------------
core = ["engine", "engine.paths", "engine.modules", "engine.registry", "engine.library",
        "engine.presets", "engine.loop", "engine.graph", "engine.nodes", "engine.signals",
        "run", "server", "control", "sources", "sources.base", "sinks", "sinks.base"]
# Never pull a module folder in, even if something comes to import one.
modules = [f"{parent}.{d.name}" for parent in ("sources", "sinks")
           for d in (ROOT / parent).iterdir() if (d / "module.toml").is_file()]

# pystray picks its backend at import time, which can fail on the build machine
# (no tray there), so name every backend rather than collecting by import.
tray = ["pystray"] + [f"pystray.{m}" for m in (
    "_base", "_info", "_dummy", "_xorg", "_gtk", "_appindicator", "_win32", "_darwin",
    "_util", "_util.gtk", "_util.notify_dbus", "_util.win32")]

# uv installs the packages uploaded modules declare (engine/modules.py looks
# for it next to the executable).
from uv import find_uv_bin  # noqa: E402

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[(find_uv_bin(), ".")],
    datas=[(str(ROOT / "ui" / "dist"), "ui/dist")],
    hiddenimports=core + stdlib + tray + collect_submodules("webview"),
    excludes=modules + ["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(exclude_binaries=True, debug=False, strip=False, upx=False,
              icon=None, target_arch=None, codesign_identity=None, entitlements_file=None)
gui = EXE(pyz, a.scripts, [], name="SensorPatchbay", console=False, **common)
cli = EXE(pyz, a.scripts, [], name="patchbay", console=True, **common)

coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Sensor Patchbay.app",
        bundle_identifier="io.github.sensorpatchbay",
        info_plist={
            "CFBundleDisplayName": "Sensor Patchbay",
            "NSHighResolutionCapable": True,
            # Asked for the first time a module uses each of these.
            "NSBluetoothAlwaysUsageDescription": "Read Bluetooth controllers such as a Joy-Con.",
            "NSCameraUsageDescription": "Track hands with a camera source module.",
        },
    )
