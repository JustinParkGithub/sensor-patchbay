import { Fragment } from 'react'
import { Jack } from './Jack'
import type { ModuleSpec } from '../types'

/**
 * One source or sink panel. Ports arrive pre-ordered from the plugin; a group
 * heading is emitted wherever the group changes, so the plugin's grouping is
 * the only thing deciding layout.
 */
export function ModuleCard({ module }: { module: ModuleSpec }) {
  let lastGroup: string | null = null

  return (
    <div className={`module ${module.kind === 'source' ? 'src-mod' : 'sink-mod'}`}>
      <div className="mh">
        <span className="swatch" />
        <span className="mname">{module.label}</span>
        <span className="mstatus">{module.status}</span>
      </div>
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
