# joycon-patchbay

A working slice of the **sensor → routing → command** pipeline, using a Nintendo
Switch **Joy-Con (R)** as the input instead of hardware that hasn't shipped yet.

Motion and buttons from the Joy-Con come in over Bluetooth, get normalised onto a
typed signal bus, run through a hot-editable **routing graph** (scale, curve,
deadzone, smoothing, thresholds, gesture gates…), and drive a **virtual mouse and
keyboard**. You wire it together in a browser-based **patch panel** that runs
entirely offline and saves its presets as plain JSON on the machine.

Every layer here is the real one except the Pico firmware. When the stretch
sensors arrive you add a single file — `plugins/pico_serial.py` — and the graph,
the transforms, the GUI, the output adapters and the presets are unchanged.

```
Joy-Con (R)  ──BT───►  plugins/joycon_r.py  ─┐
                                              ├─►  engine (bus + graph + nodes) ──►  sinks/mouse_keyboard.py ──►  OS
Nano + BMI160 ──USB──► plugins/arduino_bmi160.py ─┘        ▲     ▲                             ▲
                                                     fixed 120 Hz  presets/*.json         sinks/generic_out.py ──UDP──► your robot bridge
                                                            │
                                                  ui/  (patch panel, SSE + REST)
```

Every source and sink is a plugin registered by `id` in `engine/registry.py`
(`--list-sources` / `--list-sinks` shows what's available). Joy-Con/mock and
the mouse+keyboard sink have their own dedicated flags below because they're
deliberate stand-ins for each other under one shared bus id; anything else —
the BMI160, a future MIDI or OSC sink, another sensor — is added with
`--source`/`--sink` and no changes to `run.py`. See **Extending it**.

---

## Quick start

```bash
cd joycon-patchbay
python -m pip install -r requirements.txt        # only needed for the real Joy-Con + real mouse/keyboard

python run.py --mock --dry-run                    # no hardware, no real input events — just explore the UI
#   open http://127.0.0.1:8420

python run.py                                     # real Joy-Con if paired, real mouse/keyboard
python run.py --preset keyboard                   # start on the tilt-to-WASD preset
```

`run.py` degrades gracefully: no Joy-Con paired → synthetic **mock** source; no
`pynput` / no display → **dry-run** sink that logs instead of moving the cursor.

| flag | effect |
|---|---|
| `--mock` | force the synthetic source (oscillators shaped like real Joy-Con ports) |
| `--dry-run` | don't touch the real mouse/keyboard; print what would happen |
| `--preset NAME` | load `presets/NAME.json` at startup (default `mouse`) |
| `--robot` | also fan every routed signal out to `sinks/generic_out.py` (UDP/JSON) |
| `--rate HZ` | engine tick rate (default 120) |
| `--list-ports` | print every source/sink port and exit |
| `--source NAME[:k=v,...]` | add a registered source plugin (repeatable) — e.g. `--source bmi160:port=/dev/ttyUSB0` |
| `--sink NAME[:k=v,...]` | add a registered sink plugin (repeatable) — e.g. `--sink robot:host=192.168.1.5` |
| `--list-sources` / `--list-sinks` | list what's registered and its constructor args, then exit |
| `--selftest` | headless: run mock → dry-run for 2 s, assert, exit |
| `--host` / `--port` | bind address for the UI (default `127.0.0.1:8420`) |

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

This *adds* the `bmi160` source alongside the default Joy-Con/mock slot — both
run at once, so you can patch either (or both) into the same sinks. `--preset
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
- **Presets** — the dropdown + Load / Save / Save as / New / Delete. A preset is
  the whole graph, saved to `presets/<name>.json`. Diff them, copy them, hand-edit
  them.
- **PANIC** — disables every output instantly and releases held keys/buttons.
- Mapping `joycon/btn.home → sys/preset.cycle` (both shipped presets do this) makes
  the Home button walk through your preset files.

### Type rules

Ports are `scalar` (continuous) or `event` (0/1 gate or a pulse). `scalar → event`
is allowed but you almost always want a `threshold` or `schmitt` node in between,
or the key/button chatters. The UI highlights compatible sink jacks when you arm a
source.

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

**Sink `robot`** (only with `--robot`) — `axis.0..5`, `gripper`, `e-stop`, plus
any port id you invent; see below.

---

## Extending it

Every source and sink is a plugin registered by `id` in a small registry
(`engine/registry.py`) so adding one is *one new file* — no edits to `run.py`,
the engine, or the UI. `--list-sources` / `--list-sinks` show everything
currently registered, including the constructor args each one takes.

### A new output — subclass `sinks.base.Sink`

```python
from engine.registry import register_sink
from engine.signals import PortSpec, SCALAR, EVENT
from sinks.base import Sink

@register_sink
class MidiSink(Sink):
    id = "midi"; label = "MIDI out"
    PORTS = [PortSpec("cc.1", SCALAR, "mod wheel", "midi"),
             PortSpec("note.60", EVENT, "middle C", "midi")]
    ARGS = {"port_name": {"default": None, "type": str, "help": "MIDI output port"}}
    def __init__(self, port_name=None): self._port_name = port_name
    def start(self): import rtmidi; self.out = rtmidi.MidiOut(); self.out.open_port(0)
    def apply(self, values, dt):
        if "cc.1" in values: self.out.send_message([0xB0, 1, int(values["cc.1"] * 127)])
    def release_all(self): ...
```

Drop that in `sinks/midi.py` and it's immediately usable as
`python run.py --sink midi` (or `--sink midi:port_name=IAC Driver`) — nothing
else to touch. `@register_sink` + `id` is all `--list-sinks` and `--sink` need
to find it; `ARGS` is only for CLI parsing (types + `--list-sinks` help text).

### A new input — subclass `plugins.base.Source`

Return `{port_id: float}` from `read()` each tick; flatten vectors to
`accel.x` etc. Keep `read()` non-blocking (do I/O on your own thread, like
`plugins/joycon_r.py` or `plugins/arduino_bmi160.py`). Decorate with
`@register_source` (from `engine.registry`) the same way, and it's usable as
`--source yourid[:k=v,...]`.

The one exception: don't register a class that's a deliberate *stand-in* for
another under the same `id` (the mock Joy-Con, the dry-run HID sink) — the
registry is one-class-per-id, and that choice is already made explicitly in
`run.py` (`--mock`, `--dry-run`) rather than left to the registry to arbitrate.

### A robot arm — use the `robot` sink, write a bridge

`sinks/generic_out.py` is intentionally protocol-agnostic: with `--robot` it
sends one JSON datagram per tick to `127.0.0.1:9870` —

```json
{"t": 12.34, "axis.0": 0.12, "axis.1": -0.4, "gripper": 1.0}
```

— and knows nothing about how it's consumed. You write a small **bridge** that
receives that feed and speaks your hardware's language: ROS 2, Dynamixel SDK,
serial G-code, CAN, LeRobot, OSC. `bridges/serial_bridge.py` is a complete
example (UDP → pyserial). This keeps the real-time routing loop isolated from
slow or blocking transport, and lets the bridge run on another machine.

```bash
python run.py --robot
python bridges/serial_bridge.py /dev/ttyACM0 --map axis.0,axis.1,gripper
```

---

## Layout

```
engine/     signals.py  nodes.py  graph.py  loop.py  registry.py   # bus, transforms, routing, fixed-rate loop, plugin registry
plugins/    base.py  joycon_r.py  mock.py  arduino_bmi160.py        # sources
sinks/      base.py  mouse_keyboard.py  null.py  generic_out.py
ui/         index.html  style.css  app.js                 # patch panel — vanilla, no build step
presets/    mouse.json  keyboard.json  bmi160-mouse.json
firmware/   bmi160_nano/bmi160_nano.ino                    # Arduino Nano + BMI160 sketch
bridges/    serial_bridge.py                              # example robot bridge
server.py   http.server + Server-Sent Events + REST       # stdlib only
run.py      entrypoint
```

## Notes

- The engine loop, the graph and every node are pure standard library. The web UI
  is served by `http.server` and talks over `fetch` + `EventSource`. `pynput`,
  `joycon-python` and `pyserial` are the only third-party pieces, and only for
  real I/O.
- The engine runs at 120 Hz by default; that is plenty for motion input and keeps
  Python comfortable without numpy.
- `--selftest` is the CI check (mock source → dry-run sink, asserts the snapshot).
- Tested here: engine math, the REST API, the SSE stream, presets and panic via
  `--selftest` and a scripted API pass; the plugin registry (`discover`,
  `--list-sources`/`--list-sinks`, `--source`/`--sink` instantiation) with a
  scripted CLI pass. `plugins/arduino_bmi160.py`'s parser/calibration/tilt math
  is unit-tested against synthetic serial frames — it has not been run against
  a real Nano+BMI160 in the build environment; check `--list-ports` picks up
  `bmi160` and the meters move once you have the hardware in hand. The browser
  UI's JavaScript is syntax- and logic-checked but was not rendered in a real
  browser in the build environment — give it a visual once-over on first run.
```
