import { formatValue } from '../lib/ports'
import { jacks } from '../state/jacks'
import { live } from '../state/live'

/** Floor for the auto-gain peak, so a silent port doesn't divide by zero. */
const MIN_PEAK = 0.01
/** Per-frame decay of the peak, giving the bars a slow release. */
const PEAK_DECAY = 0.97

/**
 * Paint every jack's readout and meter bar from the live stream.
 *
 * The values change ~30x/s and touch exactly two leaf nodes per jack, so this
 * is a `textContent` and a `style.width` write per jack per frame, nothing
 * more. Scalar bars are auto-gained against a decaying peak, which is what
 * makes an unknown sensor axis readable without anyone configuring a range.
 */
export function startMeters(): void {
  const peaks = new Map<string, number>()

  live.subscribe((snapshot) => {
    for (const [id, jack] of jacks.entries()) {
      const value = (jack.kind === 'source' ? snapshot.ports[id] : snapshot.sinks[id]) ?? 0

      if (jack.type === 'event') {
        const on = value >= 0.5
        jack.value.textContent = on ? '●' : '○'
        jack.meter.style.width = on ? '100%' : '0'
        continue
      }

      const magnitude = Math.abs(value)
      const peak = Math.max(magnitude, (peaks.get(id) ?? MIN_PEAK) * PEAK_DECAY, MIN_PEAK)
      peaks.set(id, peak)
      jack.value.textContent = formatValue(value)
      jack.meter.style.width = `${Math.min(100, (magnitude / peak) * 100).toFixed(0)}%`
    }
  })
}
