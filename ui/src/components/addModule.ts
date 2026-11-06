import { h } from '../lib/dom'
import { patchbay } from '../state/patchbay'
import type { ModuleKind, PluginArg, PluginInfo } from '../types'

/** One arg input, read back when the form is submitted. */
interface ArgInput {
  arg: PluginArg
  input: HTMLInputElement
}

function argField(arg: PluginArg): [HTMLElement, ArgInput] {
  const input =
    arg.type === 'bool'
      ? h('input', { type: 'checkbox', checked: Boolean(arg.default) })
      : h('input', {
          type: arg.type === 'str' ? 'text' : 'number',
          step: arg.type === 'float' ? 'any' : undefined,
          value: (arg.default ?? '').toString(),
        })
  return [h('label', { title: arg.help || undefined }, arg.name, input), { arg, input }]
}

/** Blank fields are omitted so the plugin's own default applies. */
function toArgs(fields: ArgInput[]): Record<string, unknown> {
  const args: Record<string, unknown> = {}
  for (const { arg, input } of fields) {
    if (arg.type === 'bool') args[arg.name] = input.checked
    else if (input.value !== '')
      args[arg.name] =
        arg.type === 'int' || arg.type === 'float' ? Number.parseFloat(input.value) : input.value
  }
  return args
}

/**
 * The add-source / add-sink picker under each column. Built entirely from the
 * engine's plugin catalog (`GET /api/state` → `plugins`), so a new plugin or a
 * module folder dropped into `sources/` or `sinks/` shows up here with no UI change. Plugins whose
 * optional dependency is missing stay listed but disabled, with the reason.
 */
export function addModule(kind: ModuleKind): HTMLElement {
  let list: PluginInfo[] = []
  let type = ''
  /** Which plugin's args the form currently holds; a catalog re-read keeps the typed values. */
  let formFor = ''
  let fields: ArgInput[] = []
  let busy = false

  const select = h('select', { className: 'addType', title: `${kind} plugin` })
  const argsBox = h('div', { className: 'addArgs' })
  const button = h('button', { type: 'button', className: 'addBtn' })
  const reason = h('div', { className: 'addReason' })
  const root = h('div', { className: 'add-mod', 'data-kind': kind })

  const plugin = () => list.find((p) => p.type === type)

  const paint = () => {
    const current = plugin()
    const signature = current ? JSON.stringify([current.type, current.args]) : ''
    if (signature !== formFor) {
      formFor = signature
      const built = (current?.args ?? []).map(argField)
      argsBox.replaceChildren(...built.map(([label]) => label))
      fields = built.map(([, field]) => field)
    }
    button.disabled = !current?.available || busy
    button.textContent = busy ? '…' : `+ add ${kind}`
    reason.textContent = !list.length
      ? `no ${kind}s installed — upload a module (.zip), or ⟳ sync`
      : current && !current.available
        ? current.reason
        : ''
    root.replaceChildren(
      select,
      ...(fields.length ? [argsBox] : []),
      button,
      ...(reason.textContent ? [reason] : []),
    )
  }

  const setCatalog = (next: PluginInfo[]) => {
    list = next
    // Default to the first runnable plugin once the catalog lands (or changes).
    if (!list.some((p) => p.type === type)) type = (list.find((p) => p.available) ?? list[0])?.type ?? ''
    select.replaceChildren(
      ...list.map((p) =>
        h('option', { value: p.type, disabled: !p.available }, p.label, p.available ? '' : ' — unavailable'),
      ),
    )
    select.value = type
    paint()
  }

  select.addEventListener('change', () => {
    type = select.value
    paint()
  })

  button.addEventListener('click', () => {
    const current = plugin()
    if (!current?.available) return
    busy = true
    paint()
    void patchbay.addModule(kind, current.type, toArgs(fields)).finally(() => {
      busy = false
      paint()
    })
  })

  const pick = (catalog: typeof patchbay.state.plugins) =>
    kind === 'source' ? catalog.sources : catalog.sinks
  setCatalog(pick(patchbay.state.plugins))
  patchbay.subscribe((state, prev) => {
    if (state.plugins !== prev.plugins) setCatalog(pick(state.plugins))
  })

  return root
}
