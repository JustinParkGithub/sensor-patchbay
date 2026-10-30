import { api } from '../lib/api'
import { h } from '../lib/dom'
import { live } from '../state/live'
import { toastError } from '../state/toast'
import { libraryBar } from './libraryBar'
import { presetBar } from './presetBar'
import { statusBar } from './statusBar'
import { zoomControl } from './zoom'

export function topBar(): HTMLElement {
  return h(
    'header',
    { id: 'bar' },
    h('div', { className: 'brand' }, h('span', { className: 'glyph' }, '▚'), ' sensor · patchbay'),
    presetBar(),
    libraryBar(),
    zoomControl(),
    h('div', { className: 'spacer' }),
    statusBar(),
    panicButton(),
    quitButton(),
  )
}

/**
 * Stops the engine (outputs off, held keys released) and the server — the
 * whole app, window and tray included. What's left of a browser tab says so.
 */
function quitButton(): HTMLElement {
  const quit = async () => {
    if (!confirm('Quit sensor-patchbay? Every output stops.')) return
    try {
      await api.quit()
    } catch (e) {
      return toastError(e)
    }
    document.body.replaceChildren(
      h(
        'div',
        { id: 'stopped' },
        h('span', { className: 'glyph' }, '▚'),
        ' sensor · patchbay has stopped. You can close this tab.',
      ),
    )
  }
  return h(
    'button',
    { id: 'quitBtn', type: 'button', title: 'quit sensor-patchbay', onClick: () => void quit() },
    'Quit',
  )
}

/**
 * Kills every output and releases held keys/buttons. Its state comes from the
 * live stream, not from the click, so it always shows what the engine is doing.
 */
function panicButton(): HTMLElement {
  const button = h('button', {
    id: 'panicBtn',
    type: 'button',
    title: 'disable all outputs',
    onClick: () => void api.setPanic(!live.status.panic).catch(toastError),
  })

  const paint = () => {
    const { panic } = live.status
    button.className = panic ? 'armed' : ''
    button.textContent = panic ? 'PANIC · ON' : 'PANIC'
  }
  paint()
  live.onStatus((status, prev) => {
    if (status.panic !== prev.panic) paint()
  })

  return button
}
