/**
 * Browse the online module catalog (see `engine/catalog.py`): search sources
 * and sinks, install one (its `depends` come with it), update one whose files
 * changed upstream, or remove one from the data folder. Every action ends in a
 * sync, so a new module lands straight in the add-source / add-sink pickers.
 *
 * Every installed module folder is listed, however it got there. One whose
 * files changed since it was installed (`modified`), or that has no install
 * record (`local`), is only overwritten after the user confirms.
 */

import { api, errorMessage } from '../lib/api'
import { h } from '../lib/dom'
import { patchbay } from '../state/patchbay'
import { toast } from '../state/toast'
import type { CatalogListing, CatalogModule, ModuleKind } from '../types'

type KindFilter = 'all' | ModuleKind | 'preset'
const FILTERS = ['all', 'source', 'sink', 'preset'] as const

function stateLabel(m: CatalogModule): string {
  switch (m.state) {
    case 'available':
      return ''
    case 'installed':
      return 'installed'
    case 'update':
      return m.change === 'downgrade' ? 'catalog has an older version' : m.change === 'upgrade' ? 'update available' : 'changed upstream'
    case 'modified':
      return 'modified locally'
    case 'local':
      return 'local only'
  }
}

/** `1.0.0`, `1.0.0 → 1.1.0` for an update, or nothing when neither side has one. */
function versionText(m: CatalogModule): string {
  const v = (s: string | null) => s || '?'
  if (m.state === 'update') return `${v(m.installed_version)} → ${v(m.version)}`
  if (m.state === 'available') return m.version ?? ''
  return m.installed_version ?? ''
}

/** What the install button says, or null when there's nothing to install. */
function installLabel(m: CatalogModule): string | null {
  if (m.state === 'available') return 'Install'
  if (!m.in_catalog) return null // nothing to install from
  if (m.state === 'update') return m.change === 'downgrade' ? 'Downgrade' : 'Update'
  if (m.state === 'modified') return 'Reinstall'
  if (m.state === 'local') return 'Replace'
  return null
}

/** Installing over this would lose files nobody installed. */
function overwrites(m: CatalogModule): string | null {
  if (m.state === 'modified')
    return `"${m.name}" was changed after it was installed. Reinstalling replaces those changes with the catalog's ${m.version ?? 'copy'}.`
  if (m.state === 'local')
    return `"${m.name}" wasn't installed from the catalog. Replacing it overwrites it with the catalog's ${m.version ?? 'copy'}.`
  return null
}

function sourceText(m: CatalogModule, catalogUrl: string): string {
  if (m.state === 'available' || m.source === null) return ''
  if (m.source.startsWith('upload:')) return `uploaded (${m.source.slice('upload:'.length)})`
  return m.source === catalogUrl ? '' : `from ${m.source}`
}

function kb(bytes: number): string {
  return bytes >= 1 << 20 ? `${(bytes / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** True if every whitespace-separated word of `query` is in the module's text. */
function matches(m: CatalogModule, query: string): boolean {
  const needs = (m.requires ?? []).map((r) => r.id)
  const text = `${m.name} ${m.kind} ${m.description} ${m.depends.join(' ')} ${needs.join(' ')}`.toLowerCase()
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => text.includes(w))
}

export function catalogButton(isBusy: () => boolean): HTMLButtonElement {
  let listing: CatalogListing | null = null
  let working: { key: string; action: 'install' | 'remove' } | null = null
  const key = (m: CatalogModule) => `${m.kind}:${m.name}`
  let kind: KindFilter = 'all'

  const search = h('input', {
    type: 'search',
    placeholder: 'search modules and presets…',
    'aria-label': 'search modules',
    className: 'catalog-search',
    onInput: () => paint(),
  })
  const kindButtons = FILTERS.map((k) =>
    h(
      'button',
      {
        type: 'button',
        className: k === kind ? 'on' : '',
        onClick: () => {
          kind = k
          kindButtons.forEach((b, i) => (b.className = FILTERS[i] === kind ? 'on' : ''))
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
    { id: 'catalog', 'aria-label': 'catalog: modules and presets' },
    h(
      'div',
      { className: 'catalog-head' },
      h('h2', {}, 'Catalog'),
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
    if (action === 'remove') {
      const lose = m.state === 'modified' || m.state === 'local' ? ' Its files, including any changes, are deleted.' : ''
      const ask =
        m.kind === 'preset'
          ? `Delete the preset "${m.name}"?${m.state === 'modified' ? ' Your saved changes go with it.' : ''}`
          : `Remove the ${m.kind} module "${m.name}"?${lose} Running instances keep running.`
      if (!confirm(ask)) return
    }
    const warning = action === 'install' ? overwrites(m) : null
    if (warning && !confirm(warning)) return
    working = { key: key(m), action }
    paint()
    const what = m.kind === 'preset' ? 'preset' : 'module'
    let res = await patchbay.fromCatalog(action, m.name, what, warning !== null)
    if (res && 'conflict' in res) {
      // It changed on disk after the list was drawn: ask now.
      res = confirm(`${res.conflict}. Go ahead?`) ? await patchbay.fromCatalog(action, m.name, what, true) : null
    }
    working = null
    if (res && 'installed' in res) {
      const extra = res.installed.map((r) => r.name).filter((n) => n !== m.name)
      const mine = res.installed.find((r) => r.name === m.name)
      const version = mine?.kind === 'module' ? mine.version : ''
      const verb = {
        available: 'installed',
        installed: 'reinstalled',
        modified: 'reinstalled',
        local: 'replaced',
        update: m.change === 'downgrade' ? 'downgraded' : 'updated',
      }[m.state]
      toast(
        `${verb} ${m.name}${version ? ` ${version}` : ''}${extra.length ? ` (+ ${extra.join(', ')})` : ''}` +
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
    const doing = working?.key === key(m) ? working.action : null
    const actions: HTMLElement[] = []
    const label = installLabel(m)
    if (label) {
      const careful = overwrites(m) !== null || m.change === 'downgrade'
      actions.push(
        h(
          'button',
          {
            type: 'button',
            className: careful ? '' : 'accent',
            disabled: working !== null,
            onClick: () => void act(m, 'install'),
          },
          doing === 'install' ? 'installing…' : label,
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
      sourceText(m, listing?.url ?? ''),
      m.runnable ? '' : `native entry (${m.entry}): this engine can't run it`,
      m.depends.length ? `needs ${m.depends.join(', ')}` : '',
      m.requires?.length ? `uses ${m.requires.map((r) => r.types.join(' or ') || r.id).join(', ')}` : '',
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
          versionText(m) && h('span', { className: 'catalog-version' }, versionText(m)),
          h('span', { className: `catalog-kind ${m.kind}` }, m.kind),
          stateLabel(m) &&
            h('span', { className: `catalog-state ${m.state} ${m.change ?? ''}` }, stateLabel(m)),
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
    const all = listing.modules
    const presets = all.filter((m) => m.kind === 'preset').length
    const installed = all.filter((m) => m.state !== 'available').length
    footer.replaceChildren(
      `${all.length - presets} modules · ${presets} presets · ${installed} installed · from `,
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
