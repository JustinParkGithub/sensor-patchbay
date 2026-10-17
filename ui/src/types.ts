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
export type ParamSpec = NumericParamSpec | ChoiceParamSpec

/** Parameters of one node type; `{}` for nodes that take none (invert, abs). */
export type NodeSpec = Record<string, ParamSpec>
export type NodeSpecs = Record<string, NodeSpec>

export function isChoiceSpec(spec: ParamSpec): spec is ChoiceParamSpec {
  return !Array.isArray(spec)
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

/** `GET /api/state` — everything that only changes when the graph is reloaded. */
export interface EngineState {
  preset: string
  presets: string[]
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
