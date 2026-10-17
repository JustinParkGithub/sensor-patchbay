"""Source plugin contract.

Subclass ``Source``, list your ports in ``PORTS`` (or override ``module()``), and
return a ``{port_id: float}`` dict from ``read()`` each tick. Flatten any vector
into per-axis scalar ports (``accel.x`` ...). Keep ``read()`` cheap and
non-blocking — it runs inside the engine loop; do real I/O on your own thread
(see ``plugins/joycon_r.py`` or ``plugins/arduino_bmi160.py``).

Making it selectable
--------------------
Decorate the class with ``@register_source`` (from ``engine.registry``) and give
it two names plus its constructor args:

    from engine.registry import register_source

    @register_source
    class MySensor(Source):
        type = "mysensor"          # registry key — the dropdown / CLI choice
        id   = "mysensor"          # default bus namespace for its ports
        label = "My Sensor"
        PORTS = [...]
        ARGS = {"port": {"default": None, "type": str, "help": "serial device"}}
        def __init__(self, port=None): ...

It then appears in the GUI's *add source* dropdown and in ``--list-sources``, and
is usable as ``--source mysensor:port=/dev/ttyACM0``. ``id`` is the namespace the
ports live under on the bus (``mysensor/whatever``); keep it stable, presets
reference it by name. ``type`` and ``id`` are separate on purpose — a *stand-in*
(the mock Joy-Con) keeps its own ``type`` but borrows the real device's ``id`` so
presets are portable between them (see ``plugins/mock.py``).

Optional dependencies
---------------------
If your source needs a third-party package, import it lazily (inside ``__init__``
or ``start``, never at module top) so the class still registers without it, and
override :meth:`available` to report whether it can run — the GUI/CLI list it
either way, greying out the unavailable ones with your reason.
"""

from __future__ import annotations

from engine.signals import ModuleSpec, PortSpec


class Source:
    type = "source"       # registry key (dropdown / CLI choice)
    id = "source"         # default instance id == bus namespace for its ports
    label = "source"
    PORTS: list[PortSpec] = []
    ARGS: dict = {}       # constructor kwargs exposed to --source type:k=v,...
    PREVIEW = False       # True if preview_jpeg() returns frames (the UI then shows them)

    @classmethod
    def available(cls):
        """Return True, or ``(False, reason)`` when a dependency/device is missing.

        Checked without instantiating, so keep it cheap (an import probe, not a
        connection). Default: always available.
        """
        return True

    def start(self):
        pass

    def stop(self):
        pass

    def status(self) -> str:
        return "ok"

    def module(self) -> ModuleSpec:
        return ModuleSpec(self.id, self.label, "source", list(self.PORTS), self.status(),
                          preview=self.PREVIEW)

    def preview_jpeg(self) -> bytes | None:
        """Latest preview frame as JPEG bytes, or None if there isn't one (yet)."""
        return None

    def read(self) -> dict:
        raise NotImplementedError
