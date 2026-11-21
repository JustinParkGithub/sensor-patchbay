/**
 * The combo builder. A combo is a dam on an ordinary cable: pick the trigger
 * (the dam), when it counts as open, the source (the water) and the sink it
 * flows into. It only writes a regular cable with `combine` gates on it (see
 * `lib/combos.ts`), so every combo also shows up on the patch panel, can be
 * fine-tuned in the inspector, and saves with the preset.
 *
 * While the dialog is open, each trigger shows its live value and whether it
 * would open the dam, so the level can be set by watching it.
 */

import { bypassCables, comboCable, comboProblem, describeLock, findCombos, lockOpen } from '../lib/combos'
import type { Combo, ComboSpec, Lock, When } from '../lib/combos'
import { h, setChildren } from '../lib/dom'
import { buildPortIndex, isPlaceholder, portId } from '../lib/ports'
import type { PortEntry } from '../lib/ports'
import { live } from '../state/live'
import { patchbay } from '../state/patchbay'
import type { PatchbayState } from '../state/patchbay'
import { toast } from '../state/toast'
import type { ModuleKind, ModuleSpec } from '../types'

/** `<option>`s for every patchable port of one kind, grouped by module. Events first. */
function portOptions(modules: ModuleSpec[], kind: ModuleKind, none: string): HTMLElement[] {
  const out: HTMLElement[] = [h('option', { value: '' }, none)]
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

const short = (id: string) => id.split('/').slice(1).join('/') || id
const fmt = (v: number | undefined) => (v === undefined ? '—' : v.toFixed(2))

/** One trigger's pickers: port, above/below, level, plus a live readout. */
function lockEditor(none: string, onChange: () => void) {
  const port = h('select', { className: 'combo-port' })
  const when = h(
    'select',
    { className: 'combo-when' },
    h('option', { value: 'above' }, 'is above'),
    h('option', { value: 'below' }, 'is below'),
  )
  const level = h('input', { type: 'number', className: 'combo-level', step: 0.05, value: 0.5 })
  const reading = h('span', { className: 'combo-live' })
  const hint = h('small', { className: 'combo-hint' })
  const condition = h('span', { className: 'combo-cond' }, 'opens while it ', when, level)

  let ports = new Map<string, PortEntry>()
  let lastPort = ''

  const lock = (): Lock | null =>
    port.value ? { port: port.value, when: when.value as When, level: Number(level.value) } : null

  const paintHint = () => {
    const entry = ports.get(port.value)
    hint.textContent = entry ? [entry.port.hint, entry.port.unit].filter(Boolean).join(' · ') : ''
    condition.hidden = !port.value
  }

  port.addEventListener('input', () => {
    // A new event (button) port opens on a press; continuous ports keep what
    // the user set, since only they know which way is "on".
    const entry = ports.get(port.value)
    if (port.value !== lastPort && entry?.port.type === 'event') {
      when.value = 'above'
      level.value = '0.5'
    }
    lastPort = port.value
    paintHint()
    onChange()
  })
  for (const el of [when, level]) el.addEventListener('input', onChange)

  return {
    el: [port, condition, reading],
    hint,
    lock,
    clear() {
      port.value = ''
      lastPort = ''
      paintHint()
    },
    fill(modules: ModuleSpec[], index: Map<string, PortEntry>) {
      ports = index
      refill(port, portOptions(modules, 'source', none))
      paintHint()
    },
    /** Paint the live value; returns whether this lock is open (null if unset). */
    tick(values: Record<string, number>): boolean | null {
      const l = lock()
      if (!l) {
        reading.textContent = ''
        reading.className = 'combo-live'
        return null
      }
      const v = values[l.port]
      const open = v !== undefined && lockOpen(l, v)
      reading.textContent = `now ${fmt(v)}`
      reading.className = `combo-live ${open ? 'open' : 'closed'}`
      return open
    },
  }
}

export function comboButton(): HTMLButtonElement {
  let check = () => {}
  const first = lockEditor('— pick a trigger —', () => check())
  const second = lockEditor('— none —', () => check())
  const source = h('select', { className: 'combo-port' })
  const sink = h('select', { className: 'combo-port' })
  const sourceReading = h('span', { className: 'combo-live' })
  const damState = h('span', { className: 'combo-dam' })
  const summary = h('div', { className: 'combo-summary' })
  const notice = h('div', { className: 'combo-notice', hidden: true })
  const create = h('button', { type: 'button', className: 'accent', onClick: () => void submit() }, 'Create combo')
  const list = h('ul', { className: 'combo-list' })
  const listLights = new Map<HTMLElement, Lock[]>()

  const spec = (): ComboSpec => ({
    locks: [first.lock(), second.lock()].filter((l): l is Lock => l !== null),
    source: source.value,
    sink: sink.value,
  })

  /** Validation, a plain-words summary, and a heads-up about cables that bypass the dam. */
  check = () => {
    const s = first.lock() ? spec() : { ...spec(), locks: [] }
    const problem = comboProblem(s)
    create.disabled = problem !== null
    summary.textContent =
      problem ??
      `${short(s.source)} flows into ${short(s.sink)} only while ${s.locks.map((l) => describeLock(l, short)).join(' and ')}; otherwise ${short(s.sink)} gets 0.`
    summary.classList.toggle('muted', problem !== null)
    const bypass = problem ? [] : bypassCables(patchbay.state.graph, s.source, s.sink)
    notice.hidden = !bypass.length
    notice.textContent = bypass.length
      ? `${s.source} → ${s.sink} is also wired without a trigger, so it flows whether the trigger is held or not. Delete that cable if the combo should replace it.`
      : ''
    paintLive(live.snapshot.ports)
  }

  const paintLive = (values: Record<string, number>) => {
    const states = [first.tick(values), second.tick(values)].filter((s): s is boolean => s !== null)
    sourceReading.textContent = source.value ? `now ${fmt(values[source.value])}` : ''
    if (!states.length) {
      damState.textContent = ''
      damState.className = 'combo-dam'
    } else {
      const open = states.every(Boolean)
      damState.textContent = open ? '● OPEN: flowing' : '● CLOSED: sink gets 0'
      damState.className = `combo-dam ${open ? 'open' : 'closed'}`
    }
    for (const [light, locks] of listLights) {
      const open = locks.every((l) => {
        const v = values[l.port]
        return v !== undefined && lockOpen(l, v)
      })
      light.textContent = open ? '● open' : '● closed'
      light.className = `combo-dam ${open ? 'open' : 'closed'}`
    }
  }

  const submit = async () => {
    const s = spec()
    if (comboProblem(s)) return
    create.disabled = true
    const ok = await patchbay.addCombo([comboCable(s)])
    if (ok) {
      toast('Combo patched.')
      first.clear()
      second.clear()
      source.value = ''
      sink.value = ''
    }
    check()
  }

  const row = (label: string, hint: string, fields: HTMLElement[], extra?: HTMLElement) =>
    h(
      'div',
      { className: 'combo-row' },
      h('span', { className: 'combo-label' }, label, h('small', null, hint)),
      h('div', { className: 'combo-fields' }, h('div', { className: 'combo-line' }, ...fields), extra ?? null),
    )

  const builder = h(
    'div',
    { className: 'combo-builder' },
    row('Trigger', 'the dam', first.el, first.hint),
    row('2nd trigger', 'optional: both must be open', second.el, second.hint),
    row('Source', 'the water: what flows', [source, sourceReading]),
    row('Sink', 'where it flows to', [sink]),
    h('div', { className: 'combo-summary-row' }, summary, damState),
    h('div', { className: 'combo-foot' }, h('div', { className: 'spacer' }), create),
    notice,
  )

  const comboItem = (combo: Combo) => {
    const c = combo.connection
    const light = h('span', { className: 'combo-dam' })
    if (combo.locks.length) listLights.set(light, combo.locks)
    const trig = combo.chord
      ? `${short(combo.chord.trigger)} + ${short(combo.chord.partner)} (chord, ${combo.chord.role})`
      : combo.locks.map((l) => describeLock(l, short)).join(' and ')
    return h(
      'li',
      { className: 'combo-item' },
      h(
        'div',
        { className: 'combo-main' },
        h('div', { className: 'combo-title' }, h('span', { className: 'combo-btn' }, trig), light),
        h('div', { className: 'combo-out' }, `${c.source} → ${c.sink}`),
      ),
      h(
        'button',
        { type: 'button', className: 'danger-ghost', onClick: () => void patchbay.deleteConnections([c.id]) },
        'Delete',
      ),
    )
  }

  const paintModules = (modules: ModuleSpec[]) => {
    const index = buildPortIndex(modules)
    first.fill(modules, index)
    second.fill(modules, index)
    refill(source, portOptions(modules, 'source', '— pick a source —'))
    refill(sink, portOptions(modules, 'sink', '— pick a sink —'))
    check()
  }

  const paintCombos = (state: Readonly<PatchbayState>) => {
    listLights.clear()
    const combos = findCombos(state.graph)
    setChildren(
      list,
      combos.length
        ? combos.map(comboItem)
        : [h('li', { className: 'combo-empty' }, 'No combos yet. Pick a trigger, a source and a sink above.')],
    )
    check()
  }

  for (const el of [source, sink]) el.addEventListener('input', check)

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
      'A trigger is a dam on a cable: the source reaches the sink only while the trigger is open. ' +
        'Hand-tracking values are continuous, so choose when the trigger counts as open and watch its live value. ' +
        'For example, pinch is about 1 with the hand open and about 0 when pinched, so "is below 0.3" means "while pinched".',
    ),
    builder,
    h('h3', { className: 'combo-heading' }, 'In this patch'),
    list,
  )
  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) dialog.close()
  })

  // Live readouts only while the dialog is open.
  let unsubscribe: (() => void) | null = null
  dialog.addEventListener('close', () => {
    unsubscribe?.()
    unsubscribe = null
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
      title: 'gate a source with a trigger',
      onClick: () => {
        if (!dialog.isConnected) document.body.append(dialog)
        check()
        unsubscribe ??= live.subscribe((frame) => paintLive(frame.ports))
        dialog.showModal()
      },
    },
    'Combos',
  )
}
