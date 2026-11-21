/**
 * Combos: triggers are locks on a dam across an ordinary cable.
 *
 * The cable runs source -> sink like any other. Each trigger is a `combine`
 * node on it that lets the signal through only while its condition holds
 * (`gate`: trigger >= level, `unless`: trigger < level); otherwise the sink
 * gets 0. Two triggers are two locks in series, so both must be open. Nodes
 * after the locks shape the signal as on any other cable.
 *
 *   wrist.x -> mouse.dx   combine op=unless input=hand.pinch level=0.3
 *                         ("flows while pinched": pinch distance below 0.3)
 *
 * Nothing about a combo is stored apart from that cable, so a preset carries it
 * like any other, and `findCombos` finds it again by reading the chain. Older
 * `chord` combos are listed too.
 */

import type { ChainNode, Connection, Graph } from '../types'

export type When = 'above' | 'below'

/** One trigger: the dam is open while `port` is above / below `level`. */
export interface Lock {
  port: string
  when: When
  level: number
}

export interface ComboSpec {
  locks: Lock[]
  /** What flows through when every lock is open. */
  source: string
  sink: string
}

export interface ComboCable {
  source: string
  sink: string
  chain: ChainNode[]
}

/** A combo found in the graph: one cable with locks (or an older chord) on it. */
export interface Combo {
  connection: Connection
  locks: Lock[]
  /** Set for `chord` combos, which the builder no longer makes. */
  chord: { trigger: string; partner: string; role: string } | null
}

export function lockNode(lock: Lock): ChainNode {
  return {
    type: 'combine',
    params: { op: lock.when === 'above' ? 'gate' : 'unless', input: lock.port, level: lock.level },
  }
}

/** The cable a spec becomes. */
export function comboCable(spec: ComboSpec): ComboCable {
  return { source: spec.source, sink: spec.sink, chain: spec.locks.map(lockNode) }
}

/** Why a spec can't be built yet, or null when it can. */
export function comboProblem(spec: ComboSpec): string | null {
  if (!spec.locks.length) return 'Pick a trigger.'
  if (spec.locks.some((l) => !Number.isFinite(l.level))) return 'Give each trigger a level.'
  if (new Set(spec.locks.map((l) => l.port)).size !== spec.locks.length) return 'Pick two different triggers.'
  if (!spec.source) return 'Pick a source to flow through.'
  if (!spec.sink) return 'Pick a sink.'
  return null
}

export function lockOpen(lock: Lock, value: number): boolean {
  return lock.when === 'above' ? value >= lock.level : value < lock.level
}

export function describeLock(lock: Lock, name: (port: string) => string = (p) => p): string {
  return `${name(lock.port)} ${lock.when === 'above' ? '≥' : '<'} ${lock.level}`
}

function lockOf(node: ChainNode): Lock | null {
  const input = String(node.params.input ?? '')
  if (node.type !== 'combine' || !input) return null
  const op = node.params.op ?? 'gate'
  if (op !== 'gate' && op !== 'unless') return null
  return { port: input, when: op === 'gate' ? 'above' : 'below', level: Number(node.params.level ?? 0.5) }
}

function comboOf(c: Connection): Combo | null {
  const locks = c.chain.map(lockOf).filter((l): l is Lock => l !== null)
  const node = c.chain.find((n) => n.type === 'chord' && n.params.input)
  const chord = node
    ? {
        trigger: String(node.params.trigger || c.source),
        partner: String(node.params.input),
        role: String(node.params.role ?? 'solo'),
      }
    : null
  return locks.length || chord ? { connection: c, locks, chord } : null
}

/** Every gated cable in the graph. */
export function findCombos(graph: Graph): Combo[] {
  return graph.connections.map(comboOf).filter((c): c is Combo => c !== null)
}

/**
 * Plain cables from the same source to the same sink: they flow around the
 * dam, so the sink gets the signal whether the trigger is held or not.
 */
export function bypassCables(graph: Graph, source: string, sink: string): Connection[] {
  return graph.connections.filter((c) => c.source === source && c.sink === sink && !comboOf(c))
}
