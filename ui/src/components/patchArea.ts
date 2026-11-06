import { h, setChildren } from '../lib/dom'
import { jacks } from '../state/jacks'
import { patchbay } from '../state/patchbay'
import type { PatchbayState } from '../state/patchbay'
import { zoom } from '../state/zoom'
import type { ModuleKind, ModuleSpec } from '../types'
import { addModule } from './addModule'
import { cables } from './cables'
import { floatingCards, placeCard } from './floating'
import { bindZoom } from './zoom'
import { startMeters } from './meters'
import { moduleCard } from './moduleCard'
import type { ModuleCard } from './moduleCard'

interface CachedCard extends ModuleCard {
  kind: ModuleKind
  /** The spec it was built from; an identical spec reuses the card as-is. */
  signature: string
}

/**
 * Sources on the left, sinks on the right, cables in between — and any card
 * dragged out of its column floating wherever it was dropped.
 *
 * `#patch` is the scroll container; inside it the cable layer, and the stage
 * that holds the columns and floating cards and is scaled by the zoom.
 */
export function patchArea(): HTMLElement {
  const sourceList = h('div', { className: 'modules', id: 'srcMods' })
  const sinkList = h('div', { className: 'modules', id: 'sinkMods' })

  const stage = h(
    'div',
    { className: 'stage' },
    column('sources', 'source', 'Sources', sourceList),
    column('sinks', 'sink', 'Sinks', sinkList),
  )
  const surface = h('main', { id: 'patch' }, stage)
  surface.prepend(cables(surface))
  bindZoom(surface)
  startMeters()
  const floating = floatingCards(stage, () => zoom.scale, () => fileCards())
  stage.append(floating.layer)

  // Cards are keyed by module id and rebuilt only when that module's spec
  // changes — the module list is re-read often (any add/remove, from any
  // client), and rebuilding would restart a camera preview's stream.
  let cards = new Map<string, CachedCard>()

  const syncCards = (modules: ModuleSpec[]) => {
    const next = new Map<string, CachedCard>()
    for (const module of modules) {
      const signature = JSON.stringify(module)
      const existing = cards.get(module.id)
      if (existing?.signature === signature) {
        next.set(module.id, existing)
        continue
      }
      const card = { ...moduleCard(module), kind: module.kind, signature }
      floating.attach(card.element, module.id)
      next.set(module.id, card)
    }
    for (const [id, card] of cards) if (next.get(id) !== card) card.dispose()
    cards = next
    fileCards()
  }

  /** Docked cards into their columns, floating ones onto the float layer. */
  const fileCards = () => {
    for (const [id, card] of cards) {
      if (floating.isFloating(id)) card.element.classList.add('floating')
      else placeCard(card.element, undefined)
    }
    const docked = (kind: ModuleKind) =>
      [...cards]
        .filter(([id, card]) => card.kind === kind && !floating.isFloating(id))
        .map(([, card]) => card.element)
    setChildren(sourceList, docked('source'))
    setChildren(sinkList, docked('sink'))
    setChildren(
      floating.layer,
      floating.order().flatMap((id) => cards.get(id)?.element ?? []),
    )
    floating.settle()
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
