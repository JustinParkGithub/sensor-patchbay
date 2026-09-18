/**
 * Typed wrapper over the engine's REST API (see `server.py`). One function per
 * endpoint, so callers never hand-write a path or a request body.
 */

import type { ChainNode, Connection, EngineState, Graph } from '../types'

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

export const api = {
  state: () => request<EngineState>('GET', '/api/state'),
  graph: () => request<Graph>('GET', '/api/graph'),

  connect: (source: string, sink: string) =>
    request<Connection>('POST', '/api/connect', { source, sink }),
  disconnect: (id: string) => request<{ ok: boolean }>('POST', '/api/disconnect', { id }),
  updateConnection: (patch: ConnectionPatch) =>
    request<Connection>('PUT', '/api/connection', patch),

  setPanic: (on: boolean) => request<{ panic: boolean }>('POST', '/api/panic', { on }),

  loadPreset: (name: string) =>
    request<{ ok: boolean; graph: Graph }>('POST', '/api/preset/load', { name }),
  savePreset: (name: string, graph: Graph) =>
    request<{ ok: boolean; preset: string; presets: string[] }>('POST', '/api/preset/save', {
      name,
      graph,
    }),
  deletePreset: (name: string) =>
    request<{ ok: boolean; presets: string[] }>('POST', '/api/preset/delete', { name }),
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
