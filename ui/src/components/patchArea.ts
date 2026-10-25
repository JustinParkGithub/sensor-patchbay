import { h, setChildren } from '../lib/dom'
import { jacks } from '../state/jacks'
import { patchbay } from '../state/patchbay'
import type { PatchbayState } from '../state/patchbay'
import type { ModuleKind, ModuleSpec } from '../types'
import { addModule } from './addModule'
import { cables } from './cables'
import { startMeters } from './meters'
import { moduleCard } from './moduleCard'
import type { ModuleCard } from './moduleCard'

interface CachedCard extends ModuleCard {
  kind: ModuleKind
  /** The spec it was built from; an identical spec reuses the card as-is. */
  signature: string
}

/** Sources on the left, sinks on the right, cables in between. */
export function patchArea(): HTMLElement {
  const sourceList = h('div', { className: 'modules', id: 'srcMods' })
  const sinkList = h('div', { className: 'modules', id: 'sinkMods' })

  const surface = h(
    'main',
    { id: 'patch' },
    column('sources', 'source', 'Sources', sourceList),
    column('sinks', 'sink', 'Sinks', sinkList),
  )
  surface.prepend(cables(surface))
  startMeters()

  // Cards are keyed by module id and rebuilt only when that module's spec
  // changes — the module list is re-read often (any add/remove, from any
  // client), and rebuilding would restart a camera preview's stream.
  let cards = new Map<string, CachedCard>()

  const syncCards = (modules: ModuleSpec[]) => {
    const next = new Map<string, CachedCard>()
    for (const module of modules) {
      const signature = JSON.stringify(module)
      const existing = cards.get(module.id)
      next.set(
        module.id,
        existing?.signature === signature
          ? existing
          : { ...moduleCard(module), kind: module.kind, signature },
      )
    }
    for (const [id, card] of cards) if (next.get(id) !== card) card.dispose()
    cards = next

    const of = (kind: ModuleKind) =>
      [...next.values()].filter((card) => card.kind === kind).map((card) => card.element)
    setChildren(sourceList, of('source'))
    setChildren(sinkList, of('sink'))
  }

  const paintJacks = ({ wired, armed, compatible }: Readonly<PatchbayState>) => {
    for (const [id, jack] of jacks.entries()) {
      jack.root.classList.toggle('wired', wired.has(id))
      jack.root.classList.toggle('armed', armed === id)
      jack.root.classList.toggle('compatible', compatible.has(id))
    }
  }

  patchbay.subscribe((state, prev) => {
    if (state.modules !== prev.modules) syncCards(state.modules)
    if (
      state.modules !== prev.modules ||
      state.wired !== prev.wired ||
      state.armed !== prev.armed ||
      state.compatible !== prev.compatible
    )
      paintJacks(state)
  })

  return surface
}

function column(id: string, kind: ModuleKind, title: string, list: HTMLElement): HTMLElement {
  return h('section', { className: 'col', id }, h('h2', null, title), list, addModule(kind))
}
