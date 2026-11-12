import { h } from '../lib/dom'
import { isChoiceSpec, isPortSpec } from '../types'
import type { NumericParamSpec, ParamSpec, ParamValue } from '../types'

export interface ParamField {
  element: HTMLElement
  /** Show a value from the engine (preset load, refresh after an edit). */
  set: (value: ParamValue | undefined) => void
}

/**
 * One editable parameter of a transform node, built entirely from the engine's
 * spec — the UI has no hard-coded knowledge of any node type.
 *
 * Edits are reported on the DOM's native `change` event — once the value is
 * committed (blur, Enter, a stepper click) — not per keystroke, which for a
 * number field would mean a PUT to the engine per digit typed.
 */
export function paramField(
  name: string,
  spec: ParamSpec,
  value: ParamValue | undefined,
  onCommit: (value: ParamValue) => void,
  sourcePorts: string[] = [],
): ParamField {
  if (isPortSpec(spec)) return portField(name, sourcePorts, value, onCommit)
  if (isChoiceSpec(spec)) {
    const shown = (v: ParamValue | undefined) => String(v ?? spec.choices[0] ?? '')
    const select = h('select', null, ...spec.choices.map((c) => h('option', { value: c }, c)))
    select.value = shown(value)
    select.addEventListener('change', () => onCommit(select.value))
    return {
      element: h('label', null, name, select),
      set: (v) => {
        select.value = shown(v)
      },
    }
  }
  return numberField(name, spec, value, onCommit)
}

function portField(
  name: string,
  ports: string[],
  value: ParamValue | undefined,
  onCommit: (value: string) => void,
): ParamField {
  const select = h('select', null)
  const show = (v: ParamValue | undefined) => {
    const current = String(v ?? '')
    // A preset can name a port whose module isn't running: show it, don't blank it.
    const missing = current && !ports.includes(current) ? [current] : []
    select.replaceChildren(
      h('option', { value: '' }, '— pick a port —'),
      ...missing.map((p) => h('option', { value: p }, `${p} (not running)`)),
      ...ports.map((p) => h('option', { value: p }, p)),
    )
    select.value = current
  }
  show(value)
  select.addEventListener('change', () => onCommit(select.value))
  return { element: h('label', null, name, select), set: show }
}

function numberField(
  name: string,
  spec: NumericParamSpec,
  value: ParamValue | undefined,
  onCommit: (value: number) => void,
): ParamField {
  const [fallback, min, max, step] = spec
  const toNumber = (v: ParamValue | undefined) => (typeof v === 'number' ? v : fallback)
  /** The engine's value, as last shown. */
  let known = toNumber(value)

  const input = h('input', { type: 'number', min, max, step, value: String(known) })
  input.addEventListener('change', () => {
    const parsed = Number.parseFloat(input.value)
    if (Number.isNaN(parsed)) {
      input.value = String(known) // reject junk rather than sending NaN
      return
    }
    onCommit(parsed)
  })

  return {
    element: h('label', null, name, input),
    set: (v) => {
      const next = toNumber(v)
      // A change from the engine wins over a draft; an unchanged value only
      // overwrites the field once you've left it (e.g. the engine clamped it).
      if (next !== known || document.activeElement !== input) input.value = String(next)
      known = next
    },
  }
}
