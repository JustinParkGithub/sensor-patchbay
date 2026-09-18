import { useEffect, useRef } from 'react'

/**
 * Run `callback` once per frame for the lifetime of the component.
 *
 * The callback is re-read from a ref each frame, so it always sees the latest
 * render's closure without the loop being torn down and restarted.
 */
export function useAnimationFrame(callback: () => void): void {
  const latest = useRef(callback)
  latest.current = callback

  useEffect(() => {
    let handle = requestAnimationFrame(function frame() {
      latest.current()
      handle = requestAnimationFrame(frame)
    })
    return () => cancelAnimationFrame(handle)
  }, [])
}
