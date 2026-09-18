import { api } from '../lib/api'
import { useLiveStatus } from '../state/LiveProvider'
import { useToastHandlers } from '../state/ToastProvider'

/**
 * Kills every output and releases held keys/buttons. Its state comes from the
 * live stream, not from the click, so it always shows what the engine is doing.
 */
export function PanicButton() {
  const { panic } = useLiveStatus()
  const { toastError } = useToastHandlers()

  return (
    <button
      id="panicBtn"
      type="button"
      title="disable all outputs"
      className={panic ? 'armed' : undefined}
      onClick={() => void api.setPanic(!panic).catch(toastError)}
    >
      {panic ? 'PANIC · ON' : 'PANIC'}
    </button>
  )
}
