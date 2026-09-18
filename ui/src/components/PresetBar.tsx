import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { usePatchbay } from '../state/PatchbayProvider'
import { useToastHandlers } from '../state/ToastProvider'

/**
 * Preset dropdown + Load / Save / Save as / New / Delete.
 *
 * The dropdown tracks its own selection so you can browse it without loading;
 * it snaps back to the engine's current preset whenever that changes. Save
 * always writes the *loaded* preset, not whatever the dropdown happens to show.
 */
export function PresetBar() {
  const { presets, presetName, graph, reloadAll, setPresets } = usePatchbay()
  const { toast, toastError } = useToastHandlers()
  const [choice, setChoice] = useState(presetName)

  useEffect(() => setChoice(presetName), [presetName, presets])

  /** Every button is "do the calls, then re-read everything, then say so". */
  const run = (work: () => Promise<string | null>) => () =>
    void work()
      .then((message) => {
        if (message) toast(message)
      })
      .catch(toastError)

  const load = run(async () => {
    await api.loadPreset(choice)
    await reloadAll()
    return `loaded ${choice}`
  })

  const save = run(async () => {
    await api.savePreset(presetName, graph)
    return `saved ${presetName}`
  })

  const saveAs = run(async () => {
    const name = (window.prompt('Save preset as:', `${presetName}-copy`) ?? '').trim()
    if (!name) return null
    await api.savePreset(name, { ...graph, name })
    await api.loadPreset(name)
    await reloadAll()
    return `saved ${name}`
  })

  const create = run(async () => {
    const name = (window.prompt('New empty preset name:') ?? '').trim()
    if (!name) return null
    await api.savePreset(name, { name, connections: [] })
    await api.loadPreset(name)
    await reloadAll()
    return `new preset ${name}`
  })

  const remove = run(async () => {
    if (!window.confirm(`Delete preset "${choice}"?`)) return null
    const result = await api.deletePreset(choice)
    setPresets(result.presets)
    return `deleted ${choice}`
  })

  return (
    <div className="group presets">
      <select
        id="presetSel"
        title="preset"
        value={choice}
        onChange={(e) => setChoice(e.target.value)}
      >
        {presets.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
      <button id="loadBtn" type="button" onClick={load}>
        Load
      </button>
      <button id="saveBtn" type="button" className="accent" onClick={save}>
        Save
      </button>
      <button id="saveAsBtn" type="button" onClick={saveAs}>
        Save as…
      </button>
      <button id="newBtn" type="button" onClick={create}>
        New
      </button>
      <button id="delBtn" type="button" className="danger-ghost" onClick={remove}>
        Delete
      </button>
    </div>
  )
}
