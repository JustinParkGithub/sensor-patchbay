import { h } from '../lib/dom'
import { patchbay } from '../state/patchbay'

/** The one-line prompt at the bottom, tracking where you are in a patch. */
export function hint(): HTMLElement {
  const element = h('div', { id: 'hint' })

  const paint = (armed: boolean) =>
    element.replaceChildren(
      ...(armed
        ? ['Now click a ', h('b', null, 'sink'), ' jack.']
        : [
            'Click a ',
            h('b', null, 'source'),
            ' jack, then a ',
            h('b', null, 'sink'),
            ' jack, to patch. Click a cable to shape it.',
          ]),
    )

  paint(false)
  patchbay.subscribe((state, prev) => {
    if (Boolean(state.armed) !== Boolean(prev.armed)) paint(Boolean(state.armed))
  })

  return element
}
