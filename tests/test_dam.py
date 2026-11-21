"""Combos as a dam: trigger gates on an ordinary source -> sink cable.
``.venv/bin/python -m unittest discover tests``
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.graph import Connection, Graph          # noqa: E402

DT = 1 / 100


def lock(port, when="above", level=0.5):
    """What the combo builder writes for one trigger."""
    return {"type": "combine", "params": {"op": "gate" if when == "above" else "unless",
                                          "input": port, "level": level}}


class Dam(unittest.TestCase):
    def test_pinch_trigger_lets_the_wrist_through_only_while_pinched(self):
        g = Graph([Connection("cv/wrist.x", "hid/mouse.dx",
                              [lock("cv/hand.pinch", "below", 0.3),
                               {"type": "scale", "params": {"factor": 400}}])])
        out = [g.tick({"cv/wrist.x": wx, "cv/hand.pinch": p}, DT)["hid/mouse.dx"]
               for wx, p in [(0.5, 1.0), (-0.2, 0.9), (0.5, 0.1), (-0.25, 0.05), (0.5, 0.8)]]
        self.assertEqual(out, [0.0, 0.0, 200.0, -100.0, 0.0])

    def test_two_triggers_are_two_locks(self):
        g = Graph([Connection("cv/wrist.y", "osc/scale",
                              [lock("cv/hand.pinch", "below", 0.3), lock("pad/btn")])])
        out = [g.tick({"cv/wrist.y": 0.7, "cv/hand.pinch": p, "pad/btn": b}, DT)["osc/scale"]
               for p, b in [(0.1, 0), (1.0, 1), (0.1, 1)]]
        self.assertEqual(out, [0.0, 0.0, 0.7])

    def test_other_cables_on_the_source_are_untouched(self):
        g = Graph([Connection("cv/wrist.x", "hid/mouse.dx", [lock("pad/btn")]),
                   Connection("cv/wrist.x", "osc/x")])
        out = g.tick({"cv/wrist.x": 0.3, "pad/btn": 0}, DT)
        self.assertEqual(out, {"hid/mouse.dx": 0.0, "osc/x": 0.3})


if __name__ == "__main__":
    unittest.main()
