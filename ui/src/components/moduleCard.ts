import { classes, h } from '../lib/dom'
import { isPlaceholder, portId } from '../lib/ports'
import { jacks } from '../state/jacks'
import { patchbay } from '../state/patchbay'
import type { ModuleSpec, PortSpec, PortType } from '../types'

/** The engine's built-in sink (preset cycling); it can't be removed. */
const PERMANENT = 'sys'

/** What a readout shows before the first frame of live data arrives. */
const IDLE_GLYPH: Record<PortType, string> = { scalar: '–', event: '○' }

export interface ModuleCard {
  element: HTMLElement
  /** Unregister the card's jacks; call once the card is thrown away. */
  dispose: () => void
}

/**
 * One source or sink panel. Ports arrive pre-ordered from the plugin; a group
 * heading is emitted wherever the group changes, so the plugin's grouping is
 * the only thing deciding layout.
 */
export function moduleCard(module: ModuleSpec): ModuleCard {
  const remove = () => {
    if (!confirm(`Remove ${module.kind} "${module.id}"? Cables using it are deleted.`)) return
    void patchbay.removeModule(module.kind, module.id)
  }

  const element = h(
    'div',
    { className: `module ${module.kind === 'source' ? 'src-mod' : 'sink-mod'}` },
    h(
      'div',
      { className: 'mh' },
      h('span', { className: 'swatch' }),
      h('span', { className: 'mname' }, module.label),
      h('span', { className: 'mstatus' }, module.status),
      module.id !== PERMANENT &&
        h('button', { type: 'button', className: 'mdrop', title: 'remove', onClick: remove }, '✕'),
    ),
    module.preview &&
      h('img', {
        className: 'mpreview',
        src: `/api/source/${encodeURIComponent(module.id)}/preview`,
        alt: `${module.label} preview`,
      }),
  )

  const unregister: (() => void)[] = []
  let lastGroup: string | null = null
  for (const port of module.ports) {
    if (port.group !== lastGroup) element.append(h('div', { className: 'grp-label' }, port.group))
    lastGroup = port.group
    const [jackElement, dispose] = jack(module, port)
    element.append(jackElement)
    unregister.push(dispose)
  }

  return { element, dispose: () => unregister.forEach((fn) => fn()) }
}

/**
 * One patchable jack.
 *
 * Its state classes (armed / compatible / wired) are toggled by the patch area,
 * and the readout and meter bar are painted by `meters.ts` — both find it
 * through the jack registry.
 */
function jack(module: ModuleSpec, port: PortSpec): [HTMLElement, () => void] {
  const id = portId(module.id, port.id)
  const placeholder = isPlaceholder(port)

  const portElement = h('span', { className: 'port' })
  const value = h('span', { className: 'val' }, IDLE_GLYPH[port.type])
  const meter = h('i')

  const root = h(
    'div',
    {
      className: classes('jack', port.type === 'event' && 'evt', placeholder && 'placeholder'),
      onClick: placeholder ? undefined : () => patchbay.clickJack(id),
    },
    h(
      'div',
      { className: 'jrow' },
      portElement,
      h(
        'span',
        { className: 'lbl' },
        h('span', { className: 'name' }, port.label || port.id),
        h('span', { className: 'sub' }, placeholder ? port.hint : port.unit || port.hint),
      ),
      value,
    ),
    h('span', { className: 'meter' }, meter),
  )

  if (placeholder) return [root, () => {}]
  return [
    root,
    jacks.register(id, {
      type: port.type,
      kind: module.kind,
      root,
      port: portElement,
      meter,
      value,
    }),
  ]
}
