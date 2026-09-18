import { useLayoutEffect, useRef } from 'react'
import { isPlaceholder, portId } from '../lib/ports'
import { useJackRegistry } from '../state/JackRegistry'
import { usePatchbay } from '../state/PatchbayProvider'
import type { ModuleSpec, PortSpec, PortType } from '../types'

/** What a readout shows before the first frame of live data arrives. */
const IDLE_GLYPH: Record<PortType, string> = { scalar: '–', event: '○' }

function classes(...parts: (string | false | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}

/**
 * One patchable jack.
 *
 * React owns the structure and the state classes (armed / compatible / wired).
 * The readout and the meter bar are left empty here and driven imperatively by
 * `useMeters` via the registry — see that hook for why.
 */
export function Jack({ module, port }: { module: ModuleSpec; port: PortSpec }) {
  const { armed, compatible, wired, clickJack } = usePatchbay()
  const registry = useJackRegistry()

  const id = portId(module.id, port.id)
  const placeholder = isPlaceholder(port)

  const portRef = useRef<HTMLSpanElement>(null)
  const meterRef = useRef<HTMLElement>(null)
  const valueRef = useRef<HTMLSpanElement>(null)

  useLayoutEffect(() => {
    if (placeholder) return
    const portEl = portRef.current
    const meterEl = meterRef.current
    const valueEl = valueRef.current
    if (!portEl || !meterEl || !valueEl) return

    // The meter painter owns this text from here on; seed it so the jack reads
    // as idle rather than blank until the stream connects.
    valueEl.textContent = IDLE_GLYPH[port.type]
    return registry.register(id, {
      type: port.type,
      kind: module.kind,
      port: portEl,
      meter: meterEl,
      value: valueEl,
    })
  }, [registry, id, placeholder, port.type, module.kind])

  const className = classes(
    'jack',
    port.type === 'event' && 'evt',
    placeholder && 'placeholder',
    wired.has(id) && 'wired',
    armed === id && 'armed',
    compatible.has(id) && 'compatible',
  )

  return (
    <div className={className} onClick={placeholder ? undefined : () => clickJack(id)}>
      <div className="jrow">
        <span className="port" ref={portRef} />
        <span className="lbl">
          <span className="name">{port.label || port.id}</span>
          <span className="sub">{placeholder ? port.hint : port.unit || port.hint}</span>
        </span>
        <span className="val" ref={valueRef}>
          {placeholder ? IDLE_GLYPH[port.type] : null}
        </span>
      </div>
      <span className="meter">
        <i ref={meterRef} />
      </span>
    </div>
  )
}
