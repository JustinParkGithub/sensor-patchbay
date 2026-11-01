# Sources `gamepad` and `pico2` — XInput / DInput controllers, 8BitDo Pico 2

Reads any game controller through SDL2's game controller API (`pysdl2`, with the
SDL2 library from `pysdl2-dll`). Both packages come from
[`module.toml`](module.toml); you only need to connect the controller.

| type | picks |
|---|---|
| `gamepad` | the first controller found, or the first whose name contains `name=` |
| `pico2` | an 8BitDo Pico 2 (USB vendor `2DC8`, or "8BitDo" in its name), else any controller |

Both put their ports under the same `gamepad` id, so a preset built with one runs
on the other. `index=` picks the second, third, … match. The source can be added
before the controller is connected: it shows `searching` until one appears, and
goes back to searching if it's unplugged.

## Connecting

USB or Bluetooth, in any of the controller's modes (on 8BitDo pads the mode is
picked with a switch or a button held at power-on — see its manual):

- **XInput** — every OS sees an Xbox pad. On Windows
  this is the most reliable mode. The 8BitDo name isn't visible in this mode, so
  `pico2` falls back to the first controller.
- **DInput** — read through SDL's controller database;
  a pad SDL doesn't know is read raw (see below).
- **Switch** — read through SDL's Switch driver, which
  also provides `accel.*` / `gyro.*` if the controller has motion sensors.

On **Linux** your user needs read access to `/dev/input/event*` — most desktops
grant it to the logged-in user already; otherwise add yourself to the `input`
group. On **macOS** and **Windows** nothing extra is needed.

Input is read in the background, so it reaches the patchbay while another app
has focus.

## Ports

Positional, Xbox-shaped: `btn.a` is the *bottom* face button whatever is printed
on it (so on a Nintendo-layout pad it's the one labelled B).

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

[`gamepad-mouse-keyboard.json`](../../presets/gamepad-mouse-keyboard.json) drives
the mouse and keyboard from the pad; see the main README.
