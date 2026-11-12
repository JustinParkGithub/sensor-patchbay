"""OS media keys: transport controls and system volume.

Port semantics
--------------
  play_pause, next, previous, mute,
  volume.up, volume.down    event gate: >=0.5 held = media key down
  volume.rate               scalar, volume steps per second (+ up, - down); a
                            stick or tilt works as a volume knob
"""

from __future__ import annotations

from engine.registry import register_sink
from engine.signals import PortSpec, SCALAR, EVENT
from sinks.hid import MouseKeyboardSink

_KEYS = {
    "play_pause": "media_play_pause",
    "next": "media_next",
    "previous": "media_previous",
    "mute": "media_volume_mute",
    "volume.up": "media_volume_up",
    "volume.down": "media_volume_down",
}
_MAX_STEPS_PER_TICK = 4   # a huge scale factor shouldn't flood the OS with key events


@register_sink
class MediaSink(MouseKeyboardSink):
    type = "media"
    id = "media"
    label = "media keys + volume"
    PORTS = [
        *(PortSpec(p, EVENT, p, "volume" if p.startswith(("volume", "mute")) else "transport")
          for p in _KEYS),
        PortSpec("volume.rate", SCALAR, "volume.rate", "volume", "steps/s"),
    ]

    def __init__(self):
        super().__init__()
        self._fv = 0.0

    def apply(self, values, dt):
        if self._kbd is None:
            return
        # hid's gate handling already holds a key for at least MIN_HOLD_S
        super().apply({f"key.{k}": values.get(p, 0.0) for p, k in _KEYS.items()}, dt)

        self._fv += values.get("volume.rate", 0.0) * dt
        steps = int(self._fv)
        self._fv -= steps
        key = "media_volume_up" if steps > 0 else "media_volume_down"
        for _ in range(min(abs(steps), _MAX_STEPS_PER_TICK)):
            self._key_press(key, True)
            self._key_press(key, False)

    def release_all(self):
        super().release_all()
        self._fv = 0.0
