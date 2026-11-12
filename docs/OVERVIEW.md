# sensor-patchbay — the friendly overview

This is the "sit down and get it" version. For exact contracts and protocols see
[`SPECIFICATION.md`](SPECIFICATION.md); for setup and hardware tutorials see the
[`README`](../README.md).

## What is it?

It's a **patchbay for motion**. Think of an old audio patch panel: jacks on the
left, jacks on the right, and you run a cable from one to the other. Here the
left-hand jacks are *things that sense the world* (a Joy-Con's gyro, an
accelerometer on an Arduino, whatever you plug in) and the right-hand jacks are
*things that do stuff* (move the mouse, press keys, wiggle a servo, fly a drone).
You draw a cable between them and the sensor now drives the thing — live, no
restart.

Each cable can have a little **chain of tweaks** on it: scale it up, ignore the
jittery middle (a deadzone), smooth it, turn "past 20°" into a key press. You
build all of this by clicking, and you save it as a **preset** — just a JSON file
you can copy, diff, and hand to a friend.

## The pipeline, in one breath

```
  sensor  ──►  named signals on a bus  ──►  routing graph (cables + tweaks)  ──►  output
 (source)         joycon/gyro.x                  scale · deadzone · expo               (sink)
                  bmi160/accel.mag                threshold · debounce                  hid/mouse.dx
                                                                                        gpio/pwm.0
```

1. **Sources** produce named numbers every tick: `joycon/gyro.x`,
   `bmi160/accel.mag`, and so on. Everything is just a number.
2. The **bus** carries those numbers. Names are `who/what` — the instance and the
   port.
3. The **routing graph** is your cables. Each cable pulls one source number,
   pushes it through its chain of tweak *nodes*, and drops the result on a sink.
4. **Sinks** take the numbers and make something happen in the real world.

It ticks 120 times a second by default, which is plenty for motion and leaves
Python relaxed.

## Two ways to drive it — same brain

- **The patch panel (GUI).** Open `http://127.0.0.1:8420`. Click a source jack,
  click a sink jack, you've got a cable. Click the cable to shape it. Great when
  you have a screen.
- **The console (CLI).** `python run.py --no-ui --cli` gives you a `patchbay>`
  prompt. `add sink gpio`, `connect bmi160/tilt.roll gpio/pwm.0`, `save myrig`.
  Great when the whole thing is running headless on a Pi and you're on SSH.

They're two windows onto the *same* running engine. Anything you can click you can
type, and vice-versa. Change something in the console and the browser updates
itself; no refresh.

## Sources and sinks are a menu, not a wiring job

You don't recompile to change hardware. Every source and sink is a **plugin**, and
the running app shows them as a menu:

- In the GUI there's an **"add source" / "add sink" dropdown** at the bottom of
  each column. Pick one, fill in its options (serial port, pins, …), hit add. It
  appears with its jacks, ready to patch. Each module has an ✕ to remove it.
- In the console it's `plugins` to see the menu and `add source bmi160
  port=/dev/ttyACM0` to add one.

Each plugin's folder declares the libraries it needs, and the app installs them
on start. A plugin that still can't run, for example because there's no Joy-Con
paired or it's the Pi-only GPIO sink on a laptop, shows up in the menu greyed
out, with a note explaining why, instead of silently vanishing.

## What gets installed (declarative, NixOS-style)

Every source and sink is a folder like `sources/bmi160/`. Next to its code is a
`module.toml` that lists the Python packages it needs (`python = ["pyserial"]`),
any files to download (the camera tracker's model), and setup steps pip can't do
for you (pairing, permissions). The folders on disk *are* the configuration.
`patchbay.toml` can `disable` a module, or `autostart` some. Nothing starts on its
own by default.

On every start the app compares the installed packages with that declaration and
makes them match **exactly**. Missing packages are installed, and packages no
enabled module needs are removed, so nothing is left over. The exact versions are
pinned in a committed `patchbay.lock`, so every machine gets the same set. When
nothing changed, this check is instant and needs no internet. To strip the camera
tracker's large libraries from a machine, add `disable = ["cv"]` and restart.

## Adding your own thing (an "extension")

This is the whole point of the design: **adding hardware is one file, no core
edits.** Want to send signals to a drone's flight controller, or blink an LED on a
Pi, or read a new sensor?

1. Make a folder named after your plugin: `sinks/drone/` or `sources/mysensor/`.
2. Put the code in its `__init__.py`. A sink subclasses `Sink` and implements
   `apply(values, dt)`; a source subclasses `Source` and implements `read()`.
   Give it a `type` (its menu name, the same as the folder name), an `id` (the
   name its jacks live under), and an `ARGS` dict of its options.
3. Add a `module.toml` listing the packages it needs, e.g.
   `python = ["pymavlink"]`.
4. Start the app. Its packages get installed, and it appears in the dropdown.

There's a complete, working example in
[`sinks/gpio/`](https://github.com/JustinParkGithub/sensor-patchbay-modules/tree/main/sinks/gpio): it drives
Raspberry Pi GPIO pins — PWM channels for servos or a drone's ESCs, digital pins
for relays — and, cleverly, falls back to just *printing* what it would do when
you're building the patch on a laptop with no Pi attached. Copy it as your
starting point.

Keep your heavy `import` inside `__init__`/`start` (not at the top of the file) and
add an `available()` method. Then your plugin lists itself politely even on a
machine that can't run it yet.

## "Runs on a microcontroller too"

The routing brain — the bus, the tweak nodes, the graph, the tick — is pure
standard-library Python with no PC-only dependencies. The mouse driver, the web
server, and the browser UI are *front-ends* bolted on for the desktop. On a small
board you keep the brain and swap the front-ends: call `engine.step(dt)` from the
board's own loop instead of the desktop's background thread, register on-device
sources/sinks, and reconfigure over the CLI. Because presets are just JSON keyed
by stable names, a mapping you built in the browser on your laptop runs unchanged
on the board. The precise porting contract is §12 of the spec.

## The safety valve

There's a **PANIC** button (and a `panic` console command, and a
`sys/panic.toggle` jack you can patch a physical button to). Hit it and every
output is cut and everything held is released — keys up, servos to neutral. Use it
the instant a mapping does something you didn't expect.

## Where things live

```
engine/     the brain: signals · nodes · graph · loop · registry   (portable core) + modules (installs)
sources/    base.py + installed source folders (from the module catalog; git-ignored)
sinks/      base.py + installed sink folders   — the catalog repo is sensor-patchbay-modules
patchbay.toml / patchbay.lock   what's enabled / exactly which packages that means
ui/         the browser patch panel (plain TypeScript, no framework; built dist/ is committed)
presets/    saved graphs, plain JSON
control.py  the CLI console
server.py   the local web server (HTTP + SSE + REST)
run.py      the entry point
docs/       this overview + the formal spec
```
