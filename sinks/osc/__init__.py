"""Open Sound Control over UDP, for anything that listens to OSC: DAWs, lighting
and show-control software, visual tools. Standard library only.

Each port sends one float to ``<prefix>/<port with dots as slashes>``, so
``fader.1`` is ``/patchbay/fader/1``. A value is sent only when it changes, every
change is sent (so a one-tick pulse isn't lost), and a port that goes quiet sends
a final 0. Any port id works from a preset, not just the listed jacks.
"""

from __future__ import annotations

import socket
import struct

from engine.registry import register_sink
from engine.signals import PortSpec, SCALAR, EVENT
from sinks.base import Sink


def _osc_string(s: str) -> bytes:
    """Null-terminated and padded to a multiple of 4 bytes, per the OSC 1.0 spec."""
    raw = s.encode() + b"\0"
    return raw + b"\0" * (-len(raw) % 4)


def encode_message(address: str, value: float) -> bytes:
    return _osc_string(address) + _osc_string(",f") + struct.pack(">f", value)


@register_sink
class OscSink(Sink):
    type = "osc"
    id = "osc"
    label = "OSC over UDP"
    accepts_any = True
    PORTS = [
        *(PortSpec(f"fader.{i}", SCALAR, f"fader.{i}", "faders") for i in range(1, 5)),
        *(PortSpec(f"button.{i}", EVENT, f"button.{i}", "buttons") for i in range(1, 5)),
    ]
    ARGS = {
        "host": {"default": "127.0.0.1", "type": str, "help": "where the OSC receiver runs"},
        "port": {"default": 9000, "type": int, "help": "the receiver's UDP port"},
        "prefix": {"default": "/patchbay", "type": str, "help": "start of every OSC address"},
    }

    def __init__(self, host="127.0.0.1", port=9000, prefix="/patchbay"):
        self.host, self.port = host, int(port)
        self.prefix = "/" + str(prefix).strip("/") if str(prefix).strip("/") else ""
        self._sock = None
        self._addr = None
        self._last: dict[str, float] = {}
        self._err = None

    def start(self):
        # resolved once here: a DNS lookup must not stall the engine tick
        family, kind, _, _, addr = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_DGRAM)[0]
        self._addr = addr
        self._sock = socket.socket(family, kind)
        self._sock.setblocking(False)

    def stop(self):
        self.release_all()
        if self._sock:
            self._sock.close()
            self._sock = None

    def status(self):
        return f"error: {self._err}" if self._err else "ok"

    def _send(self, port, value):
        address = f"{self.prefix}/{port.replace('.', '/')}"
        try:
            self._sock.sendto(encode_message(address, value), self._addr)
            self._err = None
        except (OSError, OverflowError) as e:   # never let the network stall the tick
            self._err = str(e)

    def apply(self, values, dt):
        if self._sock is None:
            return
        for port, value in values.items():
            if self._last.get(port, 0.0) != value:
                self._send(port, value)
                self._last[port] = value
        for port in [p for p in self._last if p not in values]:
            if self._last.pop(port):
                self._send(port, 0.0)

    def release_all(self):
        if self._sock is None:
            return
        for port, value in self._last.items():
            if value:
                self._send(port, 0.0)
        self._last.clear()
