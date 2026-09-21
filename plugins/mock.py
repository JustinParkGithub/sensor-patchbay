"""Synthetic 'Joy-Con' source: same ports as the real one, driven by slow
oscillators so you can build and test patches with no hardware.

A distinct plugin *type* (``mock``) from the real Joy-Con (``joycon``), but it
borrows the real device's default bus *id* (``joycon``) so a preset built here
runs unchanged once a real Joy-Con is paired. It needs no third-party packages,
so it is always available — the guaranteed fallback when no hardware is present.
"""

from __future__ import annotations

import math
import time

from engine.registry import register_source
from plugins.base import Source
from plugins.joycon_r import JOYCON_PORTS


@register_source
class MockJoyCon(Source):
    type = "mock"
    id = "joycon"
    label = "Joy-Con (R) · mock"
    PORTS = JOYCON_PORTS

    def __init__(self):
        self._t0 = time.perf_counter()

    def status(self):
        return "mock"

    def read(self):
        t = time.perf_counter() - self._t0
        roll = 35.0 * math.sin(t * 0.7)
        pitch = 25.0 * math.sin(t * 0.5 + 1.0)
        shake = 1.0 if (t % 6.0) < 0.15 else 0.0     # periodic "shake" spike
        return {
            "stick.x": 0.6 * math.sin(t * 1.3),
            "stick.y": 0.6 * math.cos(t * 1.1),
            "accel.x": math.sin(math.radians(pitch)),
            "accel.y": math.sin(math.radians(roll)),
            "accel.z": 1.0,
            "accel.mag": 1.0 + 2.0 * shake,
            "gyro.x": 60.0 * math.cos(t * 0.5 + 1.0),
            "gyro.y": 40.0 * math.sin(t * 0.9),
            "gyro.z": 90.0 * math.cos(t * 0.7),
            "tilt.pitch": pitch,
            "tilt.roll": roll,
            "btn.a": 1.0 if (t % 4.0) < 0.4 else 0.0,
            "btn.zr": 1.0 if (t % 3.0) < 0.6 else 0.0,
            "btn.r": 0.0, "btn.b": 0.0, "btn.x": 0.0, "btn.y": 0.0,
            "btn.sl": 0.0, "btn.sr": 0.0, "btn.plus": 0.0,
            "btn.home": 0.0,  # real btn.home cycles presets; mock leaves it alone
            "btn.rstick": 0.0,
        }
