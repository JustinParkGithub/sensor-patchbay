# sensor-patchbay — Specification

Formal reference for the architecture, data model, plugin contracts, and wire
protocols. For a narrative introduction read [`OVERVIEW.md`](OVERVIEW.md); for
tutorials read the top-level [`README.md`](../README.md). This document is the
authority when the three disagree.

- Status: living specification, tracks `main`.
- Scope: the routing core, the plugin system, the host server, and the porting
  contract for microcontroller targets.
- Keywords **MUST**, **SHOULD**, **MAY** are used in the RFC 2119 sense.

---

## 1. Overview

sensor-patchbay is a real-time **sensor → routing → command** pipeline. Named
signals from one or more *sources* are carried on a typed bus, transformed by a
hot-editable *routing graph* of small DSP *nodes*, and delivered to one or more
*sinks* that drive something real (OS input, GPIO pins, …).

The same running core is edited two interchangeable ways: a browser **patch
panel** (GUI) and an on-device **CLI console**. Both are thin front-ends over one
controller (`EngineLoop`); neither can perform an operation the other cannot.

```
 sources                     routing core                         sinks
┌─────────────┐   {port:      ┌───────────────────────────┐   {port:   ┌──────────────┐
│ joycon/mock │──► float} ───►│  bus  →  graph  →  nodes   │──► float}─►│ hid / dryrun │
│ bmi160      │   per tick    │  (namespaced ports)        │   per sink │ gpio         │
│ <extension> │              └───────────┬───────────────┘            │ <extension>  │
└─────────────┘                          │ fixed rate (default 120 Hz)└──────────────┘
        ▲                                 │
        │              ┌──────────────────┴───────────────────┐
        │              │  EngineLoop.step(dt)  — single tick   │
        │              └──────────────────┬───────────────────┘
        │                                 │ snapshot (SSE) + REST
   presets/*.json  ◄──── save/load ───────┤
                                          ▼
                            GUI (ui/) and/or CLI console (control.py)
```

---

## 2. Signal model

### 2.1 Values
Every value on the bus is a Python `float`. There is no other runtime value type.

### 2.2 Port types
A port declares a **type** used only as metadata (UI rendering and connect-time
validation); it does not change the runtime representation:

| type     | meaning                                            |
|----------|----------------------------------------------------|
| `scalar` | continuous quantity (roughly −1..1 or a physical unit) |
| `event`  | a gate (0/1) or a single-tick pulse                |

Type compatibility for a patch (`engine.signals.types_compatible`):

- `scalar → scalar` and `event → event`: allowed.
- `event → scalar`: allowed (0/1 is a valid scalar).
- `scalar → event`: allowed by the graph, but the chain **SHOULD** contain a
  `threshold` or `schmitt` node or the sink will chatter. The GUI greys the drop
  target and warns; it does not forbid it.

### 2.3 Port identifiers
A port has a local id (e.g. `gyro.z`). On the bus it is **namespaced** by its
owning instance id: `"<instance_id>/<port_id>"` (e.g. `joycon/gyro.z`,
`hid/mouse.dx`). Namespacing is the single string join `f"{iid}/{pid}"`; the first
`/` separates instance from port. Instance ids and port ids therefore **MUST NOT**
contain `/`.

### 2.4 `PortSpec`
`engine.signals.PortSpec(id, type=SCALAR, label="", group="misc", unit="", hint="")`.
`group` is a UI grouping hint. Serialised via `to_dict()`.

### 2.5 `ModuleSpec`
`engine.signals.ModuleSpec(id, label, kind, ports=[], status="ok")` where
`kind ∈ {"source","sink"}`. `status` is free-form (`"ok"`, `"mock"`,
`"dry-run"`, `"disconnected"`, `"error: …"`).

---

## 3. Transform nodes

A node is a stateful single-input single-output DSP block:

```
class Node:
    type: str                       # unique registry key
    def process(self, x: float, dt: float) -> float: ...
    def reset(self) -> None: ...     # clear internal state
```

- `process` is called once per tick per connection, in chain order, with `dt` the
  seconds elapsed since the previous tick. It **MUST** be pure with respect to
  everything except the node's own declared state and **MUST NOT** block.
- Node instances are **not** shared between connections; each connection builds
  its own chain (`Connection.rebuild`).
- `engine.nodes.NODE_CLASSES` maps `type → class`; `make_node(type, params)`
  constructs one. `NODE_SPECS` describes each node's editable parameters as either
  `{name: [default, min, max, step]}` (numeric) or `{name: {"choices": [...]}}`
  (enum). The GUI builds its editor solely from `NODE_SPECS`; adding a node type
  requires adding to both `NODE_CLASSES` and `NODE_SPECS`.

Shipped node types: `scale, offset, invert, abs, clamp, deadzone, expo, quantize,
ema, one_euro, rate_limit, threshold, schmitt, debounce, toggle, hold`.

---

## 4. Routing graph

`engine.graph` defines the patchbay's state.

### 4.1 Connection
```
Connection { id, source, sink, enabled=true, chain: [ {type, params}, ... ] }
```
- `id`: stable string; auto-assigned `c_<hex8>` when omitted.
- `source`, `sink`: namespaced port ids.
- `chain`: ordered list of node descriptors. `_nodes` is the live, instantiated
  chain, rebuilt on any `chain` change.
- Runtime-only fields: `activity` (smoothed |output|, for the cable glow) and
  `last` (last output value).

### 4.2 Graph evaluation — `Graph.tick(source_values, dt) -> {sink_port: float}`
For each **enabled** connection: read `source_values[source]` (absent ⇒ `0.0`),
run it through the chain, and **sum** the result into `out[sink]`. Multiple
connections into one sink port therefore add. Disabled connections are skipped and
have their `last`/`activity` decayed to 0.

### 4.3 Serialisation
A preset file **is** a serialised graph:
```json
{ "name": "<preset>",
  "connections": [
    { "id": "m_dx", "source": "joycon/gyro.x", "sink": "hid/mouse.dx",
      "enabled": true,
      "chain": [ {"type": "scale", "params": {"factor": 0.006}}, … ] }
  ] }
```
`enabled` defaults to `true`; `id` is generated if absent; `params` defaults to
`{}`. Presets are plain JSON in `presets/` (`<name>.json`).

---

## 5. Plugin system

`engine.registry` is the single source of truth for what is pluggable.

### 5.1 Type vs. instance id (normative)
Each plugin class declares two distinct names:

- **`type`** — the registry key: the value shown in the GUI dropdown, named on the
  CLI (`add source <type>`), and passed to `--source <type>`. One class per type.
- **`id`** — the *default instance id*, i.e. the bus namespace its ports appear
  under. Presets reference this; it **MUST** be stable across releases.

They are separate so a *stand-in* can share another plugin's bus namespace: the
mock source is `type="mock"`, `id="joycon"`; the dry-run sink is `type="dryrun"`,
`id="hid"`. A preset built against `joycon`/`hid` therefore runs unchanged whether
the real or the stand-in plugin is loaded.

When an instance is added, `EngineLoop` assigns it a **unique** instance id: the
requested id if free, else the requested id suffixed `-2`, `-3`, … The engine sets
`instance.id` to the assigned value, so `module()`, the bus namespace (the engine's
dict key), and the reported id always agree — including for a second board.

### 5.2 Registration & discovery
- `@register_source` / `@register_sink` register a class under `_type_key(cls)`
  (its `type`, falling back to `id`).
- A plugin is a **module folder** (§5.6) named after its `type`: `sources/<type>/`
  or `sinks/<type>/`, or a folder in an **extension directory**. Extension
  directories are every path in the `PATCHBAY_EXT_PATH` environment variable
  (`os.pathsep`-separated) plus every `--ext` entry.
- `discover(modules=None)` imports each enabled module (as returned by
  `engine.modules.ensure`, §5.6; default: every module found), each in its own
  `try/except`. Repo modules are imported as `sources.<type>` / `sinks.<type>`;
  extension folders are imported by path as packages.
- A module that raises on import is reported and skipped; it never registers. A
  folder whose name matches no registered `type` of its kind is reported.

### 5.3 Availability
A plugin **MUST** import its optional third-party dependencies lazily (inside
`__init__`/`start`, never at module top) so the class still registers when the
dependency is absent. It **SHOULD** override:
```
@classmethod
def available(cls) -> bool | tuple[bool, str]
```
returning `True`, or `(False, reason)` when it cannot run. `registry.availability`
normalises this. Unavailable plugins are **listed** (in the dropdown, `--list-*`,
and the CLI) but disabled with the reason, never hidden.

### 5.4 Introspection
- `catalog(registry, kind) -> [ {type, label, kind, default_id, available, reason,
  args:[{name, default, type, help}]} ]`. `args[].type ∈ {"int","float","str",
  "bool"}` tells a GUI which input widget to use.
- `describe(registry) -> str` renders the same for `--list-sources`/`--list-sinks`.

### 5.5 Instantiation
- `build(registry, type_name, kwargs=None, instance_id=None) -> (instance_id,
  instance)`. Constructor args are coerced by `ARGS[name]["type"]`: string inputs
  (CLI) are coerced; already-typed inputs (JSON) are trusted unless the target is
  `str`; a coercion that raises falls back to the raw value.
- `build_spec(registry, "type:k=v,k2=v2")` parses a CLI spec, then calls `build`.

### 5.6 Modules & dependencies (`engine.modules`)
Package management is declarative: the enabled module folders define the
environment, and a sync makes the installed packages match them **exactly**.

- **Manifest.** Each module folder **MUST** contain `__init__.py` and
  `module.toml`. A folder without `module.toml` is skipped with a warning.
  Manifest keys, all optional (unknown keys are warned about and ignored):

  | key | type | meaning |
  |---|---|---|
  | `kind` | `"source"`\|`"sink"` | implied by `sources/`/`sinks/`; **required** in extension dirs |
  | `python` | `[str]` | PEP 508 requirement strings (markers allowed) |
  | `depends` | `[str]` | module types whose *code* this one imports |
  | `system` | `[str]` | setup pip can't perform; printed, never executed |
  | `assets` | `[{file, url, sha256}]` | files fetched into the module folder |

- **Config.** `patchbay.toml` at the repo root, with all keys optional: `python`
  (core requirements, `["uv"]`), `disable` (module types to exclude), and
  `autostart` (`"type[:k=v,…]"` specs added on start; empty by default).
- **Resolution.** Enabled = found − `disable`. Then any module whose `depends` are
  not all enabled is removed, repeatedly, until the set is stable. Module names
  are unique across all directories, and the first one found wins.
- **Lock.** The requirement inputs are core `python` plus each enabled module's
  `python`, one input file per module, so the lock's `# via` lines name the module.
  They are hashed together with the minimum Python version (3.11). If
  `patchbay.lock`'s first line `# patchbay-inputs: <hash>` differs, or on
  `--upgrade`, the inputs are re-resolved with `uv pip compile --universal`. That
  run keeps existing pins as preferences unless upgrading. A resolution failure
  leaves the old lock and environment untouched.
- **Sync.** `uv pip sync patchbay.lock` runs against the running interpreter. It
  is exact: packages absent from the lock are uninstalled. Then each enabled
  module's assets are downloaded if they are missing or fail the sha256 check.
- **Failure modes are non-fatal.** If uv is missing, the sync fails, or `--no-sync`
  is given, the engine still starts with whatever is installed. Plugins whose
  packages are missing then show as unavailable (§5.3).

---

## 6. Source contract (`sources.base.Source`)

```
class Source:
    type: str; id: str; label: str
    PORTS: list[PortSpec]
    ARGS: dict            # {argname: {"default":…, "type":…, "help":…}}
    @classmethod
    def available(cls) -> bool | (bool, str)
    def start(self) -> None          # begin I/O (spawn your own thread here)
    def stop(self) -> None
    def status(self) -> str
    def module(self) -> ModuleSpec
    def read(self) -> dict[str, float]   # {port_id: value}, called every tick
```

- `read()` **MUST** be non-blocking and cheap: it runs inside the tick. Perform
  device/serial/Bluetooth I/O on the plugin's own thread and have `read()` return
  the latest cached sample.
- Vectors (accel/gyro/quaternions) **MUST** be flattened to per-axis scalar ports
  (`accel.x`, …); the graph only ever handles one number per port.
- Port ids returned by `read()` **SHOULD** match `PORTS`. Extra keys are still
  placed on the bus but have no `PortSpec` (no UI jack); missing keys read as `0`.

---

## 7. Sink contract (`sinks.base.Sink`)

```
class Sink:
    type: str; id: str; label: str
    PORTS: list[PortSpec]
    ARGS: dict
    accepts_any: bool = False        # True ⇒ graph may target ids not in PORTS
    @classmethod
    def available(cls) -> bool | (bool, str)
    def start(self) -> None
    def stop(self) -> None
    def status(self) -> str
    def release_all(self) -> None    # silence everything immediately (panic/stop)
    def module(self) -> ModuleSpec
    def apply(self, values: dict[str, float], dt: float) -> None   # every tick
```

- `apply` receives only the port ids routed to this sink this tick. A port
  **absent** from `values` means "no signal": the sink **MUST** treat it as 0 and
  release whatever it was holding.
- `release_all` **MUST** leave hardware safe (keys/buttons up, PWM neutral, e-stop
  asserted). It is called on panic and on shutdown.
- `PORTS` **MAY** be a dynamic `@property` (see `gpio`). Advertise a
  placeholder port whose id contains `<…>` (e.g. `key.<name>`) to
  signal "any id here is accepted"; set `accepts_any = True`.

### 7.1 Built-in `sys` sink
`EngineLoop` always injects a non-removable `sys` sink. Both ports are `event`
and act on a rising edge:

- `preset.cycle` loads the next preset file.
- `panic.toggle` flips panic, exactly like `set_panic(not panic)`.

Unlike every other sink, `sys` keeps receiving its inputs while panic is on, so
`panic.toggle` can end a panic. It drives no outputs, and its `release_all` keeps
its edge memory, so a button still held when panic engages is not read as a
second press. It cannot be added or removed via any interface.

---

## 8. Engine (`engine.loop.EngineLoop`)

Owns sources, sinks, the live graph, presets, and the shared snapshot.

### 8.1 The tick — `step(dt, clock=None)`
One tick, in order: read every source into `src_vals` → `graph.tick` → group by
sink namespace → `sink.apply` (empty dict when `panic`, except for `sys`) → service
a pending panic toggle, then a pending preset cycle → write the snapshot. `step` takes a consistent view of sources/sinks/graph
under the lock, so concurrent add/remove is safe.

`step` has **no dependency on threads**. `start()` runs it on a background thread
at a fixed rate for the PC build; a microcontroller target omits the thread and
calls `engine.step(dt)` from its own loop (see §12).

### 8.2 Runtime module management
| method | effect |
|---|---|
| `add_source(id, src, start=True)` / `add_sink(id, sink, start=True)` | assign a unique id, `start()` it, insert; bump `mod_rev`. Returns the id. |
| `create_source(type, kwargs=None, id=None)` / `create_sink(…)` | `build` from the registry, then add. |
| `remove_source(id)` / `remove_sink(id)` | stop + `release_all`, remove, and **prune** every connection whose source/sink is in that namespace. Returns the number pruned. `sys` cannot be removed. |

`mod_rev` is a monotonically increasing counter, published in the snapshot; a
client re-reads the module list whenever it changes.

### 8.3 Graph & preset operations
`graph_dict`, `replace_graph`, `add_connection`, `remove_connection`,
`update_connection`; `list_presets`, `load_preset`, `save_preset`,
`delete_preset`. `set_panic(on)` sets the flag and, when enabling, immediately
`release_all`s every sink.

### 8.4 Snapshot
`snapshot()` returns the latest:
```json
{ "t": <seconds>, "rate": <hz>, "preset": "<name>", "panic": <bool>,
  "mod_rev": <int>,
  "ports":       { "<src_port>":  <value>, … },
  "sinks":       { "<sink_port>": <value>, … },
  "connections": { "<conn_id>": { "activity": <0..1>, "value": <float> }, … } }
```

---

## 9. Host server (`server.py`)

Standard-library `http.server` + Server-Sent Events + REST. Binds `127.0.0.1:8420`
by default; serves the static UI and talks only to the local engine. No external
network access.

### 9.1 Endpoints
| method + path | body → response |
|---|---|
| `GET /` and any non-`/api/` path | static UI, served from `ui/dist/` |
| `GET /events` | SSE stream of §8.4 snapshots, ~30 Hz |
| `GET /api/state` | `{preset, presets, panic, rate, modules, nodes, plugins}` |
| `GET /api/graph` | graph dict (§4.3) |
| `GET /api/nodes` | `NODE_SPECS` |
| `GET /api/presets` | `{presets, current}` |
| `GET /api/plugins` | `{sources:[…catalog], sinks:[…catalog]}` (§5.4) |
| `PUT /api/graph` | `{name?, connections}` → `{ok, graph}` |
| `PUT /api/connection` | `{id, chain?, enabled?}` → connection \| `{error}` |
| `POST /api/connect` | `{source, sink, chain?}` → connection |
| `POST /api/disconnect` | `{id}` → `{ok}` |
| `POST /api/panic` | `{on}` → `{panic}` |
| `POST /api/rate` | `{rate}` → `{ok, rate}` (live tick-rate change) |
| `POST /api/preset/load` | `{name}` → `{ok, graph}` |
| `POST /api/preset/save` | `{name, graph?}` → `{ok, preset, presets}` |
| `POST /api/preset/delete` | `{name}` → `{ok, presets}` |
| `POST /api/source` | `{type, id?, args?}` → `{ok, id, modules}` |
| `POST /api/sink` | `{type, id?, args?}` → `{ok, id, modules}` |
| `POST /api/source/remove` | `{id}` → `{ok, dropped, modules, graph}` |
| `POST /api/sink/remove` | `{id}` → `{ok, dropped, modules, graph}` |

Errors are `{"error": "<message>"}` with a 4xx status. `modules` in a response is
the full post-change module list (`[ModuleSpec.to_dict()]`).

---

## 10. CLI console (`control.py`)

`Console(engine).run()` is an interactive REPL that maps each command onto the
`EngineLoop` methods of §8 — the same operations the REST API calls. Commands:
`plugins`, `modules`, `ports`, `add source|sink <type> [k=v …]`,
`remove source|sink <id>`, `connect`, `disconnect`, `graph`, `presets`,
`load`/`save`/`delete`, `panic`, `state`, `quit` (aliases: `ls`, `rm`, `?`,
`exit`, `q`). Quitting the console does **not** stop the engine when a web server
is also running.

---

## 11. Entry point (`run.py`)

Requires Python ≥ 3.11. Runs `engine.modules.ensure` (§5.6; `--no-sync` skips
the environment step, `--upgrade` forces re-resolution, and `--sync` syncs,
prints every enabled module's `system` notes and exits), then discovery, then
either a one-shot mode (`--list-sources`, `--list-sinks`,
`--list-ports`, `--selftest`) or the engine. Source/sink selection:

- no default source or sink: the engine comes up empty and you add modules live
  from the UI or the `--cli` console. `--mock` pre-loads the synthetic source
  (shorthand for `--source mock`) and `--source TYPE[:k=v]` (repeatable) pre-loads
  registered source plugins.
- `--dry-run` pre-loads the logging-only sink (shorthand for `--sink dryrun`) and
  `--sink TYPE[:k=v]` (repeatable) pre-loads registered sink plugins (e.g.
  `--sink hid` for the real mouse + keyboard).
- `patchbay.toml`'s `autostart` specs are appended to the matching list, by
  looking up each spec's type among the registered sources and sinks. Unknown or
  disabled types are reported and skipped. `--no-autostart` ignores the list for
  that run.

Front-end selection: web UI (default), `--cli` (web UI + console), `--no-ui`
(no server; with `--cli`, console only; without, a headless appliance loop).
`--ext DIR` (repeatable) adds extension directories of module folders. `--rate HZ` sets the tick
rate; `--preset NAME` the startup preset; `--host`/`--port` the bind address.

`--selftest` is the CI check: mock source → dry-run sink for 2 s, asserting the
snapshot has `joycon/gyro.z` and `rate == 120`.

---

## 12. Portability contract (microcontroller targets)

The project is layered so the routing core can run on a constrained target
(MicroPython/CircuitPython) while the editor stays on a PC.

- **Core (portable, standard library only):** `engine/signals.py`,
  `engine/nodes.py`, `engine/graph.py`, `engine/registry.py`, the `Source`/`Sink`
  contracts, and `EngineLoop.step`. No `numpy`, no third-party imports.
- **Host-only (PC / full CPython):** `server.py`, `ui/`, the `pynput` HID sink,
  the `pyjoycon` source, and `engine/modules.py` (package management: `tomllib`,
  `subprocess`, uv). These are optional front-ends and I/O adapters, not part of
  the routing core.
- **Threads are optional.** A target without usable threads omits
  `EngineLoop.start()` and instead calls `engine.step(dt)` from its own real-time
  loop, driving on-device sources/sinks written against the same contracts. A
  source that must poll a blocking bus either does so between ticks or on whatever
  concurrency the target offers.
- **Config portability.** Presets are plain JSON and portable verbatim. A target
  without a filesystem embeds them as a string/bytes literal. Because presets
  reference the stable bus **id** (§5.1), a preset authored in the PC GUI against
  `joycon`/`hid` runs on-device provided the target registers instances under the
  same ids.
- **Reconfiguration on-device** uses the CLI console (§10) or a subset of the REST
  API (§9), whichever the target can host.

---

## 13. Invariants

1. All bus values are `float`; port type is metadata only.
2. A port's bus id is exactly `"<instance_id>/<port_id>"`; neither part contains `/`.
3. Instance ids are unique within a running engine; the engine enforces this by
   suffixing and keeps `instance.id` equal to its bus namespace.
4. A plugin `type` maps to exactly one class; a preset's stability depends only on
   plugin **ids**, never on **types**.
5. `read()` and `process()` and `apply()` never block the tick.
6. Panic and shutdown call `release_all()` on every sink.
7. Removing a module prunes exactly the connections in its namespace and nothing
   else.
8. `EngineLoop.step` requires no threads and no host libraries.
