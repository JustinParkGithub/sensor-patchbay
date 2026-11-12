<p align="center"><img src="packaging/icon/sensor-patchbay.png" width="160" alt="sensor-patchbay logo: patch cables plugged into a patchbay in front of a gear"></p>

# sensor-patchbay

A **sensor → routing → command** pipeline: named signals from any sensor go on a
typed bus, run through a hot-editable **routing graph** (scale, curve, deadzone,
smoothing, thresholds, combining two signals…), and drive any output. The catalog's
inputs are **any game controller** (Xbox, PlayStation, Switch, 8BitDo, …, with
motion and touchpad where the pad has them), **flex sensors** and **webcam hand
tracking**. Its output is a **virtual mouse & keyboard**; this repo also carries
sinks for **key combos, media keys, OSC and webhooks** (see
[Sources & sinks](#sources--sinks)). Sources and sinks are plugins you install
from a catalog, add live, and extend with one folder.

**[Download the desktop app](https://github.com/JustinParkGithub/sensor-patchbay/releases/latest)**
for Windows, macOS or Linux, or run it from source.

You wire it together in a browser-based **patch panel**, or, on a headless board,
from an on-device **CLI console** — two front-ends over one engine. It runs
offline (once its modules are installed) and saves presets as plain JSON.

```
any controller ─USB/BT─► sources/controller/ ─┐
flex sensors ──USB─────► sources/bend4/      ┤                                 ┌─► sinks/hid/ ──► OS
your sensor  ──────────► sources/<yours>/    ├─► engine (bus + graph + nodes) ─┤
                                             ┘        ▲          ▲             └─► sinks/<yours>/ ─► …
                                                fixed 120 Hz  presets/*.json
                                                   │
                             ui/ (patch panel)  +  control.py (CLI console)  — same engine, two editors
```

Every source and sink is a **plugin** with a `type` (the menu / CLI name) and an
`id` (the bus namespace its ports live under). They're chosen at runtime — a
dropdown in the GUI, `add source|sink` in the console, or `--source`/`--sink` on
the command line — and a new one is a single folder dropped in `sources/` or
`sinks/`, no edits to `run.py`, the engine, or the UI. None ship with the engine:
they live in the [module catalog](https://github.com/JustinParkGithub/sensor-patchbay-modules) and you install the ones you
want from the GUI's **Browse…** panel (see **Module catalog**). Each module declares the
Python packages it needs, and the environment is kept to exactly that set (see
**Modules & dependencies**). See **Choosing sources & sinks** and
**Extending it**, and the deeper [`docs/`](docs) (an informal
[overview](docs/OVERVIEW.md) and a formal [specification](docs/SPECIFICATION.md)).

---

## Installation

There are two ways to run it, and both include the command-line console:

| | what you get | modules & presets |
|---|---|---|
| **Desktop app** | one download, no Python needed: a native window plus a tray icon | none bundled; install from the catalog |
| **From source** | `python run.py` in a checkout; the patch panel in your browser | `presets/`; modules from the catalog |

### Desktop app

Download the build for your OS from
[**Releases**](https://github.com/JustinParkGithub/sensor-patchbay/releases/latest):

| platform | download | run | notes |
|---|---|---|---|
| Windows (x86-64) | `sensor-patchbay-windows-x86_64.zip` | unzip, run `sensor-patchbay\SensorPatchbay.exe` | uses the WebView2 runtime that ships with Windows 10/11; unsigned, so SmartScreen asks once (*More info → Run anyway*) |
| macOS (Apple silicon) | `sensor-patchbay-macos-arm64.zip` | unzip, move `Sensor Patchbay.app` to Applications | unsigned: right-click → **Open** the first time; the `hid` sink still needs Accessibility |
| Linux (x86-64) | `sensor-patchbay-linux-x86_64.tar.gz` | extract, run `sensor-patchbay/SensorPatchbay` | needs WebKitGTK 4.1 (`gir1.2-webkit2-4.1`); the tray needs AppIndicator on GNOME |

#### Building it yourself

PyInstaller can't cross-compile, so each OS builds its own:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r packaging/requirements.txt         # PyInstaller, pywebview, pystray, Pillow, uv
pyinstaller packaging/sensor-patchbay.spec        # -> dist/  (Linux: system WebKitGTK + PyGObject, see packaging/requirements.txt)
```

The **Desktop app** GitHub Actions workflow does this on all three OSes. Run it
from the Actions tab to get the builds as run artifacts. Pushing a `v*` tag
(`git tag v0.2.0 && git push origin v0.2.0`) also publishes them as a release.
The logo is drawn by `packaging/icon/make_icons.py`, which writes the `.icns`,
`.ico` and PNG files; rerun it after changing the drawing.

Launch it, and the patch panel opens in its own window with an icon in the tray
(menu bar on macOS). **Closing the window keeps the engine running.** The tray
menu brings it back, opens it in a browser, toggles PANIC, opens the data folder,
and quits. Starting it again while it's running just opens the running one.

The app **ships with no modules and no presets**. Install both from **Browse…**
in the patch panel (see [Module catalog](#module-catalog)). Your own preset
files can be added with **Upload…**, or by dropping them on the window. Everything you add lives in a per-user
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

python run.py                                     # starts empty: open http://127.0.0.1:8420, then
                                                  # Browse… to install modules and presets
python run.py --install controller-mouse-keyboard # a preset, plus the modules it needs (controller, hid)
python run.py --sink hid --source controller --preset controller-mouse-keyboard
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
| `--preset NAME` | load `presets/NAME.json` at startup (default: none, an empty patch) |
| `--rate HZ` | engine tick rate (default 120; also settable live in the UI/console) |
| `--source TYPE[:k=v,...]` | pre-load a registered source plugin (repeatable) — e.g. `--source controller:name=dualsense` |
| `--sink TYPE[:k=v,...]` | pre-load a registered sink plugin (repeatable) — e.g. `--sink hid` for the real mouse + keyboard |
| `--list-sources` / `--list-sinks` | list what's registered and its constructor args, then exit |
| `--cli` | also start the interactive control console (reconfigure live) |
| `--no-ui` | don't start the web server (headless board / appliance) |
| `--ext DIR` | also load module folders from `DIR` (repeatable) |
| `--sync` | make the environment match the enabled modules, print their system-setup notes, exit |
| `--upgrade` | re-resolve every module's packages to the newest versions, then sync |
| `--no-sync` | don't check or change installed packages this run |
| `--no-autostart` | ignore `patchbay.toml`'s `autostart` list this run |
| `--catalog` | list the catalog (modules and presets) with what's installed, then exit |
| `--install NAME` | install a module or preset from the catalog before starting (repeatable); `--force` overwrites a modified or hand-placed copy |
| `--selftest` | headless: tick a built-in test source → sink for 2 s, assert, exit (needs no modules) |
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
sources/bend4/
  __init__.py      # the plugin
  module.toml      # what it needs
  firmware/        # anything else that belongs to it
```

```toml
# sources/bend4/module.toml
description = "Arduino Nano + four flex sensors over USB serial"   # one line, for the catalog
version = "1.0.0"                                  # dotted numbers; bump on every change
entry   = "__init__.py"                            # optional: the file that runs (this is the default)
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
network. Shared packages are counted once: a package two modules need stays
installed while either of them is enabled.

**`patchbay.toml`** is the rig-wide config, and everything in it is optional:

```toml
python    = ["uv"]          # core packages (uv itself, so the sync keeps it)
disable   = []              # opt-out, e.g. ["cv"]: never imported, packages removed
autostart = []              # added on start, e.g. ["controller", "hid"]
catalog   = ""              # where to install from (default: the modules repo on GitHub)
```

Being installed isn't the same as being added. Nothing autostarts by default.
Installed modules wait in the *add source / add sink* dropdowns. A module whose `depends` is disabled is disabled
too. What pip can't do — pairing,
udev rules, serial groups, macOS Accessibility and camera permissions — is listed
in each module's `system` notes. `python run.py --sync` prints them.

All modules share one environment because they run in one process, so two
modules that pin incompatible versions of a package can't both be enabled. The
resolver names both modules' files when that happens.

---

## Sources & sinks

Sources, sinks **and presets** live in their own repo,
[sensor-patchbay-modules](https://github.com/JustinParkGithub/sensor-patchbay-modules),
and install from its catalog. Each module's setup (pairing, wiring, firmware,
permissions) and its ports are documented in its folder there. Packages are
installed automatically; the module README covers what pip can't do.

| type | kind | what |
|---|---|---|
| `controller` | source | any game controller via SDL2: Xbox, PlayStation, Switch Pro / Joy-Con, 8BitDo, generic. Motion and touchpad where the pad has them |
| `bend4` | source | Arduino Nano + four flex sensors over USB serial |
| `cv` | source | webcam hand tracking (OpenCV + MediaPipe) |
| `hid` | sink | virtual mouse + keyboard (pynput) |

Four more sinks are in **this repo's `sinks/`** folder and aren't in the catalog
yet. Running from source they load like any installed module (`hotkey` and `media` once `hid` is installed). The
desktop app doesn't bundle them; zip a folder and add it with **Upload…**.

| type | kind | what | needs |
|---|---|---|---|
| `hotkey` | sink | key combos on one gate (`combo.ctrl+c`), pressed in order; `combos=` picks the jacks | `hid` |
| `media` | sink | play/pause, next, previous, mute, volume keys, and `volume.rate` for a stick or tilt | `hid` |
| `osc` | sink | OSC floats over UDP to `host:port`, for DAWs, lighting and visual tools | — |
| `webhook` | sink | a rising edge requests `url1`..`url4` (set on the sink, never in a preset) | — |

| preset | what | uses |
|---|---|---|
| `controller-mouse-keyboard` | any controller as keyboard + mouse: d-pad/left stick are arrows, right stick the mouse | `controller`, `hid` |
| `controller-mouse` | right stick (and a PlayStation touchpad) as the mouse, triggers click | `controller`, `hid` |
| `controller-air-mouse` | point a motion controller to move the cursor | `controller`, `hid` |
| `controller-tilt-keys` | tilt a motion controller for WASD, shake for Esc | `controller`, `hid` |
| `bend4-mouse-keyboard` | bend fingers to look, walk and jump | `bend4`, `hid` |

`python run.py --sync` prints every enabled module's system-setup notes.

### Module catalog

The engine reads the modules repo's `index.json` and installs from it:

| where | how |
|---|---|
| patch panel | **Browse…** in the top bar: search, filter sources / sinks / presets, **Install** / **Update** / **Remove** |
| console (`--cli`) | `catalog [query]`, `install <name> [--force]`, `uninstall <name>` |
| command line | `python run.py --catalog`, `python run.py --install controller-mouse-keyboard` |

Installing a module downloads every file of it, checks each against the sha256
in the index, writes it to the data folder (`sources/<type>/` in a checkout,
which git ignores), and syncs. Whatever the module `depends` on comes with it.
Installing a **preset** writes it to `presets/` and also installs any module it
uses that isn't installed yet. The last index fetched is cached, so the panel
still lists the catalog offline.

**Any module folder or preset file on disk counts as installed**, however it got
there: from the catalog, uploaded, copied in by hand, or loaded with `--ext`.
Installs and uploads also leave a record of where it came from, its version, and
a digest of its files: `.install.json` in a module's folder, and one shared
`presets/.install-records` for presets. That record is how the panel tells
these apart:

| state | meaning | button |
|---|---|---|
| **installed** | unchanged since it was installed (or no record, but identical to the catalog's) | — |
| **update available** | unchanged locally; the catalog's files differ. Shown as *1.0.0 → 1.1.0*, or as *catalog has an older version* | **Update** / **Downgrade** |
| **modified locally** | its files changed after it was installed (for a preset: saved over) | **Reinstall** (asks first) |
| **local only** | no install record: copied in by hand or from `--ext` | **Replace** (asks first), if the catalog has it |

Installing over a modified or local copy would lose files nobody installed, so
it needs confirming in the panel, `install <name> --force` in the console, or
`--install <name> --force` on the command line.

The catalog location is, first match wins: `$PATCHBAY_CATALOG`, then `catalog`
in `patchbay.toml`, then the modules repo on GitHub. It can be any URL serving
that repo's layout (a fork, GitHub Pages, a LAN server) or a local path, which
is the easy way to develop modules:

```bash
PATCHBAY_CATALOG=path/to/sensor-patchbay-modules python run.py
```

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
  installed plugin, plus its options. Pick one (e.g. `Game controller`), fill in
  its args, hit **add**, and its jacks appear ready to patch — no
  restart. Plugins that need a missing library are listed greyed-out with the
  reason. Each module header has an **✕** to remove it (its cables go with it).
- **Presets** — the dropdown + Load / Save / Save as / New / Delete. A preset is
  the whole graph, saved to `presets/<name>.json`. Diff them, copy them, hand-edit
  them. A preset that needs a source or sink you don't have is marked **⚠** in
  the dropdown. The badge beside it says which (hover it for why), and loading
  it warns too. See [Preset dependencies](#preset-dependencies).
- **Browse…** — search the catalog and install, update or remove sources, sinks
  and presets. See [Module catalog](#module-catalog).
- **Upload… / ⟳ Sync** — add modules and presets from files, and re-read what's
  on disk. See [Adding modules & presets](#adding-modules--presets).
- **Rate** — the `Hz` box in the top bar sets the engine tick rate live.
- **PANIC** — disables every output instantly and releases held keys/buttons.
  Patch any button to `sys/panic.toggle` to get the same switch on hardware.
- Mapping `controller/btn.guide → sys/preset.cycle` (the controller presets do
  this) makes the Xbox / PS / Home button walk through your preset files.

### Adding modules & presets

**Upload…** in the top bar takes a **module** as a `.zip` of its folder, or a
**preset** as a `.json` file. You can pick several at once, or drop files anywhere
on the window. After uploading, the panel syncs on its own. New sources and sinks
then show up in the *add* dropdowns, and new presets in the preset list.
Uploading a module or preset that already exists replaces it.

- A module zip holds one module folder (`hid/__init__.py`, `hid/module.toml`,
  ...). The files can also sit at the top of the zip, which then names the
  module, or under `sources/` / `sinks/`. Outside those, `module.toml` must say
  `kind = "source"` or `"sink"`; every module in the catalog does.
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
patchbay> catalog controller            # search the catalog
patchbay> install controller-mouse      # a preset, plus the modules it uses
patchbay> plugins                       # what can I add?  (the dropdown, as text)
patchbay> add source controller name=dualsense   # add a module live
patchbay> add sink hid
patchbay> ports                         # list every jack on the bus
patchbay> connect controller/tilt.roll hid/key.d
patchbay> save my-rig                   # write presets/my-rig.json
patchbay> install ~/my-module.zip       # add a module (or a preset .json) from a file, then sync
patchbay> sync                          # re-read modules + presets from disk
patchbay> panic on                      # cut all outputs
patchbay> help
```

Anything you do in the console shows up in the browser instantly, and vice-versa —
they're two editors on one engine. `python run.py --no-ui` with neither flag just
runs a preset as a fixed appliance.

---

## Presets

None ship with the engine. Install them from **Browse…** (the *presets* filter),
`install <name>` in the console, or `--install <name>`. The catalog's presets
and what each cable does are listed in the
[modules repo](https://github.com/JustinParkGithub/sensor-patchbay-modules#presets).
Installing a preset also installs the modules it uses.

Your own presets are files in `presets/`: **Save** / **Save as** write them, and
they're plain JSON to diff, copy and hand-edit. Saving over a preset installed
from the catalog marks it *modified locally*, so an update never overwrites
your changes without asking.

Tune magnitudes with a `scale` node in the preset, never in the plugin, so one
preset works across devices that report in different units.

### Preset dependencies

A preset patches into bus namespaces (`controller/…`, `hid/…`). A namespace is an
instance id, not a plugin type, so each preset lists which types can fill each
namespace it uses:

```json
"requires": [
  {"id": "controller", "kind": "source", "types": ["controller"]},
  {"id": "hid",        "kind": "sink",   "types": ["hid"]}
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
| `combine` | merge the cable with a second source port (see below) |

`GET /api/nodes` returns the parameter spec the UI builds its editor from.

### Combining two sources

A cable carries one source, and `combine` adds a second. Click a cable, add a
`combine` node, and pick the other port in its `input` field; a dashed line on the
panel shows the link. For example, to steer the mouse with the gyro only while the
left bumper is held (a "gyro clutch"):

```json
{"source": "controller/gyro.y", "sink": "hid/mouse.dx",
 "chain": [{"type": "combine", "params": {"op": "gate", "input": "controller/btn.lb"}},
           {"type": "scale", "params": {"factor": 10.0}}]}
```

| `op` | output |
|---|---|
| `gate` | the signal while `input` is on, else 0 |
| `unless` | the signal while `input` is off, else 0 |
| `add`, `mul`, `min`, `max` | arithmetic on the two values |
| `and`, `or` | 0/1 from both values |

"On" means `>= level` (default 0.5), so an analog trigger can gate too. The node
works anywhere in the chain, and `input` reads the port's raw value. If its module
isn't running, `input` reads 0: `gate` stays closed, and `unless` stays open.
Removing a module also drops cables that use it as an `input`.

A `gate`/`unless` pair on one modifier button gives each button a second function,
like a macropad layer. For example, patch `controller/btn.a` to both `media/play_pause`
(`unless` `controller/btn.lb`) and `media/next` (`gate` `controller/btn.lb`): A
plays and pauses, and with the bumper held it skips. For the other direction, one source to several sinks, patch one cable to
each. On the console: `combine <conn-id> <op> <port> [level]`.

---

## Ports

`ports` in the console lists every live jack. Source ports are listed in each
source's README (see **Sources & sinks**).

**Sink `hid`** — `mouse.dx`, `mouse.dy` (pixels/second), `mouse.wheel`
(clicks/second), `mouse.{left,right,middle,btn_back,btn_forward}`, and
`key.<name>` for any single character or named key (`space`, `esc`, `enter`,
`tab`, `shift`, `ctrl`, `up`, …).

**Sinks `hotkey`, `media`, `osc`, `webhook`** — `combo.<keys>` (e.g.
`combo.ctrl+shift+t`); `play_pause`, `next`, `previous`, `mute`, `volume.up`,
`volume.down`, `volume.rate`; `fader.1`..`4` and `button.1`..`4` (any port id
works from a preset); `hook.1`..`4`. Each one's docstring in `sinks/<type>/`
has the details.

**Sink `sys`** — `preset.cycle` (rising edge loads the next preset file) and
`panic.toggle` (rising edge toggles panic, same as the PANIC button).

---

## Extending it

> **The full requirements for a source or sink** (manifest keys, ports, what
> `read()`, `apply()`, `release_all()` and `available()` must do, and the
> pull-request checklist) are in the
> [modules repo's README](https://github.com/JustinParkGithub/sensor-patchbay-modules#writing-a-source-or-sink).
> Publish a module by opening a pull request there.

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
They're separate on purpose: a *stand-in* (a simulator, or a second driver for
the same device) can have its own `type` but borrow the real module's `id`, so a
preset built against one runs unchanged on the other.

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

For a complete, working sink to copy, see
[`sinks/hid/`](https://github.com/JustinParkGithub/sensor-patchbay-modules/tree/main/sinks/hid) in the modules repo (virtual mouse + keyboard).

### A new input — subclass `sources.base.Source`

Return `{port_id: float}` from `read()` each tick; flatten vectors to `accel.x`
etc. Keep `read()` non-blocking (do I/O on your own thread, like
[`sources/controller/`](https://github.com/JustinParkGithub/sensor-patchbay-modules/tree/main/sources/controller) or
[`sources/bend4/`](https://github.com/JustinParkGithub/sensor-patchbay-modules/tree/main/sources/bend4)). Decorate with
`@register_source`, give it a `type`/`id`/`ARGS`, and it's selectable the same way
(`--source yourtype[:k=v,...]`, the dropdown, or `add source`).

The full contract — every method, the port/preset formats, the availability rules —
is in [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) §6–7.

### Driving external hardware — write a sink

A sink can speak whatever protocol you like. For hardware that lives on another
machine or behind a slow/blocking transport, keep the real-time loop isolated by
having the sink hand each tick's `{port: value}` to a queue or socket and doing
the actual I/O off the engine thread — the same pattern the source plugins use
for reads.

---

## Layout

```
engine/     signals.py nodes.py graph.py loop.py registry.py   # portable core: bus, transforms, routing, tick, plugin registry
            modules.py                                     # module manifests, patchbay.lock, environment sync
            paths.py library.py presets.py                 # data folder, uploads + sync, preset dependencies
            catalog.py                                     # module catalog: search / install / update / remove
sources/    base.py  (+ installed source folders, git-ignored)    # the plugin contract; modules come from the catalog
sinks/      base.py  hotkey/ media/ osc/ webhook/  (+ installed sink folders, git-ignored)
patchbay.toml                                              # rig config: disable / autostart / core packages / catalog
patchbay.lock                                              # generated per machine (git-ignored): exact packages for installed modules
ui/         src/ (plain TS)    dist/ (committed build)    # patch panel — see ui/README.md
presets/    (installed and saved presets, git-ignored)       # presets come from the catalog
docs/       OVERVIEW.md  SPECIFICATION.md                  # informal + formal docs
control.py  interactive CLI console (--cli)                # reconfigure a headless engine
server.py   http.server + Server-Sent Events + REST       # stdlib only
run.py      entrypoint (and the command line)
app.py      desktop app: native window + tray around run.py's startup
packaging/  sensor-patchbay.spec  requirements.txt         # PyInstaller build of the desktop app
            icon/  make_icons.py (+ the .png/.icns/.ico it writes)   # the logo
tests/      unittest suite (combine node + the software sinks)
.github/    workflows/desktop-app.yml                      # builds every OS; a v* tag publishes a release
```

## Notes

- The **routing core** (`engine/`, the plugin/sink contracts, `EngineLoop.step`)
  is pure standard library — no numpy, no third-party imports — so it ports to a
  microcontroller. `server.py`, `ui/` and modules like the `pynput` sink and the
  SDL `controller` source are PC-only front-ends and I/O adapters bolted on top; on a small board you keep
  the core, call `engine.step(dt)` from your own loop, and reconfigure over the
  CLI. See [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) §12.
- The engine runs at 120 Hz by default; plenty for motion input, comfortable for
  Python without numpy.
- `--selftest` is the CI check: a built-in oscillator source → recording sink, so it
  needs no modules installed. `python -m unittest discover tests` covers the
  `combine` node and the four software sinks without touching OS input.
- Tested here: engine math, the REST API (including the new `/api/plugins` and the
  runtime `/api/source|sink` add/remove endpoints), the SSE stream and its
  `mod_rev` live-refresh signal, presets and panic via `--selftest` and a scripted
  API pass; the plugin registry (`discover`, availability probing,
  `--list-sources`/`--list-sinks`, type-based instantiation) and the CLI console
  via scripted passes. The browser UI, including the catalog panel, has been
  driven in headless Chromium. The `controller` source has been tested against
  SDL's virtual gamepad, not yet with physical controllers; motion and
  touchpad axis signs especially want a check on real hardware.
