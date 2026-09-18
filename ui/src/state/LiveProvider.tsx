/**
 * The `/events` SSE stream.
 *
 * Snapshots arrive ~30x/s. Routing every one of them through React state would
 * re-render the whole patch panel 30 times a second for values that are painted
 * straight onto two DOM nodes per jack, so the stream is split in two:
 *
 *   - `snapshot` / `subscribe` — the raw frame, delivered imperatively. Meters
 *     and cables read it from a ref or a subscription and write the DOM
 *     themselves (see `useMeters`, `Cables`).
 *   - `status` — the handful of fields that drive real UI structure (link,
 *     panic, rounded rate, preset). This *is* React state, but it only changes
 *     identity when one of those fields actually changes, so re-renders are rare.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { EMPTY_SNAPSHOT } from '../types'
import type { Snapshot } from '../types'

export type LinkState = 'ok' | 'bad'

export interface LiveStatus {
  link: LinkState
  panic: boolean
  /** Engine tick rate in Hz, rounded; `null` until the first frame arrives. */
  rate: number | null
  /** Preset the engine believes is loaded — it can change without us asking. */
  preset: string
}

type Subscriber = (snapshot: Snapshot) => void

interface LiveValue {
  /** Latest frame, mutated in place. Read it from rAF/stream callbacks only. */
  snapshot: { readonly current: Snapshot }
  subscribe: (fn: Subscriber) => () => void
  status: LiveStatus
}

const INITIAL_STATUS: LiveStatus = { link: 'bad', panic: false, rate: null, preset: '' }

const LiveContext = createContext<LiveValue | null>(null)

export function LiveProvider({ children }: { children: ReactNode }) {
  const snapshot = useRef<Snapshot>(EMPTY_SNAPSHOT)
  const subscribers = useRef(new Set<Subscriber>())
  const [status, setStatus] = useState<LiveStatus>(INITIAL_STATUS)

  useEffect(() => {
    const source = new EventSource('/events')

    source.onopen = () => setStatus((prev) => (prev.link === 'ok' ? prev : { ...prev, link: 'ok' }))
    source.onerror = () =>
      setStatus((prev) => (prev.link === 'bad' ? prev : { ...prev, link: 'bad' }))

    source.onmessage = (event) => {
      let frame: Snapshot
      try {
        frame = JSON.parse(event.data) as Snapshot
      } catch {
        return // a truncated frame; the next one is 33ms away
      }
      snapshot.current = frame
      for (const fn of subscribers.current) fn(frame)

      const rate = Math.round(frame.rate)
      setStatus((prev) =>
        prev.panic === frame.panic && prev.rate === rate && prev.preset === frame.preset
          ? prev
          : { link: prev.link, panic: frame.panic, rate, preset: frame.preset },
      )
    }

    return () => source.close()
  }, [])

  // Stable across status changes so subscribers are never torn down and
  // rebuilt just because the rate ticked over a whole Hz.
  const subscribe = useCallback((fn: Subscriber) => {
    subscribers.current.add(fn)
    return () => {
      subscribers.current.delete(fn)
    }
  }, [])

  const value = useMemo<LiveValue>(
    () => ({ snapshot, subscribe, status }),
    [subscribe, status],
  )

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>
}

export function useLive(): LiveValue {
  const value = useContext(LiveContext)
  if (!value) throw new Error('useLive must be used inside <LiveProvider>')
  return value
}

export function useLiveStatus(): LiveStatus {
  return useLive().status
}
