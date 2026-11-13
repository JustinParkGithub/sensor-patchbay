"""Fixed-rate engine loop. Owns the sources, the sinks and the live graph, and is
the single writer of the state snapshot the web UI reads over SSE.

Portability note
----------------
The whole tick is one method, :meth:`EngineLoop.step`, that takes ``dt`` and does
one pass (read sources → route → drive sinks → snapshot). :meth:`start` runs it on
a background thread for the PC build; a microcontroller port drops the thread and
calls ``engine.step(dt)`` straight from its own ``while True`` loop instead —
nothing in ``step`` requires threads. Everything ``step`` touches (the graph, the
nodes, the registry) is pure standard library.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path

from . import presets, registry
from .graph import Graph
from .nodes import chain_inputs
from .signals import ModuleSpec, PortSpec, EVENT


class SysSink:
    """Built-in sink. Each port acts on a rising edge, which the loop services
    after the sinks are driven:

    - ``preset.cycle`` loads the next preset — map ``controller/btn.guide -> sys/preset.cycle``.
    - ``panic.toggle`` flips panic, like the UI's PANIC button.

    Unlike every other sink it keeps receiving its inputs while panic is on —
    it drives no outputs, and ``panic.toggle`` must be able to turn panic off.
    """
    type = "sys"
    id = "sys"

    def __init__(self):
        self._prev = {"preset.cycle": 0.0, "panic.toggle": 0.0}
        self.pending = False
        self.panic_pending = False

    def module(self):
        return ModuleSpec("sys", "system", "sink", [
            PortSpec("preset.cycle", EVENT, "preset.cycle", "presets",
                     hint="rising edge loads the next preset file"),
            PortSpec("panic.toggle", EVENT, "panic.toggle", "safety",
                     hint="rising edge toggles panic (all outputs off)"),
        ])

    def _rose(self, values, port):
        v = values.get(port, 0.0)
        rose = v >= 0.5 and self._prev[port] < 0.5
        self._prev[port] = v
        return rose

    def apply(self, values, dt):
        if self._rose(values, "preset.cycle"):
            self.pending = True
        if self._rose(values, "panic.toggle"):
            self.panic_pending = True

    def release_all(self):
        # Nothing is held. The edge memory must survive a panic: set_panic()
        # calls this, and forgetting a still-held button would read as a
        # fresh press on the next tick and toggle panic straight back.
        pass

    def start(self):  # noqa: D401 - symmetry with real sinks
        pass

    def stop(self):
        pass


class EngineLoop:
    def __init__(self, sources: dict, sinks: dict, graph: Graph,
                 preset_dir: str | Path, rate: float = 120.0):
        self.sources = dict(sources)          # id -> Source
        self.sys = SysSink()
        self.sinks = dict(sinks)              # id -> Sink
        self.sinks[self.sys.id] = self.sys
        # An instance's bus namespace is its dict key here; keep .id in sync so
        # module()/read()/the UI all agree, even for a suffixed second instance.
        for iid, inst in {**self.sources, **self.sinks}.items():
            inst.id = iid
        self.graph = graph
        self.preset_dir = Path(preset_dir)
        self.preset_dir.mkdir(parents=True, exist_ok=True)
        self.rate = rate
        self.panic = False
        self.current_preset = graph.name

        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self._mod_rev = 0                     # bumped whenever a module is added/removed
        self._snap = {"t": 0.0, "ports": {}, "sinks": {}, "connections": {},
                      "panic": False, "preset": self.current_preset, "rate": rate,
                      "mod_rev": 0}

    # ---- lifecycle -------------------------------------------------
    def start(self):
        for m in list(self.sources.values()) + list(self.sinks.values()):
            try:
                m.start()
            except Exception:
                traceback.print_exc()
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        for m in list(self.sources.values()) + list(self.sinks.values()):
            try:
                if hasattr(m, "release_all"):
                    m.release_all()
                m.stop()
            except Exception:
                pass

    # ---- main loop ------------------------------------------------
    # Further behind schedule than this (a suspend, a debugger, a long stall),
    # skip the missed ticks rather than run them back to back.
    MAX_LAG = 0.25

    def _run(self):
        t0 = time.perf_counter()
        prev = deadline = t0
        while not self._stop.is_set():
            now = time.perf_counter()
            dt = now - prev
            prev = now
            self.step(dt, clock=now - t0)
            # read the rate each tick so set_rate() takes effect live
            period = 1.0 / self.rate if self.rate > 0 else 0.0
            # Pace against fixed deadlines, not "period minus this tick's work":
            # sleep() overshoots (timer coalescing, a busy machine), and with
            # relative pacing every overshoot is lost for good, so the real rate
            # sags well below the setting. Here the next tick just comes sooner.
            deadline += period
            slack = deadline - time.perf_counter()
            if slack > 0:
                time.sleep(slack)
            elif slack < -self.MAX_LAG:
                deadline = time.perf_counter()

    def step(self, dt: float, clock: float | None = None):
        """One engine tick: read every source, route through the graph, drive every
        sink, refresh the snapshot. Safe to call from any loop (thread or bare
        microcontroller ``while``); it takes its own consistent view of the
        sources/sinks/graph under the lock so a concurrent add/remove is safe.
        """
        with self._lock:
            sources = list(self.sources.items())
            sinks = list(self.sinks.items())
            graph = self.graph
            panic = self.panic

        src_vals: dict[str, float] = {}
        for sid, src in sources:
            try:
                for k, v in src.read().items():
                    src_vals[f"{sid}/{k}"] = float(v)
            except Exception:
                pass

        sink_vals = graph.tick(src_vals, dt)

        by_sink: dict[str, dict] = {}
        for full, val in sink_vals.items():
            sid, _, port = full.partition("/")
            by_sink.setdefault(sid, {})[port] = val

        for sid, sink in sinks:
            # sys drives no outputs, and must still see panic.toggle to end a panic
            payload = {} if panic and sink is not self.sys else by_sink.get(sid, {})
            try:
                sink.apply(payload, dt)
            except Exception:
                traceback.print_exc()

        if self.sys.panic_pending:
            self.sys.panic_pending = False
            self.set_panic(not panic)
            panic = self.panic
        if self.sys.pending:
            self.sys.pending = False
            self._cycle_preset()

        self._snap = {
            "t": self._snap["t"] + dt if clock is None else clock,
            "ports": {k: round(v, 5) for k, v in src_vals.items()},
            "sinks": {k: round(v, 5) for k, v in sink_vals.items()},
            "connections": graph.activity_map(),
            "panic": panic,
            "preset": self.current_preset,
            "rate": self.rate,
            "mod_rev": self._mod_rev,
        }

    # ---- state for the server -----------------------------------
    def snapshot(self):
        return self._snap

    def modules(self):
        # snapshot under the lock: a concurrent add/remove from another request
        # thread would otherwise change the dicts mid-iteration
        with self._lock:
            modules = [*self.sources.values(), *self.sinks.values()]
        return [m.module().to_dict() for m in modules]

    def set_rate(self, hz: float) -> float:
        """Change the engine tick rate live (Hz). The run loop reads it each tick."""
        hz = float(hz)
        if hz <= 0 or hz > 2000:
            raise ValueError("rate must be between 1 and 2000 Hz")
        with self._lock:
            self.rate = hz
        return self.rate

    def set_panic(self, on: bool):
        with self._lock:
            self.panic = bool(on)
        if on:
            for sink in self.sinks.values():
                if hasattr(sink, "release_all"):
                    try:
                        sink.release_all()
                    except Exception:
                        pass

    # ---- runtime module management ------------------------------
    def _unique_id(self, base: str, taken: dict) -> str:
        if base not in taken:
            return base
        i = 2
        while f"{base}-{i}" in taken:
            i += 1
        return f"{base}-{i}"

    def add_source(self, instance_id: str, src, start: bool = True) -> str:
        with self._lock:
            iid = self._unique_id(instance_id, self.sources)
            src.id = iid
            if start:
                src.start()
            self.sources[iid] = src
            self._mod_rev += 1
        return iid

    def add_sink(self, instance_id: str, sink, start: bool = True) -> str:
        with self._lock:
            iid = self._unique_id(instance_id, self.sinks)
            sink.id = iid
            if start:
                sink.start()
            self.sinks[iid] = sink
            self._mod_rev += 1
        return iid

    def create_source(self, type_name: str, kwargs: dict | None = None,
                       instance_id: str | None = None) -> str:
        """Instantiate a registered source type and add it live. Returns its id."""
        iid, inst = registry.build(registry.SOURCES, type_name, kwargs, instance_id)
        return self.add_source(iid, inst)

    def create_sink(self, type_name: str, kwargs: dict | None = None,
                    instance_id: str | None = None) -> str:
        iid, inst = registry.build(registry.SINKS, type_name, kwargs, instance_id)
        return self.add_sink(iid, inst)

    def remove_source(self, instance_id: str) -> int:
        """Remove a source instance and prune connections that referenced it.
        Returns the number of connections dropped."""
        with self._lock:
            src = self.sources.pop(instance_id, None)
            if src is None:
                raise KeyError(f"no source instance {instance_id!r}")
            dropped = self._prune_connections(namespace=instance_id, side="source")
            self._mod_rev += 1
        self._safe_stop(src)
        return dropped

    def remove_sink(self, instance_id: str) -> int:
        if instance_id == self.sys.id:
            raise ValueError("the built-in 'sys' sink cannot be removed")
        with self._lock:
            sink = self.sinks.pop(instance_id, None)
            if sink is None:
                raise KeyError(f"no sink instance {instance_id!r}")
            dropped = self._prune_connections(namespace=instance_id, side="sink")
            self._mod_rev += 1
        self._safe_stop(sink)
        return dropped

    def _prune_connections(self, namespace: str, side: str) -> int:
        prefix = namespace + "/"
        before = len(self.graph.connections)
        self.graph.connections = [
            c for c in self.graph.connections
            if not getattr(c, side).startswith(prefix)
            and not (side == "source"
                     and any(p.startswith(prefix) for p in chain_inputs(c.chain)))
        ]
        return before - len(self.graph.connections)

    @staticmethod
    def _safe_stop(module):
        try:
            if hasattr(module, "release_all"):
                module.release_all()
            module.stop()
        except Exception:
            pass

    # ---- graph editing ----------------------------------------
    def graph_dict(self):
        with self._lock:
            return self.graph.to_dict()

    def replace_graph(self, d: dict, name: str | None = None):
        g = Graph.from_dict(d)
        if name:
            g.name = name
        with self._lock:
            self.graph = g
            self.current_preset = g.name

    def add_connection(self, source, sink, chain=None):
        with self._lock:
            return self.graph.add(source, sink, chain).to_dict()

    def remove_connection(self, cid):
        with self._lock:
            return self.graph.remove(cid)

    def update_connection(self, cid, chain=None, enabled=None):
        with self._lock:
            c = self.graph.update(cid, chain=chain, enabled=enabled)
            return c.to_dict() if c else None

    # ---- presets ---------------------------------------------
    def list_presets(self):
        return sorted(p.stem for p in self.preset_dir.glob("*.json"))

    def _preset_path(self, name: str) -> Path:
        return self.preset_dir / f"{presets.check_name(name)}.json"

    def read_preset(self, name: str) -> dict:
        data = json.loads(self._preset_path(name).read_text())
        data.setdefault("name", name)
        return data

    def load_preset(self, name: str):
        data = self.read_preset(name)
        self.replace_graph(data, name=name)
        return data

    def running_types(self) -> dict[str, dict[str, str]]:
        """``{"source": {instance id: plugin type}, "sink": {...}}`` (not ``sys``)."""
        with self._lock:
            groups = {"source": dict(self.sources), "sink": dict(self.sinks)}
        return {kind: {iid: registry._type_key(type(inst)) for iid, inst in mods.items()
                       if inst is not self.sys}
                for kind, mods in groups.items()}

    def save_preset(self, name: str, graph_dict: dict | None = None):
        path = self._preset_path(name)
        with self._lock:
            d = graph_dict or self.graph.to_dict()
        d["name"] = name
        previous = None
        if path.is_file():
            try:
                previous = json.loads(path.read_text()).get("requires")
            except Exception:
                pass
        d["requires"] = presets.derive_requires(d, self.running_types(), previous)
        path.write_text(json.dumps(d, indent=2))
        if graph_dict is not None:
            self.replace_graph(d, name=name)
        else:
            self.current_preset = name
        return d

    def delete_preset(self, name: str):
        p = self._preset_path(name)
        if p.exists():
            p.unlink()
            presets.forget_record(p.stem)
            return True
        return False

    def preset_info(self) -> dict[str, dict]:
        """Per preset file: what it requires, and which of that isn't installed."""
        out = {}
        for name in self.list_presets():
            try:
                data = self.read_preset(name)
            except Exception as e:
                out[name] = {"requires": [], "missing": [], "error": str(e)}
                continue
            out[name] = {"requires": presets.requirements(data),
                         "missing": presets.missing(data)}
        return out

    def _cycle_preset(self):
        names = self.list_presets()
        if not names:
            return
        try:
            i = names.index(self.current_preset)
        except ValueError:
            i = -1
        self.load_preset(names[(i + 1) % len(names)])
