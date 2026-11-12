"""Keyboard chords, the staple macropad action: one gate presses a whole combo.

The ``hid`` sink can press ``key.ctrl`` and ``key.c`` from two cables, but it
doesn't order them. Here each combo presses its modifiers first and releases them
last, and a key shared by two held combos stays down until both let go.

Port semantics
--------------
  combo.<keys>   event gate: >=0.5 held = combo down. <keys> are joined by "+",
                 using the same names as hid's key.<name> ("ctrl+c", "cmd+shift+4").

The ``combos`` arg picks which combos appear as jacks. Any combo.<keys> works from
a preset, listed or not.
"""

from __future__ import annotations

import sys
import time

from engine.registry import register_sink
from engine.signals import PortSpec, EVENT
from sinks.hid import MIN_HOLD_S, MouseKeyboardSink

_MOD = "cmd" if sys.platform == "darwin" else "ctrl"
DEFAULT_COMBOS = f"{_MOD}+c {_MOD}+v {_MOD}+z {_MOD}+shift+z {_MOD}+tab"


@register_sink
class HotkeySink(MouseKeyboardSink):
    type = "hotkey"
    id = "hotkey"
    label = "hotkeys (key combos)"
    ARGS = {
        "combos": {"default": DEFAULT_COMBOS, "type": str,
                   "help": "space-separated combos to show as jacks, e.g. ctrl+c cmd+shift+4"},
    }

    def __init__(self, combos=DEFAULT_COMBOS):
        super().__init__()
        self.PORTS = [PortSpec(f"combo.{c}", EVENT, c, "combos") for c in str(combos).split()]
        self.PORTS.append(PortSpec("combo.<keys>", EVENT, "combo.<any>", "combos",
                                   hint="any combo works from a preset"))
        self._held: dict[str, float] = {}     # combo -> press time
        self._refs: dict[str, int] = {}       # key -> how many held combos use it

    def apply(self, values, dt):
        if self._kbd is None:
            return
        wanted = sorted(p.split(".", 1)[1] for p, v in values.items()
                        if p.startswith("combo.") and v >= 0.5 and "<" not in p)
        now = time.perf_counter()
        for combo in list(self._held):
            if combo not in wanted and now - self._held[combo] >= MIN_HOLD_S:
                self._release(combo)
        for combo in wanted:
            if combo not in self._held:
                self._press(combo, now)

    def _press(self, combo, now):
        self._held[combo] = now
        for key in combo.split("+"):
            if not self._refs.get(key):
                self._key_press(key, True)
            self._refs[key] = self._refs.get(key, 0) + 1

    def _release(self, combo):
        del self._held[combo]
        for key in reversed(combo.split("+")):
            self._refs[key] -= 1
            if not self._refs[key]:
                self._key_press(key, False)
                del self._refs[key]

    def release_all(self):
        for combo in list(self._held):
            self._release(combo)
