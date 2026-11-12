/**
 * Everything the patch panel edits: the module list, the routing graph, and the
 * two bits of transient UI state that drive patching (which source jack is
 * armed, which cable is selected).
 *
 * The engine is the single source of truth — every mutation is a REST call
 * followed by a re-read of `/api/graph`, so the UI can never drift from what is
 * actually running.
 *
 * State is immutable: each change produces a new `PatchbayState`, and fields
 * that did not change keep their identity. Views subscribe, get `(state, prev)`
 * and compare fields with `!==` to decide what to repaint.
 */

import { api, ApiError, errorMessage } from '../lib/api'
import type { CatalogKind, ConnectionPatch } from '../lib/api'
import { buildPortIndex, compatibleSinks, lastConnectionBetween, wiredPorts } from '../lib/ports'
import type { PortEntry } from '../lib/ports'
import { EMPTY_CATALOG, EMPTY_GRAPH } from '../types'
import type {
  ChainNode,
  Connection,
  Graph,
  ModuleKind,
  ModuleSpec,
  MissingRequirement,
  NodeSpecs,
  PluginCatalog,
  PresetInfoMap,
  SyncReport,
} from '../types'
import { live } from './live'
import { toast, toastError } from './toast'

interface BaseState {
  /** False until the first `/api/state` + `/api/graph` pair has landed. */
  ready: boolean
  modules: ModuleSpec[]
  nodeSpecs: NodeSpecs
  presets: string[]
  /** Per preset: what it requires and what of that isn't installed. */
  presetInfo: PresetInfoMap
  presetName: string
  graph: Graph
  /** Every registered plugin type, for the add-source / add-sink pickers. */
  plugins: PluginCatalog
  armed: string | null
  selectedId: string | null
}

export interface PatchbayState extends BaseState {
  portIndex: Map<string, PortEntry>
  wired: Set<string>
  /** Sink jacks the armed source may legally drive. */
  compatible: Set<string>
  selected: Connection | null
}

type Listener = (state: Readonly<PatchbayState>, prev: Readonly<PatchbayState>) => void

/** Recompute the derived fields, reusing the previous ones whose inputs are unchanged. */
function derive(base: BaseState, prev?: PatchbayState): PatchbayState {
  const portIndex =
    prev && prev.modules === base.modules ? prev.portIndex : buildPortIndex(base.modules)
  const wired = prev && prev.graph === base.graph ? prev.wired : wiredPorts(base.graph)
  const compatible =
    prev && prev.portIndex === portIndex && prev.armed === base.armed
      ? prev.compatible
      : compatibleSinks(portIndex, base.armed)
  const selected = base.graph.connections.find((c) => c.id === base.selectedId) ?? null
  return { ...base, portIndex, wired, compatible, selected }
}

const INITIAL: BaseState = {
  ready: false,
  modules: [],
  nodeSpecs: {},
  presets: [],
  presetInfo: {},
  presetName: '',
  graph: EMPTY_GRAPH,
  plugins: EMPTY_CATALOG,
  armed: null,
  selectedId: null,
}

export class Patchbay {
  private current: PatchbayState = derive(INITIAL)
  private readonly listeners = new Set<Listener>()

  /** Bumped per background re-read, so a slow, superseded one is dropped. */
  private presetGen = 0
  private modulesGen = 0
  /** The live preset a background re-read is already chasing. */
  private chasingPreset: string | null = null
  private seenModRev = 0

  get state(): Readonly<PatchbayState> {
    return this.current
  }

  /** @returns an unsubscribe function. */
  subscribe(fn: Listener): () => void {
    this.listeners.add(fn)
    return () => {
      this.listeners.delete(fn)
    }
  }

  private set(patch: Partial<BaseState>): void {
    const prev = this.current
    this.current = derive({ ...prev, ...patch }, prev)
    for (const fn of this.listeners) fn(this.current, prev)
  }

  // ---- boot ------------------------------------------------------
  start(): void {
    live.onStatus(() => this.followLive())
    void (async () => {
      try {
        const [state, graph] = await Promise.all([api.state(), api.graph()])
        this.set({
          modules: state.modules,
          nodeSpecs: state.nodes,
          presets: state.presets,
          presetInfo: state.preset_info,
          presetName: state.preset,
          plugins: state.plugins,
          graph,
          ready: true,
        })
        this.followLive()
      } catch (e) {
        toast(`startup: ${errorMessage(e)}`, true)
      }
    })()
  }

  /** Re-read modules, presets and the graph — after any preset-level change. */
  async reloadAll(): Promise<void> {
    const [state, graph] = await Promise.all([api.state(), api.graph()])
    this.set({
      modules: state.modules,
      presets: state.presets,
      presetInfo: state.preset_info,
      presetName: state.preset,
      plugins: state.plugins,
      graph,
      selectedId: null,
      armed: null,
    })
  }

  setPresets(presets: string[], presetInfo: PresetInfoMap): void {
    this.set({ presets, presetInfo })
  }

  // ---- the library: uploads + sync -------------------------------
  /**
   * Re-read every module and preset on disk (and install what modules need).
   * Resolves with the report, or null if the engine refused.
   */
  async sync(): Promise<SyncReport | null> {
    try {
      const res = await api.sync()
      this.set({ plugins: res.plugins, presets: res.presets, presetInfo: res.preset_info })
      return res.report
    } catch (e) {
      toastError(e)
      return null
    }
  }

  /**
   * Install a module from the online catalog (with whatever it depends on), or
   * delete an installed one. The engine syncs either way; resolves with its
   * reply so the caller can say what happened, or null if it refused.
   */
  async fromCatalog(
    action: 'install' | 'remove',
    name: string,
    kind: CatalogKind,
    force = false,
  ): Promise<Awaited<ReturnType<typeof api.catalogInstall | typeof api.catalogRemove>> | { conflict: string } | null> {
    try {
      const res =
        action === 'install' ? await api.catalogInstall(name, kind, force) : await api.catalogRemove(name, kind)
      this.set({ plugins: res.plugins, presets: res.presets, presetInfo: res.preset_info })
      return res
    } catch (e) {
      // Installing over a modified or hand-placed copy: the caller asks first.
      if (e instanceof ApiError && e.status === 409) return { conflict: e.message }
      toastError(e)
      return null
    }
  }

  /**
   * Install each file (a module `.zip` or a preset `.json`), then sync once so
   * new modules show up in the pickers. Resolves with a line per file.
   */
  async upload(files: File[]): Promise<{ lines: string[]; report: SyncReport | null }> {
    const lines: string[] = []
    let failed = false
    for (const file of files) {
      try {
        const res = await api.upload(file)
        const verb = res.replaced ? 'replaced' : 'added'
        lines.push(
          res.kind === 'preset'
            ? `${verb} preset ${res.name}${res.missing.length ? ` (${needs(res.missing)})` : ''}`
            : `${verb} ${res.module_kind} ${res.name}`,
        )
      } catch (e) {
        failed = true
        lines.push(errorMessage(e))
      }
    }
    const report = await this.sync()
    if (failed) toast(lines.join(' · '), true)
    return { lines, report }
  }

  // ---- changes made behind our back ------------------------------
  private followLive(): void {
    if (!this.current.ready) return
    const { preset, modRev } = live.status

    // e.g. joycon/btn.home -> sys/preset.cycle walks through the preset files.
    if (preset && preset !== this.current.presetName && preset !== this.chasingPreset) {
      this.chasingPreset = preset
      void this.followPreset()
    }

    // another tab, or the --cli console. Our own add/remove bumps it too; the
    // re-read is cheap and keeps every client converging on the same view.
    if (modRev !== this.seenModRev) {
      this.seenModRev = modRev
      if (modRev) void this.followModules()
    }
  }

  private async followPreset(): Promise<void> {
    const gen = ++this.presetGen
    try {
      const [state, graph] = await Promise.all([api.state(), api.graph()])
      if (gen !== this.presetGen) return
      this.set({
        modules: state.modules,
        presets: state.presets,
        presetInfo: state.preset_info,
        presetName: state.preset,
        plugins: state.plugins,
        graph,
      })
      toast(`preset → ${state.preset}`)
    } catch (e) {
      if (gen === this.presetGen) toastError(e)
    } finally {
      if (gen === this.presetGen) this.chasingPreset = null
    }
  }

  private async followModules(): Promise<void> {
    const gen = ++this.modulesGen
    try {
      const [state, graph] = await Promise.all([api.state(), api.graph()])
      if (gen !== this.modulesGen) return
      this.set({ modules: state.modules, plugins: state.plugins, presetInfo: state.preset_info, graph })
    } catch (e) {
      if (gen === this.modulesGen) toastError(e)
    }
  }

  // ---- modules ---------------------------------------------------
  /** Instantiate a plugin type live; resolves false if the engine refused. */
  async addModule(kind: ModuleKind, type: string, args: Record<string, unknown>): Promise<boolean> {
    try {
      const res = await api.addModule(kind, type, args)
      this.set({ modules: res.modules })
      await this.refreshGraph()
      toast(`added ${kind} "${res.id}"`)
      return true
    } catch (e) {
      toastError(e)
      return false
    }
  }

  /** Stop and drop a module; the engine deletes every cable that used it. */
  async removeModule(kind: ModuleKind, id: string): Promise<void> {
    try {
      const res = await api.removeModule(kind, id)
      const { selectedId, armed } = this.current
      this.set({
        modules: res.modules,
        graph: res.graph,
        // the selected cable / armed jack may have gone with the module
        selectedId: res.graph.connections.some((c) => c.id === selectedId) ? selectedId : null,
        armed: armed?.startsWith(`${id}/`) ? null : armed,
      })
      const n = res.dropped
      toast(`removed ${id}${n ? ` (−${n} cable${n > 1 ? 's' : ''})` : ''}`)
    } catch (e) {
      toastError(e)
    }
  }

  // ---- patching --------------------------------------------------
  clickJack(id: string): void {
    const { portIndex, armed } = this.current
    const entry = portIndex.get(id)
    if (!entry || entry.placeholder) return

    if (entry.module.kind === 'source') {
      this.set({ armed: armed === id ? null : id })
      return
    }
    if (!armed) {
      toast('Arm a source jack first.', true)
      return
    }
    const source = portIndex.get(armed)
    void api
      .connect(armed, id)
      .then(async () => {
        const graph = await api.graph()
        this.set({ graph, armed: null, selectedId: lastConnectionBetween(graph, armed, id) })
        toast(
          source?.port.type === 'scalar' && entry.port.type === 'event'
            ? 'Patched — add a threshold / schmitt node to gate it.'
            : 'Patched.',
        )
      })
      .catch(toastError)
  }

  selectConnection(id: string | null): void {
    this.set({ selectedId: id })
  }

  // ---- inspector edits -------------------------------------------
  setChain(id: string, chain: ChainNode[]): Promise<void> {
    return this.applyPatch({ id, chain })
  }

  setEnabled(id: string, enabled: boolean): Promise<void> {
    return this.applyPatch({ id, enabled })
  }

  async deleteConnection(id: string): Promise<void> {
    try {
      await api.disconnect(id)
      this.set({ selectedId: null })
      await this.refreshGraph()
    } catch (e) {
      toastError(e)
    }
  }

  private async applyPatch(patch: ConnectionPatch): Promise<void> {
    try {
      await api.updateConnection(patch)
      await this.refreshGraph()
    } catch (e) {
      toastError(e)
    }
  }

  private async refreshGraph(): Promise<void> {
    this.set({ graph: await api.graph() })
  }
}

/** `needs source joycon, sink hid` — a one-line summary of missing requirements. */
export function needs(missing: MissingRequirement[]): string {
  return `needs ${missing.map((m) => `${m.kind} ${m.id}`).join(', ')}`
}

export const patchbay = new Patchbay()
