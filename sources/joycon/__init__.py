"""Nintendo Switch Joy-Con (R) over Bluetooth, via `joycon-python` (`pyjoycon`).

Pairing is done at the OS level (see README.md in this folder); this plugin just opens the already
paired HID device. If the library or the device is missing, construction raises —
``run.py`` catches that and falls back to the mock source so the rest of the
pipeline still runs.

Raw sensor units are arbitrary but stable. Tune them in a preset with a `scale`
node rather than here, so your mappings stay portable to the mock source.
"""

from __future__ import annotations

import math
import threading
import time

from engine.registry import register_source
from engine.signals import PortSpec, SCALAR, EVENT
from sources.base import Source

# Shared by the mock source so presets built against one work against the other.
JOYCON_PORTS = [
    PortSpec("stick.x", SCALAR, "stick.x", "stick", "-1..1"),
    PortSpec("stick.y", SCALAR, "stick.y", "stick", "-1..1"),
    PortSpec("accel.x", SCALAR, "accel.x", "motion", "g"),
    PortSpec("accel.y", SCALAR, "accel.y", "motion", "g"),
    PortSpec("accel.z", SCALAR, "accel.z", "motion", "g"),
    PortSpec("accel.mag", SCALAR, "accel.mag", "motion", "g", "~1.0 at rest; spikes on shake"),
    PortSpec("gyro.x", SCALAR, "gyro.x (pitch rate)", "motion", "deg/s"),
    PortSpec("gyro.y", SCALAR, "gyro.y (yaw rate)", "motion", "deg/s"),
    PortSpec("gyro.z", SCALAR, "gyro.z (roll rate)", "motion", "deg/s"),
    PortSpec("tilt.pitch", SCALAR, "tilt.pitch", "derived", "deg", "gravity-referenced, drift-free"),
    PortSpec("tilt.roll", SCALAR, "tilt.roll", "derived", "deg", "gravity-referenced, drift-free"),
]
_BTN = ["a", "b", "x", "y", "r", "zr", "sl", "sr", "plus", "home", "rstick"]
JOYCON_PORTS += [PortSpec(f"btn.{b}", EVENT, f"btn.{b}", "buttons") for b in _BTN]

ACCEL_LSB_PER_G = 4096.0
GYRO_DPS_PER_LSB = 0.06103
STICK_HALF_RANGE = 1400.0


@register_source
class JoyConR(Source):
    type = "joycon"
    id = "joycon"
    label = "Joy-Con (R)"
    PORTS = JOYCON_PORTS

    @classmethod
    def available(cls):
        try:
            import pyjoycon  # noqa: F401
        except Exception as e:
            return False, f"needs joycon-python/hidapi ({e})"
        return True

    def __init__(self):
        from pyjoycon import JoyCon, get_R_id  # raises ImportError if not installed
        ids = get_R_id()
        if not ids or ids[0] is None:
            raise RuntimeError("no right Joy-Con found (is it paired and connected?)")
        self._jc = JoyCon(*ids)
        self._ok = True
        self._lock = threading.Lock()
        self._latest = {p.id: 0.0 for p in self.PORTS}
        self._cal_n = 0
        self._gyro_bias = [0.0, 0.0, 0.0]
        self._stick_center = [2048.0, 2048.0]
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._poll, name="joycon", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def status(self):
        return "ok" if self._ok else "disconnected"

    def read(self):
        with self._lock:
            return dict(self._latest)

    # ------------------------------------------------------------------
    def _poll(self):
        while not self._stop.is_set():
            try:
                st = self._jc.get_status()
                self._ok = True
            except Exception:
                self._ok = False
                time.sleep(0.1)
                continue
            try:
                self._ingest(st)
            except Exception:
                pass
            time.sleep(1 / 120)

    def _ingest(self, st):
        a = st["accel"]
        g = st["gyro"]
        s = st["analog-sticks"]["right"]
        b = st["buttons"]

        # calibration: first ~90 frames establish gyro bias + stick centre
        if self._cal_n < 90:
            self._cal_n += 1
            k = 1.0 / self._cal_n
            for i, v in enumerate((g["x"], g["y"], g["z"])):
                self._gyro_bias[i] += k * (v - self._gyro_bias[i])
            self._stick_center[0] += k * (s["horizontal"] - self._stick_center[0])
            self._stick_center[1] += k * (s["vertical"] - self._stick_center[1])

        ax = a["x"] / ACCEL_LSB_PER_G
        ay = a["y"] / ACCEL_LSB_PER_G
        az = a["z"] / ACCEL_LSB_PER_G
        gx = (g["x"] - self._gyro_bias[0]) * GYRO_DPS_PER_LSB
        gy = (g["y"] - self._gyro_bias[1]) * GYRO_DPS_PER_LSB
        gz = (g["z"] - self._gyro_bias[2]) * GYRO_DPS_PER_LSB

        # Joy-Con R resting orientation: +x out the rail, +y up the buttons, +z out the face.
        pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az)))
        roll = math.degrees(math.atan2(ay, az))

        out = {
            "stick.x": _clamp((s["horizontal"] - self._stick_center[0]) / STICK_HALF_RANGE),
            "stick.y": _clamp((s["vertical"] - self._stick_center[1]) / STICK_HALF_RANGE),
            "accel.x": ax, "accel.y": ay, "accel.z": az,
            "accel.mag": math.sqrt(ax * ax + ay * ay + az * az),
            "gyro.x": gx, "gyro.y": gy, "gyro.z": gz,
            "tilt.pitch": pitch, "tilt.roll": roll,
        }
        right = b.get("right", {})
        shared = b.get("shared", {})
        out["btn.a"] = float(right.get("a", 0))
        out["btn.b"] = float(right.get("b", 0))
        out["btn.x"] = float(right.get("x", 0))
        out["btn.y"] = float(right.get("y", 0))
        out["btn.r"] = float(right.get("r", 0))
        out["btn.zr"] = float(right.get("zr", 0))
        out["btn.sl"] = float(right.get("sl", 0))
        out["btn.sr"] = float(right.get("sr", 0))
        out["btn.plus"] = float(shared.get("plus", 0))
        out["btn.home"] = float(shared.get("home", 0))
        out["btn.rstick"] = float(shared.get("r-stick", 0))

        with self._lock:
            self._latest = out


def _clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))
