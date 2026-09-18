/**
 * The cables between source and sink jacks.
 *
 * React owns the *set* of paths — one `<g>` per connection, keyed by id. The
 * numbers on them do not go through React at all:
 *
 *   - geometry (`d`, and the SVG's own size) is measured from the live DOM, so
 *     it is recomputed only when something could have moved — a graph change, a
 *     jack mounting, a scroll, a resize;
 *   - width / opacity / dash offset are animated every frame from the signal
 *     activity in the live stream.
 *
 * Both are attribute writes on existing elements, which is what keeps this
 * affordable at 60fps on a Raspberry Pi.
 */

import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import { useAnimationFrame } from '../hooks/useAnimationFrame'
import { useJackRegistry } from '../state/JackRegistry'
import type { JackRegistry } from '../state/JackRegistry'
import { useLive } from '../state/LiveProvider'
import { usePatchbay } from '../state/PatchbayProvider'
import type { Connection } from '../types'

/** Horizontal pull of the bezier handles, as a fraction of the span. */
const CURVE_RATIO = 0.45
const CURVE_MIN = 42
const CURVE_MAX = 170

const SELECTED_WIDTH = 3
const IDLE_WIDTH = 1.4
const DISABLED_OPACITY = 0.12

interface CablePaths {
  /** Fat transparent stroke that catches clicks. */
  hit: SVGPathElement
  vis: SVGPathElement
}

interface Point {
  x: number
  y: number
}

export function Cables({ surfaceRef }: { surfaceRef: React.RefObject<HTMLElement | null> }) {
  const { graph, portIndex, selected, selectConnection } = usePatchbay()
  const registry = useJackRegistry()
  const { snapshot } = useLive()

  const svgRef = useRef<SVGSVGElement>(null)
  const paths = useRef(new Map<string, CablePaths>())
  const dirty = useRef(true)
  const dashPhase = useRef(0)

  const invalidate = useCallback(() => {
    dirty.current = true
  }, [])

  const register = useCallback(
    (id: string, elements: CablePaths) => {
      paths.current.set(id, elements)
      invalidate()
      return () => {
        if (paths.current.get(id) === elements) paths.current.delete(id)
      }
    },
    [invalidate],
  )

  // Anything that can move a jack invalidates the cached path geometry: the
  // graph changing, a module mounting, the window resizing, or the patch area
  // scrolling under the (content-space) cable layer.
  useEffect(invalidate, [invalidate, graph])
  useEffect(() => registry.subscribe(invalidate), [registry, invalidate])
  useEffect(() => {
    const surface = surfaceRef.current
    window.addEventListener('resize', invalidate)
    surface?.addEventListener('scroll', invalidate, { passive: true })
    return () => {
      window.removeEventListener('resize', invalidate)
      surface?.removeEventListener('scroll', invalidate)
    }
  }, [invalidate, surfaceRef])

  const layout = useCallback(() => {
    const svg = svgRef.current
    const surface = surfaceRef.current
    if (!svg || !surface) return

    const width = surface.scrollWidth
    const height = surface.scrollHeight
    svg.setAttribute('width', String(width))
    svg.setAttribute('height', String(height))
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`)

    const origin = surface.getBoundingClientRect()
    for (const connection of graph.connections) {
      const elements = paths.current.get(connection.id)
      if (!elements) continue
      const from = anchor(registry, surface, origin, connection.source)
      const to = anchor(registry, surface, origin, connection.sink)
      if (!from || !to) {
        elements.hit.removeAttribute('d')
        elements.vis.removeAttribute('d')
        continue
      }
      const d = bezier(from, to)
      elements.hit.setAttribute('d', d)
      elements.vis.setAttribute('d', d)
    }
  }, [graph, registry, surfaceRef])

  const animate = useCallback(() => {
    const live = snapshot.current
    for (const connection of graph.connections) {
      const elements = paths.current.get(connection.id)
      if (!elements) continue
      const activity = live.connections[connection.id]?.activity ?? 0
      const isSelected = selected?.id === connection.id

      elements.vis.setAttribute(
        'stroke-width',
        ((isSelected ? SELECTED_WIDTH : IDLE_WIDTH) + activity * 3).toFixed(2),
      )
      elements.vis.setAttribute(
        'stroke-opacity',
        (connection.enabled ? 0.3 + activity * 0.6 : DISABLED_OPACITY).toFixed(2),
      )
      // The dash crawls faster the busier the cable is — the "signal flowing"
      // read you get from a patch bay's blinkenlights.
      elements.vis.setAttribute(
        'stroke-dashoffset',
        (dashPhase.current * (0.5 + activity * 4)).toFixed(1),
      )
    }
  }, [graph, selected, snapshot])

  useAnimationFrame(() => {
    dashPhase.current -= 1
    if (dirty.current) {
      dirty.current = false
      layout()
    }
    animate()
  })

  return (
    <svg id="cables" ref={svgRef} xmlns="http://www.w3.org/2000/svg">
      {graph.connections.map((connection) => (
        <Cable
          key={connection.id}
          connection={connection}
          isEvent={portIndex.get(connection.source)?.port.type === 'event'}
          onSelect={selectConnection}
          register={register}
        />
      ))}
    </svg>
  )
}

function Cable({
  connection,
  isEvent,
  onSelect,
  register,
}: {
  connection: Connection
  isEvent: boolean
  onSelect: (id: string) => void
  register: (id: string, elements: CablePaths) => () => void
}) {
  const hit = useRef<SVGPathElement>(null)
  const vis = useRef<SVGPathElement>(null)

  useLayoutEffect(() => {
    if (!hit.current || !vis.current) return
    return register(connection.id, { hit: hit.current, vis: vis.current })
  }, [register, connection.id])

  return (
    <g>
      <path
        ref={hit}
        className="hit"
        data-id={connection.id}
        onClick={() => onSelect(connection.id)}
      />
      <path
        ref={vis}
        data-id={connection.id}
        fill="none"
        strokeLinecap="round"
        stroke={isEvent ? 'var(--out)' : 'var(--bridge)'}
        strokeDasharray={isEvent ? '2 7' : '1 7'}
      />
    </g>
  )
}

/**
 * Centre of a jack's connector in the scroll container's content space.
 *
 * `#cables` is an absolutely-positioned child of the (position:relative) scroll
 * container, so its origin sits at the container's padding-box corner and it
 * scrolls with the content — hence adding scrollLeft/Top to the viewport-space
 * rects.
 */
function anchor(
  registry: JackRegistry,
  surface: HTMLElement,
  origin: DOMRect,
  id: string,
): Point | null {
  const jack = registry.get(id)
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
