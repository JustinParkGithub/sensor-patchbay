import { h } from '../lib/dom'
import { zoom, ZOOM_MAX, ZOOM_MIN } from '../state/zoom'

/** The − 100% + control in the top bar; the percentage resets to 100%. */
export function zoomControl(): HTMLElement {
  const out = h('button', { type: 'button', title: 'zoom out (⌘−)', onClick: () => zoom.step(-1) }, '−')
  const level = h('button', {
    type: 'button',
    className: 'zoom-level',
    title: 'reset zoom (⌘0) · pinch or ⌘/Ctrl+scroll to zoom',
    onClick: () => zoom.set(1),
  })
  const into = h('button', { type: 'button', title: 'zoom in (⌘+)', onClick: () => zoom.step(1) }, '+')

  const paint = (scale: number) => {
    level.textContent = `${Math.round(scale * 100)}%`
    out.disabled = scale <= ZOOM_MIN
    into.disabled = scale >= ZOOM_MAX
  }
  paint(zoom.scale)
  zoom.subscribe(paint)

  return h('div', { className: 'group zoom', 'aria-label': 'zoom' }, out, level, into)
}

/** WebKit's trackpad pinch (Safari, the macOS app window); not in the DOM types. */
interface GestureEvent extends UIEvent {
  scale: number
  clientX: number
  clientY: number
}

/**
 * Scale `stage` inside the scroll container `surface`, and route the zoom
 * gestures there: pinch (WebKit gesture events, or Ctrl+wheel elsewhere),
 * ⌘/Ctrl+wheel, and ⌘/Ctrl + = / − / 0. The browser's own page zoom is
 * suppressed for those, since this one keeps the cables and the top bar sane.
 */
export function bindZoom(surface: HTMLElement): void {
  surface.style.setProperty('--zoom', String(zoom.scale))

  zoom.subscribe((scale, prev, anchor) => {
    // Keep the content point under the anchor (or the view's centre) still.
    const frame = surface.getBoundingClientRect()
    const px = anchor ? anchor.clientX - frame.left : surface.clientWidth / 2
    const py = anchor ? anchor.clientY - frame.top : surface.clientHeight / 2
    const cx = (surface.scrollLeft + px) / prev
    const cy = (surface.scrollTop + py) / prev
    surface.style.setProperty('--zoom', String(scale))
    surface.scrollLeft = cx * scale - px
    surface.scrollTop = cy * scale - py
    surface.dispatchEvent(new Event('layoutchange'))
  })

  surface.addEventListener(
    'wheel',
    (e) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const lines = e.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : 1
      zoom.set(zoom.scale * Math.exp(-e.deltaY * lines * 0.01), e)
    },
    { passive: false },
  )

  let pinchFrom = 1
  surface.addEventListener('gesturestart', (e) => {
    e.preventDefault()
    pinchFrom = zoom.scale
  })
  surface.addEventListener('gesturechange', (e) => {
    e.preventDefault()
    const gesture = e as GestureEvent
    zoom.set(pinchFrom * gesture.scale, gesture)
  })

  window.addEventListener('keydown', (e) => {
    if (!(e.metaKey || e.ctrlKey) || e.altKey) return
    if (e.key === '=' || e.key === '+') zoom.step(1)
    else if (e.key === '-' || e.key === '_') zoom.step(-1)
    else if (e.key === '0') zoom.set(1)
    else return
    e.preventDefault()
  })
}
