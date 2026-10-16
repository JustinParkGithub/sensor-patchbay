"""Sink plugin contract.

Subclass ``Sink``, advertise ports in ``PORTS`` (or override ``module()`` for a
dynamic port list), and act on the ``{port_id: float}`` dict handed to ``apply()``
every tick. A port that is *absent* from that dict means "no signal this tick" —
treat it as 0 and release whatever it was holding. Implement ``release_all()`` so
the panic button and a clean shutdown can silence you instantly.

Making it selectable is identical to a source (see ``plugins/base.py``): decorate
with ``@register_sink``, give it a ``type`` (registry / dropdown key), an ``id``
(default bus namespace), ``label``, and an ``ARGS`` dict. It then appears in the
GUI's *add sink* dropdown and in ``--list-sinks``, and is usable as
``--sink mytype:k=v,...``. Import optional dependencies lazily and override
:meth:`available` so the picker can grey it out with a reason when it can't run.
"""

from __future__ import annotations

from engine.signals import ModuleSpec, PortSpec


class Sink:
    type = "sink"                  # registry key (dropdown / CLI choice)
    id = "sink"                    # default instance id == bus namespace
    label = "sink"
    PORTS: list[PortSpec] = []
    ARGS: dict = {}                # constructor kwargs exposed to --sink type:k=v,...
    accepts_any = False            # True => graph may target port ids not in PORTS

    @classmethod
    def available(cls):
        """Return True, or ``(False, reason)`` when a dependency/device is missing.
        Checked without instantiating; keep it cheap. Default: always available."""
        return True

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
