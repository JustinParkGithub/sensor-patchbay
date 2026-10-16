import { useState } from 'react'
import { api } from '../lib/api'
import { usePatchbay } from '../state/PatchbayProvider'
import { useToastHandlers } from '../state/ToastProvider'

/**
 * Starts / stops the camera hand + gesture tracker (`plugins/cv_hands.py`).
 * Turning it on adds a `cv` source module to the patch area; turning it off
 * removes it (cables to it stay in the graph and just read 0).
 */
export function VisionButton() {
  const { vision, reloadAll } = usePatchbay()
  const { toast, toastError } = useToastHandlers()
  const [busy, setBusy] = useState(false)

  const toggle = () => {
    setBusy(true)
    void api
      .setVision(!vision.on)
      .then(async (next) => {
        await reloadAll()
        toast(next.on ? 'vision on — camera tracking hands' : 'vision off')
      })
      .catch(toastError)
      .finally(() => setBusy(false))
  }

  return (
    <button
      id="visionBtn"
      type="button"
      className={vision.on ? 'on' : undefined}
      disabled={!vision.available || busy}
      title={
        vision.available
          ? 'start / stop the camera hand + gesture tracker'
          : 'unavailable — pip install opencv-python mediapipe'
      }
      onClick={toggle}
    >
      {busy ? 'VISION · …' : vision.on ? 'VISION · ON' : 'VISION'}
    </button>
  )
}
