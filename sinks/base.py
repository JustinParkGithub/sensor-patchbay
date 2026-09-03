"""Sink plugin contract.

Subclass ``Sink``, advertise ports in ``PORTS`` (or override ``module()`` for a
dynamic port list), and act on the ``{port_id: float}`` dict handed to ``apply()``
every tick. A port that is *absent* from that dict means "no signal this tick" —
treat it as 0 and release whatever it was holding. Implement ``release_all()`` so
the panic button and a clean shutdown can silence you instantly.
"""

from __future__ import annotations

from engine.signals import ModuleSpec, PortSpec


class Sink:
    id = "sink"
    label = "sink"
    PORTS: list[PortSpec] = []
    accepts_any = False           # True => graph may target port ids not in PORTS

    def start(self):
        pass

    def stop(self):
        pass

    def status(self) -> str:
        return "ok"

    def release_all(self):
        pass

    def module(self) -> ModuleSpec:
        m = ModuleSpec(self.id, self.label, "sink", list(self.PORTS), self.status())
        return m

    def apply(self, values: dict, dt: float):
        raise NotImplementedError
