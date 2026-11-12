/**
 * Browse the online module catalog (see `engine/catalog.py`): search sources
 * and sinks, install one (its `depends` come with it), update one whose files
 * changed upstream, or remove one from the data folder. Every action ends in a
 * sync, so a new module lands straight in the add-source / add-sink pickers.
 */

import { api, errorMessage } from '../lib/api'
import { h } from '../lib/dom'
import { patchbay } from '../state/patchbay'
import { toast } from '../state/toast'
import type { CatalogListing, CatalogModule, ModuleKind } from '../types'

type KindFilter = 'all' | ModuleKind

const STATE_LABEL: Record<CatalogModule['state'], string> = {
  available: '',
  installed: 'installed',
  update: 'update available',
  local: 'local only',
}

function kb(bytes: number): string {
  return bytes >= 1 << 20 ? `${(bytes / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** True if every whitespace-separated word of `query` is in the module's text. */
function matches(m: CatalogModule, query: string): boolean {
  const text = `${m.name} ${m.kind} ${m.description} ${m.depends.join(' ')}`.toLowerCase()
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => text.includes(w))
}

export function catalogButton(isBusy: () => boolean): HTMLButtonElement {
  let listing: CatalogListing | null = null
  let working: { name: string; action: 'install' | 'remove' } | null = null
  let kind: KindFilter = 'all'

  const search = h('input', {
    type: 'search',
    placeholder: 'search modules…',
    'aria-label': 'search modules',
    className: 'catalog-search',
    onInput: () => paint(),
  })
  const kindButtons = (['all', 'source', 'sink'] as const).map((k) =>
    h(
      'button',
      {
        type: 'button',
        className: k === kind ? 'on' : '',
        onClick: () => {
          kind = k
          kindButtons.forEach((b, i) => (b.className = (['all', 'source', 'sink'] as const)[i] === kind ? 'on' : ''))
          paint()
        },
      },
      k === 'all' ? 'all' : `${k}s`,
    ),
  )
  const refreshBtn = h(
    'button',
    { type: 'button', title: 'fetch the catalog again', 'aria-label': 'refresh', onClick: () => void load(true) },
    '⟳',
  )
  const notice = h('div', { className: 'catalog-notice', hidden: true })
  const list = h('ul', { className: 'catalog-list' })
  const footer = h('div', { className: 'catalog-footer' })

  const dialog = h(
    'dialog',
    { id: 'catalog', 'aria-label': 'module catalog' },
    h(
      'div',
      { className: 'catalog-head' },
      h('h2', {}, 'Modules'),
      h('div', { className: 'group kinds' }, ...kindButtons),
      refreshBtn,
      h('button', { type: 'button', className: 'close', 'aria-label': 'close', onClick: () => dialog.close() }, '✕'),
    ),
    search,
    notice,
    list,
    footer,
  )
  // A click on the backdrop (outside the box) closes it.
  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) dialog.close()
  })

  async function load(refresh = false) {
    list.replaceChildren(h('li', { className: 'catalog-empty' }, 'loading the catalog…'))
    refreshBtn.disabled = true
    try {
      listing = await api.catalog(refresh)
    } catch (e) {
      listing = null
      list.replaceChildren(h('li', { className: 'catalog-empty bad' }, errorMessage(e)))
      footer.textContent = ''
      return
    } finally {
      refreshBtn.disabled = false
    }
    paint()
  }

  async function act(m: CatalogModule, action: 'install' | 'remove') {
    if (working || isBusy()) return
    if (action === 'remove' && !confirm(`Remove the ${m.kind} module "${m.name}"? Running instances keep running.`)) return
    working = { name: m.name, action }
    paint()
    const res = await patchbay.fromCatalog(action, m.name)
    working = null
    if (res && 'installed' in res) {
      const names = res.installed.map((r) => r.name)
      const extra = names.filter((n) => n !== m.name)
      toast(
        `${m.state === 'update' ? 'updated' : 'installed'} ${m.name}${extra.length ? ` (+ ${extra.join(', ')})` : ''}` +
          ` — ${res.report.sources} sources · ${res.report.sinks} sinks`,
      )
    } else if (res && 'removed' in res) {
      const { needed_by } = res.removed
      toast(
        `removed ${m.name}${needed_by.length ? ` — ${needed_by.join(', ')} needed it and is now unavailable` : ''}`,
        needed_by.length > 0,
        needed_by.length ? 6000 : undefined,
      )
    }
    await load()
  }

  function row(m: CatalogModule): HTMLElement {
    const doing = working?.name === m.name ? working.action : null
    const actions: HTMLElement[] = []
    if (m.state === 'available' || m.state === 'update') {
      actions.push(
        h(
          'button',
          {
            type: 'button',
            className: 'accent',
            disabled: working !== null,
            onClick: () => void act(m, 'install'),
          },
          doing === 'install' ? 'installing…' : m.state === 'update' ? 'Update' : 'Install',
        ),
      )
    }
    if (m.removable) {
      actions.push(
        h(
          'button',
          {
            type: 'button',
            className: 'danger-ghost',
            disabled: working !== null,
            onClick: () => void act(m, 'remove'),
          },
          doing === 'remove' ? 'removing…' : 'Remove',
        ),
      )
    }
    const details = [
      m.depends.length ? `needs ${m.depends.join(', ')}` : '',
      m.python.length ? `pip: ${m.python.map((p) => p.split(/[<>=;! ]/)[0]).join(', ')}` : '',
      m.size ? kb(m.size) : '',
    ].filter(Boolean)
    return h(
      'li',
      { className: `catalog-item ${m.state}` },
      h(
        'div',
        { className: 'catalog-main' },
        h(
          'div',
          { className: 'catalog-title' },
          h('span', { className: 'catalog-name' }, m.name),
          h('span', { className: `catalog-kind ${m.kind}` }, m.kind),
          STATE_LABEL[m.state] && h('span', { className: `catalog-state ${m.state}` }, STATE_LABEL[m.state]),
        ),
        m.description && h('div', { className: 'catalog-desc' }, m.description),
        details.length > 0 && h('div', { className: 'catalog-meta' }, details.join(' · ')),
        m.system.length > 0 &&
          h(
            'details',
            { className: 'catalog-setup' },
            h('summary', {}, 'setup pip can’t do'),
            h('ul', {}, ...m.system.map((s) => h('li', {}, s))),
          ),
      ),
      h('div', { className: 'catalog-actions' }, ...actions),
    )
  }

  function paint() {
    if (!listing) return
    notice.hidden = !listing.cached
    notice.textContent = listing.cached
      ? `Offline: showing the last catalog fetched. Installing needs the network. (${listing.error ?? ''})`
      : ''
    const query = search.value.trim()
    const shown = listing.modules.filter((m) => (kind === 'all' || m.kind === kind) && matches(m, query))
    list.replaceChildren(
      ...(shown.length
        ? shown.map(row)
        : [h('li', { className: 'catalog-empty' }, query ? `nothing matches “${query}”` : 'the catalog is empty')]),
    )
    const installed = listing.modules.filter((m) => m.state !== 'available').length
    footer.replaceChildren(
      `${listing.modules.length} modules · ${installed} installed · from `,
      h('code', { title: listing.url }, listing.url),
    )
  }

  return h(
    'button',
    {
      id: 'catalogBtn',
      type: 'button',
      title: 'browse, install and update sources and sinks from the module catalog',
      onClick: () => {
        if (!dialog.isConnected) document.body.append(dialog)
        dialog.showModal()
        search.focus()
        void load()
      },
    },
    'Browse…',
  )
}
