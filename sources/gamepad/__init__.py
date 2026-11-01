"""Any gamepad — XInput, DInput, Switch Pro-style — via SDL2's game controller API
(`pysdl2`, with the SDL2 library itself from `pysdl2-dll`).

SDL maps every controller it knows onto one Xbox-shaped layout, so the ports are
*positional*: ``btn.a`` is the bottom face button whatever is printed on it, and
``btn.lb``/``btn.rb`` are the bumpers. Controllers SDL has no mapping for (some
DInput pads) are read as a raw joystick with the usual axis/button order instead
— add a mapping line to the ``SDL_GAMECONTROLLERCONFIG`` env var if that order is
wrong for yours (see README.md).

Two types share the ``gamepad`` bus id, so presets work with either:

* ``gamepad`` — the first controller found (or the one ``name`` matches);
* ``pico2``   — prefers an 8BitDo Pico 2, falling back to any controller (in
  XInput mode it presents as a generic Xbox pad, with no 8BitDo name to match).

The device is opened from the poll thread and re-found if it's unplugged, so the
source can be added before the controller is connected.
"""

from __future__ import annotations

import ctypes
import math
import threading
import time

from engine.registry import register_source
from engine.signals import PortSpec, SCALAR, EVENT
from sources.base import Source

GAMEPAD_PORTS = [
    PortSpec("stick.lx", SCALAR, "stick.lx", "sticks", "-1..1"),
    PortSpec("stick.ly", SCALAR, "stick.ly", "sticks", "-1..1", "up is +"),
    PortSpec("stick.rx", SCALAR, "stick.rx", "sticks", "-1..1"),
    PortSpec("stick.ry", SCALAR, "stick.ry", "sticks", "-1..1", "up is +"),
    PortSpec("trig.l", SCALAR, "trig.l", "triggers", "0..1"),
    PortSpec("trig.r", SCALAR, "trig.r", "triggers", "0..1"),
]
_BTN = ["a", "b", "x", "y", "lb", "rb", "lt", "rt", "back", "start", "guide", "ls", "rs"]
GAMEPAD_PORTS += [PortSpec(f"btn.{b}", EVENT, f"btn.{b}", "buttons") for b in _BTN]
GAMEPAD_PORTS += [PortSpec(f"dpad.{d}", EVENT, f"dpad.{d}", "dpad")
                  for d in ("up", "down", "left", "right")]
_MOTION_HINT = "0 unless the controller reports motion (e.g. Switch mode)"
GAMEPAD_PORTS += [PortSpec(f"accel.{a}", SCALAR, f"accel.{a}", "motion", "g", _MOTION_HINT)
                  for a in "xyz"]
GAMEPAD_PORTS += [
    PortSpec("gyro.x", SCALAR, "gyro.x (pitch rate)", "motion", "deg/s", _MOTION_HINT),
    PortSpec("gyro.y", SCALAR, "gyro.y (yaw rate)", "motion", "deg/s", _MOTION_HINT),
    PortSpec("gyro.z", SCALAR, "gyro.z (roll rate)", "motion", "deg/s", _MOTION_HINT),
]

TRIGGER_PRESSED = 0.5        # btn.lt / btn.rt: the analog trigger past this
STANDARD_GRAVITY = 9.80665   # SDL reports accel in m/s^2

# SDL calls from more than one instance's poll thread go one at a time.
_SDL_LOCK = threading.Lock()


def _sdl_available():
    try:
        import sdl2  # noqa: F401  (raises if the SDL2 library itself can't be found)
    except Exception as e:
        return False, f"needs pysdl2 + pysdl2-dll ({e})"
    return True


@register_source
class Gamepad(Source):
    type = "gamepad"
    id = "gamepad"
    label = "Gamepad (XInput / DInput)"
    PORTS = GAMEPAD_PORTS
    ARGS = {
        "name": {"default": None, "type": str,
                 "help": "use the first controller whose name contains this (case-insensitive)"},
        "index": {"default": 0, "type": int, "help": "which matching controller, 0 = first"},
    }
    # Tried in order before falling back to any controller; (usb vendor id, name substrings).
    PREFER: tuple[int | None, tuple[str, ...]] | None = None

    @classmethod
    def available(cls):
        return _sdl_available()

    def __init__(self, name=None, index=0):
        import sdl2  # noqa: F401  (fail at construction, like the other sources)
        self._name = (name or "").lower() or None
        self._index = int(index or 0)
        self._state = "searching"
        self._lock = threading.Lock()
        self._latest = {p.id: 0.0 for p in self.PORTS}
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._run, name=self.type, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def status(self):
        return self._state

    def read(self):
        with self._lock:
            return dict(self._latest)

    # ------------------------------------------------------------------
    def _run(self):
        import sdl2
        # No window of ours ever has focus, so input must count in the background;
        # and keep A/B/X/Y positional on Nintendo-layout pads (SDL swaps them by default).
        sdl2.SDL_SetHint(sdl2.SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, b"1")
        sdl2.SDL_SetHint(sdl2.SDL_HINT_GAMECONTROLLER_USE_BUTTON_LABELS, b"0")
        flags = sdl2.SDL_INIT_GAMECONTROLLER | sdl2.SDL_INIT_JOYSTICK | sdl2.SDL_INIT_SENSOR
        with _SDL_LOCK:
            if sdl2.SDL_InitSubSystem(flags) != 0:
                self._state = f"error: {sdl2.SDL_GetError().decode(errors='replace')}"
                return
            # Polled, not evented: nothing here runs an SDL event loop.
            sdl2.SDL_JoystickEventState(sdl2.SDL_IGNORE)
            sdl2.SDL_GameControllerEventState(sdl2.SDL_IGNORE)
        dev = None
        try:
            while not self._stop.is_set():
                if dev is None:
                    with _SDL_LOCK:
                        sdl2.SDL_JoystickUpdate()   # also detects newly attached devices
                        dev = self._open()
                    if dev is None:
                        self._state = "searching"
                        self._publish({p.id: 0.0 for p in self.PORTS})
                        self._stop.wait(0.5)
                        continue
                    self._state = "ok"
                with _SDL_LOCK:
                    sdl2.SDL_GameControllerUpdate()
                    if not dev.attached():
                        dev.close()
                        dev = None
                        self._state = "disconnected"
                        continue
                    try:
                        out = dev.read()
                    except Exception:
                        out = None
                if out is not None:
                    self._publish(out)
                time.sleep(1 / 250)
        finally:
            with _SDL_LOCK:
                if dev is not None:
                    dev.close()
                sdl2.SDL_QuitSubSystem(flags)

    def _publish(self, out):
        with self._lock:
            self._latest = out

    def _open(self):
        """Open the controller this instance should use, or None if there isn't one."""
        import sdl2
        found = []
        for i in range(sdl2.SDL_NumJoysticks()):
            name = (sdl2.SDL_JoystickNameForIndex(i) or b"").decode(errors="replace")
            vendor = sdl2.SDL_JoystickGetDeviceVendor(i)
            found.append((i, name, vendor))
        if self._name:
            found = [f for f in found if self._name in f[1].lower()]
        elif self.PREFER:
            vid, names = self.PREFER
            preferred = [f for f in found
                         if f[2] == vid or any(n in f[1].lower() for n in names)]
            found = preferred or found
        if self._index >= len(found):
            return None
        i, name, _ = found[self._index]
        if sdl2.SDL_IsGameController(i):
            gc = sdl2.SDL_GameControllerOpen(i)
            return _Controller(gc, name) if gc else None
        js = sdl2.SDL_JoystickOpen(i)
        return _RawJoystick(js, name) if js else None


@register_source
class Pico2(Gamepad):
    type = "pico2"
    label = "8BitDo Pico 2"
    PREFER = (0x2DC8, ("8bitdo", "pico"))   # 8BitDo's USB vendor id


# ----------------------------------------------------------------- device readers
def _axis(v):
    """SDL axis (-32768..32767) -> -1..1."""
    return max(-1.0, min(1.0, v / 32767.0))


class _Controller:
    """A device SDL has a game-controller mapping for: named, positional inputs."""

    def __init__(self, gc, name):
        import sdl2
        self.gc = gc
        self.name = name
        self.motion = []
        for kind in (sdl2.SDL_SENSOR_ACCEL, sdl2.SDL_SENSOR_GYRO):
            if (sdl2.SDL_GameControllerHasSensor(gc, kind)
                    and sdl2.SDL_GameControllerSetSensorEnabled(gc, kind, sdl2.SDL_TRUE) == 0):
                self.motion.append(kind)
        self._buf = (ctypes.c_float * 3)()

    def attached(self):
        import sdl2
        return bool(sdl2.SDL_GameControllerGetAttached(self.gc))

    def close(self):
        import sdl2
        sdl2.SDL_GameControllerClose(self.gc)

    def read(self):
        import sdl2
        gc = self.gc
        ax = lambda a: _axis(sdl2.SDL_GameControllerGetAxis(gc, a))   # noqa: E731
        bt = lambda b: float(sdl2.SDL_GameControllerGetButton(gc, b))  # noqa: E731
        tl = max(0.0, ax(sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT))
        tr = max(0.0, ax(sdl2.SDL_CONTROLLER_AXIS_TRIGGERRIGHT))
        out = {
            "stick.lx": ax(sdl2.SDL_CONTROLLER_AXIS_LEFTX),
            "stick.ly": -ax(sdl2.SDL_CONTROLLER_AXIS_LEFTY),
            "stick.rx": ax(sdl2.SDL_CONTROLLER_AXIS_RIGHTX),
            "stick.ry": -ax(sdl2.SDL_CONTROLLER_AXIS_RIGHTY),
            "trig.l": tl, "trig.r": tr,
            "btn.lt": float(tl > TRIGGER_PRESSED), "btn.rt": float(tr > TRIGGER_PRESSED),
            "btn.a": bt(sdl2.SDL_CONTROLLER_BUTTON_A),
            "btn.b": bt(sdl2.SDL_CONTROLLER_BUTTON_B),
            "btn.x": bt(sdl2.SDL_CONTROLLER_BUTTON_X),
            "btn.y": bt(sdl2.SDL_CONTROLLER_BUTTON_Y),
            "btn.lb": bt(sdl2.SDL_CONTROLLER_BUTTON_LEFTSHOULDER),
            "btn.rb": bt(sdl2.SDL_CONTROLLER_BUTTON_RIGHTSHOULDER),
            "btn.back": bt(sdl2.SDL_CONTROLLER_BUTTON_BACK),
            "btn.start": bt(sdl2.SDL_CONTROLLER_BUTTON_START),
            "btn.guide": bt(sdl2.SDL_CONTROLLER_BUTTON_GUIDE),
            "btn.ls": bt(sdl2.SDL_CONTROLLER_BUTTON_LEFTSTICK),
            "btn.rs": bt(sdl2.SDL_CONTROLLER_BUTTON_RIGHTSTICK),
            "dpad.up": bt(sdl2.SDL_CONTROLLER_BUTTON_DPAD_UP),
            "dpad.down": bt(sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN),
            "dpad.left": bt(sdl2.SDL_CONTROLLER_BUTTON_DPAD_LEFT),
            "dpad.right": bt(sdl2.SDL_CONTROLLER_BUTTON_DPAD_RIGHT),
            "accel.x": 0.0, "accel.y": 0.0, "accel.z": 0.0,
            "gyro.x": 0.0, "gyro.y": 0.0, "gyro.z": 0.0,
        }
        # SDL's controller frame: +x right, +y up, +z toward the player.
        for kind in self.motion:
            if sdl2.SDL_GameControllerGetSensorData(gc, kind, self._buf, 3) != 0:
                continue
            x, y, z = self._buf
            if kind == sdl2.SDL_SENSOR_ACCEL:
                out["accel.x"], out["accel.y"], out["accel.z"] = (
                    x / STANDARD_GRAVITY, y / STANDARD_GRAVITY, z / STANDARD_GRAVITY)
            else:
                out["gyro.x"], out["gyro.y"], out["gyro.z"] = (
                    math.degrees(x), math.degrees(y), math.degrees(z))
        return out


class _RawJoystick:
    """A device with no SDL mapping, read in the common DInput order:
    axes lx, ly, rx, ry[, lt, rt]; buttons a, b, x, y, lb, rb, back, start, ls, rs,
    guide; d-pad on hat 0 (or buttons 11-14 when there's no hat)."""

    BUTTONS = ["a", "b", "x", "y", "lb", "rb", "back", "start", "ls", "rs", "guide"]

    def __init__(self, js, name):
        import sdl2
        self.js = js
        self.name = name
        self.n_axes = sdl2.SDL_JoystickNumAxes(js)
        self.n_buttons = sdl2.SDL_JoystickNumButtons(js)
        self.n_hats = sdl2.SDL_JoystickNumHats(js)

    def attached(self):
        import sdl2
        return bool(sdl2.SDL_JoystickGetAttached(self.js))

    def close(self):
        import sdl2
        sdl2.SDL_JoystickClose(self.js)

    def read(self):
        import sdl2
        js = self.js
        ax = lambda i: _axis(sdl2.SDL_JoystickGetAxis(js, i)) if i < self.n_axes else 0.0  # noqa: E731
        bt = lambda i: float(sdl2.SDL_JoystickGetButton(js, i)) if i < self.n_buttons else 0.0  # noqa: E731
        # Raw triggers rest at -1; with no trigger axes they read 0.
        tl = (ax(4) + 1.0) / 2.0 if self.n_axes > 4 else 0.0
        tr = (ax(5) + 1.0) / 2.0 if self.n_axes > 5 else 0.0
        out = {p.id: 0.0 for p in GAMEPAD_PORTS}
        out.update({
            "stick.lx": ax(0), "stick.ly": -ax(1), "stick.rx": ax(2), "stick.ry": -ax(3),
            "trig.l": tl, "trig.r": tr,
            "btn.lt": float(tl > TRIGGER_PRESSED), "btn.rt": float(tr > TRIGGER_PRESSED),
        })
        for i, b in enumerate(self.BUTTONS):
            out[f"btn.{b}"] = bt(i)
        if self.n_hats:
            hat = sdl2.SDL_JoystickGetHat(js, 0)
            out["dpad.up"] = float(bool(hat & sdl2.SDL_HAT_UP))
            out["dpad.down"] = float(bool(hat & sdl2.SDL_HAT_DOWN))
            out["dpad.left"] = float(bool(hat & sdl2.SDL_HAT_LEFT))
            out["dpad.right"] = float(bool(hat & sdl2.SDL_HAT_RIGHT))
        else:
            for i, d in enumerate(("up", "down", "left", "right"), start=len(self.BUTTONS)):
                out[f"dpad.{d}"] = bt(i)
        return out
