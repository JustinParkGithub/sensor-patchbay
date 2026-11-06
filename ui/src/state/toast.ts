/** Transient one-line messages at the top of the screen. */

import { h } from '../lib/dom'
import { errorMessage } from '../lib/api'

const TOAST_MS = 2400

const element = h('div', { id: 'toast', hidden: true })
let timer: ReturnType<typeof setTimeout> | undefined

export function toast(text: string, bad = false, ms = TOAST_MS): void {
  if (!element.isConnected) document.body.append(element)
  element.textContent = text
  element.className = bad ? 'bad' : ''
  element.hidden = false
  clearTimeout(timer)
  timer = setTimeout(() => {
    element.hidden = true
  }, ms)
}

/** Report a rejected promise without tearing down the UI. */
export function toastError(e: unknown): void {
  toast(errorMessage(e), true)
}
