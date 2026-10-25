import { api } from '../lib/api'
import { h } from '../lib/dom'
import { patchbay } from '../state/patchbay'
import { toast, toastError } from '../state/toast'

/**
 * Preset dropdown + Load / Save / Save as / New / Delete.
 *
 * The dropdown keeps its own selection so you can browse it without loading;
 * it snaps back to the engine's current preset whenever that changes. Save
 * always writes the *loaded* preset, not whatever the dropdown happens to show.
 */
export function presetBar(): HTMLElement {
  const select = h('select', { id: 'presetSel', title: 'preset' })

  /** Every button is "do the calls, then re-read everything, then say so". */
  const run = (work: () => Promise<string | null>) => () =>
    void work()
      .then((message) => {
        if (message) toast(message)
      })
      .catch(toastError)

  const load = run(async () => {
    const choice = select.value
    await api.loadPreset(choice)
    await patchbay.reloadAll()
    return `loaded ${choice}`
  })

  const save = run(async () => {
    const { presetName, graph } = patchbay.state
    await api.savePreset(presetName, graph)
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
    patchbay.setPresets(result.presets)
    return `deleted ${choice}`
  })

  patchbay.subscribe((state, prev) => {
    if (state.presets === prev.presets && state.presetName === prev.presetName) return
    select.replaceChildren(...state.presets.map((name) => h('option', { value: name }, name)))
    select.value = state.presetName
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
  )
}
