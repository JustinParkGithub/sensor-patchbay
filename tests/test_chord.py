"""Chord node: two-button combos. Standard library only:
``.venv/bin/python -m unittest discover tests``
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.graph import Connection, Graph          # noqa: E402
from engine.nodes import chain_inputs               # noqa: E402

DT = 1 / 100          # 10 ms ticks
WINDOW = 60.0         # ms


def chord(role, partner, window=WINDOW):
    return [{"type": "chord", "params": {"role": role, "input": partner, "window_ms": window}}]


def combo_graph(window=WINDOW):
    """The three cables the combo builder makes for pad/a + pad/b."""
    return Graph([
        Connection("pad/a", "out/a", chord("solo", "pad/b", window)),
        Connection("pad/b", "out/b", chord("solo", "pad/a", window)),
        Connection("pad/a", "out/ab", chord("both", "pad/b", window)),
    ])


def play(timeline, window=WINDOW):
    """timeline: list of (ticks, a, b). Returns per-tick (out/a, out/b, out/ab)."""
    g = combo_graph(window)
    frames = []
    for ticks, a, b in timeline:
        for _ in range(ticks):
            out = g.tick({"pad/a": float(a), "pad/b": float(b)}, DT)
            frames.append((out["out/a"], out["out/b"], out["out/ab"]))
    return frames


def fired(frames, i):
    return any(f[i] for f in frames)


class ChordNode(unittest.TestCase):
    def test_a_alone_fires_after_the_window(self):
        f = play([(20, 1, 0), (5, 0, 0)])
        self.assertEqual(f[3][0], 0.0)          # still waiting for b at 40 ms
        self.assertEqual(f[10][0], 1.0)         # solo by 110 ms
        self.assertFalse(fired(f, 1) or fired(f, 2))
        self.assertEqual(f[-1][0], 0.0)         # released

    def test_b_alone_fires_its_own_action(self):
        f = play([(20, 0, 1), (5, 0, 0)])
        self.assertTrue(fired(f, 1))
        self.assertFalse(fired(f, 0) or fired(f, 2))

    def test_both_within_the_window_is_the_combo_only(self):
        # a, then b 30 ms later; held, then both let go
        f = play([(3, 1, 0), (20, 1, 1), (5, 0, 0)])
        self.assertTrue(fired(f, 2))
        self.assertFalse(fired(f, 0) or fired(f, 1))
        self.assertEqual(f[-1][2], 0.0)

    def test_same_tick_press_is_the_combo(self):
        f = play([(10, 1, 1), (2, 0, 0)])
        self.assertEqual(f[0], (0.0, 0.0, 1.0))

    def test_quick_tap_still_fires_solo_as_a_pulse(self):
        f = play([(2, 1, 0), (10, 0, 0)])       # 20 ms tap, shorter than the window
        self.assertEqual(sum(1 for x in f if x[0]), 1)
        self.assertFalse(fired(f, 2))

    def test_late_second_press_is_not_a_combo(self):
        # a held past the window, then b: both are solo presses
        f = play([(10, 1, 0), (10, 1, 1), (2, 0, 0)])
        self.assertTrue(fired(f, 0))
        self.assertTrue(fired(f[10:], 1))       # b fires straight away
        self.assertFalse(fired(f, 2))

    def test_releasing_one_leaves_the_other_spent(self):
        f = play([(5, 1, 1), (20, 0, 1), (2, 0, 0)])
        self.assertFalse(fired(f[5:], 1))       # b still held, fires nothing
        self.assertFalse(fired(f[5:], 2))

    def test_holding_one_and_retapping_the_other_repeats_the_combo(self):
        f = play([(5, 1, 1), (3, 0, 1), (5, 1, 1), (3, 0, 1), (5, 1, 1), (2, 0, 0)])
        rises = sum(1 for prev, cur in zip(f, f[1:]) if cur[2] and not prev[2])
        self.assertEqual(rises + (1 if f[0][2] else 0), 3)
        self.assertFalse(fired(f, 0) or fired(f, 1))

    def test_zero_window_means_no_waiting(self):
        f = play([(3, 1, 0), (2, 0, 0)], window=0)
        self.assertEqual(f[0][0], 1.0)

    def test_partner_counts_as_a_chain_input(self):
        g = combo_graph()
        self.assertEqual(chain_inputs(g.connections[0].chain), ["pad/b"])

    def test_roundtrips_through_a_preset_dict(self):
        g = Graph.from_dict(combo_graph().to_dict())
        f = []
        for a, b in [(1, 1)] * 3:
            out = g.tick({"pad/a": a, "pad/b": b}, DT)
            f.append(out["out/ab"])
        self.assertEqual(f, [1.0, 1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
