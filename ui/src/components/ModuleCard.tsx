import { Fragment } from 'react'
import { Jack } from './Jack'
import { usePatchbay } from '../state/PatchbayProvider'
import type { ModuleSpec } from '../types'

/** The engine's built-in sink (preset cycling); it can't be removed. */
const PERMANENT = 'sys'

/**
 * One source or sink panel. Ports arrive pre-ordered from the plugin; a group
 * heading is emitted wherever the group changes, so the plugin's grouping is
 * the only thing deciding layout.
 */
export function ModuleCard({ module }: { module: ModuleSpec }) {
  const { removeModule } = usePatchbay()
  let lastGroup: string | null = null

  const remove = () => {
    if (!confirm(`Remove ${module.kind} "${module.id}"? Cables using it are deleted.`)) return
    void removeModule(module.kind, module.id)
  }

  return (
    <div className={`module ${module.kind === 'source' ? 'src-mod' : 'sink-mod'}`}>
      <div className="mh">
        <span className="swatch" />
        <span className="mname">{module.label}</span>
        <span className="mstatus">{module.status}</span>
        {module.id !== PERMANENT && (
          <button type="button" className="mdrop" title="remove" onClick={remove}>
            ✕
          </button>
        )}
      </div>
      {module.preview && (
        <img
          className="mpreview"
          src={`/api/source/${encodeURIComponent(module.id)}/preview`}
          alt={`${module.label} preview`}
        />
      )}
      {module.ports.map((port) => {
        const heading = port.group !== lastGroup ? port.group : null
        lastGroup = port.group
        return (
          <Fragment key={port.id}>
            {heading !== null && <div className="grp-label">{heading}</div>}
            <Jack module={module} port={port} />
          </Fragment>
        )
      })}
    </div>
  )
}
