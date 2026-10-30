/**
 * Free-floating module cards.
 *
 * A card starts docked in its column. Dragging it by its header lifts it onto
 * the float layer, an absolutely-positioned layer in the (zoomed) stage, so
 * floating cards scroll and scale with everything else; double-clicking the
 * header docks it again.
 *
 * Cards never overlap. Each floating card has the position it was dropped at
 * (kept per module id in this browser's localStorage — a per-viewer layout,
 * not part of the patch) and is *shown* at the nearest spot to it that's clear
 * of the columns and of the cards above it. That's re-worked out whenever
 * something could have moved underneath: a card added, removed, docked,
 * resized, or the columns reflowing on a window resize or zoom. Stored order
 * is raise order: the card dropped last keeps its spot first.
 */

import { h } from '../lib/dom'

const STORAGE_KEY = 'patchbay.cardPositions'
/** Pointer travel before a press on the header becomes a drag. */
const DRAG_THRESHOLD = 4
/** Clear space kept around every card, in stage pixels. */
const GAP = 12
/** The single-column phone layout has no room to float in. */
const NARROW = window.matchMedia('(max-width: 820px)')

interface Position {
  x: number
  y: number
}

interface Rect extends Position {
  w: number
  h: number
}

function load(): Map<string, Position> {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as [string, Position][]
    return new Map(raw.filter(([, p]) => Number.isFinite(p?.x) && Number.isFinite(p?.y)))
  } catch {
    return new Map()
  }
}

function overlaps(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w + GAP && a.x + a.w + GAP > b.x && a.y < b.y + b.h + GAP && a.y + a.h + GAP > b.y
}

/**
 * The free position nearest `want` for a `want.w` × `want.h` card. Candidates
 * are the wanted spot and every edge-to-edge spot beside an obstacle, so the
 * card slides just clear of whatever it was dropped on.
 */
export function freeSpot(want: Rect, obstacles: Rect[]): Position {
  const clear = (x: number, y: number) => !obstacles.some((o) => overlaps({ ...want, x, y }, o))
  if (clear(want.x, want.y)) return want
  const xs = [want.x, 0, ...obstacles.flatMap((o) => [o.x - want.w - GAP, o.x + o.w + GAP])]
  const ys = [want.y, 0, ...obstacles.flatMap((o) => [o.y - want.h - GAP, o.y + o.h + GAP])]
  let best: Position | null = null
  let bestDistance = Infinity
  for (const x of xs) {
    if (x < 0) continue
    for (const y of ys) {
      const distance = Math.hypot(x - want.x, y - want.y)
      if (y < 0 || distance >= bestDistance || !clear(x, y)) continue
      best = { x, y }
      bestDistance = distance
    }
  }
  // Unreachable in practice (below everything is always clear), but be total.
  return best ?? { x: want.x, y: Math.max(...obstacles.map((o) => o.y + o.h + GAP)) }
}

/** Pin a card to a floating position, or (undefined) let it flow docked. */
export function placeCard(element: HTMLElement, position: Position | undefined): void {
  element.classList.toggle('floating', !!position)
  element.style.left = position ? `${position.x}px` : ''
  element.style.top = position ? `${position.y}px` : ''
}

export interface FloatingCards {
  layer: HTMLElement
  /** Whether a module's card floats (else it's docked in its column). */
  isFloating: (id: string) => boolean
  /** Floating module ids, bottom to top. */
  order: () => string[]
  /** Make a card's header its drag handle. */
  attach: (element: HTMLElement, id: string) => void
  /** Show every floating card at its nearest clear spot. */
  settle: () => void
}

/**
 * `stage` is the zoomed content the float layer goes in (its `scale()` is
 * passed so pointer and layout pixels can be converted); `relayout` re-files
 * cards into columns / the float layer after one is lifted or docked. Moves
 * fire `layoutchange` on the stage so the cables can follow.
 */
export function floatingCards(
  stage: HTMLElement,
  scale: () => number,
  relayout: () => void,
): FloatingCards {
  const layer = h('div', { className: 'float-layer' })
  const wanted = load()
  const elements = new Map<string, HTMLElement>()

  const save = () => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...wanted]))
    } catch {
      // private window / storage blocked: the layout just doesn't persist
    }
  }
  const changed = () => stage.dispatchEvent(new Event('layoutchange', { bubbles: true }))

  /** An element's box in the float layer's (unzoomed) coordinates. */
  const box = (element: Element): Rect => {
    const rect = element.getBoundingClientRect()
    const origin = layer.getBoundingClientRect()
    const z = scale()
    return {
      x: (rect.left - origin.left) / z,
      y: (rect.top - origin.top) / z,
      w: rect.width / z,
      h: rect.height / z,
    }
  }
  /** What a floating card must keep clear of: the columns' contents. */
  const dockedBoxes = () =>
    [...stage.querySelectorAll('.col h2, .col .module, .col .add-mod')].map(box)
  const floatingCard = (id: string) => {
    const element = elements.get(id)
    return element?.parentElement === layer ? element : undefined
  }

  const settle = () => {
    if (NARROW.matches) return
    const taken = dockedBoxes()
    // Topmost first: the card placed last keeps its spot, older ones give way.
    for (const id of [...wanted.keys()].reverse()) {
      const element = floatingCard(id)
      // The card in hand finds its own spot when it's dropped.
      if (!element || element.classList.contains('dragging')) continue
      const want = { ...wanted.get(id)!, w: element.offsetWidth, h: element.offsetHeight }
      const spot = freeSpot(want, taken)
      placeCard(element, spot)
      taken.push({ ...want, ...spot })
    }
    changed()
  }

  // A card growing (a camera preview loading) or the columns reflowing (window
  // resize, zoom) can push things into each other.
  let pending = 0
  const resized = new ResizeObserver(() => {
    cancelAnimationFrame(pending)
    pending = requestAnimationFrame(settle)
  })
  resized.observe(stage)

  const attach = (element: HTMLElement, id: string) => {
    elements.set(id, element)
    resized.observe(element)
    const header = element.querySelector<HTMLElement>('.mh')
    if (!header) return
    header.title = 'drag to move · double-click to dock'

    header.addEventListener('pointerdown', (down) => {
      if (down.button !== 0 || NARROW.matches || (down.target as Element).closest('button')) return
      down.preventDefault() // no text selection while dragging
      header.setPointerCapture(down.pointerId)

      let origin: Position | null = null
      let at: Position = { x: 0, y: 0 }
      const onMove = (move: PointerEvent) => {
        const z = scale()
        const dx = (move.clientX - down.clientX) / z
        const dy = (move.clientY - down.clientY) / z
        if (!origin) {
          if (Math.hypot(dx, dy) * z < DRAG_THRESHOLD) return
          // Lift from wherever the card is drawn now, docked or floating, and
          // put it on top of the stack.
          origin = box(element)
          wanted.delete(id)
          wanted.set(id, origin)
          element.classList.add('dragging')
          relayout()
        }
        at = { x: Math.max(0, origin.x + dx), y: Math.max(0, origin.y + dy) }
        placeCard(element, at)
        changed()
      }
      const onUp = () => {
        header.removeEventListener('pointermove', onMove)
        header.removeEventListener('pointerup', onUp)
        header.removeEventListener('pointercancel', onUp)
        if (!origin) return
        element.classList.remove('dragging')
        // Dropped on something: slide to the nearest clear spot, and keep that.
        const others = [...wanted.keys()].filter((other) => other !== id)
        const taken = [
          ...dockedBoxes(),
          ...others.flatMap((other) => {
            const card = floatingCard(other)
            return card ? [box(card)] : []
          }),
        ]
        const spot = freeSpot({ ...at, w: element.offsetWidth, h: element.offsetHeight }, taken)
        wanted.set(id, spot)
        placeCard(element, spot)
        save()
        changed()
      }
      header.addEventListener('pointermove', onMove)
      header.addEventListener('pointerup', onUp)
      header.addEventListener('pointercancel', onUp)
    })

    header.addEventListener('dblclick', (e) => {
      if ((e.target as Element).closest('button') || !wanted.delete(id)) return
      save()
      relayout()
    })
  }

  return {
    layer,
    isFloating: (id) => wanted.has(id),
    order: () => [...wanted.keys()],
    attach,
    settle,
  }
}
