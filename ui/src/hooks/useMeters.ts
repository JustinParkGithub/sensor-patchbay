import { useEffect, useRef } from 'react'
import { formatValue } from '../lib/ports'
import { useJackRegistry } from '../state/JackRegistry'
import { useLive } from '../state/LiveProvider'

/** Floor for the auto-gain peak, so a silent port doesn't divide by zero. */
const MIN_PEAK = 0.01
/** Per-frame decay of the peak, giving the bars a slow release. */
const PEAK_DECAY = 0.97

/**
 * Paint every jack's readout and meter bar from the live stream.
 *
 * This writes to the DOM directly rather than through React: the values change
 * ~30x/s and touch exactly two leaf nodes per jack, so a re-render would be
 * orders of magnitude more work than the update itself. Scalar bars are
 * auto-gained against a decaying peak, which is what makes an unknown sensor
 * axis readable without anyone configuring a range.
 */
export function useMeters(): void {
  const registry = useJackRegistry()
  const { subscribe } = useLive()
  const peaks = useRef(new Map<string, number>())

  useEffect(
    () =>
      subscribe((snapshot) => {
        for (const [id, jack] of registry.entries()) {
          const value = (jack.kind === 'source' ? snapshot.ports[id] : snapshot.sinks[id]) ?? 0

          if (jack.type === 'event') {
            const on = value >= 0.5
            jack.value.textContent = on ? '●' : '○'
            jack.meter.style.width = on ? '100%' : '0'
            continue
          }

          const magnitude = Math.abs(value)
          const peak = Math.max(magnitude, (peaks.current.get(id) ?? MIN_PEAK) * PEAK_DECAY, MIN_PEAK)
          peaks.current.set(id, peak)
          jack.value.textContent = formatValue(value)
          jack.meter.style.width = `${Math.min(100, (magnitude / peak) * 100).toFixed(0)}%`
        }
      }),
    [registry, subscribe],
  )
}
