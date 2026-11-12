import { h } from '../lib/dom'
import { shortPortId, sourcePorts } from '../lib/ports'
import { patchbay } from '../state/patchbay'
import { isChoiceSpec, isPortSpec } from '../types'
import type { ChainNode, Connection, ModuleSpec, NodeSpec, NodeSpecs, ParamValue } from '../types'
import { paramField } from './paramField'
import type { ParamField } from './paramField'

/**
 * Side panel for the selected cable: enable/disable, shape, or cut it.
 *
 * Built once per selected cable. While the same cable stays selected, refreshes
 * from the engine only update values in place, so a field you are tabbing
 * through keeps its focus.
 */
export function inspector(): HTMLElement {
  const aside = h('aside', { id: 'inspector', hidden: true })
  let shownId: string | null = null
  let enabled: HTMLInputElement | null = null
  let chain: ChainEditor | null = null

  const build = (connection: Connection, specs: NodeSpecs, modules: ModuleSpec[]) => {
    const id = connection.id
    shownId = id
    const toggle = h('input', { type: 'checkbox', id: 'inspEnabled', checked: connection.enabled })
    toggle.addEventListener('change', () => void patchbay.setEnabled(id, toggle.checked))
    enabled = toggle
    chain = new ChainEditor(connection, specs, modules)

    aside.replaceChildren(
      h(
        'div',
        { className: 'insp-head' },
        h(
          'div',
          null,
          h(
            'div',
            { className: 'insp-title', id: 'inspTitle' },
            `${shortPortId(connection.source)}  →  ${shortPortId(connection.sink)}`,
          ),
          h(
            'div',
            { className: 'insp-sub', id: 'inspSub' },
            `${connection.source}   →   ${connection.sink}`,
          ),
        ),
        h(
          'button',
          {
            id: 'inspClose',
            type: 'button',
            'aria-label': 'close',
            onClick: () => patchbay.selectConnection(null),
          },
          '×',
        ),
      ),
      h('label', { className: 'row-toggle' }, toggle, ' connection enabled'),
      chain.element,
      h(
        'button',
        {
          id: 'inspDelete',
          type: 'button',
          className: 'danger',
          onClick: () => void patchbay.deleteConnection(id),
        },
        'Delete connection',
      ),
    )
  }

  patchbay.subscribe((state, prev) => {
    if (
      state.selected === prev.selected &&
      state.nodeSpecs === prev.nodeSpecs &&
      state.modules === prev.modules
    )
      return
    const { selected } = state
    if (!selected) {
      shownId = enabled = chain = null
      aside.hidden = true
      aside.replaceChildren()
      return
    }
    if (selected.id !== shownId || !enabled || !chain) build(selected, state.nodeSpecs, state.modules)
    else {
      enabled.checked = selected.enabled
      chain.update(selected, state.nodeSpecs, state.modules)
    }
    aside.hidden = false
  })

  return aside
}

/** The default parameter set the engine would use for a freshly added node. */
function defaultParams(spec: NodeSpec): Record<string, ParamValue> {
  return Object.fromEntries(
    Object.entries(spec).map(([key, param]) => [
      key,
      isPortSpec(param) ? '' : isChoiceSpec(param) ? (param.choices[0] ?? '') : param[0],
    ]),
  )
}

/**
 * The transform chain on one cable: source → node → node → sink.
 *
 * Every edit rewrites the whole chain and PUTs it, which the engine applies on
 * its next tick — no restart, no reconnect.
 */
class ChainEditor {
  readonly element: HTMLElement
  private connection: Connection
  private specs: NodeSpecs | null = null
  private modules: ModuleSpec[] | null = null
  private sources: string[] = []
  /** Node types in order — when unchanged, a refresh updates values in place. */
  private shape: string | null = null
  private fields: Map<string, ParamField>[] = []
  private readonly list = h('div', { id: 'chainList' })
  private readonly typeSelect = h('select', { id: 'nodeType' })

  constructor(connection: Connection, specs: NodeSpecs, modules: ModuleSpec[]) {
    this.connection = connection
    this.element = h(
      'div',
      { className: 'chain-wrap' },
      h('div', { className: 'chain-label' }, 'transform chain ', h('span', null, 'source → … → sink')),
      this.list,
      h(
        'div',
        { className: 'chain-add' },
        this.typeSelect,
        h('button', { id: 'addNode', type: 'button', onClick: () => this.addNode() }, '+ add node'),
      ),
    )
    this.update(connection, specs, modules)
  }

  update(connection: Connection, specs: NodeSpecs, modules: ModuleSpec[]): void {
    this.connection = connection
    const modulesChanged = modules !== this.modules
    if (modulesChanged) {
      this.modules = modules
      this.sources = sourcePorts(modules)
    }
    const specsChanged = specs !== this.specs
    if (specsChanged) {
      this.specs = specs
      const keep = this.typeSelect.value
      const types = Object.keys(specs)
      this.typeSelect.replaceChildren(...types.map((t) => h('option', { value: t }, t)))
      this.typeSelect.value = types.includes(keep) ? keep : (types[0] ?? '')
    }

    const shape = JSON.stringify(connection.chain.map((node) => node.type))
    if (specsChanged || modulesChanged || shape !== this.shape) {
      this.shape = shape
      this.render()
      return
    }
    connection.chain.forEach((node, index) => {
      for (const [name, field] of this.fields[index] ?? []) field.set(node.params[name])
    })
  }

  private render(): void {
    const { chain } = this.connection
    this.fields = []
    if (chain.length === 0) {
      this.list.replaceChildren(h('div', { className: 'node empty' }, 'pass-through — no transform'))
      return
    }
    this.list.replaceChildren(...chain.map((node, index) => this.nodeCard(node, index)))
  }

  private nodeCard(node: ChainNode, index: number): HTMLElement {
    const fields = new Map<string, ParamField>()
    for (const [name, spec] of Object.entries(this.specs?.[node.type] ?? {})) {
      fields.set(
        name,
        paramField(name, spec, node.params[name], (value) => {
          const current = this.connection.chain[index]
          if (current) this.updateNode(index, { ...current, params: { ...current.params, [name]: value } })
        }, this.sources),
      )
    }
    this.fields[index] = fields

    return h(
      'div',
      { className: 'node' },
      h(
        'div',
        { className: 'nh' },
        h('span', { className: 'nt' }, node.type),
        h(
          'span',
          { className: 'nord' },
          h('button', { type: 'button', onClick: () => this.moveNode(index, -1) }, '↑'),
          h('button', { type: 'button', onClick: () => this.moveNode(index, +1) }, '↓'),
          h('button', { type: 'button', onClick: () => this.removeNode(index) }, '✕'),
        ),
      ),
      fields.size > 0 &&
        h('div', { className: 'params' }, [...fields.values()].map((field) => field.element)),
    )
  }

  private replace(chain: ChainNode[]): void {
    void patchbay.setChain(this.connection.id, chain)
  }

  private updateNode(index: number, node: ChainNode): void {
    this.replace(this.connection.chain.map((existing, i) => (i === index ? node : existing)))
  }

  private removeNode(index: number): void {
    this.replace(this.connection.chain.filter((_, i) => i !== index))
  }

  private moveNode(index: number, delta: number): void {
    const target = index + delta
    if (target < 0 || target >= this.connection.chain.length) return
    const chain = [...this.connection.chain]
    const [a, b] = [chain[index]!, chain[target]!]
    chain[index] = b
    chain[target] = a
    this.replace(chain)
  }

  private addNode(): void {
    const type = this.typeSelect.value
    const spec = this.specs?.[type]
    if (!spec) return
    this.replace([...this.connection.chain, { type, params: defaultParams(spec) }])
  }
}
