/**
 * The wire format the Python engine speaks over REST + SSE.
 *
 * These mirror `engine/signals.py` (PortSpec, ModuleSpec), `engine/graph.py`
 * (Connection, Graph) and `engine/nodes.py` (NODE_SPECS). Keep them in step
 * when a field is added on that side — nothing else here knows the shapes.
 */

export type PortType = 'scalar' | 'event'
export type ModuleKind = 'source' | 'sink'

/** One jack. `id` is module-local; the graph addresses it as `module/port`. */
export interface PortSpec {
  id: string
  type: PortType
  label: string
  group: string
  unit: string
  hint: string
}

export interface ModuleSpec {
  id: string
  label: string
  kind: ModuleKind
  ports: PortSpec[]
  /** Free-form: "ok" | "mock" | "dry-run" | "error: ..." */
  status: string
  /** Serves a live MJPEG preview at `/api/source/<id>/preview` (e.g. the camera). */
  preview?: boolean
}

export type ParamValue = number | string

/** One transform sitting on a cable. */
export interface ChainNode {
  type: string
  params: Record<string, ParamValue>
}

export interface Connection {
  id: string
  source: string
  sink: string
  enabled: boolean
  chain: ChainNode[]
}

export interface Graph {
  name: string
  connections: Connection[]
}

/** `[default, min, max, step]` — the engine's spec for a numeric parameter. */
export type NumericParamSpec = readonly [number, number, number, number]
export interface ChoiceParamSpec {
  choices: string[]
}
/** A second input: the value is a source port id, read off the bus each tick. */
export interface PortParamSpec {
  port: 'source'
}
export type ParamSpec = NumericParamSpec | ChoiceParamSpec | PortParamSpec

/** Parameters of one node type; `{}` for nodes that take none (invert, abs). */
export type NodeSpec = Record<string, ParamSpec>
export type NodeSpecs = Record<string, NodeSpec>

export function isChoiceSpec(spec: ParamSpec): spec is ChoiceParamSpec {
  return 'choices' in spec
}

export function isPortSpec(spec: ParamSpec): spec is PortParamSpec {
  return 'port' in spec
}

/** One constructor arg of a plugin, from its `ARGS` (see `engine/registry.py`). */
export interface PluginArg {
  name: string
  default: string | number | boolean | null
  type: 'int' | 'float' | 'str' | 'bool'
  help: string
}

/** One registered plugin type — an entry in the add-source / add-sink picker. */
export interface PluginInfo {
  type: string
  label: string
  kind: ModuleKind
  default_id: string
  /** False when an optional dependency is missing; `reason` says which. */
  available: boolean
  reason: string
  args: PluginArg[]
}

export interface PluginCatalog {
  sources: PluginInfo[]
  sinks: PluginInfo[]
}

/**
 * A bus namespace a preset patches into, and the plugin types that can fill it
 * (see `engine/presets.py`). Written into the preset file on every save.
 */
export interface PresetRequirement {
  id: string
  kind: ModuleKind
  types: string[]
}

/** A requirement no installed, runnable module meets. */
export interface MissingRequirement extends PresetRequirement {
  reason: string
}

export interface PresetInfo {
  requires: PresetRequirement[]
  missing: MissingRequirement[]
  /** Set when the file couldn't be read. */
  error?: string
}

export type PresetInfoMap = Record<string, PresetInfo>

/** What `POST /api/sync` did, for the sync button's report. */
export interface SyncReport {
  /** Every message the module sync printed (installs, import failures, ...). */
  log: string[]
  /** Setup steps pip can't do, per enabled module. */
  notes: { module: string; note: string }[]
  sources: number
  sinks: number
}

/** Where a catalog module stands on this machine (see `engine/catalog.py`). */
export type CatalogState = 'available' | 'installed' | 'update' | 'modified' | 'local'

/** One entry of `GET /api/catalog`: a module, or (kind `preset`) a preset. */
export interface CatalogModule {
  name: string
  kind: ModuleKind | 'preset'
  description: string
  /** Presets only: the modules it patches into (any one of `types` will do). */
  requires?: PresetRequirement[]
  depends: string[]
  python: string[]
  system: string[]
  /** The catalog's version; null for a module the catalog doesn't have. */
  version: string | null
  /** What runs: a `.py` file, or a native program (see `runnable`). */
  entry: string
  /** The catalog has it (so it can be installed, updated or replaced from there). */
  in_catalog: boolean
  /** False when this engine can't run the entry (a native plugin). */
  runnable: boolean
  state: CatalogState
  /** The installed copy's version; null when not installed. */
  installed_version: string | null
  /** For `update`: how the catalog's version compares with the installed one. */
  change: 'upgrade' | 'downgrade' | 'changed' | null
  /** Where the installed copy came from (its install record): the index URL, `upload:<file>`, or null. */
  source: string | null
  /** Whether the engine may delete it (it lives in the data folder). */
  removable: boolean
  /** Bytes to download; 0 for modules the catalog doesn't have. */
  size: number
}

/** `GET /api/catalog` — the online module index, marked with what's installed. */
export interface CatalogListing {
  url: string
  /** True when the index couldn't be fetched and this is the last copy seen. */
  cached: boolean
  error: string | null
  modules: CatalogModule[]
}

/** `POST /api/upload` — one file written into the data folder. */
export type UploadResult =
  | { ok: true; kind: 'preset'; name: string; replaced: boolean; missing: MissingRequirement[] }
  | {
      ok: true
      kind: 'module'
      name: string
      module_kind: ModuleKind
      replaced: boolean
      path: string
      version: string
      digest: string
    }

/** `GET /api/state` — everything that only changes when the graph is reloaded. */
export interface EngineState {
  preset: string
  presets: string[]
  preset_info: PresetInfoMap
  panic: boolean
  rate: number
  modules: ModuleSpec[]
  nodes: NodeSpecs
  plugins: PluginCatalog
}

export interface ConnectionActivity {
  activity: number
  value: number
}

/** One frame of live state, pushed ~30x/s over `/events`. */
export interface Snapshot {
  t: number
  ports: Record<string, number>
  sinks: Record<string, number>
  connections: Record<string, ConnectionActivity>
  panic: boolean
  preset: string
  rate: number
  /** Bumped whenever a module is added or removed, from any client. */
  mod_rev: number
}

export const EMPTY_SNAPSHOT: Snapshot = {
  t: 0,
  ports: {},
  sinks: {},
  connections: {},
  panic: false,
  preset: '',
  rate: 0,
  mod_rev: 0,
}

export const EMPTY_GRAPH: Graph = { name: '', connections: [] }
export const EMPTY_CATALOG: PluginCatalog = { sources: [], sinks: [] }
