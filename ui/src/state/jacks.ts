/**
 * A live index of the DOM nodes behind each jack.
 *
 * Three things work from real elements rather than from the patchbay state:
 * the meter painter (writes a width and a number 30x/s), the cable layout
 * (measures where the round connector actually landed), and the patch area's
 * armed / compatible / wired classes. Jacks register their elements here when
 * they are built.
 *
 * Registration notifies subscribers, which use it to invalidate cached geometry.
 */

import type { ModuleKind, PortType } from '../types'

export interface JackHandle {
  type: PortType
  kind: ModuleKind
  /** The whole jack row — carries the state classes. */
  root: HTMLElement
  /** The round connector — cables anchor to its centre. */
  port: HTMLElement
  /** The bar that gets its width driven by the signal level. */
  meter: HTMLElement
  /** The numeric/gate readout. */
  value: HTMLElement
}

export class JackRegistry {
  private readonly jacks = new Map<string, JackHandle>()
  private readonly listeners = new Set<() => void>()

  /** @returns an unregister function, for when the jack is thrown away. */
  register(id: string, handle: JackHandle): () => void {
    this.jacks.set(id, handle)
    this.notify()
    return () => {
      // Guard against a rebuilt jack having already replaced this entry.
      if (this.jacks.get(id) === handle) {
        this.jacks.delete(id)
        this.notify()
      }
    }
  }

  get(id: string): JackHandle | undefined {
    return this.jacks.get(id)
  }

  entries(): IterableIterator<[string, JackHandle]> {
    return this.jacks.entries()
  }

  /** Called whenever the set of registered jacks changes. */
  subscribe(fn: () => void): () => void {
    this.listeners.add(fn)
    return () => {
      this.listeners.delete(fn)
    }
  }

  private notify(): void {
    for (const fn of this.listeners) fn()
  }
}

export const jacks = new JackRegistry()
