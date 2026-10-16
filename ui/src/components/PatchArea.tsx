import { useMemo, useRef } from 'react'
import { AddModule } from './AddModule'
import { Cables } from './Cables'
import { ModuleCard } from './ModuleCard'
import { useMeters } from '../hooks/useMeters'
import { usePatchbay } from '../state/PatchbayProvider'
import type { ModuleKind, ModuleSpec } from '../types'

/** Sources on the left, sinks on the right, cables in between. */
export function PatchArea() {
  const { modules } = usePatchbay()
  const surfaceRef = useRef<HTMLElement>(null)

  useMeters()

  const sources = useMemo(() => modules.filter((m) => m.kind === 'source'), [modules])
  const sinks = useMemo(() => modules.filter((m) => m.kind === 'sink'), [modules])

  return (
    <main id="patch" ref={surfaceRef}>
      <Cables surfaceRef={surfaceRef} />
      <Column id="sources" kind="source" title="Sources" listId="srcMods" modules={sources} />
      <Column id="sinks" kind="sink" title="Sinks" listId="sinkMods" modules={sinks} />
    </main>
  )
}

function Column({
  id,
  kind,
  title,
  listId,
  modules,
}: {
  id: string
  kind: ModuleKind
  title: string
  listId: string
  modules: ModuleSpec[]
}) {
  return (
    <section className="col" id={id}>
      <h2>{title}</h2>
      <div className="modules" id={listId}>
        {modules.map((module) => (
          <ModuleCard key={module.id} module={module} />
        ))}
      </div>
      <AddModule kind={kind} />
    </section>
  )
}
