"""Combine node and the software sinks. Standard library only, no OS input:
``.venv/bin/python -m unittest discover tests``
"""

import json
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import presets                          # noqa: E402
from engine.graph import Connection, Graph          # noqa: E402
from engine.loop import EngineLoop                  # noqa: E402
from engine.nodes import chain_inputs               # noqa: E402
from sinks.hotkey import HotkeySink                 # noqa: E402
from sinks.media import MediaSink                   # noqa: E402
from sinks.osc import OscSink, encode_message       # noqa: E402
from sinks.webhook import WebhookSink               # noqa: E402

DT = 1 / 120


def combine(op, port="pad/btn", level=0.5):
    return {"type": "combine", "params": {"op": op, "input": port, "level": level}}


def run(op, x, other, level=0.5):
    g = Graph([Connection("pad/x", "out/y", [combine(op, level=level)])])
    bus = {"pad/x": x} if other is None else {"pad/x": x, "pad/btn": other}
    return g.tick(bus, DT)["out/y"]


class CombineNode(unittest.TestCase):
    def test_gate_follows_the_second_port(self):
        self.assertEqual(run("gate", 7.0, 0.0), 0.0)
        self.assertEqual(run("gate", 7.0, 1.0), 7.0)

    def test_gate_is_closed_when_second_port_is_absent(self):
        self.assertEqual(run("gate", 7.0, None), 0.0)

    def test_unless_is_the_opposite_layer(self):
        self.assertEqual(run("unless", 7.0, 0.0), 7.0)
        self.assertEqual(run("unless", 7.0, 1.0), 0.0)

    def test_level_lets_an_analog_trigger_gate(self):
        self.assertEqual(run("gate", 7.0, 0.3, level=0.25), 7.0)
        self.assertEqual(run("gate", 7.0, 0.2, level=0.25), 0.0)

    def test_arithmetic_and_logic(self):
        for op, x, y, want in [("add", 2, 3, 5), ("mul", 2, 3, 6), ("min", 2, 3, 2),
                               ("max", 2, 3, 3), ("and", 1, 1, 1), ("and", 1, 0, 0),
                               ("or", 0, 1, 1), ("or", 0, 0, 0)]:
            self.assertEqual(run(op, float(x), float(y)), want, op)

    def test_unset_input_closes_the_gate(self):
        g = Graph([Connection("pad/x", "out/y", [{"type": "combine", "params": {"input": ""}}])])
        self.assertEqual(g.tick({"pad/x": 7.0}, DT)["out/y"], 0.0)

    def test_chain_after_the_gate_still_runs(self):
        chain = [combine("gate"), {"type": "scale", "params": {"factor": 2.0}}]
        g = Graph([Connection("pad/x", "out/y", chain)])
        self.assertEqual(g.tick({"pad/x": 3.0, "pad/btn": 1.0}, DT)["out/y"], 6.0)

    def test_roundtrips_through_a_preset_dict(self):
        g = Graph([Connection("pad/x", "out/y", [combine("gate")])])
        again = Graph.from_dict(json.loads(json.dumps(g.to_dict())))
        self.assertEqual(again.tick({"pad/x": 3.0, "pad/btn": 1.0}, DT)["out/y"], 3.0)


class CombineInTheEngine(unittest.TestCase):
    def test_preset_requires_the_second_inputs_module(self):
        preset = {"connections": [{"source": "a/x", "sink": "s/y", "chain": [combine("gate", "b/btn")]}]}
        self.assertEqual(chain_inputs(preset["connections"][0]["chain"]), ["b/btn"])
        self.assertIn(("source", "b"), presets.namespaces(preset))

    def test_removing_the_second_inputs_module_drops_the_cable(self):
        class Src:
            def module(self): ...
            def start(self): ...
            def stop(self): ...

        keep = Connection("a/x", "s/y")
        gated = Connection("a/x", "s/y", [combine("gate", "b/btn")])
        with tempfile.TemporaryDirectory() as d:
            eng = EngineLoop({"a": Src(), "b": Src()}, {}, Graph([keep, gated]), d)
            self.assertEqual(eng.remove_source("b"), 1)
            self.assertEqual([c.id for c in eng.graph.connections], [keep.id])


def fake_pynput(sink):
    """Record key presses instead of sending them to the OS."""
    log = []
    sink._kbd = sink._mouse = object()
    sink._key_press = lambda name, down: log.append(("down" if down else "up", name))
    sink._btn_map = lambda name: name   # mouse buttons need a real pynput Button
    sink._hold = lambda *a: None
    return log


class Hotkey(unittest.TestCase):
    def test_modifiers_go_down_first_and_up_last(self):
        s = HotkeySink()
        log = fake_pynput(s)
        s.apply({"combo.ctrl+shift+c": 1.0}, DT)
        self.assertEqual(log, [("down", "ctrl"), ("down", "shift"), ("down", "c")])
        log.clear()
        s._held["ctrl+shift+c"] -= 1.0     # past the minimum hold
        s.apply({}, DT)
        self.assertEqual(log, [("up", "c"), ("up", "shift"), ("up", "ctrl")])

    def test_short_pulse_is_held_for_the_minimum(self):
        s = HotkeySink()
        log = fake_pynput(s)
        s.apply({"combo.ctrl+c": 1.0}, DT)
        s.apply({}, DT)
        self.assertNotIn(("up", "c"), log)

    def test_shared_modifier_stays_down_until_both_release(self):
        s = HotkeySink()
        log = fake_pynput(s)
        s.apply({"combo.ctrl+c": 1.0, "combo.ctrl+v": 1.0}, DT)
        self.assertEqual(log.count(("down", "ctrl")), 1)
        s._held["ctrl+c"] -= 1.0
        s.apply({"combo.ctrl+v": 1.0}, DT)
        self.assertNotIn(("up", "ctrl"), log)
        s.release_all()
        self.assertEqual(log.count(("up", "ctrl")), 1)

    def test_combos_arg_sets_the_jacks(self):
        ids = [p.id for p in HotkeySink(combos="ctrl+c cmd+shift+4").PORTS]
        self.assertEqual(ids, ["combo.ctrl+c", "combo.cmd+shift+4", "combo.<keys>"])


class Media(unittest.TestCase):
    def test_gate_presses_the_media_key(self):
        s = MediaSink()
        log = fake_pynput(s)
        s.apply({"play_pause": 1.0}, DT)
        self.assertEqual(log, [("down", "media_play_pause")])

    def test_volume_rate_accumulates_into_steps(self):
        s = MediaSink()
        log = fake_pynput(s)
        for _ in range(126):               # just over a second at 5 steps/s, then down
            s.apply({"volume.rate": 5.0}, DT)
        self.assertEqual(log.count(("down", "media_volume_up")), 5)
        log.clear()
        s.release_all()                    # drop the fractional step left over
        s.apply({"volume.rate": -240.0}, DT)
        self.assertEqual(log.count(("down", "media_volume_down")), 2)


class Osc(unittest.TestCase):
    def setUp(self):
        self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx.bind(("127.0.0.1", 0))
        self.rx.settimeout(1.0)
        self.sink = OscSink(port=self.rx.getsockname()[1])
        self.sink.start()
        self.addCleanup(self.rx.close)
        self.addCleanup(self.sink.stop)

    def recv(self):
        data = self.rx.recv(256)
        return data[:-4], struct.unpack(">f", data[-4:])[0]

    def test_wire_format_matches_the_osc_spec(self):
        self.assertEqual(encode_message("/a/b", 1.0),
                         b"/a/b\0\0\0\0" + b",f\0\0" + b"\x3f\x80\0\0")

    def test_sends_changes_only(self):
        self.sink.apply({"fader.1": 0.5}, DT)
        self.sink.apply({"fader.1": 0.5}, DT)
        self.sink.apply({"fader.1": 0.25}, DT)
        self.assertEqual(self.recv()[1], 0.5)
        self.assertEqual(self.recv()[1], 0.25)

    def test_silence_and_panic_send_zero(self):
        self.sink.apply({"button.1": 1.0}, DT)
        self.assertEqual(self.recv(), (encode_message("/patchbay/button/1", 0.0)[:-4], 1.0))
        self.sink.apply({}, DT)
        self.assertEqual(self.recv()[1], 0.0)
        self.sink.apply({"button.2": 1.0}, DT)
        self.recv()
        self.sink.release_all()
        self.assertEqual(self.recv()[1], 0.0)


class Webhook(unittest.TestCase):
    def setUp(self):
        got = self.got = []
        done = self.done = threading.Event()

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                got.append(json.loads(self.rfile.read(n)))
                self.send_response(204)
                self.end_headers()
                done.set()

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/x"

    def test_fires_once_per_rising_edge(self):
        s = WebhookSink(url1=self.url)
        s.start()
        self.addCleanup(s.stop)
        s.apply({"hook.1": 1.0}, DT)
        s.apply({"hook.1": 1.0}, DT)
        self.assertTrue(self.done.wait(2.0))
        s.stop()
        self.assertEqual(self.got, [{"port": "hook.1", "value": 1.0}])
        self.assertEqual(s.status(), "ok")

    def test_refuses_non_http_urls(self):
        with self.assertRaises(ValueError):
            WebhookSink(url1="file:///etc/passwd")

    def test_unreachable_url_reports_in_status_without_raising(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            dead = f"http://127.0.0.1:{probe.getsockname()[1]}/"
        s = WebhookSink(url1=dead)
        s.start()
        self.addCleanup(s.stop)
        s.apply({"hook.1": 1.0}, DT)
        deadline = time.monotonic() + 2.0
        while s.status() == "ok" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn("error", s.status())


if __name__ == "__main__":
    unittest.main()
