"""Source plugin contract.

Subclass ``Source``, list your ports in ``PORTS`` (or override ``module()``), and
return a ``{port_id: float}`` dict from ``read()`` each tick. Flatten any vector
into per-axis scalar ports (``accel.x`` ...). Keep ``read()`` cheap and
non-blocking — it runs inside the engine loop.
"""

from __future__ import annotations

from engine.signals import ModuleSpec, PortSpec


class Source:
    id = "source"
    label = "source"
    PORTS: list[PortSpec] = []

    def start(self):
        pass

    def stop(self):
        pass

    def status(self) -> str:
        return "ok"

    def module(self) -> ModuleSpec:
        return ModuleSpec(self.id, self.label, "source", list(self.PORTS), self.status())

    def read(self) -> dict:
        raise NotImplementedError
