"""Signal vocabulary shared by sources, sinks and the routing graph.

Everything on the bus is a plain ``float``. The *type* is only metadata: it drives
the UI and the connect-time validation ("don't wire a continuous scalar straight
into an event jack"). Vectors (accel / gyro) and quaternions are flattened by the
plugin into per-axis scalar ports (``gyro.z`` etc.) so the graph only ever deals
with one number per port.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

SCALAR = "scalar"   # continuous, roughly -1..1 or a physical unit
EVENT = "event"     # gate (0/1) or single-tick pulse

TYPES = (SCALAR, EVENT)


@dataclass
class PortSpec:
    id: str                       # e.g. "gyro.z"  (namespaced to "joycon/gyro.z" in the graph)
    type: str = SCALAR
    label: str = ""
    group: str = "misc"           # UI grouping inside a module
    unit: str = ""
    hint: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = self.id
        if self.type not in TYPES:
            raise ValueError(f"bad port type {self.type!r}")

    def to_dict(self):
        return asdict(self)


@dataclass
class ModuleSpec:
    """A source or a sink as the UI sees it: an id, a label and a list of ports."""
    id: str
    label: str
    kind: str                     # "source" | "sink"
    ports: list = field(default_factory=list)
    status: str = "ok"            # free-form: "ok" | "mock" | "disconnected" | "error: ..."
    preview: bool = False         # serves a live JPEG preview at /api/source/<id>/preview

    def to_dict(self):
        d = asdict(self)
        d["ports"] = [p.to_dict() if isinstance(p, PortSpec) else p for p in self.ports]
        return d


def types_compatible(src_type: str, dst_type: str) -> bool:
    """A patch is allowed only if the endpoints agree, OR the chain will convert.

    The graph re-checks after the transform chain is applied; this is the quick
    pre-check the UI uses to grey out illegal drops. scalar->scalar and
    event->event are always fine; scalar->event needs a threshold/schmitt node,
    event->scalar is always fine (0/1 is a valid scalar).
    """
    if src_type == dst_type:
        return True
    if src_type == EVENT and dst_type == SCALAR:
        return True
    return False
