"""Headless sink: no OS input, just a throttled log of what it *would* do. Use it
over SSH, in CI, on a headless Pi, or with ``--dry-run``.

A distinct plugin *type* (``dryrun``) from the real HID sink (``hid``), but it
borrows the real sink's default bus *id* (``hid``) so presets built for the real
mouse/keyboard load unchanged. Needs nothing beyond the standard library, so it
is always available — the guaranteed fallback when ``pynput`` or a display is
missing."""

from __future__ import annotations

import time

from engine.registry import register_sink
from sinks.mouse_keyboard import MouseKeyboardSink


@register_sink
class NullSink(MouseKeyboardSink):
    type = "dryrun"
    id = "hid"
    label = "mouse + keyboard · dry-run"

    @classmethod
    def available(cls):
        return True

    def __init__(self):
        super().__init__()
        self._last_log = 0.0
        self._acc = {}

    def start(self):
        pass

    def status(self):
        return "dry-run"

    def apply(self, values, dt):
        active = {k: round(v, 3) for k, v in values.items() if abs(v) > 1e-3}
        for k, v in active.items():
            self._acc[k] = v
        now = time.perf_counter()
        if active and now - self._last_log > 0.5:
            self._last_log = now
            print("  [hid:dry-run]", " ".join(f"{k}={v}" for k, v in sorted(active.items())))

    def release_all(self):
        self._acc.clear()
