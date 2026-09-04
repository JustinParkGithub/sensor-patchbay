"""Sink plugin contract.

Subclass ``Sink``, advertise ports in ``PORTS`` (or override ``module()`` for a
dynamic port list), and act on the ``{port_id: float}`` dict handed to ``apply()``
every tick. A port that is *absent* from that dict means "no signal this tick" —
treat it as 0 and release whatever it was holding. Implement ``release_all()`` so
the panic button and a clean shutdown can silence you instantly.

To make a new sink selectable from the command line with no edits to
``run.py``, decorate the class with ``@register_sink`` (from
``engine.registry``) and declare its constructor kwargs in ``ARGS`` — see
``plugins/base.py`` for the exact convention (it's identical for sources and
sinks). It then shows up in ``--list-sinks`` and is usable as
``--sink myoutput:k=v,...``.
"""

from __future__ import annotations

from engine.signals import ModuleSpec, PortSpec


class Sink:
    id = "sink"
    label = "sink"
    PORTS: list[PortSpec] = []
    ARGS: dict = {}                # constructor kwargs exposed to --sink name:k=v,...
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
