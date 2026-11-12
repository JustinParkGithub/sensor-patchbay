"""Interactive control console for a running patchbay.

This is the "reconfigure the patchbay from the patchbay itself" path: when the
engine runs on a headless board (a Pi, or anything with no browser handy) you
drive it from a terminal instead of the GUI. Every command maps onto the exact
same :class:`~engine.loop.EngineLoop` operations the REST API calls, so the CLI
and the web editor are two front-ends over one core — neither can do anything the
other can't.

    python run.py --cli              # web UI + this console side by side
    python run.py --no-ui --cli      # console only, no web server (true headless)

Type ``help`` at the prompt for the command list.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from engine import catalog, library, presets, registry


class Console:
    def __init__(self, engine):
        self.engine = engine

    # ------------------------------------------------------------------ loop
    def run(self):
        print("patchbay console — type 'help' for commands, 'quit' to exit.")
        while True:
            try:
                line = input("patchbay> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not line:
                continue
            try:
                if self.dispatch(line) is False:
                    return
            except Exception as e:
                print(f"error: {e}")

    def dispatch(self, line: str):
        parts = shlex.split(line)
        cmd, args = parts[0].lower(), parts[1:]
        handler = getattr(self, f"cmd_{cmd}", None)
        if handler is None:
            aliases = {"?": self.cmd_help, "exit": self.cmd_quit, "q": self.cmd_quit,
                       "ls": self.cmd_modules, "rm": self.cmd_remove}
            handler = aliases.get(cmd)
        if handler is None:
            print(f"unknown command {cmd!r}; type 'help'")
            return
        return handler(args)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _kwargs(pairs):
        out = {}
        for p in pairs:
            k, _, v = p.partition("=")
            out[k] = v
        return out

    # ------------------------------------------------------------------ commands
    def cmd_help(self, args):
        print(__doc__.strip())
        print("""
commands:
  plugins [sources|sinks]        list installed plugin types (dropdown choices)
  modules                        list the active source/sink instances (alias: ls)
  ports [source|sink]            list every live port on the bus
  add source <type> [k=v ...]    add a source instance (see 'plugins')
  add sink   <type> [k=v ...]    add a sink instance
  remove source <id> | remove sink <id>     drop an instance (alias: rm)
  connect <src.port> <sink.port> patch a cable (full ids, e.g. joycon/gyro.x hid/mouse.dx)
  disconnect <conn-id>           remove a cable
  graph                          show the current connections
  presets                        list preset files (with what each needs that's missing)
  load <name> | save [name] | delete <name>
  catalog [query] [--refresh]    search the online module catalog
  install <name>                 download a module (and what it depends on) from the catalog
  install <file.zip|file.json>   add a module folder (zipped) or a preset file
  uninstall <name>               delete an installed module from the data folder
  sync                           re-read modules + presets, install module packages
  panic [on|off]                 toggle emergency stop
  rate [hz]                      show or set the engine tick rate (live)
  state                          one-line snapshot summary
  quit                           exit the console (engine keeps running if the web UI is up)
""".rstrip())

    def cmd_plugins(self, args):
        which = args[0].lower() if args else "all"
        if which in ("all", "sources"):
            print("SOURCES (add with: add source <type> [k=v ...])")
            print(registry.describe(registry.SOURCES))
        if which in ("all", "sinks"):
            print("SINKS (add with: add sink <type> [k=v ...])")
            print(registry.describe(registry.SINKS))

    def cmd_modules(self, args):
        for m in self.engine.modules():
            print(f"  {m['kind']:6} {m['id']:14} {m['label']}  [{m['status']}]")

    def cmd_ports(self, args):
        want = args[0].lower() if args else None
        for m in self.engine.modules():
            if want and m["kind"] != want:
                continue
            for p in m["ports"]:
                print(f"  {p['type']:7} {m['id']}/{p['id']}")

    def cmd_add(self, args):
        if len(args) < 2 or args[0].lower() not in ("source", "sink"):
            print("usage: add source|sink <type> [k=v ...]")
            return
        kind, type_name, kwargs = args[0].lower(), args[1], self._kwargs(args[2:])
        create = self.engine.create_source if kind == "source" else self.engine.create_sink
        iid = create(type_name, kwargs)
        print(f"added {kind} '{iid}' (type {type_name})")

    def cmd_remove(self, args):
        if len(args) != 2 or args[0].lower() not in ("source", "sink"):
            print("usage: remove source|sink <id>")
            return
        kind, iid = args[0].lower(), args[1]
        remove = self.engine.remove_source if kind == "source" else self.engine.remove_sink
        dropped = remove(iid)
        print(f"removed {kind} '{iid}' ({dropped} connection(s) pruned)")

    def cmd_connect(self, args):
        if len(args) != 2:
            print("usage: connect <src.port> <sink.port>   e.g. joycon/gyro.x hid/mouse.dx")
            return
        c = self.engine.add_connection(args[0], args[1])
        print(f"patched {c['id']}: {c['source']} -> {c['sink']}")

    def cmd_disconnect(self, args):
        if not args:
            print("usage: disconnect <conn-id>")
            return
        print("removed" if self.engine.remove_connection(args[0]) else "no such connection")

    def cmd_graph(self, args):
        g = self.engine.graph_dict()
        print(f"preset '{g['name']}' — {len(g['connections'])} connection(s):")
        for c in g["connections"]:
            chain = " · ".join(n["type"] for n in c.get("chain", [])) or "pass-through"
            flag = "" if c.get("enabled", True) else "  (disabled)"
            print(f"  {c['id']}  {c['source']} -> {c['sink']}   [{chain}]{flag}")

    def cmd_presets(self, args):
        info = self.engine.preset_info()
        for name in self.engine.list_presets():
            mark = " *" if name == self.engine.current_preset else ""
            print(f"  {name}{mark}")
            for m in info.get(name, {}).get("missing", []):
                print(f"      ! needs {m['kind']} '{m['id']}': {m['reason']}")

    def cmd_catalog(self, args):
        refresh = "--refresh" in args
        words = [a.lower() for a in args if a != "--refresh"]
        listing = catalog.listing(refresh=refresh)
        if listing["cached"]:
            print(f"(offline: showing the cached catalog; {listing['error']})")
        shown = [m for m in listing["modules"]
                 if all(w in f"{m['name']} {m['kind']} {m['description']}".lower() for w in words)]
        if not shown:
            print("nothing matches" if words else "the catalog is empty")
        for m in shown:
            mark = {"installed": "✓", "update": "↑", "local": "·"}.get(m["state"], " ")
            print(f"  {mark} {m['kind']:6} {m['name']:10} {m['description']}")
        print(f"\n  ✓ installed  ↑ update available  · local only    ({listing['url']})")

    def cmd_install(self, args):
        if len(args) != 1:
            print("usage: install <name> | install <file.zip|file.json>")
            return
        path = Path(args[0]).expanduser()
        if not path.is_file() and path.suffix.lower() not in (".zip", ".json"):
            results = catalog.install(args[0])
            for res in results:
                verb = "updated" if res["replaced"] else "installed"
                print(f"{verb} {res['module_kind']} '{res['name']}'")
            if results:
                print("syncing...")
                self.cmd_sync([])
            else:
                print(f"'{args[0]}' is already installed")
            return
        res = library.install_upload(path.name, path.read_bytes())
        verb = "replaced" if res["replaced"] else "installed"
        if res["kind"] == "preset":
            print(f"{verb} preset '{res['name']}'")
            for m in res["missing"]:
                print(f"  ! needs {m['kind']} '{m['id']}': {m['reason']}")
        else:
            print(f"{verb} {res['module_kind']} '{res['name']}'; syncing...")
            self.cmd_sync([])

    def cmd_uninstall(self, args):
        if len(args) != 1:
            print("usage: uninstall <name>")
            return
        res = catalog.remove(args[0])
        print(f"removed {res['kind']} '{res['name']}'")
        if res["needed_by"]:
            print(f"  ! still needed by: {', '.join(res['needed_by'])}")
        self.cmd_sync([])

    def cmd_sync(self, args):
        report = library.sync()      # prints its own log as it goes
        print(f"synced: {report['sources']} source type(s), {report['sinks']} sink type(s), "
              f"{len(self.engine.list_presets())} preset(s)")

    def cmd_load(self, args):
        if not args:
            print("usage: load <name>")
            return
        self.engine.load_preset(args[0])
        print(f"loaded {args[0]}")
        for m in presets.missing(self.engine.read_preset(args[0])):
            print(f"  ! needs {m['kind']} '{m['id']}': {m['reason']}")

    def cmd_save(self, args):
        name = args[0] if args else self.engine.current_preset
        self.engine.save_preset(name)
        print(f"saved {name}")

    def cmd_delete(self, args):
        if not args:
            print("usage: delete <name>")
            return
        print("deleted" if self.engine.delete_preset(args[0]) else "no such preset")

    def cmd_panic(self, args):
        on = True if not args else args[0].lower() in ("on", "1", "true", "yes")
        self.engine.set_panic(on)
        print(f"panic {'ON' if on else 'off'}")

    def cmd_rate(self, args):
        if not args:
            print(f"rate {self.engine.rate:.0f} Hz")
            return
        try:
            hz = self.engine.set_rate(float(args[0]))
            print(f"rate {hz:.0f} Hz")
        except Exception as e:
            print(f"error: {e}")

    def cmd_state(self, args):
        s = self.engine.snapshot()
        print(f"  t={s['t']:.1f}s  rate={self.engine.rate:.0f}Hz  "
              f"preset={self.engine.current_preset}  panic={self.engine.panic}  "
              f"ports={len(s['ports'])}  connections={len(s['connections'])}")

    def cmd_quit(self, args):
        print("leaving console.")
        return False
