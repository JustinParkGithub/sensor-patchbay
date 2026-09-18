/** Port-id arithmetic and value formatting shared across the patch panel. */

import type { Graph, ModuleSpec, PortSpec } from '../types'

/** Graph-wide address of a jack: `module/port`. */
export function portId(moduleId: string, portLocalId: string): string {
  return `${moduleId}/${portLocalId}`
}

/** `joycon/gyro.z` -> `gyro.z` — what the inspector shows as a title. */
export function shortPortId(fullId: string): string {
  return fullId.split('/').slice(1).join('/')
}

/**
 * Some modules advertise a templated jack (`key.<name>`) purely as
 * documentation. It is rendered greyed out and cannot be patched.
 */
export function isPlaceholder(port: PortSpec): boolean {
  return port.id.includes('<')
}

export interface PortEntry {
  module: ModuleSpec
  port: PortSpec
  placeholder: boolean
}

/** Flatten the module list into a lookup keyed by full port id. */
export function buildPortIndex(modules: ModuleSpec[]): Map<string, PortEntry> {
  const index = new Map<string, PortEntry>()
  for (const module of modules) {
    for (const port of module.ports) {
      index.set(portId(module.id, port.id), { module, port, placeholder: isPlaceholder(port) })
    }
  }
  return index
}

/** Every port that currently has a cable on it, for the "wired" jack style. */
export function wiredPorts(graph: Graph): Set<string> {
  const used = new Set<string>()
  for (const c of graph.connections) {
    used.add(c.source)
    used.add(c.sink)
  }
  return used
}

/**
 * Sinks the armed source may legally drive. `scalar -> event` is allowed (the
 * engine re-checks after the chain runs), so an event source fits anywhere.
 */
export function compatibleSinks(index: Map<string, PortEntry>, armed: string | null): Set<string> {
  const ok = new Set<string>()
  if (!armed) return ok
  const source = index.get(armed)
  if (!source) return ok
  for (const [id, entry] of index) {
    if (entry.placeholder || entry.module.kind !== 'sink') continue
    if (entry.port.type === source.port.type || source.port.type === 'event') ok.add(id)
  }
  return ok
}

/** The newest cable between two jacks — the one we just created. */
export function lastConnectionBetween(graph: Graph, source: string, sink: string): string | null {
  const matches = graph.connections.filter((c) => c.source === source && c.sink === sink)
  return matches.length ? matches[matches.length - 1]!.id : null
}

/** Meter readout: enough precision to be useful, narrow enough to not jitter. */
export function formatValue(v: number): string {
  const a = Math.abs(v)
  if (a >= 100) return v.toFixed(0)
  if (a >= 1) return v.toFixed(2)
  return v.toFixed(3)
}
