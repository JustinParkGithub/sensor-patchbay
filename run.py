#!/usr/bin/env python3
"""sensor-patchbay entrypoint.

The engine starts with *no* sources or sinks by default — you add them live from
the web UI (or the ``--cli`` console), which is the whole point: swap hardware in
and out without ever stopping the process. The flags below just pre-load modules
so a headless board can come up ready; nothing here can't also be done live.

    python run.py                 # start empty; add sources/sinks live from the UI
    python run.py --source mock   # pre-load the synthetic source (no hardware)
    python run.py --sink dryrun   # pre-load a logging-only mouse/keyboard sink
    python run.py --sink hid      # pre-load the real mouse + keyboard sink
    python run.py --preset mouse  # load a routing preset on start
    python run.py --list-ports
    python run.py --selftest      # headless: tick mock->dry-run for 2s and exit

    python run.py --source bmi160:port=/dev/ttyUSB0    # pre-load a plugin source
    python run.py --sink hid --source mock             # both, at once
    python run.py --list-sources  # what's pluggable (the dropdown choices) + its args
    python run.py --list-sinks

    python run.py --cli           # web UI + an interactive console for reconfiguring live
    python run.py --no-ui --cli   # console only, no web server (headless board)
    python run.py --no-ui         # run the engine as an appliance (no UI, no console)
    python run.py --ext ~/my-plugins   # also load module folders from a directory

    python run.py --sync          # make the environment match the modules, then exit
    python run.py --upgrade       # same, but re-resolve every package to its newest version
    python run.py --no-sync       # skip the environment check (fully offline, as-is)

Modules listed in patchbay.toml's ``autostart`` are added on start (none by
default); ``--no-autostart`` ignores that list for one run.

Then open http://127.0.0.1:8420 in a browser on the same machine. The desktop
app (app.py) is this same startup in a native window with a tray icon; its
``patchbay`` executable takes every flag above.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

if sys.version_info < (3, 11):
    sys.exit("sensor-patchbay needs Python 3.11+ (found %d.%d)" % sys.version_info[:2])

from engine import library, modules, paths
from engine.graph import Graph
from engine.loop import EngineLoop
from engine.registry import (SINKS, SOURCES, build, describe,
                             build_spec, discover)

PRESETS = paths.PRESETS


def build_extra(registry: dict, specs: list, kind: str) -> dict:
    """Instantiate every ``TYPE[:k=v,...]`` spec against a plugin registry.

    Shared by --source and --sink: every pre-loaded module goes through here,
    keyed by the resulting instance's own id. A spec that fails to build (bad
    arg, hardware not found, ...) is logged and skipped rather than aborting the
    whole run — you can still add a working module from the UI afterwards.
    """
    out = {}
    for spec in specs:
        try:
            iid, inst = build_spec(registry, spec)
        except Exception as e:
            print(f"[{kind}] failed to build '{spec}': {e}")
            continue
        if iid in out:
            print(f"[{kind}] '{iid}' already added; skipping duplicate '{spec}'")
            continue
        out[iid] = inst
        print(f"[{kind}] {iid} ready ({spec})")
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


def _need_standins() -> bool:
    missing = [n for n, reg in (("mock", SOURCES), ("dryrun", SINKS)) if n not in reg]
    if missing:
        print(f"needs the {' and '.join(missing)} module(s); install them first "
              "(upload in the UI, or `install` in the --cli console)")
    return not missing


def selftest():
    if not _need_standins():
        sys.exit(1)
    _, mock = build(SOURCES, "mock")
    _, null = build(SINKS, "dryrun")
    eng = EngineLoop({"joycon": mock}, {"hid": null}, load_graph("mouse"), PRESETS, rate=120)
    eng.start()
    time.sleep(2.0)
    snap = eng.snapshot()
    eng.stop()
    assert snap["ports"], "no source ports in snapshot"
    assert "joycon/gyro.z" in snap["ports"], "expected joycon/gyro.z"
    assert snap["rate"] == 120
    print(f"[selftest] OK  ({len(snap['ports'])} ports, "
          f"{len(snap['connections'])} connections, preset={snap['preset']})")


def list_ports():
    """Print the ports of the always-available stand-ins (mock source, dry-run
    sink) so you can see the bus namespace presets are written against."""
    if not _need_standins():
        sys.exit(1)
    _, src = build(SOURCES, "mock")
    _, hid = build(SINKS, "dryrun")
    for m in (src.module(), hid.module()):
        print(f"\n{m.kind.upper()}  {m.id}  ({m.label}) [{m.status}]")
        for p in m.ports:
            pd = p if isinstance(p, dict) else p.to_dict()
            print(f"  {pd['type']:7} {m.id}/{pd['id']:20} {pd.get('hint','')}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--rate", type=float, default=120.0)
    ap.add_argument("--preset", default="mouse")
    ap.add_argument("--mock", action="store_true",
                    help="pre-load the synthetic source (shorthand for --source mock)")
    ap.add_argument("--dry-run", action="store_true",
                    help="pre-load a logging-only sink (shorthand for --sink dryrun)")
    ap.add_argument("--list-ports", action="store_true", help="print every source/sink port and exit")
    ap.add_argument("--source", action="append", default=[], metavar="TYPE[:k=v,...]",
                    help="pre-load a source from the plugin registry (repeatable); see --list-sources")
    ap.add_argument("--sink", action="append", default=[], metavar="TYPE[:k=v,...]",
                    help="pre-load a sink from the plugin registry (repeatable); see --list-sinks")
    ap.add_argument("--list-sources", action="store_true",
                    help="list registered source plugins and their args, then exit")
    ap.add_argument("--list-sinks", action="store_true",
                    help="list registered sink plugins and their args, then exit")
    ap.add_argument("--ext", action="append", default=[], metavar="DIR",
                    help="also load module folders from DIR (repeatable)")
    ap.add_argument("--sync", action="store_true",
                    help="sync the environment to the enabled modules, print setup notes, exit")
    ap.add_argument("--upgrade", action="store_true",
                    help="re-resolve every module's packages to the newest versions, then sync")
    ap.add_argument("--no-sync", action="store_true",
                    help="don't check or change installed packages this run")
    ap.add_argument("--no-autostart", action="store_true",
                    help="ignore patchbay.toml's autostart list this run")
    ap.add_argument("--cli", action="store_true",
                    help="start an interactive control console (reconfigure live)")
    ap.add_argument("--no-ui", action="store_true",
                    help="don't start the web server (headless / appliance)")
    ap.add_argument("--selftest", action="store_true")
    return ap


def prepare(args) -> bool:
    """Sync + import modules, then run a one-shot flag if one was given.
    Returns True when that flag's job is done and there's nothing left to run."""
    paths.ensure_layout()
    library.EXTRA_DIRS[:] = args.ext
    library.ENV_SYNC = not args.no_sync
    # Make the environment match the declared modules, then import the enabled ones.
    enabled = modules.ensure(args.ext, sync=not args.no_sync,
                             upgrade=args.upgrade, verbose=args.sync)
    if args.sync:
        return True
    discover(enabled)  # populate SOURCES/SINKS

    if args.list_sources:
        print(describe(SOURCES))
    elif args.list_sinks:
        print(describe(SINKS))
    elif args.selftest:
        selftest()
    elif args.list_ports:
        list_ports()
    else:
        return False
    return True


def start_engine(args) -> EngineLoop:
    # No default source or sink: the engine comes up empty and you patch in
    # hardware live. The flags below are pure pre-load shorthands.
    source_specs = (["mock"] if args.mock else []) + list(args.source)
    sink_specs = (["dryrun"] if args.dry_run else []) + list(args.sink)
    if not args.no_autostart:
        for spec in modules.load_config().get("autostart", []):
            type_name = spec.partition(":")[0].strip()
            if type_name in SOURCES:
                source_specs.append(spec)
            elif type_name in SINKS:
                sink_specs.append(spec)
            else:
                print(f"[autostart] no enabled module {type_name!r}; skipping '{spec}'")
    sources = build_extra(SOURCES, source_specs, "source")
    sinks = build_extra(SINKS, sink_specs, "sink")

    engine = EngineLoop(sources, sinks, load_graph(args.preset), PRESETS, rate=args.rate)
    engine.start()
    return engine


def main(argv=None):
    args = build_parser().parse_args(argv)
    if prepare(args):
        return
    engine = start_engine(args)

    httpd = None
    if not args.no_ui:
        from server import serve
        httpd = serve(engine, args.host, args.port)
        url = f"http://{args.host}:{args.port}"
        print(f"\n  patchbay UI  ->  {url}")

    try:
        if args.cli:
            from control import Console
            if httpd is not None:
                threading.Thread(target=httpd.serve_forever, name="httpd", daemon=True).start()
            print()
            Console(engine).run()          # blocks until the user quits the console
        elif httpd is not None:
            print("  Ctrl+C to stop\n")
            httpd.serve_forever()
        else:
            print("\n  engine running headless (no UI, no console); Ctrl+C to stop\n")
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        engine.stop()          # releases any held keys/buttons
        if httpd is not None:
            httpd.server_close()


if __name__ == "__main__":
    sys.exit(main())
