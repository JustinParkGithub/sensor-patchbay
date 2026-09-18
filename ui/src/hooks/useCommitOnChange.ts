import { useEffect, useRef } from 'react'

/**
 * Fire `onCommit` on the DOM's native `change` event.
 *
 * React's `onChange` is really the `input` event — it fires on every keystroke,
 * which for a number field would mean a PUT to the engine per digit typed.
 * The native `change` event fires once the value is committed (blur, Enter, or
 * a stepper click), which is the granularity the transform chain wants.
 */
export function useCommitOnChange<T extends HTMLElement>(onCommit: (element: T) => void) {
  const ref = useRef<T>(null)
  const latest = useRef(onCommit)
  latest.current = onCommit

  useEffect(() => {
    const element = ref.current
    if (!element) return
    const handler = () => latest.current(element)
    element.addEventListener('change', handler)
    return () => element.removeEventListener('change', handler)
  }, [])

  return ref
}
