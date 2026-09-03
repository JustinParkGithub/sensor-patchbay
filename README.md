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
Joy-Con (R)  ──BT──►  plugins/joycon_r.py ──►  engine (bus + graph + nodes) ──►  sinks/mouse_keyboard.py ──►  OS
                              ▲                        ▲     ▲                             ▲
                         mock source            fixed 120 Hz  presets/*.json         sinks/generic_out.py ──UDP──► your robot bridge
                                                        │
                                              ui/  (patch panel, SSE + REST)
```

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

**Sink `hid`** — `mouse.dx`, `mouse.dy` (pixels/second), `mouse.wheel`
(clicks/second), `mouse.{left,right,middle,btn_back,btn_forward}`, and
`key.<name>` for any single character or named key (`space`, `esc`, `enter`,
`tab`, `shift`, `ctrl`, `up`, …).

**Sink `sys`** — `preset.cycle` (rising edge loads the next preset file).

**Sink `robot`** (only with `--robot`) — `axis.0..5`, `gripper`, `e-stop`, plus
any port id you invent; see below.

---

## Extending it

### A new output — subclass `sinks.base.Sink`

```python
from engine.signals import PortSpec, SCALAR, EVENT
from sinks.base import Sink

class MidiSink(Sink):
    id = "midi"; label = "MIDI out"
    PORTS = [PortSpec("cc.1", SCALAR, "mod wheel", "midi"),
             PortSpec("note.60", EVENT, "middle C", "midi")]
    def start(self): import rtmidi; self.out = rtmidi.MidiOut(); self.out.open_port(0)
    def apply(self, values, dt):
        if "cc.1" in values: self.out.send_message([0xB0, 1, int(values["cc.1"] * 127)])
    def release_all(self): ...
```

Register it in `engine/registry`-style wiring inside `run.py` (`build_sinks`).

### A new input — subclass `plugins.base.Source`

Return `{port_id: float}` from `read()` each tick; flatten vectors to
`accel.x` etc. Keep `read()` non-blocking (do I/O on your own thread, like
`plugins/joycon_r.py`).

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
engine/     signals.py  nodes.py  graph.py  loop.py      # bus, transforms, routing, fixed-rate loop
plugins/    base.py  joycon_r.py  mock.py                 # sources
sinks/      base.py  mouse_keyboard.py  null.py  generic_out.py
ui/         index.html  style.css  app.js                 # patch panel — vanilla, no build step
presets/    mouse.json  keyboard.json
bridges/    serial_bridge.py                              # example robot bridge
server.py   http.server + Server-Sent Events + REST       # stdlib only
run.py      entrypoint
```

## Notes

- The engine loop, the graph and every node are pure standard library. The web UI
  is served by `http.server` and talks over `fetch` + `EventSource`. `pynput` and
  `joycon-python` are the only third-party pieces, and only for real I/O.
- The engine runs at 120 Hz by default; that is plenty for motion input and keeps
  Python comfortable without numpy.
- `--selftest` is the CI check (mock source → dry-run sink, asserts the snapshot).
- Tested here: engine math, the REST API, the SSE stream, presets and panic via
  `--selftest` and a scripted API pass. The browser UI's JavaScript is
  syntax- and logic-checked but was not rendered in a real browser in the build
  environment — give it a visual once-over on first run.
```
