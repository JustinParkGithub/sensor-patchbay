/**
 * Two-button combos, built from `chord` nodes (see `engine/nodes.py`).
 *
 * A combo is up to three ordinary cables, each starting with a chord node that
 * names the other button and shares one window:
 *
 *   A -> aloneA   chord role=solo  input=B
 *   B -> aloneB   chord role=solo  input=A
 *   A -> both     chord role=both  input=B
 *
 * Nothing about a combo is stored apart from those cables, so a preset carries
 * them like any other, and `findCombos` regroups them by reading the chains.
 */

import type { ChainNode, Connection, Graph } from '../types'

export const DEFAULT_WINDOW_MS = 60

export interface ComboSpec {
  a: string
  b: string
  windowMs: number
  /** Sink ports; '' leaves that output unpatched. */
  aloneA: string
  aloneB: string
  both: string
}

export interface ComboCable {
  source: string
  sink: string
  chain: ChainNode[]
}

/** A combo found in the graph. The outputs are connections, when present. */
export interface Combo {
  key: string
  a: string
  b: string
  windowMs: number
  aloneA: Connection | null
  aloneB: Connection | null
  both: Connection | null
}

function chordNode(role: 'solo' | 'both', partner: string, windowMs: number): ChainNode {
  return { type: 'chord', params: { role, input: partner, window_ms: windowMs } }
}

/** The cables a spec becomes, one per patched output. */
export function comboCables(spec: ComboSpec): ComboCable[] {
  const { a, b, windowMs } = spec
  const out: ComboCable[] = []
  if (spec.aloneA) out.push({ source: a, sink: spec.aloneA, chain: [chordNode('solo', b, windowMs)] })
  if (spec.aloneB) out.push({ source: b, sink: spec.aloneB, chain: [chordNode('solo', a, windowMs)] })
  if (spec.both) out.push({ source: a, sink: spec.both, chain: [chordNode('both', b, windowMs)] })
  return out
}

/** Why a spec can't be built yet, or null when it can. */
export function comboProblem(spec: ComboSpec): string | null {
  if (!spec.a || !spec.b) return 'Pick both buttons.'
  if (spec.a === spec.b) return 'Pick two different buttons.'
  if (!spec.aloneA && !spec.aloneB && !spec.both) return 'Patch at least one output.'
  if (!(spec.windowMs >= 0)) return 'The window must be 0 ms or more.'
  return null
}

/** The connection's chord node, if its chain has one. */
function chordOf(c: Connection): { partner: string; role: string; windowMs: number } | null {
  const node = c.chain.find((n) => n.type === 'chord')
  if (!node) return null
  const partner = String(node.params.input ?? '')
  if (!partner) return null
  return {
    partner,
    role: String(node.params.role ?? 'solo'),
    windowMs: Number(node.params.window_ms ?? DEFAULT_WINDOW_MS),
  }
}

/**
 * Regroup the graph's chord cables into combos: one per unordered button pair
 * and window. `a` is whichever button the combo cable (or else the first
 * cable found) starts from.
 */
export function findCombos(graph: Graph): Combo[] {
  const combos = new Map<string, Combo>()
  for (const c of graph.connections) {
    const chord = chordOf(c)
    if (!chord) continue
    const pair = [c.source, chord.partner].sort()
    const key = `${pair[0]}|${pair[1]}|${chord.windowMs}`
    let combo = combos.get(key)
    if (!combo) {
      combo = { key, a: c.source, b: chord.partner, windowMs: chord.windowMs, aloneA: null, aloneB: null, both: null }
      combos.set(key, combo)
    }
    if (chord.role === 'both') {
      if (!combo.both && !combo.aloneA && !combo.aloneB) {
        combo.a = c.source
        combo.b = chord.partner
      }
      combo.both ??= c
    } else if (c.source === combo.a) {
      combo.aloneA ??= c
    } else {
      combo.aloneB ??= c
    }
  }
  return [...combos.values()]
}

/** Every connection a combo is made of. */
export function comboConnections(combo: Combo): Connection[] {
  return [combo.aloneA, combo.aloneB, combo.both].filter((c): c is Connection => c !== null)
}

/**
 * Plain cables (no chord node) from either button: they keep firing whatever
 * the combo decides, which is usually not what's wanted.
 */
export function directCables(graph: Graph, buttons: string[]): Connection[] {
  return graph.connections.filter((c) => buttons.includes(c.source) && !chordOf(c))
}
