import { useEffect, useMemo, useState } from 'react'
import { Pill } from './Pill'
import type { PillTone } from './Pill'
import { useCommitOnChange } from '../hooks/useCommitOnChange'
import { api } from '../lib/api'
import { useLiveStatus } from '../state/LiveProvider'
import { usePatchbay } from '../state/PatchbayProvider'
import { useToastHandlers } from '../state/ToastProvider'
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

  // The first source and the first real sink stand in for the whole
  // pipeline: is something feeding it, and is anything coming out.
  const source = useMemo(() => modules.find((m) => m.kind === 'source'), [modules])
  const sink = useMemo(() => modules.find((m) => m.kind === 'sink' && m.id !== 'sys'), [modules])

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
      <RateInput rate={rate} />
    </div>
  )
}

/** Engine tick rate, editable live; follows the stream until you edit it. */
function RateInput({ rate }: { rate: number | null }) {
  const { toast, toastError } = useToastHandlers()
  const [draft, setDraft] = useState(rate === null ? '' : String(rate))
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    if (!editing) setDraft(rate === null ? '' : String(rate))
  }, [rate, editing])

  const ref = useCommitOnChange<HTMLInputElement>((element) => {
    const hz = Number.parseFloat(element.value)
    if (!(hz > 0)) {
      setDraft(rate === null ? '' : String(rate))
      return
    }
    void api
      .setRate(hz)
      .then((r) => toast(`rate → ${Math.round(r.rate)} Hz`))
      .catch(toastError)
  })

  return (
    <label className="rate-set" title="engine tick rate (Hz) — applied live">
      <input
        ref={ref}
        id="rateInput"
        type="number"
        min={1}
        max={2000}
        step={10}
        value={draft}
        onFocus={() => setEditing(true)}
        onBlur={() => setEditing(false)}
        onChange={(e) => setDraft(e.target.value)}
      />{' '}
      Hz
    </label>
  )
}
