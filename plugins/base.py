"""Source plugin contract.

Subclass ``Source``, list your ports in ``PORTS`` (or override ``module()``), and
return a ``{port_id: float}`` dict from ``read()`` each tick. Flatten any vector
into per-axis scalar ports (``accel.x`` ...). Keep ``read()`` cheap and
non-blocking — it runs inside the engine loop; do real I/O on your own thread
(see ``plugins/joycon_r.py`` or ``plugins/arduino_bmi160.py``).

To make a new source selectable from the command line with no edits to
``run.py``, decorate the class with ``@register_source`` (from
``engine.registry``) and declare its constructor kwargs in ``ARGS``:

    from engine.registry import register_source

    @register_source
    class MySensor(Source):
        id = "mysensor"
        label = "My Sensor"
        PORTS = [...]
        ARGS = {"port": {"default": None, "type": str, "help": "serial device"}}
        def __init__(self, port=None): ...

It then shows up in ``--list-sources`` and is usable as
``--source mysensor:port=/dev/ttyACM0``. ``id`` is also the namespace every
port is exposed under on the bus (``mysensor/whatever``), so keep it stable —
presets reference it by name.

Exception: when a class is a drop-in *stand-in* for another under the same
``id`` — the mock Joy-Con for the real one, the dry-run HID sink for the real
one — don't decorate it. The registry is one-class-per-id; a real/mock pair
sharing an id is a deliberate runtime choice (real-if-available-else-mock),
which ``run.py`` already makes explicitly, not something to expose as two
competing registry entries.
"""

from __future__ import annotations

from engine.signals import ModuleSpec, PortSpec


class Source:
    id = "source"
    label = "source"
    PORTS: list[PortSpec] = []
    ARGS: dict = {}       # constructor kwargs exposed to --source name:k=v,...

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
