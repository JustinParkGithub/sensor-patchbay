/**
 * The `/events` SSE stream.
 *
 * Snapshots arrive ~30x/s. Most of the panel only cares about a handful of
 * fields, so the stream is split in two:
 *
 *   - `snapshot` / `subscribe` — the raw frame. Meters and cables read it and
 *     write the DOM themselves (see `components/meters.ts`, `cables.ts`).
 *   - `status` / `onStatus` — the fields that drive real UI structure (link,
 *     panic, rounded rate, preset, module revision). Listeners hear about it
 *     only when one of those fields actually changes, which is rare.
 */

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
  /** Module-set revision; a change means another client added/removed a module. */
  modRev: number
}

type FrameSubscriber = (snapshot: Snapshot) => void
type StatusSubscriber = (status: LiveStatus, prev: LiveStatus) => void

const INITIAL_STATUS: LiveStatus = { link: 'bad', panic: false, rate: null, preset: '', modRev: 0 }

export class LiveStream {
  private frame: Snapshot = EMPTY_SNAPSHOT
  private current: LiveStatus = INITIAL_STATUS
  private readonly frameSubscribers = new Set<FrameSubscriber>()
  private readonly statusSubscribers = new Set<StatusSubscriber>()

  /** Latest frame. Read it from frame callbacks or rAF; it changes 30x/s. */
  get snapshot(): Snapshot {
    return this.frame
  }

  get status(): LiveStatus {
    return this.current
  }

  connect(): void {
    const source = new EventSource('/events')

    source.onopen = () => this.setStatus({ ...this.current, link: 'ok' })
    source.onerror = () => this.setStatus({ ...this.current, link: 'bad' })

    source.onmessage = (event) => {
      let frame: Snapshot
      try {
        frame = JSON.parse(event.data) as Snapshot
      } catch {
        return // a truncated frame; the next one is 33ms away
      }
      this.frame = frame
      for (const fn of this.frameSubscribers) fn(frame)

      this.setStatus({
        link: this.current.link,
        panic: frame.panic,
        rate: Math.round(frame.rate),
        preset: frame.preset,
        modRev: frame.mod_rev ?? 0,
      })
    }
  }

  /** Every frame. @returns an unsubscribe function. */
  subscribe(fn: FrameSubscriber): () => void {
    this.frameSubscribers.add(fn)
    return () => {
      this.frameSubscribers.delete(fn)
    }
  }

  /** Status changes only. @returns an unsubscribe function. */
  onStatus(fn: StatusSubscriber): () => void {
    this.statusSubscribers.add(fn)
    return () => {
      this.statusSubscribers.delete(fn)
    }
  }

  private setStatus(next: LiveStatus): void {
    const prev = this.current
    if (
      prev.link === next.link &&
      prev.panic === next.panic &&
      prev.rate === next.rate &&
      prev.preset === next.preset &&
      prev.modRev === next.modRev
    )
      return
    this.current = next
    for (const fn of this.statusSubscribers) fn(next, prev)
  }
}

export const live = new LiveStream()
