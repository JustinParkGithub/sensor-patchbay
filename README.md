# sensor-patchbay

A **sensor → routing → command** pipeline: named signals from any sensor go on a
typed bus, run through a hot-editable **routing graph** (scale, curve, deadzone,
smoothing, thresholds, gesture gates…), and drive any output. The shipping input
is a Nintendo Switch **Joy-Con (R)** and an **Arduino Nano + BMI160**; the
shipping output is a **virtual mouse & keyboard** — but sources and sinks are
plugins you pick from a menu, add live, and extend with one file.

You wire it together in a browser-based **patch panel**, or, on a headless board,
from an on-device **CLI console** — two front-ends over one engine. It runs
offline (once its modules are installed) and saves presets as plain JSON.

```
Joy-Con (R)  ──BT───►  sources/joycon/    ─┐
Nano + BMI160 ──USB──► sources/bmi160/    ┤                                 ┌─► sinks/hid/ ──────► OS
your sensor  ──────►   sources/<yours>/   ├─► engine (bus + graph + nodes) ─┤
                                          ┘        ▲          ▲             └─► sinks/gpio/, … ──► GPIO / …
                                             fixed 120 Hz  presets/*.json
                                                   │
                             ui/ (patch panel)  +  control.py (CLI console)  — same engine, two editors
```

Every source and sink is a **plugin** with a `type` (the menu / CLI name) and an
`id` (the bus namespace its ports live under). They're chosen at runtime — a
dropdown in the GUI, `add source|sink` in the console, or `--source`/`--sink` on
the command line — and a new one is a single folder dropped in `sources/` or
`sinks/`, no edits to `run.py`, the engine, or the UI. Each module declares the
Python packages it needs, and the environment is kept to exactly that set (see
**Modules & dependencies**). See **Choosing sources & sinks** and
**Extending it**, and the deeper [`docs/`](docs) (an informal
[overview](docs/OVERVIEW.md) and a formal [specification](docs/SPECIFICATION.md)).

---

## Installation

There are two ways to run it, and both include the command-line console:

| | what you get | modules & presets |
|---|---|---|
| **Desktop app** | one download, no Python needed: a native window plus a tray icon | none bundled; you upload the ones you want |
| **From source** | `python run.py` in a checkout; the patch panel in your browser | every folder in `sources/`, `sinks/`, `presets/` |

### Desktop app

Build it per platform (PyInstaller can't cross-compile), or take the build from
the **Desktop app** GitHub Actions workflow (run it from the Actions tab, or push
a `v*` tag; each OS's build is attached to the run):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r packaging/requirements.txt         # PyInstaller, pywebview, pystray, Pillow, uv
pyinstaller packaging/sensor-patchbay.spec
```

| platform | output | notes |
|---|---|---|
| Windows | `dist/sensor-patchbay/SensorPatchbay.exe` | uses the WebView2 runtime that ships with Windows 10/11 |
| macOS | `dist/Sensor Patchbay.app` | unsigned: right-click → Open the first time; the `hid` sink still needs Accessibility |
| Linux | `dist/sensor-patchbay/SensorPatchbay` | build with system WebKitGTK + PyGObject (see `packaging/requirements.txt`); the tray needs AppIndicator on GNOME |

Launch it, and the patch panel opens in its own window with an icon in the tray
(menu bar on macOS). **Closing the window keeps the engine running.** The tray
menu brings it back, opens it in a browser, toggles PANIC, opens the data folder,
and quits. Starting it again while it's running just opens the running one.

The app **ships with no modules and no presets**, not even `mock`. Add them from
the patch panel (**Upload…**, or drop files on the window; see
[Adding modules & presets](#adding-modules--presets)). For example, zip any folder
from this repo:

```bash
cd sources && zip -r ~/mock.zip mock      # and joycon (mock depends on it), bmi160, ...
cd sinks   && zip -r ~/hid.zip hid        # dryrun needs hid too
```

Then upload `presets/*.json` for presets. Everything you add lives in a per-user
data folder, so updating the app keeps it:

| | data folder |
|---|---|
| Linux | `~/.local/share/sensor-patchbay/` (`$XDG_DATA_HOME`) |
| macOS | `~/Library/Application Support/sensor-patchbay/` |
| Windows | `%APPDATA%\sensor-patchbay\` |

It holds `sources/`, `sinks/`, `presets/`, `patchbay.toml` (same format as
below), `patchbay.lock`, and `site-packages/`. The last one holds the Python
packages your modules declare. The app's bundled `uv` installs them on sync, so
the first sync of a module with packages needs the network. A package with no
prebuilt wheel for your platform is compiled with a uv-managed Python. If that
fails (e.g. no compiler), only the modules that need it are unavailable. Set
`PATCHBAY_HOME` to use another folder; that also works with `python run.py` or
`python app.py` from source.

#### Command line, from the app

The app folder holds a second executable, `patchbay` (`patchbay.exe`; inside the
macOS bundle at `Sensor Patchbay.app/Contents/MacOS/patchbay`). It is a console
program that takes every flag from the table below and uses the same data folder:

```bash
patchbay --cli                 # web UI on :8420 + the patchbay> console, no window
patchbay --no-ui --cli         # console only (headless / over SSH)
patchbay --list-sources        # what's installed, and why anything is unavailable
patchbay --sync                # install uploaded modules' packages, print setup notes
patchbay                       # no console flags: the window + tray, like the app
```

`SensorPatchbay` takes the same flags, plus `--browser` (patch panel in your
browser instead of a window) and `--no-tray` (closing the window quits). On
Windows only `patchbay.exe` has a console to type into, so use it for `--cli`.

### From source

```bash
cd sensor-patchbay
python3.12 -m venv .venv && .venv/bin/pip install uv   # any Python 3.11+, plus uv
source .venv/bin/activate

python run.py                                     # installs every module's packages on first run,
                                                  # then starts empty; add modules live from the UI
#   open http://127.0.0.1:8420

python run.py --mock --dry-run                    # no hardware, no real input events — just explore
python run.py --sink hid --mock --preset mouse    # real mouse/keyboard, synthetic source, air-mouse
python app.py                                     # the desktop app's window + tray, from source
                                                  #   (pip install -r packaging/requirements.txt)
```

`run.py` is the command-line entry point: `--cli` adds the console, and
`--no-ui --cli` runs without the browser UI (see
[the CLI console](#reconfiguring-from-the-device-itself-the-cli-console)).

The engine starts with **no sources or sinks** — you add them live from the GUI's
*add source / add sink* dropdowns (or the `--cli` console), which is the point:
swap hardware in and out without ever restarting. The flags below only *pre-load*
modules so a rig comes up ready; anything they do can also be done live in the UI.

| flag | effect |
|---|---|
| `--mock` | pre-load the synthetic source (oscillators shaped like real Joy-Con ports) — same as `--source mock` |
| `--dry-run` | pre-load a logging-only sink instead of the real mouse/keyboard — same as `--sink dryrun` |
| `--preset NAME` | load `presets/NAME.json` at startup (default `mouse`) |
| `--rate HZ` | engine tick rate (default 120; also settable live in the UI/console) |
| `--list-ports` | print every source/sink port and exit |
| `--source TYPE[:k=v,...]` | pre-load a registered source plugin (repeatable) — e.g. `--source bmi160:port=/dev/ttyUSB0` |
| `--sink TYPE[:k=v,...]` | pre-load a registered sink plugin (repeatable) — e.g. `--sink hid` for the real mouse + keyboard |
| `--list-sources` / `--list-sinks` | list what's registered and its constructor args, then exit |
| `--cli` | also start the interactive control console (reconfigure live) |
| `--no-ui` | don't start the web server (headless board / appliance) |
| `--ext DIR` | also load module folders from `DIR` (repeatable) |
| `--sync` | make the environment match the enabled modules, print their system-setup notes, exit |
| `--upgrade` | re-resolve every module's packages to the newest versions, then sync |
| `--no-sync` | don't check or change installed packages this run |
| `--no-autostart` | ignore `patchbay.toml`'s `autostart` list this run |
| `--selftest` | headless: run mock → dry-run for 2 s, assert, exit |
| `--host` / `--port` | bind address for the UI (default `127.0.0.1:8420`) |

You never *need* `--source`/`--sink`: it's usually easier to add modules live from
the GUI dropdown or the console (below). The flags are for scripting a fixed rig —
or list the modules in `patchbay.toml`'s `autostart` (below) to have them added on
every start.

---

## Modules & dependencies

The setup is declarative, after NixOS: each module says what it needs, the module
folders on disk are the configuration, and the environment is made to match it
exactly. **Every module is enabled by default**: its packages and assets are
installed up front, so any source or sink can be added live from the UI at any
time without a reinstall or restart. You opt modules *out* with `disable`.

```
sources/bmi160/
  __init__.py      # the plugin
  module.toml      # what it needs
  firmware/        # anything else that belongs to it
```

```toml
# sources/bmi160/module.toml
python  = ["pyserial>=3.5"]                        # pip requirement strings (markers ok)
depends = []                                       # modules whose code this one imports
system  = ["Linux: your user in the `dialout` group"]   # printed, not managed

[[assets]]                                         # downloaded into the folder, sha256-checked
file = "model.task"
url = "https://…"
sha256 = "…"
```

On every start, `run.py` collects the `python` lists of all enabled modules. If
they changed, it re-resolves them into **`patchbay.lock`** (with `uv pip compile
--universal`, so one committed lock works on macOS, Linux and a Pi). It then runs
`uv pip sync`, which installs what's missing and **uninstalls anything no enabled
module needs**. When nothing changed this takes well under a second and needs no
network. Shared packages are counted once: `pyserial` stays installed while
either `bmi160` or `bend4` is enabled.

**`patchbay.toml`** is the rig-wide config, and everything in it is optional:

```toml
python    = ["uv"]          # core packages (uv itself, so the sync keeps it)
disable   = []              # opt-out, e.g. ["cv"]: never imported, packages removed
autostart = []              # added on start, e.g. ["bmi160:port=/dev/ttyACM0", "hid"]
```

Being installed isn't the same as being added. Nothing autostarts by default.
Installed modules wait in the *add source / add sink* dropdowns. A module whose `depends` is disabled is disabled
too (`mock` needs `joycon`, `dryrun` needs `hid`). What pip can't do — pairing,
udev rules, serial groups, macOS Accessibility and camera permissions — is listed
in each module's `system` notes. `python run.py --sync` prints them.

All modules share one environment because they run in one process, so two
modules that pin incompatible versions of a package can't both be enabled. The
resolver names both modules' files when that happens.

---
---

## Sources & sinks

Each module's setup (pairing, wiring, firmware, permissions) and its ports are
documented in its own folder. Packages are installed automatically; the module
README covers what pip can't do.

| type | kind | what | setup |
|---|---|---|---|
| `joycon` | source | Nintendo Switch Joy-Con (R) over Bluetooth | [sources/joycon/](sources/joycon/README.md) |
| `mock` | source | synthetic Joy-Con stand-in, no hardware | — |
| `ds4` | source | Sony DualShock 4 over USB or Bluetooth | [sources/ds4/](sources/ds4/README.md) |
| `bmi160` | source | Arduino Nano + BMI160 IMU over USB serial | [sources/bmi160/](sources/bmi160/README.md) |
| `bend4` | source | Arduino Nano + four flex sensors over USB serial | [sources/bend4/](sources/bend4/) |
| `cv` | source | webcam hand tracking (OpenCV + MediaPipe) | [sources/cv/](sources/cv/README.md) |
| `gamepad` | source | any XInput / DInput / Switch-style controller (SDL2) | [sources/gamepad/](sources/gamepad/README.md) |
| `zero2` | source | 8BitDo Zero 2 (falls back to any controller), same ports as `gamepad` | [sources/gamepad/](sources/gamepad/README.md) |
| `hid` | sink | virtual mouse + keyboard (pynput) | see **Ports** |
| `dryrun` | sink | logging-only stand-in for `hid` | — |
| `gpio` | sink | Raspberry Pi PWM + digital out | [sinks/gpio/](sinks/gpio/) |

`python run.py --sync` prints every enabled module's system-setup notes.

---

## The patch panel

`http://127.0.0.1:8420` — sources on the left, sinks on the right, cables in the
middle. Nothing loads from the internet.

- **Patch** — click a source jack, then a sink jack. A cable appears; a dashed
  pulse runs along it at the live signal level.
- **Shape a cable** — click it. The inspector opens with the transform chain:
  add / remove / reorder nodes, edit every parameter live. Changes take effect on
  the next engine tick — no restart, no reconnect.
- **Meters** — every jack shows its current value and an auto-gained bar, so you
  can see exactly what a sensor axis is doing before you wire it anywhere.
- **Add a source / sink** — at the bottom of each column is a dropdown of every
  installed plugin, plus its options. Pick one (e.g. `BMI160`, `Raspberry Pi
  GPIO`), fill in its args, hit **add**, and its jacks appear ready to patch — no
  restart. Plugins that need a missing library are listed greyed-out with the
  reason. Each module header has an **✕** to remove it (its cables go with it).
- **Presets** — the dropdown + Load / Save / Save as / New / Delete. A preset is
  the whole graph, saved to `presets/<name>.json`. Diff them, copy them, hand-edit
  them. A preset that needs a source or sink you don't have is marked **⚠** in
  the dropdown. The badge beside it says which (hover it for why), and loading
  it warns too. See [Preset dependencies](#preset-dependencies).
- **Upload… / ⟳ Sync** — add modules and presets, and re-read what's on disk.
  See [Adding modules & presets](#adding-modules--presets).
- **Rate** — the `Hz` box in the top bar sets the engine tick rate live.
- **PANIC** — disables every output instantly and releases held keys/buttons.
  Patch any button to `sys/panic.toggle` to get the same switch on hardware.
- Mapping `joycon/btn.home → sys/preset.cycle` (both shipped presets do this) makes
  the Home button walk through your preset files.

### Adding modules & presets

**Upload…** in the top bar takes a **module** as a `.zip` of its folder, or a
**preset** as a `.json` file. You can pick several at once, or drop files anywhere
on the window. After uploading, the panel syncs on its own. New sources and sinks
then show up in the *add* dropdowns, and new presets in the preset list.
Uploading a module or preset that already exists replaces it.

- A module zip holds one module folder (`mock/__init__.py`, `mock/module.toml`,
  ...). The files can also sit at the top of the zip, which then names the
  module, or under `sources/` / `sinks/`. Outside those, `module.toml` must say
  `kind = "source"` or `"sink"`; every module in this repo does.
- Uploads go to the data folder: the repo itself when running from source, the
  per-user folder in the app.

**⟳ Sync** re-reads everything on disk without a restart. It finds module
folders, installs the packages their `module.toml` lists, imports new modules,
and re-imports ones whose files changed. It also drops modules that were deleted
or disabled from the menus, and re-checks every preset's dependencies. Use it
after copying a folder in by hand, editing a module, or changing `patchbay.toml`.
A toast sums up the result. Hover the button for the full log, including each
module's setup steps that pip can't do. Instances that are already running keep
running; remove and re-add one to pick up a reloaded module. In the console,
`install <file>` and `sync` do the same.

Installing a module runs its code, so the server refuses upload, sync and other
changes from any page that isn't the patch panel itself. It also refuses
requests that reach it under an unexpected host name, which blocks DNS
rebinding. It only listens on `127.0.0.1` unless you pass `--host`.

### Type rules

Ports are `scalar` (continuous) or `event` (0/1 gate or a pulse). `scalar → event`
is allowed but you almost always want a `threshold` or `schmitt` node in between,
or the key/button chatters. The UI highlights compatible sink jacks when you arm a
source.

---

## Reconfiguring from the device itself (the CLI console)

When the patchbay runs on a headless board — a Pi with no screen, an appliance you
reach over SSH — you don't need a browser. `--cli` gives you a `patchbay>` prompt
that drives the *same running engine* the GUI would; `--no-ui` drops the web
server entirely.

```bash
python run.py --no-ui --cli            # console only, truly headless
python run.py --cli                    # web UI and console side by side
```

```
patchbay> plugins                       # what can I add?  (the dropdown, as text)
patchbay> add sink gpio pwm_pins=18,13  # add a module live
patchbay> ports                         # list every jack on the bus
patchbay> connect bmi160/tilt.roll gpio/pwm.0
patchbay> save my-rig                   # write presets/my-rig.json
patchbay> install ~/hid.zip             # add a module (or a preset .json), then sync
patchbay> sync                          # re-read modules + presets from disk
patchbay> panic on                      # cut all outputs
patchbay> help
```

Anything you do in the console shows up in the browser instantly, and vice-versa —
they're two editors on one engine. `python run.py --no-ui` with neither flag just
runs a preset as a fixed appliance.

---

## Shipped presets

**`mouse.json`** — air-mouse

| source | chain | sink |
|---|---|---|
| `gyro.y` (yaw rate) | scale · deadzone · expo · scale · clamp | `mouse.dx` |
| `gyro.x` (pitch rate) | scale · deadzone · expo · scale · invert · clamp | `mouse.dy` |
| `btn.zr` | — | `mouse.left` |
| `btn.r` | — | `mouse.right` |
| `stick.y` | deadzone · scale · rate-limit | `mouse.wheel` |
| `accel.mag` | threshold 2.2 g · debounce 500 ms · hold | `mouse.btn_forward` (wrist flick) |
| `btn.home` | — | `sys/preset.cycle` |

**`keyboard.json`** — tilt to WASD

| source | chain | sink |
|---|---|---|
| `tilt.roll` | schmitt +20°/+12° | `key.d` |
| `tilt.roll` | schmitt −20°/−12° | `key.a` |
| `tilt.pitch` | schmitt −20°/−12° | `key.w` |
| `tilt.pitch` | schmitt +20°/+12° | `key.s` |
| `btn.a` | — | `key.space` |
| `accel.mag` | threshold 2.5 g · debounce 400 ms · hold | `key.esc` (shake) |
| `btn.home` | — | `sys/preset.cycle` |

**`bmi160-mouse.json`** — air-mouse, BMI160

| source | chain | sink |
|---|---|---|
| `gyro.y` | scale · deadzone · expo · scale · clamp | `mouse.dx` |
| `gyro.x` | scale · deadzone · expo · scale · invert · clamp | `mouse.dy` |
| `accel.mag` | threshold 2.2 g · debounce 500 ms · hold | `mouse.left` (shake to click) |

**`gamepad-mouse-keyboard.json`** — 8BitDo Zero 2 (`zero2`) or any controller (`gamepad`) as keyboard + mouse

| source | chain | sink |
|---|---|---|
| `dpad.*` | — | `key.up/down/left/right` |
| `btn.a` / `btn.b` / `btn.x` / `btn.y` / `btn.start` | — | `key.space` / `key.esc` / `key.e` / `key.tab` / `key.enter` |
| `btn.lb` / `btn.rb` (L / R) | — | `mouse.left` / `mouse.right` |
| `btn.back` (Select) | — | `sys/preset.cycle` |
| *full-size pads only:* | | |
| `stick.lx` / `stick.ly` | schmitt ±0.5/±0.35 | `key.left/right` / `key.down/up` |
| `stick.rx` / `stick.ry` | deadzone 0.12 · expo · scale 1400 (· invert for y) | `mouse.dx` / `mouse.dy` |
| `btn.rt` / `btn.lt` / `btn.rs` | — | `mouse.left` / `mouse.right` / `mouse.middle` |

**`ds4-mouse.json`** — DualShock 4 as a mouse

| source | chain | sink |
|---|---|---|
| `rstick.x` / `rstick.y` | deadzone · expo · scale | `mouse.dx` / `mouse.dy` |
| `touch.dx` / `touch.dy` | scale · clamp | `mouse.dx` / `mouse.dy` (trackpad) |
| `r2` | schmitt 0.5/0.35 | `mouse.left` |
| `btn.touchpad` | — | `mouse.left` |
| `l2` | schmitt 0.5/0.35 | `mouse.right` |
| `btn.r3` | — | `mouse.middle` |
| `btn.l1` / `btn.r1` | — | `mouse.btn_back` / `mouse.btn_forward` |
| `lstick.y` | deadzone · invert · scale · rate_limit | `mouse.wheel` |
| `btn.ps` | — | `sys/preset.cycle` |

Raw Joy-Con sensor units are arbitrary but stable — tune magnitudes with a
`scale` node in the preset, never in the plugin, so a preset built against the
mock source works unchanged on real hardware.

### Preset dependencies

A preset patches into bus namespaces (`joycon/…`, `hid/…`). A namespace is an
instance id, not a plugin type, so each preset lists which types can fill each
namespace it uses:

```json
"requires": [
  {"id": "joycon", "kind": "source", "types": ["joycon", "mock"]},
  {"id": "hid",    "kind": "sink",   "types": ["dryrun", "hid"]}
]
```

**Save** writes this list. It includes the type running under each namespace,
every installed type whose default id matches, and whatever the file already
listed, so hand-added alternatives survive a save. A requirement is met when at
least one of its types is installed and available. Otherwise the panel flags
the preset (*not installed*, or *installed but unavailable* with the reason),
and so do `presets` and `load` in the console. A preset without `requires` is
checked against the namespaces its connections use.

---

## Transform nodes

| node | does |
|---|---|
| `scale`, `offset`, `invert`, `abs`, `clamp`, `quantize` | arithmetic |
| `deadzone` | zero out small values, rescale the rest continuously |
| `expo` | blend linear ↔ cubic response (fine control near centre) |
| `ema`, `one_euro` | smoothing; `one_euro` stays crisp on fast motion |
| `rate_limit` | slew limiter (units/second) |
| `threshold` | scalar → 0/1 gate (`gt` / `lt`) |
| `schmitt` | hysteresis gate; `on < off` makes a "less-than" gate |
| `debounce` | rising edge → one pulse + lockout |
| `hold` | stretch a pulse so it lasts at least N ms |
| `toggle` | rising edge flips a latched 0/1 |

`GET /api/nodes` returns the parameter spec the UI builds its editor from.

---

## Ports

`python run.py --list-ports` for the live list.

Source ports are listed in each source's README (see **Sources & sinks**).

**Sink `hid`** — `mouse.dx`, `mouse.dy` (pixels/second), `mouse.wheel`
(clicks/second), `mouse.{left,right,middle,btn_back,btn_forward}`, and
`key.<name>` for any single character or named key (`space`, `esc`, `enter`,
`tab`, `shift`, `ctrl`, `up`, …).

**Sink `sys`** — `preset.cycle` (rising edge loads the next preset file) and
`panic.toggle` (rising edge toggles panic, same as the PANIC button).

---

## Extending it

Adding a source or sink is **one new folder**, with no edits to `run.py`, the
engine, or the UI. Create `sinks/<type>/` (or `sources/<type>/`) containing an
`__init__.py` and a `module.toml`. The folder name must match the class's `type`.
On the next start its packages are installed, and it shows up in the GUI dropdown,
the console's `add` command, `--list-sources`/`--list-sinks`, and the
`--source`/`--sink` flags. To keep modules outside the repo, point `--ext DIR` or
`PATCHBAY_EXT_PATH` at a directory of module folders. Those manifests also need
`kind = "source"` or `"sink"`.

A plugin declares two names: **`type`** — the registry key you pick from the menu —
and **`id`** — the bus namespace its ports live under (`type/port` on the wire).
They're separate on purpose: a *stand-in* like the mock Joy-Con is a different
`type` (`mock`) but borrows the real device's `id` (`joycon`), so a preset built
against one runs unchanged on the other.

### A new output — subclass `sinks.base.Sink`

```python
from engine.registry import register_sink
from engine.signals import PortSpec, SCALAR, EVENT
from sinks.base import Sink

@register_sink
class MidiSink(Sink):
    type = "midi"; id = "midi"; label = "MIDI out"
    PORTS = [PortSpec("cc.1", SCALAR, "mod wheel", "midi"),
             PortSpec("note.60", EVENT, "middle C", "midi")]
    ARGS = {"port_name": {"default": None, "type": str, "help": "MIDI output port"}}

    @classmethod
    def available(cls):                      # lists greyed-out with a reason if missing
        try: import rtmidi  # noqa
        except Exception as e: return False, f"needs python-rtmidi ({e})"
        return True

    def __init__(self, port_name=None): self._port_name = port_name
    def start(self): import rtmidi; self.out = rtmidi.MidiOut(); self.out.open_port(0)
    def apply(self, values, dt):
        if "cc.1" in values: self.out.send_message([0xB0, 1, int(values["cc.1"] * 127)])
    def release_all(self): ...
```

Save it as `sinks/midi/__init__.py` next to a `sinks/midi/module.toml` containing
`python = ["python-rtmidi"]`. On the next start, rtmidi is installed and the sink
is selectable from the dropdown, with `add sink midi port_name=…`, or with
`--sink midi:port_name=IAC Driver`.
`ARGS` is what the GUI builds its little form from and what the CLI coerces values
against (its `type` picks the input widget). Import your third-party dependency
**lazily** (inside `__init__`/`start`, never at module top) and add `available()`
so a machine where the library didn't install (wrong platform, `--no-sync`) still
lists it politely instead of failing to load.

There's a complete, working example already in the tree:
[`sinks/gpio/`](sinks/gpio/) drives
Raspberry Pi GPIO — PWM channels for servos / drone ESCs, digital pins for relays —
and falls back to logging when there's no Pi, so you can build the patch on a
laptop. Copy it.

### A new input — subclass `sources.base.Source`

Return `{port_id: float}` from `read()` each tick; flatten vectors to `accel.x`
etc. Keep `read()` non-blocking (do I/O on your own thread, like
`sources/joycon/` or `sources/bmi160/`). Decorate with
`@register_source`, give it a `type`/`id`/`ARGS`, and it's selectable the same way
(`--source yourtype[:k=v,...]`, the dropdown, or `add source`).

The full contract — every method, the port/preset formats, the availability rules —
is in [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) §6–7.

### Driving external hardware — write a sink

A sink can speak whatever protocol you like. For hardware that lives on another
machine or behind a slow/blocking transport, keep the real-time loop isolated by
having the sink hand each tick's `{port: value}` to a queue or socket and doing
the actual I/O off the engine thread — the same pattern the source plugins use
for reads. `sinks/gpio/` (below) is a complete working sink
to copy.

---

## Layout

```
engine/     signals.py nodes.py graph.py loop.py registry.py   # portable core: bus, transforms, routing, tick, plugin registry
            modules.py                                     # module manifests, patchbay.lock, environment sync
            paths.py library.py presets.py                 # data folder, uploads + sync, preset dependencies
sources/    base.py  joycon/ mock/ bmi160/ bend4/ cv/ ds4/ gamepad/  # one folder per source type (code + module.toml + firmware/assets)
sinks/      base.py  hid/ dryrun/ gpio/                    # one folder per sink type
patchbay.toml                                              # rig config: disable / autostart / core packages
patchbay.lock                                              # generated: exact package set for the enabled modules
ui/         src/ (plain TS)    dist/ (committed build)    # patch panel — see ui/README.md
presets/    mouse.json  keyboard.json  bmi160-mouse.json  bend4-mouse-keyboard.json  gamepad-mouse-keyboard.json  ds4-mouse.json
docs/       OVERVIEW.md  SPECIFICATION.md                  # informal + formal docs
control.py  interactive CLI console (--cli)                # reconfigure a headless engine
server.py   http.server + Server-Sent Events + REST       # stdlib only
run.py      entrypoint (and the command line)
app.py      desktop app: native window + tray around run.py's startup
packaging/  sensor-patchbay.spec  requirements.txt         # PyInstaller build of the desktop app
```

## Notes

- The **routing core** (`engine/`, the plugin/sink contracts, `EngineLoop.step`)
  is pure standard library — no numpy, no third-party imports — so it ports to a
  microcontroller. `server.py`, `ui/`, the `pynput` sink and the `pyjoycon` source
  are PC-only front-ends and I/O adapters bolted on top; on a small board you keep
  the core, call `engine.step(dt)` from your own loop, and reconfigure over the
  CLI. See [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) §12.
- The engine runs at 120 Hz by default; plenty for motion input, comfortable for
  Python without numpy.
- `--selftest` is the CI check (mock source → dry-run sink, asserts the snapshot).
- Tested here: engine math, the REST API (including the new `/api/plugins` and the
  runtime `/api/source|sink` add/remove endpoints), the SSE stream and its
  `mod_rev` live-refresh signal, presets and panic via `--selftest` and a scripted
  API pass; the plugin registry (`discover`, availability probing,
  `--list-sources`/`--list-sinks`, type-based instantiation) and the CLI console
  via scripted passes. `sources/bmi160/`'s parser/calibration/tilt math
  is unit-tested against synthetic serial frames — it has not been run against a
  real Nano+BMI160 here; check `--list-ports` picks up `bmi160` and the meters move
  once you have the hardware. The browser UI's JavaScript is syntax- and
  logic-checked but was not rendered in a real browser here — give it a visual
  once-over on first run.
