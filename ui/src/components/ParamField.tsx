import { useEffect, useState } from 'react'
import { useCommitOnChange } from '../hooks/useCommitOnChange'
import { isChoiceSpec } from '../types'
import type { ParamSpec, ParamValue } from '../types'

/**
 * One editable parameter of a transform node, built entirely from the engine's
 * spec — the UI has no hard-coded knowledge of any node type.
 */
export function ParamField({
  name,
  spec,
  value,
  onCommit,
}: {
  name: string
  spec: ParamSpec
  value: ParamValue | undefined
  onCommit: (value: ParamValue) => void
}) {
  return (
    <label>
      {name}
      {isChoiceSpec(spec) ? (
        <select
          value={String(value ?? spec.choices[0] ?? '')}
          onChange={(e) => onCommit(e.target.value)}
        >
          {spec.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      ) : (
        <NumberInput spec={spec} value={typeof value === 'number' ? value : spec[0]} onCommit={onCommit} />
      )}
    </label>
  )
}

/**
 * Controlled while you type, but only reported upstream on the DOM's `change`
 * event — otherwise every keystroke would be a round-trip to the engine.
 */
function NumberInput({
  spec,
  value,
  onCommit,
}: {
  spec: readonly [number, number, number, number]
  value: number
  onCommit: (value: number) => void
}) {
  const [, min, max, step] = spec
  const [draft, setDraft] = useState(String(value))

  // A change from the engine (preset load, reorder) wins over a stale draft.
  useEffect(() => setDraft(String(value)), [value])

  const ref = useCommitOnChange<HTMLInputElement>((element) => {
    const parsed = Number.parseFloat(element.value)
    if (Number.isNaN(parsed)) {
      setDraft(String(value)) // reject junk rather than sending NaN
      return
    }
    onCommit(parsed)
  })

  return (
    <input
      ref={ref}
      type="number"
      min={min}
      max={max}
      step={step}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
    />
  )
}
