import { useMemo } from 'react'
import { Pill } from './Pill'
import type { PillTone } from './Pill'
import { useLiveStatus } from '../state/LiveProvider'
import { usePatchbay } from '../state/PatchbayProvider'
import type { ModuleSpec } from '../types'

/** A sink whose status says it isn't really driving the OS. */
const DEGRADED_SINK = /dry|unavail/

function sourceTone(source: ModuleSpec | undefined): PillTone {
  if (!source) return 'bad'
  return source.status === 'mock' ? 'mock' : 'ok'
}

function sinkTone(sink: ModuleSpec | undefined): PillTone {
  if (!sink) return 'bad'
  return DEGRADED_SINK.test(sink.status) ? 'warn' : 'ok'
}

export function StatusBar() {
  const { modules } = usePatchbay()
  const { link, rate } = useLiveStatus()

  // The first source and the mouse/keyboard sink stand in for the whole
  // pipeline: is something feeding it, and is anything coming out.
  const source = useMemo(() => modules.find((m) => m.kind === 'source'), [modules])
  const sink = useMemo(() => modules.find((m) => m.kind === 'sink' && m.id === 'hid'), [modules])

  return (
    <div className="group status" id="statusBox">
      <Pill id="linkPill" tone={link}>
        link
      </Pill>
      <Pill id="srcPill" tone={sourceTone(source)}>
        {source ? source.label : 'no source'}
      </Pill>
      <Pill id="sinkPill" tone={sinkTone(sink)}>
        {sink ? sink.status : 'no sink'}
      </Pill>
      <span className="rate" id="ratePill">
        {rate === null ? '— Hz' : `${rate} Hz`}
      </span>
    </div>
  )
}
