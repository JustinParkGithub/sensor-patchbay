"""The routing graph: a flat list of connections, each a source port -> node chain
-> sink port. This is the whole "patchbay". A preset file *is* a serialised graph.
"""

from __future__ import annotations

import uuid

from .nodes import make_node


class Connection:
    __slots__ = ("id", "source", "sink", "enabled", "chain", "_nodes", "activity", "last")

    def __init__(self, source, sink, chain=None, enabled=True, id=None):
        self.id = id or ("c_" + uuid.uuid4().hex[:8])
        self.source = source          # namespaced port id, e.g. "joycon/gyro.z"
        self.sink = sink              # namespaced port id, e.g. "hid/mouse.dx"
        self.enabled = bool(enabled)
        self.chain = list(chain or [])  # [{"type": "...", "params": {...}}, ...]
        self._nodes = [make_node(n["type"], n.get("params")) for n in self.chain]
        self.activity = 0.0           # smoothed |output|, for the UI cable glow
        self.last = 0.0

    def rebuild(self):
        self._nodes = [make_node(n["type"], n.get("params")) for n in self.chain]
        self.activity = 0.0
        self.last = 0.0

    def process(self, x, dt):
        for node in self._nodes:
            x = node.process(x, dt)
        self.last = x
        self.activity += 0.25 * (min(1.0, abs(x)) - self.activity)
        return x

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "sink": self.sink,
            "enabled": self.enabled,
            "chain": self.chain,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(d["source"], d["sink"], d.get("chain"), d.get("enabled", True), d.get("id"))


class Graph:
    def __init__(self, connections=None, name="untitled"):
        self.name = name
        self.connections: list[Connection] = list(connections or [])

    # ---- mutation -------------------------------------------------------
    def add(self, source, sink, chain=None) -> Connection:
        c = Connection(source, sink, chain)
        self.connections.append(c)
        return c

    def remove(self, cid) -> bool:
        n = len(self.connections)
        self.connections = [c for c in self.connections if c.id != cid]
        return len(self.connections) != n

    def get(self, cid) -> Connection | None:
        return next((c for c in self.connections if c.id == cid), None)

    def update(self, cid, *, chain=None, enabled=None) -> Connection | None:
        c = self.get(cid)
        if c is None:
            return None
        if chain is not None:
            c.chain = list(chain)
            c.rebuild()
        if enabled is not None:
            c.enabled = bool(enabled)
        return c

    def reset(self):
        for c in self.connections:
            c.rebuild()

    # ---- evaluation ---------------------------------------------------
    def tick(self, source_values: dict, dt: float) -> dict:
        """Return {sink_port: summed_value}. Same-typed signals into one sink add."""
        out: dict[str, float] = {}
        for c in self.connections:
            if not c.enabled:
                c.last = 0.0
                c.activity += 0.25 * (0.0 - c.activity)
                continue
            v = c.process(source_values.get(c.source, 0.0), dt)
            out[c.sink] = out.get(c.sink, 0.0) + v
        return out

    # ---- serialisation ----------------------------------------------
    def to_dict(self):
        return {"name": self.name, "connections": [c.to_dict() for c in self.connections]}

    @classmethod
    def from_dict(cls, d):
        conns = [Connection.from_dict(c) for c in d.get("connections", [])]
        return cls(conns, d.get("name", "untitled"))

    def activity_map(self):
        return {c.id: {"activity": round(c.activity, 4), "value": round(c.last, 4)}
                for c in self.connections}
