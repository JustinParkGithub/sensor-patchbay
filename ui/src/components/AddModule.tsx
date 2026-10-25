import { useEffect, useMemo, useState } from 'react'
import { usePatchbay } from '../state/PatchbayProvider'
import type { ModuleKind, PluginArg, PluginInfo } from '../types'

type Draft = Record<string, string | boolean>

/** Form state for a plugin's args, seeded from the defaults it declares. */
function initialDraft(plugin: PluginInfo | undefined): Draft {
  const draft: Draft = {}
  for (const arg of plugin?.args ?? []) {
    draft[arg.name] = arg.type === 'bool' ? Boolean(arg.default) : (arg.default ?? '').toString()
  }
  return draft
}

/** Blank fields are omitted so the plugin's own default applies. */
function toArgs(plugin: PluginInfo, draft: Draft): Record<string, unknown> {
  const args: Record<string, unknown> = {}
  for (const arg of plugin.args) {
    const value = draft[arg.name]
    if (typeof value === 'boolean') args[arg.name] = value
    else if (value !== '' && value !== undefined)
      args[arg.name] = arg.type === 'int' || arg.type === 'float' ? Number.parseFloat(value) : value
  }
  return args
}

/**
 * The add-source / add-sink picker under each column. Built entirely from the
 * engine's plugin catalog (`GET /api/state` → `plugins`), so a new plugin or a
 * module folder dropped into `sources/` or `sinks/` shows up here with no UI change. Plugins whose
 * optional dependency is missing stay listed but disabled, with the reason.
 */
export function AddModule({ kind }: { kind: ModuleKind }) {
  const { plugins, addModule } = usePatchbay()
  const list = kind === 'source' ? plugins.sources : plugins.sinks

  const [type, setType] = useState('')
  const plugin = useMemo(() => list.find((p) => p.type === type), [list, type])
  const [draft, setDraft] = useState<Draft>({})
  const [busy, setBusy] = useState(false)

  // Default to the first runnable plugin once the catalog lands (or changes).
  useEffect(() => {
    if (list.some((p) => p.type === type)) return
    setType((list.find((p) => p.available) ?? list[0])?.type ?? '')
  }, [list, type])

  useEffect(() => setDraft(initialDraft(plugin)), [plugin])

  const submit = () => {
    if (!plugin?.available) return
    setBusy(true)
    void addModule(kind, plugin.type, toArgs(plugin, draft)).finally(() => setBusy(false))
  }

  return (
    <div className="add-mod" data-kind={kind}>
      <select
        className="addType"
        title={`${kind} plugin`}
        value={type}
        onChange={(e) => setType(e.target.value)}
      >
        {list.map((p) => (
          <option key={p.type} value={p.type} disabled={!p.available}>
            {p.label}
            {p.available ? '' : ' — unavailable'}
          </option>
        ))}
      </select>
      {plugin && plugin.args.length > 0 && (
        <div className="addArgs">
          {plugin.args.map((arg) => (
            <ArgField
              key={arg.name}
              arg={arg}
              value={draft[arg.name]}
              onChange={(v) => setDraft((d) => ({ ...d, [arg.name]: v }))}
            />
          ))}
        </div>
      )}
      <button
        type="button"
        className="addBtn"
        disabled={!plugin?.available || busy}
        onClick={submit}
      >
        {busy ? '…' : `+ add ${kind}`}
      </button>
      {plugin && !plugin.available && <div className="addReason">{plugin.reason}</div>}
    </div>
  )
}

function ArgField({
  arg,
  value,
  onChange,
}: {
  arg: PluginArg
  value: string | boolean | undefined
  onChange: (value: string | boolean) => void
}) {
  return (
    <label title={arg.help || undefined}>
      {arg.name}
      {arg.type === 'bool' ? (
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
      ) : (
        <input
          type={arg.type === 'str' ? 'text' : 'number'}
          step={arg.type === 'float' ? 'any' : undefined}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  )
}
