import { api } from '../lib/api'
import { h } from '../lib/dom'
import { live } from '../state/live'
import { toastError } from '../state/toast'
import { libraryBar } from './libraryBar'
import { presetBar } from './presetBar'
import { statusBar } from './statusBar'

export function topBar(): HTMLElement {
  return h(
    'header',
    { id: 'bar' },
    h('div', { className: 'brand' }, h('span', { className: 'glyph' }, '▚'), ' sensor · patchbay'),
    presetBar(),
    libraryBar(),
    h('div', { className: 'spacer' }),
    statusBar(),
    panicButton(),
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
