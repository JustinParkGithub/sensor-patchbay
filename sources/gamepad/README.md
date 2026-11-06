# Sources `gamepad` and `zero2` — XInput / DInput controllers, 8BitDo Zero 2

Reads any game controller through SDL2's game controller API (`pysdl2`, with the
SDL2 library from `pysdl2-dll`). Both packages come from
[`module.toml`](module.toml); you only need to connect the controller.

| type | picks |
|---|---|
| `gamepad` | the first controller found, or the first whose name contains `name=` |
| `zero2` | an 8BitDo Zero 2 (USB vendor `2DC8`, or "8BitDo"/"Zero" in its name), else any controller |

Both put their ports under the same `gamepad` id, so a preset built with one runs
on the other. `index=` picks the second, third, … match. The source can be added
before the controller is connected: it shows `searching` until one appears, and
goes back to searching if it's disconnected.

## Connecting

USB or Bluetooth, in any of the controller's gamepad modes.

- **XInput**: every OS sees an Xbox pad. On Windows this is the most reliable
  mode.
- **DInput**: read through SDL's controller database; a pad SDL doesn't know is
  read raw (see below).
- **Switch**: read through SDL's Switch driver, which also provides `accel.*` /
  `gyro.*` if the controller has motion sensors.

On **Linux** your user needs read access to `/dev/input/event*`. Most desktops
grant it to the logged-in user already; otherwise add yourself to the `input`
group. On **macOS** and **Windows** nothing extra is needed.

Input is read in the background, so it reaches the patchbay while another app
has focus.

## 8BitDo Zero 2

The Zero 2 pairs over Bluetooth. Pick the mode by holding a button while
pressing **Start** to turn it on, then hold **Select** for 3 seconds to pair:

| hold | mode |
|---|---|
| Start + X | XInput (Windows) — the 8BitDo name isn't visible here, so `zero2` falls back to the first controller |
| Start + B | DInput (Android) |
| Start + A | macOS |
| Start + Y | Switch |

Its keyboard mode makes it a keyboard rather than a controller, so neither
source sees it; use a gamepad mode.

It has a d-pad, A/B/X/Y, L/R, Select and Start: no sticks, analog triggers or
motion sensors. In some modes it reports the d-pad as left-stick axes, so the
`zero2` type turns the left stick into `dpad.*` and leaves `stick.lx/ly` at 0.
L/R arrive as `btn.lb`/`btn.rb`, Select as `btn.back`.

## Ports

Positional, Xbox-shaped: `btn.a` is the *bottom* face button whatever is printed
on it (so on a Nintendo-layout pad like the Zero 2 it's the one labelled B).

| port | type | |
|---|---|---|
| `stick.lx/ly`, `stick.rx/ry` | scalar | −1..1, up and right are + |
| `trig.l`, `trig.r` | scalar | 0..1 (digital triggers read 0 or 1) |
| `btn.lt`, `btn.rt` | event | the trigger past halfway |
| `btn.{a,b,x,y,lb,rb,back,start,guide,ls,rs}` | event | |
| `dpad.{up,down,left,right}` | event | |
| `accel.x/y/z` | scalar | g — 0 unless the controller reports motion |
| `gyro.x/y/z` | scalar | deg/s, pitch / yaw / roll rate — 0 unless it reports motion |

## Controllers SDL doesn't know

A controller missing from SDL's database is read as a raw joystick in the common
DInput order — axes `lx ly rx ry lt rt`, buttons `a b x y lb rb back start ls rs
guide`, d-pad on the first hat. If yours comes out scrambled, give SDL a mapping
line (generate one with the
[SDL2 Gamepad Tool](https://generalarcade.com/gamepadtool/) or copy one from
[SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB)) in the
`SDL_GAMECONTROLLERCONFIG` environment variable before starting the patchbay.

## Preset

[`gamepad-mouse-keyboard.json`](../../presets/gamepad-mouse-keyboard.json) is
built around the Zero 2's buttons, with sticks and triggers mapped too for
full-size pads; see the main README.
