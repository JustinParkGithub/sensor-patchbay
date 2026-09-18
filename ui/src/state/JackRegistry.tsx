/**
 * A live index of the DOM nodes behind each jack.
 *
 * Two things need real elements rather than React state: the meter painter
 * (writes a width and a number 30x/s) and the cable layout (measures where the
 * round connector actually landed). Both run outside the render cycle, so jacks
 * register their elements here on mount instead.
 *
 * Registration deliberately does not trigger a re-render — it notifies
 * subscribers, which use it to invalidate cached geometry.
 */

import { createContext, useContext, useRef } from 'react'
import type { ReactNode } from 'react'
import type { ModuleKind, PortType } from '../types'

export interface JackHandle {
  type: PortType
  kind: ModuleKind
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

  /** @returns an unregister function, for the caller's effect cleanup. */
  register(id: string, handle: JackHandle): () => void {
    this.jacks.set(id, handle)
    this.notify()
    return () => {
      // Guard against a remount having already replaced this entry.
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

  /** Called whenever the set of mounted jacks changes. */
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

const JackRegistryContext = createContext<JackRegistry | null>(null)

export function JackRegistryProvider({ children }: { children: ReactNode }) {
  const registry = useRef<JackRegistry | undefined>(undefined)
  registry.current ??= new JackRegistry()
  return (
    <JackRegistryContext.Provider value={registry.current}>{children}</JackRegistryContext.Provider>
  )
}

export function useJackRegistry(): JackRegistry {
  const registry = useContext(JackRegistryContext)
  if (!registry) throw new Error('useJackRegistry must be used inside <JackRegistryProvider>')
  return registry
}
