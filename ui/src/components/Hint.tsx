import { usePatchbay } from '../state/PatchbayProvider'

/** The one-line prompt at the bottom, tracking where you are in a patch. */
export function Hint() {
  const { armed } = usePatchbay()

  return (
    <div id="hint">
      {armed ? (
        <>
          Now click a <b>sink</b> jack.
        </>
      ) : (
        <>
          Click a <b>source</b> jack, then a <b>sink</b> jack, to patch. Click a cable to shape it.
        </>
      )}
    </div>
  )
}
