/**
 * Typed wrapper over the engine's REST API (see `server.py`). One function per
 * endpoint, so callers never hand-write a path or a request body.
 */

import type {
  CatalogListing,
  ChainNode,
  Connection,
  EngineState,
  Graph,
  MissingRequirement,
  ModuleKind,
  ModuleSpec,
  PluginCatalog,
  PresetInfoMap,
  SyncReport,
  UploadResult,
} from '../types'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** The engine reports failures as `{"error": "..."}`; fall back to the status line. */
async function toError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: string }
    return new ApiError(body.error || res.statusText, res.status)
  } catch {
    return new ApiError(res.statusText, res.status)
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    ...(body === undefined
      ? {}
      : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  if (!res.ok) throw await toError(res)
  return (await res.json()) as T
}

export interface ConnectionPatch {
  id: string
  chain?: ChainNode[]
  enabled?: boolean
}

/** What every call that ends in a sync answers with. */
export interface SyncedResponse {
  ok: boolean
  report: SyncReport
  plugins: PluginCatalog
  presets: string[]
  preset_info: PresetInfoMap
}

export const api = {
  state: () => request<EngineState>('GET', '/api/state'),
  graph: () => request<Graph>('GET', '/api/graph'),

  connect: (source: string, sink: string) =>
    request<Connection>('POST', '/api/connect', { source, sink }),
  disconnect: (id: string) => request<{ ok: boolean }>('POST', '/api/disconnect', { id }),
  updateConnection: (patch: ConnectionPatch) =>
    request<Connection>('PUT', '/api/connection', patch),

  setPanic: (on: boolean) => request<{ panic: boolean }>('POST', '/api/panic', { on }),
  /** Stop the whole app; the engine releases every output first. */
  quit: () => request<{ ok: boolean }>('POST', '/api/quit'),
  setRate: (rate: number) => request<{ ok: boolean; rate: number }>('POST', '/api/rate', { rate }),

  addModule: (kind: ModuleKind, type: string, args: Record<string, unknown>) =>
    request<{ ok: boolean; id: string; modules: ModuleSpec[] }>('POST', `/api/${kind}`, {
      type,
      args,
    }),
  removeModule: (kind: ModuleKind, id: string) =>
    request<{ ok: boolean; dropped: number; modules: ModuleSpec[]; graph: Graph }>(
      'POST',
      `/api/${kind}/remove`,
      { id },
    ),

  loadPreset: (name: string) =>
    request<{ ok: boolean; graph: Graph; missing: MissingRequirement[] }>(
      'POST',
      '/api/preset/load',
      { name },
    ),
  savePreset: (name: string, graph: Graph) =>
    request<{ ok: boolean; preset: string; presets: string[]; preset_info: PresetInfoMap }>(
      'POST',
      '/api/preset/save',
      { name, graph },
    ),
  deletePreset: (name: string) =>
    request<{ ok: boolean; presets: string[]; preset_info: PresetInfoMap }>(
      'POST',
      '/api/preset/delete',
      { name },
    ),

  /** Re-read modules + presets on disk and install module packages; can take a while. */
  sync: () => request<SyncedResponse>('POST', '/api/sync', {}),

  /** The online module catalog; `refresh` skips the engine's 5-minute memo. */
  catalog: (refresh = false) =>
    request<CatalogListing>('GET', `/api/catalog${refresh ? '?refresh=1' : ''}`),
  /**
   * Download a module (and its depends) from the catalog, then sync. Without
   * `force`, the engine refuses (409) to overwrite a modified or hand-placed copy.
   */
  catalogInstall: (name: string, force = false) =>
    request<SyncedResponse & { installed: UploadResult[] }>('POST', '/api/catalog/install', { name, force }),
  /** Delete an installed module from the data folder, then sync. */
  catalogRemove: (name: string) =>
    request<SyncedResponse & { removed: { name: string; kind: ModuleKind; needed_by: string[] } }>(
      'POST',
      '/api/catalog/remove',
      { name },
    ),

  /** A module `.zip` or a preset `.json`, sent as the raw body. */
  upload: async (file: File): Promise<UploadResult> => {
    const res = await fetch(`/api/upload?filename=${encodeURIComponent(file.name)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    })
    if (!res.ok) throw await toError(res)
    return (await res.json()) as UploadResult
  },
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
