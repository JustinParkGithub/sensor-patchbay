/**
 * How far the patch area is zoomed: a scale between `ZOOM_MIN` and `ZOOM_MAX`,
 * kept in this browser's localStorage (a per-viewer view setting, like the
 * floating card positions).
 *
 * Listeners get the new and previous scale and, for a pinch or Ctrl+wheel, the
 * viewport point to zoom about — the patch area keeps that point still.
 */

export const ZOOM_MIN = 0.4
export const ZOOM_MAX = 1.5
/** Where the − / + buttons and keyboard shortcuts stop. */
const STEPS = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.25, 1.5]
const STORAGE_KEY = 'patchbay.zoom'

export interface ZoomAnchor {
  clientX: number
  clientY: number
}

type Listener = (scale: number, prev: number, anchor: ZoomAnchor | null) => void

function clamp(scale: number): number {
  return Math.round(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, scale)) * 100) / 100
}

function load(): number {
  try {
    const stored = Number(localStorage.getItem(STORAGE_KEY))
    return stored ? clamp(stored) : 1
  } catch {
    return 1
  }
}

export class ZoomStore {
  private value = load()
  private readonly listeners = new Set<Listener>()

  get scale(): number {
    return this.value
  }

  set(scale: number, anchor: ZoomAnchor | null = null): void {
    const next = clamp(scale)
    if (next === this.value) return
    const prev = this.value
    this.value = next
    try {
      localStorage.setItem(STORAGE_KEY, String(next))
    } catch {
      // storage blocked: the zoom just doesn't persist
    }
    for (const listener of this.listeners) listener(next, prev, anchor)
  }

  /** To the next step in (1) or out (-1). */
  step(direction: 1 | -1): void {
    const next =
      direction > 0
        ? STEPS.find((s) => s > this.value + 0.001)
        : [...STEPS].reverse().find((s) => s < this.value - 0.001)
    if (next !== undefined) this.set(next)
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }
}

export const zoom = new ZoomStore()
