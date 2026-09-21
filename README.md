# sensor-patchbay

A **sensor → routing → command** pipeline: named signals from any sensor go on a
typed bus, run through a hot-editable **routing graph** (scale, curve, deadzone,
smoothing, thresholds, gesture gates…), and drive any output. The shipping input
is a Nintendo Switch **Joy-Con (R)** and an **Arduino Nano + BMI160**; the
shipping output is a **virtual mouse & keyboard** — but sources and sinks are
plugins you pick from a menu, add live, and extend with one file.

You wire it together in a browser-based **patch panel**, or, on a headless board,
from an on-device **CLI console** — two front-ends over one engine. It runs
entirely offline and saves presets as plain JSON.

```
Joy-Con (R)  ──BT───►  plugins/joycon_r.py       ─┐
Nano + BMI160 ──USB──► plugins/arduino_bmi160.py  ┤                                 ┌─► sinks/mouse_keyboard.py ──► OS
your sensor  ──────►   extensions/*.py            ├─► engine (bus + graph + nodes) ─┤
                                                  ┘        ▲          ▲             └─► extensions/*.py ──────► GPIO / …
                                                     fixed 120 Hz  presets/*.json
                                                           │
                                     ui/ (patch panel)  +  control.py (CLI console)  — same engine, two editors
```

Every source and sink is a **plugin** with a `type` (the menu / CLI name) and an
`id` (the bus namespace its ports live under). They're chosen at runtime — a
dropdown in the GUI, `add source|sink` in the console, or `--source`/`--sink` on
the command line — and a new one is a single file dropped in `extensions/`, no
edits to `run.py`, the engine, or the UI. See **Choosing sources & sinks** and
**Extending it**, and the deeper [`docs/`](docs) (an informal
[overview](docs/OVERVIEW.md) and a formal [specification](docs/SPECIFICATION.md)).

---

## Quick start

```bash
cd sensor-patchbay
python -m pip install -r requirements.txt        # only needed for the real Joy-Con + real mouse/keyboard

python run.py                                     # start empty; open the UI and add modules live
#   open http://127.0.0.1:8420

python run.py --mock --dry-run                    # no hardware, no real input events — just explore
python run.py --sink hid --mock --preset mouse    # real mouse/keyboard, synthetic source, air-mouse
```

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
| `--ext DIR` | also load extension plugins from `DIR` (repeatable) |
| `--selftest` | headless: run mock → dry-run for 2 s, assert, exit |
| `--host` / `--port` | bind address for the UI (default `127.0.0.1:8420`) |

You never *need* `--source`/`--sink`: it's usually easier to add modules live from
the GUI dropdown or the console (below). The flags are for scripting a fixed rig.

---

## Pairing the Joy-Con over Bluetooth

The Joy-Con pairs as a standard Bluetooth HID gamepad. Hold the small **round
sync button** on the rail (between SL and SR) until the lights run back and forth,
then pair from the OS:

- **Linux** — `bluetoothctl` → `scan on` → `pair <MAC>` → `connect <MAC>` → `trust <MAC>`.
  You then need read access to the hidraw node. Drop this in
  `/etc/udev/rules.d/70-joycon.rules` and `sudo udevadm control --reload && sudo udevadm trigger`:

  ```
  # Nintendo Switch Joy-Con / Pro Controller — user access to hidraw
  KERNEL=="hidraw*", KERNELS=="*057E:200[6-9]*", MODE="0660", TAG+="uaccess"
  SUBSYSTEM=="hidraw", ATTRS{idVendor}=="057e", MODE="0660", TAG+="uaccess"
  ```

  If a system service grabs the Joy-Con first (`joycond`), stop/mask it so
  `pyjoycon` can open the device: `sudo systemctl stop joycond`.

- **macOS** — pair from  System Settings ▸ Bluetooth. `hidapi` can open it with no
  extra permissions.

- **Windows** — pair from  Settings ▸ Bluetooth & devices. Works via the default
  HID driver.

Check it's visible:

```bash
python run.py --list-ports
python -c "from pyjoycon import get_R_id; print(get_R_id())"   # -> (1406, 8199, '...') when found
```

The right Joy-Con held horizontally (SL/SR up, rail to the left) is the reference
orientation for `tilt.pitch` / `tilt.roll`.

---

## Adding a source: Arduino Nano + BMI160

`plugins/arduino_bmi160.py` reads a Nano running `firmware/bmi160_nano/bmi160_nano.ino`
over USB serial — no Bluetooth, no pairing, just a cable.

**Wire it up** (I2C): BMI160 `VCC`→`5V` (or `3V3`, check your breakout),
`GND`→`GND`, `SCL`→`A5`, `SDA`→`A4`.

**Flash it**: open `firmware/bmi160_nano/bmi160_nano.ino` in the Arduino IDE,
install the **BMI160-Arduino** library (Library Manager, or
https://github.com/hanyazou/BMI160-Arduino), select *Arduino Nano* as the
board, upload.

**Run it**:

```bash
python -m pip install -r requirements.txt      # adds pyserial
python run.py --source bmi160 --preset bmi160-mouse
#   port is auto-detected; if that fails, or you have more than one board
#   plugged in, be explicit:
python run.py --source bmi160:port=/dev/ttyACM0     # Linux
python run.py --source bmi160:port=COM5             # Windows
python run.py --source bmi160:port=/dev/cu.usbserial-1420   # macOS
```

This pre-loads the `bmi160` source; add a mouse/keyboard sink (`--sink hid`, or
from the UI) to drive anything, and patch either into it. You can run several
sources at once — a second board just gets a suffixed id (`bmi160-2`). `--preset
bmi160-mouse` is a starting air-mouse mapping (`gyro.x/y` → cursor, a shake
past 2.2 g → left-click) since this board has no buttons of its own; wire up
whatever else you like in the patch panel.

**Linux serial permissions**: your user needs to be in the `dialout` group
(`sudo usermod -aG dialout $USER`, then log out/in) or the port opens with
"Permission denied".

**If ports look wrong or jump around**: the firmware sends a fixed ±2 g /
±250 deg/s range explicitly (`BMI160.setAccelerometerRange`/`setGyroRange` in
the sketch) — `ACCEL_LSB_PER_G`/`GYRO_LSB_PER_DPS` at the top of
`plugins/arduino_bmi160.py` assume exactly that. Change both sides together if
you reconfigure the sensor's range. If pitch/roll are inverted for how you've
mounted the board, that's an orientation convention, not a bug — flip the axis
with an `invert` node in the patch panel rather than editing the plugin.

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
  them.
- **Rate** — the `Hz` box in the top bar sets the engine tick rate live.
- **PANIC** — disables every output instantly and releases held keys/buttons.
- Mapping `joycon/btn.home → sys/preset.cycle` (both shipped presets do this) makes
  the Home button walk through your preset files.

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

Raw Joy-Con sensor units are arbitrary but stable — tune magnitudes with a
`scale` node in the preset, never in the plugin, so a preset built against the
mock source works unchanged on real hardware.

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

**Source `joycon`** — `stick.x/y`, `accel.x/y/z`, `accel.mag`, `gyro.x/y/z`,
`tilt.pitch`, `tilt.roll`, `btn.{a,b,x,y,r,zr,sl,sr,plus,home,rstick}`.
`gyro.*` is deg/s, `accel.*` is g, `tilt.*` is gravity-referenced degrees
(drift-free), `accel.mag` ≈ 1.0 at rest and spikes on a shake.

**Source `bmi160`** (with `--source bmi160`) — `accel.x/y/z`, `accel.mag`,
`gyro.x/y/z`, `tilt.pitch`, `tilt.roll`. Same units and the same derived-tilt
convention as `joycon` above; no buttons or stick — it's a bare IMU.

**Sink `hid`** — `mouse.dx`, `mouse.dy` (pixels/second), `mouse.wheel`
(clicks/second), `mouse.{left,right,middle,btn_back,btn_forward}`, and
`key.<name>` for any single character or named key (`space`, `esc`, `enter`,
`tab`, `shift`, `ctrl`, `up`, …).

**Sink `sys`** — `preset.cycle` (rising edge loads the next preset file).

---

## Extending it

Adding a source or sink is **one new file** — no edits to `run.py`, the engine, or
the UI. Drop it in [`extensions/`](extensions) and it shows up in the GUI dropdown,
the console's `add` command, `--list-sources`/`--list-sinks`, and the
`--source`/`--sink` flags. (You can also `--ext DIR` or set `PATCHBAY_EXT_PATH` to
load from anywhere.)

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

Save it as `extensions/midi_sink.py` and it's immediately selectable — from the
dropdown, `add sink midi port_name=…`, or `--sink midi:port_name=IAC Driver`.
`ARGS` is what the GUI builds its little form from and what the CLI coerces values
against (its `type` picks the input widget). Import your third-party dependency
**lazily** (inside `__init__`/`start`, never at module top) and add `available()`
so a machine without the library still lists it politely instead of failing to
load.

There's a complete, working example already in the tree:
[`extensions/example_gpio_sink.py`](extensions/example_gpio_sink.py) drives
Raspberry Pi GPIO — PWM channels for servos / drone ESCs, digital pins for relays —
and falls back to logging when there's no Pi, so you can build the patch on a
laptop. Copy it.

### A new input — subclass `plugins.base.Source`

Return `{port_id: float}` from `read()` each tick; flatten vectors to `accel.x`
etc. Keep `read()` non-blocking (do I/O on your own thread, like
`plugins/joycon_r.py` or `plugins/arduino_bmi160.py`). Decorate with
`@register_source`, give it a `type`/`id`/`ARGS`, and it's selectable the same way
(`--source yourtype[:k=v,...]`, the dropdown, or `add source`).

The full contract — every method, the port/preset formats, the availability rules —
is in [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) §6–7.

### Driving external hardware — write a sink

A sink can speak whatever protocol you like. For hardware that lives on another
machine or behind a slow/blocking transport, keep the real-time loop isolated by
having the sink hand each tick's `{port: value}` to a queue or socket and doing
the actual I/O off the engine thread — the same pattern the source plugins use
for reads. `extensions/example_gpio_sink.py` (below) is a complete working sink
to copy.

---

## Layout

```
engine/     signals.py  nodes.py  graph.py  loop.py  registry.py   # portable core: bus, transforms, routing, tick, plugin registry
plugins/    base.py  joycon_r.py  mock.py  arduino_bmi160.py        # sources
sinks/      base.py  mouse_keyboard.py  null.py            # sinks
extensions/ README.md  example_gpio_sink.py                # drop-in plugins — your own sources/sinks go here
ui/         index.html  style.css  app.js                 # patch panel — vanilla, no build step
presets/    mouse.json  keyboard.json  bmi160-mouse.json
firmware/   bmi160_nano/bmi160_nano.ino                    # Arduino Nano + BMI160 sketch
docs/       OVERVIEW.md  SPECIFICATION.md                  # informal + formal docs
control.py  interactive CLI console (--cli)                # reconfigure a headless engine
server.py   http.server + Server-Sent Events + REST       # stdlib only
run.py      entrypoint
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
  via scripted passes. `plugins/arduino_bmi160.py`'s parser/calibration/tilt math
  is unit-tested against synthetic serial frames — it has not been run against a
  real Nano+BMI160 here; check `--list-ports` picks up `bmi160` and the meters move
  once you have the hardware. The browser UI's JavaScript is syntax- and
  logic-checked but was not rendered in a real browser here — give it a visual
  once-over on first run.
