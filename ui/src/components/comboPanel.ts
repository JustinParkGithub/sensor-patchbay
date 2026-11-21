/**
 * The combo builder: pick two buttons and what each does alone and together.
 * It only writes ordinary cables with `chord` nodes on them (see
 * `lib/combos.ts`), so every combo also shows up on the patch panel, can be
 * fine-tuned in the inspector, and saves with the preset.
 */

import { comboCables, comboConnections, comboProblem, DEFAULT_WINDOW_MS, directCables, findCombos } from '../lib/combos'
import type { Combo, ComboSpec } from '../lib/combos'
import { h, setChildren } from '../lib/dom'
import { isPlaceholder, portId } from '../lib/ports'
import { patchbay } from '../state/patchbay'
import type { PatchbayState } from '../state/patchbay'
import { toast } from '../state/toast'
import type { ModuleKind, ModuleSpec } from '../types'

/** `<option>`s for every patchable port of one kind, grouped by module. Events first. */
function portOptions(modules: ModuleSpec[], kind: ModuleKind, none: string | null): HTMLElement[] {
  const out: HTMLElement[] = [h('option', { value: '' }, none ?? '— pick —')]
  for (const m of modules) {
    if (m.kind !== kind) continue
    const ports = m.ports
      .filter((p) => !isPlaceholder(p))
      .sort((x, y) => Number(y.type === 'event') - Number(x.type === 'event'))
    if (!ports.length) continue
    out.push(
      h(
        'optgroup',
        { label: m.label && m.label !== m.id ? `${m.id} · ${m.label}` : m.id },
        ports.map((p) =>
          h('option', { value: portId(m.id, p.id) }, `${p.id}${p.label && p.label !== p.id ? ` — ${p.label}` : ''}`),
        ),
      ),
    )
  }
  return out
}

/** Refill a select, keeping its value if that port still exists. */
function refill(select: HTMLSelectElement, options: HTMLElement[]): void {
  const keep = select.value
  select.replaceChildren(...options)
  select.value = keep
  if (select.value !== keep) select.value = ''
}

export function comboButton(): HTMLButtonElement {
  const pickA = h('select', { className: 'combo-port' })
  const pickB = h('select', { className: 'combo-port' })
  const outA = h('select', { className: 'combo-port' })
  const outB = h('select', { className: 'combo-port' })
  const outBoth = h('select', { className: 'combo-port' })
  const windowMs = h('input', { type: 'number', min: 0, max: 1000, step: 5, value: DEFAULT_WINDOW_MS })
  const notice = h('div', { className: 'combo-notice', hidden: true })
  const create = h('button', { type: 'button', className: 'accent', onClick: () => void submit() }, 'Create combo')
  const list = h('ul', { className: 'combo-list' })

  // Each output row names the buttons picked above; one span per mention.
  const namesA = [0, 1].map(() => h('span', { className: 'combo-btn' }, 'A'))
  const namesB = [0, 1].map(() => h('span', { className: 'combo-btn' }, 'B'))

  const spec = (): ComboSpec => ({
    a: pickA.value,
    b: pickB.value,
    windowMs: Number(windowMs.value),
    aloneA: outA.value,
    aloneB: outB.value,
    both: outBoth.value,
  })

  /** Validation, plus a heads-up about plain cables that would bypass the combo. */
  const check = () => {
    const s = spec()
    const short = (id: string) => id.split('/').slice(1).join('/') || id
    for (const el of namesA) el.textContent = s.a ? short(s.a) : 'A'
    for (const el of namesB) el.textContent = s.b ? short(s.b) : 'B'
    const problem = comboProblem(s)
    create.disabled = problem !== null
    const direct = problem ? [] : directCables(patchbay.state.graph, [s.a, s.b])
    const lines = direct.map((c) => `${c.source} → ${c.sink}`)
    notice.hidden = !lines.length
    notice.textContent = lines.length
      ? `Already wired without a combo, so ${lines.length > 1 ? 'these keep' : 'this keeps'} firing during it: ${lines.join(', ')}. Delete ${lines.length > 1 ? 'them' : 'it'} if the combo should replace ${lines.length > 1 ? 'them' : 'it'}.`
      : ''
  }

  const submit = async () => {
    const s = spec()
    if (comboProblem(s)) return
    create.disabled = true
    const ok = await patchbay.addCombo(comboCables(s))
    if (ok) {
      toast('Combo patched.')
      for (const select of [pickA, pickB, outA, outB, outBoth]) select.value = ''
    }
    check()
  }

  const row = (label: Node | string, field: HTMLElement) =>
    h('label', { className: 'combo-row' }, h('span', { className: 'combo-label' }, label), field)

  const builder = h(
    'div',
    { className: 'combo-builder' },
    h(
      'div',
      { className: 'combo-pair' },
      row('Button A', pickA),
      h('span', { className: 'combo-plus' }, '+'),
      row('Button B', pickB),
    ),
    h(
      'div',
      { className: 'combo-outs' },
      row(h('span', null, namesA[0], ' alone →'), outA),
      row(h('span', null, namesB[0], ' alone →'), outB),
      row(h('span', null, namesA[1], ' + ', namesB[1], ' →'), outBoth),
    ),
    h(
      'div',
      { className: 'combo-foot' },
      h(
        'label',
        { className: 'combo-window', title: 'how long to wait for the second button; solo actions start this much later' },
        'window ',
        windowMs,
        ' ms',
      ),
      h('div', { className: 'spacer' }),
      create,
    ),
    notice,
  )

  const comboItem = (combo: Combo) => {
    const out = (label: string, c: Combo['aloneA']) =>
      h('div', { className: 'combo-out' }, h('span', { className: 'combo-label' }, label), c ? c.sink : '—')
    const short = (id: string) => id.split('/').slice(1).join('/') || id
    return h(
      'li',
      { className: 'combo-item' },
      h(
        'div',
        { className: 'combo-main' },
        h('div', { className: 'combo-title' }, `${combo.a} + ${combo.b}`, h('span', { className: 'combo-meta' }, `${combo.windowMs} ms`)),
        out(`${short(combo.a)} alone`, combo.aloneA),
        out(`${short(combo.b)} alone`, combo.aloneB),
        out('together', combo.both),
      ),
      h(
        'button',
        {
          type: 'button',
          className: 'danger-ghost',
          onClick: () => void patchbay.deleteConnections(comboConnections(combo).map((c) => c.id)),
        },
        'Delete',
      ),
    )
  }

  const paintModules = (modules: ModuleSpec[]) => {
    refill(pickA, portOptions(modules, 'source', null))
    refill(pickB, portOptions(modules, 'source', null))
    for (const s of [outA, outB, outBoth]) refill(s, portOptions(modules, 'sink', '— nothing —'))
    check()
  }

  const paintCombos = (state: Readonly<PatchbayState>) => {
    const combos = findCombos(state.graph)
    setChildren(
      list,
      combos.length
        ? combos.map(comboItem)
        : [h('li', { className: 'combo-empty' }, 'No combos yet. Pick two buttons above.')],
    )
    check()
  }

  for (const el of [pickA, pickB, outA, outB, outBoth, windowMs]) el.addEventListener('input', check)

  const dialog = h(
    'dialog',
    { id: 'combos' },
    h(
      'div',
      { className: 'catalog-head' },
      h('h2', null, 'Combos'),
      h('button', { type: 'button', className: 'close', 'aria-label': 'close', onClick: () => dialog.close() }, '✕'),
    ),
    h(
      'p',
      { className: 'combo-intro' },
      'Two buttons, three actions: each one alone does its own thing, and pressing both together (within the window) does something else instead.',
    ),
    builder,
    h('h3', { className: 'combo-heading' }, 'In this patch'),
    list,
  )
  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) dialog.close()
  })

  patchbay.subscribe((state, prev) => {
    if (state.modules !== prev.modules) paintModules(state.modules)
    if (state.graph !== prev.graph) paintCombos(state)
  })
  paintModules(patchbay.state.modules)
  paintCombos(patchbay.state)

  return h(
    'button',
    {
      id: 'comboBtn',
      type: 'button',
      title: 'make two-button combos',
      onClick: () => {
        if (!dialog.isConnected) document.body.append(dialog)
        check()
        dialog.showModal()
      },
    },
    'Combos',
  )
}
