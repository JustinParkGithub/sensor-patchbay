/**
 * The cables between source and sink jacks.
 *
 * The *set* of paths — one `<g>` per connection, keyed by id — is reconciled
 * whenever the graph changes. The numbers on them are written separately:
 *
 *   - geometry (`d`, and the SVG's own size) is measured from the live DOM, so
 *     it is recomputed only when something could have moved — a graph change, a
 *     jack being built, a scroll, a resize;
 *   - width / opacity / dash offset are animated every frame from the signal
 *     activity in the live stream.
 *
 * Both are attribute writes on existing elements, which is what keeps this
 * affordable at 60fps on a Raspberry Pi.
 */

import { setChildren, svg } from '../lib/dom'
import { jacks } from '../state/jacks'
import { live } from '../state/live'
import { patchbay } from '../state/patchbay'
import type { PatchbayState } from '../state/patchbay'

/** Horizontal pull of the bezier handles, as a fraction of the span. */
const CURVE_RATIO = 0.45
const CURVE_MIN = 42
const CURVE_MAX = 170

const SELECTED_WIDTH = 3
const IDLE_WIDTH = 1.4
const DISABLED_OPACITY = 0.12

interface Cable {
  group: SVGGElement
  /** Fat transparent stroke that catches clicks. */
  hit: SVGPathElement
  vis: SVGPathElement
}

interface Point {
  x: number
  y: number
}

/** `surface` is the scroll container the cable layer sits in. */
export function cables(surface: HTMLElement): SVGSVGElement {
  const layer = svg('svg', { id: 'cables' })
  let paths = new Map<string, Cable>()
  let dirty = true
  let dashPhase = 0

  // Anything that can move a jack invalidates the cached path geometry: the
  // graph changing, a module being built or moved, the window resizing, a
  // zoom, or the patch area scrolling under the (content-space) cable layer.
  const invalidate = () => {
    dirty = true
  }
  jacks.subscribe(invalidate)
  window.addEventListener('resize', invalidate)
  surface.addEventListener('scroll', invalidate, { passive: true })
  surface.addEventListener('layoutchange', invalidate)

  const sync = (state: Readonly<PatchbayState>) => {
    const next = new Map<string, Cable>()
    for (const connection of state.graph.connections) {
      const cable = paths.get(connection.id) ?? createCable(connection.id)
      const isEvent = state.portIndex.get(connection.source)?.port.type === 'event'
      cable.vis.setAttribute('stroke', isEvent ? 'var(--out)' : 'var(--bridge)')
      cable.vis.setAttribute('stroke-dasharray', isEvent ? '2 7' : '1 7')
      next.set(connection.id, cable)
    }
    paths = next
    setChildren(layer, [...next.values()].map((cable) => cable.group))
    invalidate()
  }

  const layout = () => {
    const width = surface.scrollWidth
    const height = surface.scrollHeight
    layer.setAttribute('width', String(width))
    layer.setAttribute('height', String(height))
    layer.setAttribute('viewBox', `0 0 ${width} ${height}`)

    const origin = surface.getBoundingClientRect()
    for (const connection of patchbay.state.graph.connections) {
      const cable = paths.get(connection.id)
      if (!cable) continue
      const from = anchor(surface, origin, connection.source)
      const to = anchor(surface, origin, connection.sink)
      if (!from || !to) {
        cable.hit.removeAttribute('d')
        cable.vis.removeAttribute('d')
        continue
      }
      const d = bezier(from, to)
      cable.hit.setAttribute('d', d)
      cable.vis.setAttribute('d', d)
    }
  }

  const animate = () => {
    const frame = live.snapshot
    const { graph, selected } = patchbay.state
    for (const connection of graph.connections) {
      const cable = paths.get(connection.id)
      if (!cable) continue
      const activity = frame.connections[connection.id]?.activity ?? 0
      const isSelected = selected?.id === connection.id

      cable.vis.setAttribute(
        'stroke-width',
        ((isSelected ? SELECTED_WIDTH : IDLE_WIDTH) + activity * 3).toFixed(2),
      )
      cable.vis.setAttribute(
        'stroke-opacity',
        (connection.enabled ? 0.3 + activity * 0.6 : DISABLED_OPACITY).toFixed(2),
      )
      // The dash crawls faster the busier the cable is — the "signal flowing"
      // read you get from a patch bay's blinkenlights.
      cable.vis.setAttribute('stroke-dashoffset', (dashPhase * (0.5 + activity * 4)).toFixed(1))
    }
  }

  sync(patchbay.state)
  patchbay.subscribe((state, prev) => {
    if (state.graph !== prev.graph || state.portIndex !== prev.portIndex) sync(state)
  })

  requestAnimationFrame(function frame() {
    dashPhase -= 1
    if (dirty) {
      dirty = false
      layout()
    }
    animate()
    requestAnimationFrame(frame)
  })

  return layer
}

function createCable(id: string): Cable {
  const hit = svg('path', {
    class: 'hit',
    'data-id': id,
    onClick: () => patchbay.selectConnection(id),
  })
  const vis = svg('path', { 'data-id': id, fill: 'none', 'stroke-linecap': 'round' })
  return { group: svg('g', null, hit, vis), hit, vis }
}

/**
 * Centre of a jack's connector in the scroll container's content space.
 *
 * `#cables` is an absolutely-positioned child of the (position:relative) scroll
 * container, so its origin sits at the container's padding-box corner and it
 * scrolls with the content — hence adding scrollLeft/Top to the viewport-space
 * rects.
 */
function anchor(surface: HTMLElement, origin: DOMRect, id: string): Point | null {
  const jack = jacks.get(id)
  if (!jack) return null
  const rect = jack.port.getBoundingClientRect()
  return {
    x: rect.left - origin.left + surface.scrollLeft + rect.width / 2,
    y: rect.top - origin.top + surface.scrollTop + rect.height / 2,
  }
}

function bezier(from: Point, to: Point): string {
  const pull = Math.min(Math.max(Math.abs(to.x - from.x) * CURVE_RATIO, CURVE_MIN), CURVE_MAX)
  return `M ${from.x} ${from.y} C ${from.x + pull} ${from.y} ${to.x - pull} ${to.y} ${to.x} ${to.y}`
}
