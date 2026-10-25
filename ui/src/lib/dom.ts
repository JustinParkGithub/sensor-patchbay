/**
 * The whole of the patch panel's "view layer": build an element in one
 * expression, and reorder a parent's children without touching ones that are
 * already in place.
 *
 * Props are applied by name: `on<event>` functions become listeners (so
 * `onChange` is the DOM's native `change` event), names the element has as a
 * property are assigned (`className`, `value`, `checked`, `disabled`, ...),
 * and everything else — `data-*`, `aria-*`, every SVG attribute — is set as an
 * attribute. `null` / `undefined` props are skipped.
 */

export type Child = Node | string | number | false | null | undefined
export type Props = Record<string, unknown>

const SVG_NS = 'http://www.w3.org/2000/svg'

function apply(element: Element, props: Props | null | undefined, attributesOnly: boolean): void {
  if (!props) return
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null) continue
    if (key.startsWith('on') && typeof value === 'function') {
      element.addEventListener(key.slice(2).toLowerCase(), value as EventListener)
    } else if (attributesOnly || key.includes('-') || !(key in element)) {
      if (value !== false) element.setAttribute(key, value === true ? '' : String(value))
    } else {
      ;(element as unknown as Record<string, unknown>)[key] = value
    }
  }
}

function nodes(children: (Child | Child[])[]): (Node | string)[] {
  const out: (Node | string)[] = []
  for (const child of children.flat()) {
    if (child === false || child === null || child === undefined) continue
    out.push(typeof child === 'number' ? String(child) : child)
  }
  return out
}

/** Create an HTML element. Put `type` before `value` for inputs. */
export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props?: Props | null,
  ...children: (Child | Child[])[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag)
  apply(element, props, false)
  element.append(...nodes(children))
  return element
}

/** Create an SVG element; every prop except listeners is an attribute. */
export function svg<K extends keyof SVGElementTagNameMap>(
  tag: K,
  props?: Props | null,
  ...children: (Child | Child[])[]
): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG_NS, tag)
  apply(element, props, true)
  element.append(...nodes(children))
  return element
}

/**
 * Make `parent`'s children exactly `children`, in order — a no-op when they
 * already are. Reused elements are moved, never recreated, so they keep their
 * focus, listeners and (for a camera preview) their open stream.
 */
export function setChildren(parent: Element, children: Element[]): void {
  const current = parent.children
  if (current.length === children.length && children.every((child, i) => current[i] === child)) return
  parent.replaceChildren(...children)
}

/** `class` string from the truthy parts. */
export function classes(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}
