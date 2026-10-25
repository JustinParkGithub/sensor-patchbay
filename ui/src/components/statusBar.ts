import { api } from '../lib/api'
import { h } from '../lib/dom'
import { live } from '../state/live'
import { patchbay } from '../state/patchbay'
import { toast, toastError } from '../state/toast'
import type { ModuleSpec } from '../types'

type PillTone = 'ok' | 'warn' | 'mock' | 'bad' | 'idle'

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

/** The little status lamp + label in the top bar. */
function pill(id: string) {
  const label = document.createTextNode('')
  const element = h('span', { id, className: 'pill' }, h('i'), ' ', label)
  return {
    element,
    set(tone: PillTone, text: string) {
      element.className = tone === 'idle' ? 'pill' : `pill ${tone}`
      label.data = text
    },
  }
}

export function statusBar(): HTMLElement {
  const link = pill('linkPill')
  const source = pill('srcPill')
  const sink = pill('sinkPill')

  const paintLink = () => link.set(live.status.link, 'link')

  // The first source and the first real sink stand in for the whole
  // pipeline: is something feeding it, and is anything coming out.
  const paintModules = (modules: ModuleSpec[]) => {
    const src = modules.find((m) => m.kind === 'source')
    const snk = modules.find((m) => m.kind === 'sink' && m.id !== 'sys')
    source.set(sourceTone(src), src ? src.label : 'no source')
    sink.set(sinkTone(snk), snk ? snk.status : 'no sink')
  }

  paintLink()
  paintModules(patchbay.state.modules)
  live.onStatus((status, prev) => {
    if (status.link !== prev.link) paintLink()
  })
  patchbay.subscribe((state, prev) => {
    if (state.modules !== prev.modules) paintModules(state.modules)
  })

  return h(
    'div',
    { className: 'group status', id: 'statusBox' },
    link.element,
    source.element,
    sink.element,
    rateInput(),
  )
}

/** Engine tick rate, editable live; follows the stream until you edit it. */
function rateInput(): HTMLElement {
  const shown = () => (live.status.rate === null ? '' : String(live.status.rate))

  const input = h('input', { id: 'rateInput', type: 'number', min: 1, max: 2000, step: 10, value: shown() })

  input.addEventListener('blur', () => {
    input.value = shown()
  })
  // native `change`: once per commit (blur, Enter, stepper), not per keystroke
  input.addEventListener('change', () => {
    const hz = Number.parseFloat(input.value)
    if (!(hz > 0)) {
      input.value = shown()
      return
    }
    void api
      .setRate(hz)
      .then((r) => toast(`rate → ${Math.round(r.rate)} Hz`))
      .catch(toastError)
  })

  live.onStatus((status, prev) => {
    if (status.rate !== prev.rate && document.activeElement !== input) input.value = shown()
  })

  return h(
    'label',
    { className: 'rate-set', title: 'engine tick rate (Hz) — applied live' },
    input,
    ' Hz',
  )
}
