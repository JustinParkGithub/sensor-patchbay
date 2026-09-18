import { ChainEditor } from './ChainEditor'
import { shortPortId } from '../lib/ports'
import { usePatchbay } from '../state/PatchbayProvider'

/** Side panel for the selected cable: enable/disable, shape, or cut it. */
export function Inspector() {
  const { selected, selectConnection, setEnabled, deleteConnection } = usePatchbay()
  if (!selected) return null

  return (
    <aside id="inspector">
      <div className="insp-head">
        <div>
          <div className="insp-title" id="inspTitle">
            {shortPortId(selected.source)} &nbsp;→&nbsp; {shortPortId(selected.sink)}
          </div>
          <div className="insp-sub" id="inspSub">
            {selected.source} &nbsp; → &nbsp; {selected.sink}
          </div>
        </div>
        <button id="inspClose" type="button" aria-label="close" onClick={() => selectConnection(null)}>
          ×
        </button>
      </div>

      <label className="row-toggle">
        <input
          type="checkbox"
          id="inspEnabled"
          checked={selected.enabled}
          onChange={(e) => void setEnabled(selected.id, e.target.checked)}
        />{' '}
        connection enabled
      </label>

      <ChainEditor connection={selected} />

      <button
        id="inspDelete"
        type="button"
        className="danger"
        onClick={() => void deleteConnection(selected.id)}
      >
        Delete connection
      </button>
    </aside>
  )
}
