import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

const TOAST_MS = 2400

interface ToastMessage {
  text: string
  bad: boolean
}

type ToastFn = (text: string, bad?: boolean) => void

const ToastContext = createContext<ToastFn | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<ToastMessage | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const toast = useCallback<ToastFn>((text, bad = false) => {
    setMessage({ text, bad })
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setMessage(null), TOAST_MS)
  }, [])

  useEffect(() => () => clearTimeout(timer.current), [])

  return (
    <ToastContext.Provider value={toast}>
      {children}
      {message && <div id="toast" className={message.bad ? 'bad' : undefined}>{message.text}</div>}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastFn {
  const toast = useContext(ToastContext)
  if (!toast) throw new Error('useToast must be used inside <ToastProvider>')
  return toast
}

/** `toast(...)` bound to the two shapes every async handler needs. */
export function useToastHandlers() {
  const toast = useToast()
  return useMemo(
    () => ({
      toast,
      /** Report a rejected promise without tearing down the UI. */
      toastError: (e: unknown) => toast(e instanceof Error ? e.message : String(e), true),
    }),
    [toast],
  )
}
