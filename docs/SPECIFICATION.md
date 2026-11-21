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
controller (`EngineLoop`); neither can perform an operation the other cannot (the two are isomorphic).

```
 sources                     routing core                         sinks
┌─────────────┐   {port:      ┌───────────────────────────┐   {port:   ┌──────────────┐
│ controller  │──► float} ───►│  bus  →  graph  →  nodes   │──► float}─►│ hid          │
│ bend4, cv   │   per tick    │  (namespaced ports)        │   per sink │ sys          │
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
  target and warns, but does not forbid it.

### 2.3 Port identifiers
A port has a local id (e.g. `gyro.z`). On the bus it is **namespaced** by its
owning instance id: `"<instance_id>/<port_id>"` (e.g. `controller/gyro.z`,
`hid/mouse.dx`). Namespacing is the single string join `f"{iid}/{pid}"`; the first
`/` separates instance from port. Instance ids and port ids therefore **MUST NOT**
contain `/`.

### 2.4 `PortSpec`
`engine.signals.PortSpec(id, type=SCALAR, label="", group="misc", unit="", hint="")`.
`group` is a UI grouping hint. Serialised via `to_dict()`.

### 2.5 `ModuleSpec`
`engine.signals.ModuleSpec(id, label, kind, ports=[], status="ok")` where
`kind ∈ {"source","sink"}`. `status` is free-form (`"ok"`, `"searching"`,
`"disconnected"`, `"error: …"`).

---

## 3. Transform nodes

A node is a stateful DSP block with one output and, normally, one input:

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
  constructs one. `NODE_SPECS` describes each node's editable parameters as
  `{name: [default, min, max, step]}` (numeric), `{name: {"choices": [...]}}`
  (enum) or `{name: {"port": "source"}}` (a source port id). The GUI builds its
  editor solely from `NODE_SPECS`; adding a node type requires adding to both
  `NODE_CLASSES` and `NODE_SPECS`.
- A node with a non-empty `input_port` also has a second input: the connection
  copies that bus port into `node.other` before each `process` call (absent ⇒
  `0.0`). `engine.nodes.chain_inputs(chain)` lists the ports a serialised chain
  reads this way. They count toward a preset's required modules, and removing a
  source module removes every connection that reads it.

Shipped node types: `scale, offset, invert, abs, clamp, deadzone, expo, quantize,
ema, one_euro, rate_limit, threshold, schmitt, debounce, toggle, hold, combine, chord`.

`chord` (params `role`, `trigger`, `input`, `window_ms`, `level`) is a two-button combo. A
combo is up to three connections whose chord nodes share one button pair and one
window: `A → x` (`role=solo`, `input=B`), `B → y` (`solo`, `input=A`) and
`A → z` (`both`, `input=B`). Each node runs the same state machine over the pair,
so the three always agree. A press waits up to `window_ms` for the other button.
If the other button arrives in time, it's a chord, and `both` outputs 1 while the
chord is held. If not, the press is solo, and `solo` outputs 1 while it's held.
A solo tap shorter than the window fires a one-tick pulse on release. A press
that lands while the other button is already held as a solo press is solo
straight away. When a chord is broken, the button still held is spent until it's
released, but pressing the other one again re-forms the chord. There's no
separate combo object: the UI's combo builder writes and regroups these
connections (`ui/src/lib/combos.ts`).

With `trigger` unset, button A is the connection's own source and the node
outputs a 0/1 gate. With `trigger` set, A is the `trigger` port and B is
`input`. The connection's source is the payload: it passes through unchanged
while the role is active, and is 0 otherwise. For example, `stick → mouse.dx`
with `role=both, trigger=A, input=B` moves the mouse only while A + B is held.
The payload goes through the same chain, type check and sink as any other
connection.

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
    { "id": "m_dx", "source": "controller/gyro.y", "sink": "hid/mouse.dx",
      "enabled": true,
      "chain": [ {"type": "scale", "params": {"factor": 0.006}}, … ] }
  ] }
```
`enabled` defaults to `true`; `id` is generated if absent; `params` defaults to
`{}`. Presets are plain JSON in `presets/` (`<name>.json`), where `<name>` matches
`[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}` and doesn't end in `.`.

A preset **MAY** carry `"requires": [{"id", "kind", "types": [...]}, …]`, one
entry per bus namespace its connections use (`sys` excluded). `EngineLoop.save_preset`
**MUST** write it. `types` is the union of three sets: the type of the instance
running under `id` at save time, every registered type whose default `id` equals
it, and the types already listed in the file. A requirement is met when any of
`types` is registered and `available()`. With no `requires`, the namespaces in
`connections` are checked against registered default ids instead
(`engine.presets`).

---

## 5. Plugin system

`engine.registry` is the single source of truth for what is pluggable.

### 5.1 Type vs. instance id (normative)
Each plugin class declares two distinct names:

- **`type`** — the registry key: the value shown in the GUI dropdown, named on the
  CLI (`add source <type>`), and passed to `--source <type>`. One class per type.
- **`id`** — the *default instance id*, i.e. the bus namespace its ports appear
  under. Presets reference this; it **MUST** be stable across releases.

They are separate so a *stand-in* can share another plugin's bus namespace: a
simulator with `type="controller_sim"`, `id="controller"` presents the same ports
as the real `controller`, so a preset built against `controller` runs unchanged
on either.

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
  | `kind` | `"source"`\|`"sink"` | implied by `sources/`/`sinks/`; **required** in extension dirs and uploaded zips (every catalog manifest sets it) |
  | `description` | string | one line shown in the module catalog (optional) |
  | `version` | string | dotted numbers (`1.2.0`; a leading `v` and a `-suffix` are ignored when comparing); required by the catalog repo, optional elsewhere |
  | `entry` | path | the file that runs, relative to the folder; default `__init__.py`. A `.py` entry is imported as the package `<kind>s.<type>`. Any other entry is a native program: the module is found and listed, but the Python engine doesn't import it |
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
- **Packaged app.** When `sys.frozen` is set, the code is read-only and ships no
  modules or presets. Module folders, presets, `patchbay.toml` and the lock live
  in a per-user data folder (`engine.paths`; `PATCHBAY_HOME` overrides it), and
  `sources`/`sinks` import from there too. Instead of syncing the interpreter, the
  lock is installed (`uv pip install --target --no-deps`, with the bundled uv)
  into a new `site-packages/<lock digest>/`, which is appended to `sys.path`. It
  falls back to one package at a time, and a folder with failures is marked
  partial and retried. Other digests are deleted on the next start, except the
  last one in use. With no requirements, uv is not run.
- **Refresh.** `engine.library.sync()` (the UI's sync, the console's `sync`)
  repeats find → resolve → sync → `discover`. `discover` is idempotent: it
  imports new modules, re-imports a module whose `.py`/`.toml` files changed
  (path, mtime, size), and unregisters the types of modules no longer enabled.
  Running instances are untouched.
- **Failure modes are non-fatal.** If uv is missing, the sync fails, or `--no-sync`
  is given, the engine still starts with whatever is installed. Plugins whose
  packages are missing then show as unavailable (§5.3).

---

### 5.7 Module catalog (`engine.catalog`)

- No module or preset ships with the engine. Both are published by a
  **catalog**: a static tree with `index.json` at its root, module folders at
  `sources/<type>/…`, `sinks/<type>/…`, and preset files at
  `presets/<name>.json` (the `sensor-patchbay-modules` repo).
- `index.json` is `{"format": 1, "modules": [Entry…]}`. An Entry has `name`,
  `kind`, `description`, `version`, `entry`, `depends`, `python`, `system`,
  `digest`, and `files`: `[{path, sha256, size}]`. Each `path` is relative to
  the index URL and must lie under `<kind>s/<name>/`, and `entry` must be one of
  them; anything else rejects the whole index. A client refuses a `format`
  newer than it knows. (`version` and `entry` were added without a format
  bump: an index without them reads as `""` and `__init__.py`.)
- `index.json` may also hold `"presets": [{name, description, requires, path,
  sha256, size}]`, with `path` exactly `presets/<name>.json` and `requires` as
  in §8. An index without `presets` has none.
- `digest` = sha256 over the sorted lines `relpath "\0" sha256 "\n"` of the
  module's files (relpath inside the module folder), excluding dotfiles,
  `__pycache__`, `*.pyc`, `*.part` and declared `assets`.
- **Install record.** An upload or catalog install writes `.install.json` into
  the module folder: `{source, version, digest, installed}`. `source` is the
  index URL or `upload:<filename>`; `digest` is the folder's digest just after
  writing. A record inside an uploaded zip is discarded and rewritten.
- **States.** Every module found on disk (§5.6) is listed. With *cur* = its
  digest now, *rec* = its record, *cat* = the catalog's entry:
  - no *rec*: `installed` if *cat* exists and `cur == cat.digest`, else `local`;
  - `cur != rec.digest`: `modified`;
  - *cat* exists and `cat.digest != cur`: `update`, with `change` = `upgrade`,
    `downgrade` or `changed` by comparing `cat.version` with the installed
    `version` (`changed` when equal or not comparable);
  - otherwise `installed`.
  A module the catalog lacks is listed too, with `version` null.
- Location, first match wins: `$PATCHBAY_CATALOG`, `patchbay.toml` `catalog`,
  the built-in default. Plain paths and directories are allowed.
- **Install** (`name`): fetch the index, compute `name` plus the transitive
  closure of `depends` (cycles and unknown names are errors). Download every
  module not yet installed (plus `name` itself, always), check every file's
  sha256, then install it through the same path as an uploaded zip (§5.6),
  into the data folder, with the index URL as the record's `source`. Then
  sync. If `name` is installed and `modified` or `local`, refuse (a conflict)
  unless `force`.
- **Install a preset** (`name`, `kind: "preset"`, or a name only presets have):
  download it and check its sha256. For each `requires` entry that no
  installed module type meets, install the first of its `types` the catalog
  has (as a module install, above). Then write the preset through the same
  path as an uploaded `.json`. Refuse a `modified` or `local` preset file
  unless `force`.
- **Preset records.** Every preset upload or install records
  `{source, digest, catalog_sha256, installed}` under its name in
  `presets/.install-records` (JSON). `digest` is the file as written, and
  `catalog_sha256` the catalog's copy. Deleting a preset drops its record.
  States are as for modules, with no record → `local`, `digest` ≠ the file →
  `modified` (Save over it), `catalog_sha256` ≠ the index's → `update`
  (`change` = `changed`; presets have no versions).
- **Remove** (`name`): delete the module folder, but only if it is in the data
  folder (not an extension dir), and report the installed modules that depend
  on it. With `kind: "preset"` (or a name only a preset has), delete the preset
  file and its record. Then sync.
- HTTP: `GET /api/catalog[?refresh=1]` (rows for modules and presets; presets
  have `kind: "preset"` and `requires`; every row has `in_catalog`),
  `POST /api/catalog/install {name, kind?, force?}`, `POST /api/catalog/remove {name, kind?}`
  (`kind` is `"module"` or `"preset"`). Both POSTs answer like `POST /api/sync`,
  plus `installed` / `removed`. A conflict is `409 {"error", "conflict": true}`.
  Same origin/host checks as every POST.

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
- `PORTS` **MAY** be a dynamic `@property` (e.g. one port per configured pin). Advertise a
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
| `GET /api/state` | `{preset, presets, preset_info, panic, rate, modules, nodes, plugins}`; `preset_info` is `{name: {requires, missing:[{id, kind, types, reason}]}}` |
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
| `POST /api/preset/load` | `{name}` → `{ok, graph, missing}` |
| `POST /api/preset/save` | `{name, graph?}` → `{ok, preset, presets, preset_info}` |
| `POST /api/preset/delete` | `{name}` → `{ok, presets, preset_info}` |
| `POST /api/upload?filename=F` | raw file body: a preset `.json` or a module `.zip` → `{ok, kind, name, replaced, …}` (`engine.library`) |
| `POST /api/sync` | `{upgrade?}` → `{ok, report:{log, notes, sources, sinks}, plugins, presets, preset_info}`; re-runs the module sync and `discover` |
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
either a one-shot mode (`--list-sources`, `--list-sinks`, `--catalog`,
`--selftest`) or the engine. `--install NAME` (repeatable, with `--force`)
installs modules or presets from the catalog (§5.7) before discovery.
Source/sink selection:

- no default source or sink: the engine comes up empty and you add modules live
  from the UI or the `--cli` console. `--source TYPE[:k=v]` and
  `--sink TYPE[:k=v]` (repeatable) pre-load registered plugins (e.g.
  `--sink hid` for the real mouse + keyboard).
- `patchbay.toml`'s `autostart` specs are appended to the matching list, by
  looking up each spec's type among the registered sources and sinks. Unknown or
  disabled types are reported and skipped. `--no-autostart` ignores the list for
  that run.

Front-end selection: web UI (default), `--cli` (web UI + console), `--no-ui`
(no server; with `--cli`, console only; without, a headless appliance loop).
`--ext DIR` (repeatable) adds extension directories of module folders. `--rate HZ` sets the tick
rate; `--preset NAME` the startup preset (default none: an empty graph);
`--host`/`--port` the bind address.

`--selftest` is the CI check and needs no modules: a built-in oscillator source
→ a recording sink, through a `scale` → `clamp` chain, for 2 s. It asserts the
snapshot has `osc/sine`, `rate == 120`, more than 100 ticks reached the sink,
and every value stayed clamped.

---

## 12. Portability contract (microcontroller targets)

The project is layered so the routing core can run on a constrained target
(MicroPython/CircuitPython) while the editor stays on a PC.

- **Core (portable, standard library only):** `engine/signals.py`,
  `engine/nodes.py`, `engine/graph.py`, `engine/registry.py`, the `Source`/`Sink`
  contracts, and `EngineLoop.step`. No `numpy`, no third-party imports.
- **Host-only (PC / full CPython):** `server.py`, `ui/`, the `pynput` HID sink,
  the SDL `controller` source, and `engine/modules.py` (package management: `tomllib`,
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
  `controller`/`hid` runs on-device provided the target registers instances under the
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
