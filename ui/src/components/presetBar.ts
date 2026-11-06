import { api } from '../lib/api'
import { h } from '../lib/dom'
import { needs, patchbay } from '../state/patchbay'
import { toast, toastError } from '../state/toast'
import type { MissingRequirement } from '../types'

/** Tooltip body: one line per unmet requirement, with why. */
function describeMissing(missing: MissingRequirement[]): string {
  return missing.map((m) => `${m.kind} "${m.id}": ${m.reason}`).join('\n')
}

/**
 * Preset dropdown + Load / Save / Save as / New / Delete.
 *
 * The dropdown keeps its own selection so you can browse it without loading;
 * it snaps back to the engine's current preset whenever that changes. Save
 * always writes the *loaded* preset, not whatever the dropdown happens to show.
 *
 * A preset whose `requires` names a source/sink that isn't installed (or can't
 * run) is marked ⚠ in the dropdown, and the badge beside it says what's missing
 * for the preset the dropdown shows.
 */
export function presetBar(): HTMLElement {
  const select = h('select', { id: 'presetSel', title: 'preset' })
  const badge = h('span', { className: 'preset-warn', hidden: true })

  const missingFor = (name: string) => patchbay.state.presetInfo[name]?.missing ?? []

  const paintBadge = () => {
    const missing = missingFor(select.value)
    badge.hidden = missing.length === 0
    badge.textContent = `⚠ needs ${missing.map((m) => m.id).join(', ')}`
    badge.title = describeMissing(missing)
  }
  select.addEventListener('change', paintBadge)

  /** Every button is "do the calls, then re-read everything, then say so". */
  const run = (work: () => Promise<string | null>) => () =>
    void work()
      .then((message) => {
        if (message) toast(message)
      })
      .catch(toastError)

  const load = run(async () => {
    const choice = select.value
    const { missing } = await api.loadPreset(choice)
    await patchbay.reloadAll()
    if (missing.length) {
      toast(`loaded ${choice} — ${needs(missing)}`, true)
      return null
    }
    return `loaded ${choice}`
  })

  const save = run(async () => {
    const { presetName, graph } = patchbay.state
    const result = await api.savePreset(presetName, graph)
    patchbay.setPresets(result.presets, result.preset_info)
    return `saved ${presetName}`
  })

  const saveAs = run(async () => {
    const { presetName, graph } = patchbay.state
    const name = (window.prompt('Save preset as:', `${presetName}-copy`) ?? '').trim()
    if (!name) return null
    await api.savePreset(name, { ...graph, name })
    await api.loadPreset(name)
    await patchbay.reloadAll()
    return `saved ${name}`
  })

  const create = run(async () => {
    const name = (window.prompt('New empty preset name:') ?? '').trim()
    if (!name) return null
    await api.savePreset(name, { name, connections: [] })
    await api.loadPreset(name)
    await patchbay.reloadAll()
    return `new preset ${name}`
  })

  const remove = run(async () => {
    const choice = select.value
    if (!window.confirm(`Delete preset "${choice}"?`)) return null
    const result = await api.deletePreset(choice)
    patchbay.setPresets(result.presets, result.preset_info)
    return `deleted ${choice}`
  })

  patchbay.subscribe((state, prev) => {
    if (
      state.presets === prev.presets &&
      state.presetName === prev.presetName &&
      state.presetInfo === prev.presetInfo
    )
      return
    const keep = state.presetName === prev.presetName ? select.value : state.presetName
    select.replaceChildren(
      ...state.presets.map((name) => {
        const missing = missingFor(name)
        return h(
          'option',
          { value: name, title: missing.length ? describeMissing(missing) : undefined },
          missing.length ? `⚠ ${name}` : name,
        )
      }),
    )
    select.value = state.presets.includes(keep) ? keep : state.presetName
    paintBadge()
  })

  return h(
    'div',
    { className: 'group presets' },
    select,
    h('button', { id: 'loadBtn', type: 'button', onClick: load }, 'Load'),
    h('button', { id: 'saveBtn', type: 'button', className: 'accent', onClick: save }, 'Save'),
    h('button', { id: 'saveAsBtn', type: 'button', onClick: saveAs }, 'Save as…'),
    h('button', { id: 'newBtn', type: 'button', onClick: create }, 'New'),
    h('button', { id: 'delBtn', type: 'button', className: 'danger-ghost', onClick: remove }, 'Delete'),
    badge,
  )
}
