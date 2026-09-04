#!/usr/bin/env python3
"""joycon-patchbay entrypoint.

    python run.py                 # real Joy-Con if paired, else mock; opens UI
    python run.py --mock          # force the synthetic source
    python run.py --dry-run       # don't touch the real mouse/keyboard, just log
    python run.py --robot         # also fan out to the generic UDP/JSON robot sink
    python run.py --preset keyboard
    python run.py --list-ports
    python run.py --selftest      # headless: tick mock->null for 2s and exit
    python run.py --source bmi160:port=/dev/ttyUSB0     # add a registered plugin source
    python run.py --sink robot:host=192.168.1.5,port=9870
    python run.py --list-sources  # what's pluggable, and its constructor args
    python run.py --list-sinks

Then open http://127.0.0.1:8420 in a browser on the same machine.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from engine.graph import Graph
from engine.loop import EngineLoop
from engine.registry import SINKS, SOURCES, describe, discover, instantiate

HERE = Path(__file__).parent
PRESETS = HERE / "presets"


def build_source(force_mock: bool):
    if force_mock:
        from plugins.mock import MockJoyCon
        print("[joycon] using mock source (--mock)")
        return MockJoyCon()
    try:
        from plugins.joycon_r import JoyConR
        src = JoyConR()
        print("[joycon] connected")
        return src
    except Exception as e:
        # No real Joy-Con and mock wasn't requested: skip the Joy-Con source
        # entirely rather than silently substituting synthetic data. Any other
        # --source plugins still load.
        print(f"[joycon] not connected ({e}); no Joy-Con source "
              "(pass --mock for the synthetic source)")
        return None


def build_sinks(args):
    sinks = {}
    if args.dry_run:
        from sinks.null import NullSink
        sinks["hid"] = NullSink()
        print("[hid] dry-run (no real input events)")
    else:
        from sinks.mouse_keyboard import MouseKeyboardSink
        sink = MouseKeyboardSink()
        try:
            sink.start()
            sinks["hid"] = sink
            print("[hid] mouse + keyboard ready")
        except Exception as e:
            from sinks.null import NullSink
            sinks["hid"] = NullSink()
            print(f"[hid] pynput unavailable ({e}); using dry-run sink")
    if args.robot:
        from sinks.generic_out import GenericOutSink
        sinks["robot"] = GenericOutSink(host=args.robot_host, port=args.robot_port,
                                        echo=args.robot_echo)
        print(f"[robot] generic UDP/JSON out -> {args.robot_host}:{args.robot_port}")
    return sinks


def build_extra(registry: dict, specs: list, kind: str) -> dict:
    """Instantiate every ``NAME[:k=v,...]`` spec against a plugin registry.

    Shared by --source and --sink: anything beyond the built-in joycon/mock
    and hid/null/robot slots goes through here, keyed by the resulting
    instance's own ``.id`` (same convention build_source/build_sinks use).
    A spec that fails to build (bad arg, hardware not found, ...) is logged
    and skipped rather than aborting the whole run.
    """
    out = {}
    for spec in specs:
        try:
            inst = instantiate(registry, spec)
        except Exception as e:
            print(f"[{kind}] failed to build '{spec}': {e}")
            continue
        if inst.id in out:
            print(f"[{kind}] '{inst.id}' already added; skipping duplicate '{spec}'")
            continue
        out[inst.id] = inst
        print(f"[{kind}] {inst.id} ready ({spec})")
    return out


def load_graph(name: str) -> Graph:
    path = PRESETS / f"{name}.json"
    if path.is_file():
        import json
        d = json.loads(path.read_text())
        d.setdefault("name", name)
        print(f"[preset] loaded {name}")
        return Graph.from_dict(d)
    print(f"[preset] '{name}' not found; starting empty")
    return Graph(name=name)


def selftest():
    from plugins.mock import MockJoyCon
    from sinks.null import NullSink
    eng = EngineLoop({"joycon": MockJoyCon()}, {"hid": NullSink()},
                     load_graph("mouse"), PRESETS, rate=120)
    eng.start()
    time.sleep(2.0)
    snap = eng.snapshot()
    eng.stop()
    assert snap["ports"], "no source ports in snapshot"
    assert "joycon/gyro.z" in snap["ports"], "expected joycon/gyro.z"
    assert snap["rate"] == 120
    print(f"[selftest] OK  ({len(snap['ports'])} ports, "
          f"{len(snap['connections'])} connections, preset={snap['preset']})")


def list_ports(force_mock):
    src = build_source(force_mock)
    from sinks.mouse_keyboard import MouseKeyboardSink
    from sinks.generic_out import GenericOutSink
    modules = [src.module()] if src is not None else []
    modules += [MouseKeyboardSink().module(), GenericOutSink().module()]
    for m in modules:
        print(f"\n{m.kind.upper()}  {m.id}  ({m.label}) [{m.status}]")
        for p in m.ports:
            pd = p if isinstance(p, dict) else p.to_dict()
            print(f"  {pd['type']:7} {m.id}/{pd['id']:20} {pd.get('hint','')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--rate", type=float, default=120.0)
    ap.add_argument("--preset", default="mouse")
    ap.add_argument("--mock", action="store_true", help="force synthetic source")
    ap.add_argument("--dry-run", action="store_true", help="log instead of moving the real cursor")
    ap.add_argument("--robot", action="store_true", help="also enable the generic UDP/JSON sink")
    ap.add_argument("--robot-host", default="127.0.0.1")
    ap.add_argument("--robot-port", type=int, default=9870)
    ap.add_argument("--robot-echo", action="store_true")
    ap.add_argument("--list-ports", action="store_true", help="print every source/sink port and exit")
    ap.add_argument("--source", action="append", default=[], metavar="NAME[:k=v,...]",
                    help="add a source from the plugin registry (repeatable); see --list-sources")
    ap.add_argument("--sink", action="append", default=[], metavar="NAME[:k=v,...]",
                    help="add a sink from the plugin registry (repeatable); see --list-sinks")
    ap.add_argument("--list-sources", action="store_true",
                    help="list registered source plugins and their args, then exit")
    ap.add_argument("--list-sinks", action="store_true",
                    help="list registered sink plugins and their args, then exit")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    discover()  # populate SOURCES/SINKS by importing plugins/*.py, sinks/*.py

    if args.list_sources:
        return print(describe(SOURCES))
    if args.list_sinks:
        return print(describe(SINKS))
    if args.selftest:
        return selftest()
    if args.list_ports:
        return list_ports(args.mock)

    from server import serve
    sources = {}
    joycon = build_source(args.mock)
    if joycon is not None:
        sources["joycon"] = joycon
    for sid, src in build_extra(SOURCES, args.source, "source").items():
        if sid in sources:
            print(f"[source] '{sid}' already present; skipping --source duplicate")
            continue
        sources[sid] = src

    sinks = build_sinks(args)
    for sid, sink in build_extra(SINKS, args.sink, "sink").items():
        if sid in sinks:
            print(f"[sink] '{sid}' already present; skipping --sink duplicate")
            continue
        sinks[sid] = sink

    engine = EngineLoop(sources, sinks, load_graph(args.preset), PRESETS, rate=args.rate)
    engine.start()
    httpd = serve(engine, args.host, args.port)
    url = f"http://{args.host}:{args.port}"
    print(f"\n  patchbay UI  ->  {url}\n  Ctrl+C to stop\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        engine.stop()          # releases any held keys/buttons
        httpd.server_close()


if __name__ == "__main__":
    sys.exit(main())
