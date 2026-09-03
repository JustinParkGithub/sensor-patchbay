"""Headless sink: no OS input, just a throttled log of what it *would* do. Use it
over SSH, in CI, or with ``--dry-run``. Registers as ``hid`` so presets built for
the real mouse/keyboard sink load unchanged."""

from __future__ import annotations

import time

from sinks.mouse_keyboard import MouseKeyboardSink


class NullSink(MouseKeyboardSink):
    label = "mouse + keyboard · dry-run"

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
