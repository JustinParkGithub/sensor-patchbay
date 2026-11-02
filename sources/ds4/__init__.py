"""Sony DualShock 4 over USB or Bluetooth, read as raw HID reports via `hidapi`.

No driver library: the DS4 input report is a fixed layout, parsed here. Over USB
it streams report 0x01 (full data). Over Bluetooth it starts in a reduced 0x01
mode with no motion data; reading feature report 0x02 (calibration) switches it
to the extended 0x11 report, which is the USB layout shifted by two bytes.

Raw units are converted with nominal datasheet scales (no per-unit calibration
beyond a gyro bias taken over the first second — hold the pad still at start).
Tune magnitudes in a preset with a `scale` node, not here.
"""

from __future__ import annotations

import math
import threading
import time

from engine.registry import register_source
from engine.signals import PortSpec, SCALAR, EVENT
from sources.base import Source

SONY_VID = 0x054C
DS4_PIDS = (0x05C4, 0x09CC, 0x0BA0)  # v1, v2, USB wireless adapter

ACCEL_LSB_PER_G = 8192.0
GYRO_LSB_PER_DPS = 16.0
TOUCH_W, TOUCH_H = 1920.0, 942.0

DS4_PORTS = [
    PortSpec("lstick.x", SCALAR, "lstick.x", "sticks", "-1..1"),
    PortSpec("lstick.y", SCALAR, "lstick.y", "sticks", "-1..1", "+ is down"),
    PortSpec("rstick.x", SCALAR, "rstick.x", "sticks", "-1..1"),
    PortSpec("rstick.y", SCALAR, "rstick.y", "sticks", "-1..1", "+ is down"),
    PortSpec("l2", SCALAR, "l2", "triggers", "0..1"),
    PortSpec("r2", SCALAR, "r2", "triggers", "0..1"),
    PortSpec("accel.x", SCALAR, "accel.x", "motion", "g"),
    PortSpec("accel.y", SCALAR, "accel.y", "motion", "g"),
    PortSpec("accel.z", SCALAR, "accel.z", "motion", "g"),
    PortSpec("accel.mag", SCALAR, "accel.mag", "motion", "g", "~1.0 at rest; spikes on shake"),
    PortSpec("gyro.x", SCALAR, "gyro.x (pitch rate)", "motion", "deg/s"),
    PortSpec("gyro.y", SCALAR, "gyro.y (yaw rate)", "motion", "deg/s"),
    PortSpec("gyro.z", SCALAR, "gyro.z (roll rate)", "motion", "deg/s"),
    PortSpec("tilt.pitch", SCALAR, "tilt.pitch", "derived", "deg", "gravity-referenced, drift-free"),
    PortSpec("tilt.roll", SCALAR, "tilt.roll", "derived", "deg", "gravity-referenced, drift-free"),
    PortSpec("touch.x", SCALAR, "touch.x", "touchpad", "0..1", "finger 1 position"),
    PortSpec("touch.y", SCALAR, "touch.y", "touchpad", "0..1", "finger 1 position"),
    PortSpec("touch.dx", SCALAR, "touch.dx", "touchpad", "px/s", "finger 1 drag velocity, touchpad px"),
    PortSpec("touch.dy", SCALAR, "touch.dy", "touchpad", "px/s", "finger 1 drag velocity, touchpad px"),
    PortSpec("battery", SCALAR, "battery", "status", "0..1"),
]
_BTN = ["cross", "circle", "square", "triangle", "l1", "r1", "l2", "r2", "l3", "r3",
        "share", "options", "ps", "touchpad", "touch", "touch2",
        "dpad.up", "dpad.down", "dpad.left", "dpad.right"]
DS4_PORTS += [PortSpec(f"btn.{b}", EVENT, f"btn.{b}", "buttons") for b in _BTN]

# hat value (low nibble of the face-button byte) -> (up, right, down, left); 8 = released
_HAT = {0: (1, 0, 0, 0), 1: (1, 1, 0, 0), 2: (0, 1, 0, 0), 3: (0, 1, 1, 0),
        4: (0, 0, 1, 0), 5: (0, 0, 1, 1), 6: (0, 0, 0, 1), 7: (1, 0, 0, 1)}


@register_source
class DualShock4(Source):
    type = "ds4"
    id = "ds4"
    label = "DualShock 4"
    PORTS = DS4_PORTS
    ARGS = {"path": {"default": None, "type": str,
                     "help": "hidapi device path (default: first DS4 found)"}}

    @classmethod
    def available(cls):
        try:
            import hid  # noqa: F401
        except Exception as e:
            return False, f"needs hidapi ({e})"
        return True

    def __init__(self, path=None):
        import hid  # raises ImportError if not installed
        if path is None:
            found = [d for d in hid.enumerate(SONY_VID) if d["product_id"] in DS4_PIDS]
            if not found:
                raise RuntimeError("no DualShock 4 found (is it plugged in or paired?)")
            path = found[0]["path"]
        elif isinstance(path, str):
            path = path.encode()
        self._dev = hid.device()
        self._dev.open_path(path)
        self._dev.set_nonblocking(False)
        self._ok = True
        self._lock = threading.Lock()
        self._latest = {p.id: 0.0 for p in self.PORTS}
        self._cal_n = 0
        self._gyro_bias = [0.0, 0.0, 0.0]
        self._touch_prev = None          # (id, x, y) of the last finger-1 sample
        self._touch_acc = [0.0, 0.0]     # drag since the last read(), touchpad px
        self._last_read = time.monotonic()
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._poll, name="ds4", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        try:
            self._dev.close()
        except Exception:
            pass

    def status(self):
        return "ok" if self._ok else "disconnected"

    def read(self):
        now = time.monotonic()
        dt = max(now - self._last_read, 1e-3)
        self._last_read = now
        with self._lock:
            out = dict(self._latest)
            out["touch.dx"] = self._touch_acc[0] / dt
            out["touch.dy"] = self._touch_acc[1] / dt
            self._touch_acc = [0.0, 0.0]
        return out

    # ------------------------------------------------------------------
    def _poll(self):
        bt_enabled = False
        while not self._stop.is_set():
            try:
                data = self._dev.read(128, 100)
                self._ok = True
            except Exception:
                self._ok = False
                time.sleep(0.1)
                continue
            if not data:
                continue
            if data[0] == 0x11 and len(data) >= 66:
                base = 3                          # Bluetooth extended report
            elif data[0] == 0x01 and len(data) >= 64:
                base = 1                          # USB report
            else:
                # Bluetooth reduced report: ask for calibration once to switch to 0x11.
                if not bt_enabled:
                    bt_enabled = True
                    try:
                        self._dev.get_feature_report(0x02, 37)
                    except Exception:
                        pass
                continue
            try:
                self._ingest(data, base)
            except Exception:
                pass

    def _ingest(self, d, b):
        g = (_i16(d, b + 12), _i16(d, b + 14), _i16(d, b + 16))

        # calibration: first ~250 reports (~1 s) establish gyro bias
        if self._cal_n < 250:
            self._cal_n += 1
            k = 1.0 / self._cal_n
            for i, v in enumerate(g):
                self._gyro_bias[i] += k * (v - self._gyro_bias[i])

        ax = _i16(d, b + 18) / ACCEL_LSB_PER_G
        ay = _i16(d, b + 20) / ACCEL_LSB_PER_G
        az = _i16(d, b + 22) / ACCEL_LSB_PER_G
        gx, gy, gz = ((v - bias) / GYRO_LSB_PER_DPS for v, bias in zip(g, self._gyro_bias))

        # DS4 lying flat, face up: +y is up out of the face, +z toward the player.
        pitch = math.degrees(math.atan2(az, ay))
        roll = math.degrees(math.atan2(-ax, math.hypot(ay, az)))

        face, mid, sys = d[b + 4], d[b + 5], d[b + 6]
        up, right, down, left = _HAT.get(face & 0x0F, (0, 0, 0, 0))

        # touchpad finger 1: bit 7 of its id byte is set when NOT touching
        t = b + 34
        touching = not (d[t] & 0x80)
        tid = d[t] & 0x7F
        tx = d[t + 1] | ((d[t + 2] & 0x0F) << 8)
        ty = (d[t + 2] >> 4) | (d[t + 3] << 4)
        touching2 = not (d[t + 4] & 0x80)

        out = {
            "lstick.x": _axis(d[b]), "lstick.y": _axis(d[b + 1]),
            "rstick.x": _axis(d[b + 2]), "rstick.y": _axis(d[b + 3]),
            "l2": d[b + 7] / 255.0, "r2": d[b + 8] / 255.0,
            "accel.x": ax, "accel.y": ay, "accel.z": az,
            "accel.mag": math.sqrt(ax * ax + ay * ay + az * az),
            "gyro.x": gx, "gyro.y": gy, "gyro.z": gz,
            "tilt.pitch": pitch, "tilt.roll": roll,
            "touch.x": tx / TOUCH_W if touching else 0.0,
            "touch.y": ty / TOUCH_H if touching else 0.0,
            "battery": min((d[b + 29] & 0x0F) / 10.0, 1.0),
            "btn.square": float(bool(face & 0x10)),
            "btn.cross": float(bool(face & 0x20)),
            "btn.circle": float(bool(face & 0x40)),
            "btn.triangle": float(bool(face & 0x80)),
            "btn.l1": float(bool(mid & 0x01)),
            "btn.r1": float(bool(mid & 0x02)),
            "btn.l2": float(bool(mid & 0x04)),
            "btn.r2": float(bool(mid & 0x08)),
            "btn.share": float(bool(mid & 0x10)),
            "btn.options": float(bool(mid & 0x20)),
            "btn.l3": float(bool(mid & 0x40)),
            "btn.r3": float(bool(mid & 0x80)),
            "btn.ps": float(bool(sys & 0x01)),
            "btn.touchpad": float(bool(sys & 0x02)),
            "btn.touch": float(touching),
            "btn.touch2": float(touching2),
            "btn.dpad.up": float(up), "btn.dpad.right": float(right),
            "btn.dpad.down": float(down), "btn.dpad.left": float(left),
        }

        with self._lock:
            # accumulate drag only while the same finger stays down
            if touching and self._touch_prev and self._touch_prev[0] == tid:
                self._touch_acc[0] += tx - self._touch_prev[1]
                self._touch_acc[1] += ty - self._touch_prev[2]
            self._touch_prev = (tid, tx, ty) if touching else None
            self._latest = out


def _i16(d, i):
    v = d[i] | (d[i + 1] << 8)
    return v - 0x10000 if v & 0x8000 else v


def _axis(raw):
    return max(-1.0, min(1.0, (raw - 128) / 127.0))
