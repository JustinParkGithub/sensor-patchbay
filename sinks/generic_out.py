"""Protocol-agnostic sink — the extension point for a robot arm or anything else.

It does not know about ROS, Dynamixel, G-code or serial. Every tick it packs the
current ``{port: value}`` into one JSON datagram and sends it over UDP (and/or
prints it). A separate *bridge* process you write subscribes to that feed and
translates to whatever your hardware speaks:

    {"t": 12.34, "axis.0": 0.12, "axis.1": -0.4, "gripper": 1.0}

Why a datagram feed instead of calling the robot directly: it keeps the real-time
routing loop isolated from slow/blocking transport, lets the bridge run on another
machine, and means "add a new robot" never touches this codebase — you just write
a new bridge. See ``bridges/`` in the README for a ROS 2 / pyserial skeleton.

Config (constructor kwargs, also settable from run.py):
    host, port   UDP target (default 127.0.0.1:9870)
    ports        list of advertised port ids (default axis.0..5, gripper, e-stop)
    echo         also print each datagram (default False)
    hz           max send rate (default 100)
"""

from __future__ import annotations

import json
import socket
import time

from engine.registry import register_sink
from engine.signals import PortSpec, SCALAR, EVENT
from sinks.base import Sink

DEFAULT_PORTS = [f"axis.{i}" for i in range(6)] + ["gripper", "e-stop"]


@register_sink
class GenericOutSink(Sink):
    id = "robot"
    label = "generic out (UDP/JSON)"
    accepts_any = True
    ARGS = {
        "host": {"default": "127.0.0.1", "type": str, "help": "UDP target host"},
        "port": {"default": 9870, "type": int, "help": "UDP target port"},
        "echo": {"default": False, "type": lambda v: v.lower() in ("1", "true", "yes", "on"),
                 "help": "also print each datagram"},
        "hz": {"default": 100.0, "type": float, "help": "max send rate"},
    }

    def __init__(self, host="127.0.0.1", port=9870, ports=None, echo=False, hz=100.0):
        self._addr = (host, int(port))
        self._names = list(ports or DEFAULT_PORTS)
        self._echo = echo
        self._period = 1.0 / hz
        self._sock = None
        self._t0 = time.perf_counter()
        self._last = 0.0
        self._state = {}

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def stop(self):
        if self._sock:
            self._sock.close()

    @property
    def PORTS(self):
        out = []
        for n in self._names:
            t = EVENT if n in ("gripper", "e-stop") else SCALAR
            out.append(PortSpec(n, t, n, "robot"))
        out.append(PortSpec("axis.<n>", SCALAR, "axis.<any>", "robot", hint="any port id is forwarded"))
        return out

    def apply(self, values, dt):
        self._state.update({k: round(v, 5) for k, v in values.items()})
        now = time.perf_counter()
        if now - self._last < self._period:
            return
        self._last = now
        msg = {"t": round(now - self._t0, 4), **self._state}
        data = json.dumps(msg).encode()
        try:
            self._sock.sendto(data, self._addr)
        except Exception:
            pass
        if self._echo:
            print("  [robot]", msg)

    def release_all(self):
        # send one frame of zeros so a bridge can safe the hardware
        self._state = {k: 0.0 for k in self._state}
        if self._sock:
            try:
                self._sock.sendto(json.dumps({"t": 0, "estop": 1, **self._state}).encode(), self._addr)
            except Exception:
                pass
