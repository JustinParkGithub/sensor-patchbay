"""Fixed-rate engine loop. Owns the sources, the sinks and the live graph, and is
the single writer of the state snapshot the web UI reads over SSE.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path

from .graph import Graph
from .signals import ModuleSpec, PortSpec, EVENT


class SysSink:
    """Built-in sink. Currently one port: ``preset.cycle`` — a rising edge asks the
    loop to load the next preset. Lets you map ``joycon/btn.home -> sys/preset.cycle``.
    """
    id = "sys"

    def __init__(self):
        self._prev = 0.0
        self.pending = False

    def module(self):
        return ModuleSpec("sys", "system", "sink", [
            PortSpec("preset.cycle", EVENT, "preset.cycle", "presets",
                     hint="rising edge loads the next preset file"),
        ])

    def apply(self, values, dt):
        v = values.get("preset.cycle", 0.0)
        if v >= 0.5 and self._prev < 0.5:
            self.pending = True
        self._prev = v

    def release_all(self):
        self._prev = 0.0

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
        self.graph = graph
        self.preset_dir = Path(preset_dir)
        self.preset_dir.mkdir(parents=True, exist_ok=True)
        self.rate = rate
        self.panic = False
        self.current_preset = graph.name

        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self._snap = {"t": 0.0, "ports": {}, "sinks": {}, "connections": {},
                      "panic": False, "preset": self.current_preset, "rate": rate}

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
    def _run(self):
        period = 1.0 / self.rate
        t0 = time.perf_counter()
        prev = t0
        while not self._stop.is_set():
            now = time.perf_counter()
            dt = now - prev
            prev = now

            src_vals: dict[str, float] = {}
            for sid, src in self.sources.items():
                try:
                    for k, v in src.read().items():
                        src_vals[f"{sid}/{k}"] = float(v)
                except Exception:
                    pass

            with self._lock:
                graph = self.graph
                panic = self.panic
            sink_vals = graph.tick(src_vals, dt)

            by_sink: dict[str, dict] = {}
            for full, val in sink_vals.items():
                sid, _, port = full.partition("/")
                by_sink.setdefault(sid, {})[port] = val

            for sid, sink in self.sinks.items():
                payload = {} if panic else by_sink.get(sid, {})
                try:
                    sink.apply(payload, dt)
                except Exception:
                    traceback.print_exc()

            if self.sys.pending:
                self.sys.pending = False
                self._cycle_preset()

            self._snap = {
                "t": now - t0,
                "ports": {k: round(v, 5) for k, v in src_vals.items()},
                "sinks": {k: round(v, 5) for k, v in sink_vals.items()},
                "connections": graph.activity_map(),
                "panic": panic,
                "preset": self.current_preset,
                "rate": self.rate,
            }

            slack = period - (time.perf_counter() - now)
            if slack > 0:
                time.sleep(slack)

    # ---- state for the server -----------------------------------
    def snapshot(self):
        return self._snap

    def modules(self):
        mods = []
        for src in self.sources.values():
            mods.append(src.module().to_dict())
        for sink in self.sinks.values():
            mods.append(sink.module().to_dict())
        return mods

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

    def load_preset(self, name: str):
        path = self.preset_dir / f"{name}.json"
        data = json.loads(path.read_text())
        data.setdefault("name", name)
        self.replace_graph(data, name=name)
        return data

    def save_preset(self, name: str, graph_dict: dict | None = None):
        with self._lock:
            d = graph_dict or self.graph.to_dict()
        d["name"] = name
        (self.preset_dir / f"{name}.json").write_text(json.dumps(d, indent=2))
        if graph_dict is not None:
            self.replace_graph(d, name=name)
        else:
            self.current_preset = name
        return d

    def delete_preset(self, name: str):
        p = self.preset_dir / f"{name}.json"
        if p.exists():
            p.unlink()
            return True
        return False

    def _cycle_preset(self):
        names = self.list_presets()
        if not names:
            return
        try:
            i = names.index(self.current_preset)
        except ValueError:
            i = -1
        self.load_preset(names[(i + 1) % len(names)])
