/**
 * Everything the patch panel edits: the module list, the routing graph, and the
 * two bits of transient UI state that drive patching (which source jack is
 * armed, which cable is selected).
 *
 * The engine is the single source of truth — every mutation is a REST call
 * followed by a re-read of `/api/graph`, so the UI can never drift from what is
 * actually running.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { api, errorMessage } from '../lib/api'
import type { ConnectionPatch } from '../lib/api'
import {
  buildPortIndex,
  compatibleSinks,
  lastConnectionBetween,
  wiredPorts,
} from '../lib/ports'
import type { PortEntry } from '../lib/ports'
import { EMPTY_CATALOG, EMPTY_GRAPH } from '../types'
import type {
  ChainNode,
  Connection,
  Graph,
  ModuleKind,
  ModuleSpec,
  NodeSpecs,
  PluginCatalog,
} from '../types'
import { useLiveStatus } from './LiveProvider'
import { useToastHandlers } from './ToastProvider'

interface PatchbayValue {
  /** False until the first `/api/state` + `/api/graph` pair has landed. */
  ready: boolean
  modules: ModuleSpec[]
  nodeSpecs: NodeSpecs
  presets: string[]
  presetName: string
  graph: Graph
  /** Every registered plugin type, for the add-source / add-sink pickers. */
  plugins: PluginCatalog

  portIndex: Map<string, PortEntry>
  wired: Set<string>
  armed: string | null
  /** Sink jacks the armed source may legally drive. */
  compatible: Set<string>
  selected: Connection | null

  clickJack: (id: string) => void
  selectConnection: (id: string | null) => void
  setChain: (id: string, chain: ChainNode[]) => Promise<void>
  setEnabled: (id: string, enabled: boolean) => Promise<void>
  deleteConnection: (id: string) => Promise<void>
  /** Instantiate a plugin type live; resolves false if the engine refused. */
  addModule: (kind: ModuleKind, type: string, args: Record<string, unknown>) => Promise<boolean>
  /** Stop and drop a module; the engine deletes every cable that used it. */
  removeModule: (kind: ModuleKind, id: string) => Promise<void>
  /** Re-read modules, presets and the graph — after any preset-level change. */
  reloadAll: () => Promise<void>
  setPresets: (presets: string[]) => void
}

const PatchbayContext = createContext<PatchbayValue | null>(null)

export function PatchbayProvider({ children }: { children: ReactNode }) {
  const { toast, toastError } = useToastHandlers()
  const { preset: livePreset, modRev } = useLiveStatus()

  const [ready, setReady] = useState(false)
  const [modules, setModules] = useState<ModuleSpec[]>([])
  const [nodeSpecs, setNodeSpecs] = useState<NodeSpecs>({})
  const [presets, setPresets] = useState<string[]>([])
  const [presetName, setPresetName] = useState('')
  const [graph, setGraph] = useState<Graph>(EMPTY_GRAPH)
  const [plugins, setPlugins] = useState<PluginCatalog>(EMPTY_CATALOG)
  const [armed, setArmed] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const portIndex = useMemo(() => buildPortIndex(modules), [modules])
  const wired = useMemo(() => wiredPorts(graph), [graph])
  const compatible = useMemo(() => compatibleSinks(portIndex, armed), [portIndex, armed])
  const selected = useMemo(
    () => graph.connections.find((c) => c.id === selectedId) ?? null,
    [graph, selectedId],
  )

  const refreshGraph = useCallback(async () => {
    setGraph(await api.graph())
  }, [])

  const reloadAll = useCallback(async () => {
    const [state, nextGraph] = await Promise.all([api.state(), api.graph()])
    setModules(state.modules)
    setPresets(state.presets)
    setPresetName(state.preset)
    setPlugins(state.plugins)
    setGraph(nextGraph)
    setSelectedId(null)
    setArmed(null)
  }, [])

  // ---- boot ------------------------------------------------------
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [state, nextGraph] = await Promise.all([api.state(), api.graph()])
        if (cancelled) return
        setModules(state.modules)
        setNodeSpecs(state.nodes)
        setPresets(state.presets)
        setPresetName(state.preset)
        setPlugins(state.plugins)
        setGraph(nextGraph)
        setReady(true)
      } catch (e) {
        if (!cancelled) toast(`startup: ${errorMessage(e)}`, true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [toast])

  // ---- preset changed behind our back ----------------------------
  // e.g. joycon/btn.home -> sys/preset.cycle walks through the preset files.
  useEffect(() => {
    if (!ready || !livePreset || livePreset === presetName) return
    let cancelled = false
    void (async () => {
      try {
        const [state, nextGraph] = await Promise.all([api.state(), api.graph()])
        if (cancelled) return
        setModules(state.modules)
        setPresets(state.presets)
        setPresetName(state.preset)
        setPlugins(state.plugins)
        setGraph(nextGraph)
        toast(`preset → ${state.preset}`)
      } catch (e) {
        if (!cancelled) toastError(e)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [ready, livePreset, presetName, toast, toastError])

  // ---- modules added / removed behind our back -------------------
  // another tab, or the --cli console. Our own add/remove bumps it too; the
  // re-read is cheap and keeps every client converging on the same view.
  useEffect(() => {
    if (!ready || !modRev) return
    let cancelled = false
    void (async () => {
      try {
        const [state, nextGraph] = await Promise.all([api.state(), api.graph()])
        if (cancelled) return
        setModules(state.modules)
        setPlugins(state.plugins)
        setGraph(nextGraph)
      } catch (e) {
        if (!cancelled) toastError(e)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [ready, modRev, toastError])

  const addModule = useCallback(
    async (kind: ModuleKind, type: string, args: Record<string, unknown>) => {
      try {
        const res = await api.addModule(kind, type, args)
        setModules(res.modules)
        await refreshGraph()
        toast(`added ${kind} "${res.id}"`)
        return true
      } catch (e) {
        toastError(e)
        return false
      }
    },
    [refreshGraph, toast, toastError],
  )

  const removeModule = useCallback(
    async (kind: ModuleKind, id: string) => {
      try {
        const res = await api.removeModule(kind, id)
        setModules(res.modules)
        setGraph(res.graph)
        // the selected cable / armed jack may have gone with the module
        setSelectedId((cur) => (res.graph.connections.some((c) => c.id === cur) ? cur : null))
        setArmed((cur) => (cur?.startsWith(`${id}/`) ? null : cur))
        const n = res.dropped
        toast(`removed ${id}${n ? ` (−${n} cable${n > 1 ? 's' : ''})` : ''}`)
      } catch (e) {
        toastError(e)
      }
    },
    [toast, toastError],
  )

  // ---- patching --------------------------------------------------
  const clickJack = useCallback(
    (id: string) => {
      const entry = portIndex.get(id)
      if (!entry || entry.placeholder) return

      if (entry.module.kind === 'source') {
        setArmed((current) => (current === id ? null : id))
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
          const nextGraph = await api.graph()
          setGraph(nextGraph)
          setArmed(null)
          toast(
            source?.port.type === 'scalar' && entry.port.type === 'event'
              ? 'Patched — add a threshold / schmitt node to gate it.'
              : 'Patched.',
          )
          setSelectedId(lastConnectionBetween(nextGraph, armed, id))
        })
        .catch(toastError)
    },
    [portIndex, armed, toast, toastError],
  )

  // ---- inspector edits -------------------------------------------
  const applyPatch = useCallback(
    async (patch: ConnectionPatch) => {
      try {
        await api.updateConnection(patch)
        await refreshGraph()
      } catch (e) {
        toastError(e)
      }
    },
    [refreshGraph, toastError],
  )

  const setChain = useCallback(
    (id: string, chain: ChainNode[]) => applyPatch({ id, chain }),
    [applyPatch],
  )
  const setEnabled = useCallback(
    (id: string, enabled: boolean) => applyPatch({ id, enabled }),
    [applyPatch],
  )

  const deleteConnection = useCallback(
    async (id: string) => {
      try {
        await api.disconnect(id)
        setSelectedId(null)
        await refreshGraph()
      } catch (e) {
        toastError(e)
      }
    },
    [refreshGraph, toastError],
  )

  const value = useMemo<PatchbayValue>(
    () => ({
      ready,
      modules,
      nodeSpecs,
      presets,
      presetName,
      graph,
      plugins,
      portIndex,
      wired,
      armed,
      compatible,
      selected,
      clickJack,
      selectConnection: setSelectedId,
      setChain,
      setEnabled,
      deleteConnection,
      addModule,
      removeModule,
      reloadAll,
      setPresets,
    }),
    [
      ready,
      modules,
      nodeSpecs,
      presets,
      presetName,
      graph,
      plugins,
      portIndex,
      wired,
      armed,
      compatible,
      selected,
      clickJack,
      setChain,
      setEnabled,
      deleteConnection,
      addModule,
      removeModule,
      reloadAll,
    ],
  )

  return <PatchbayContext.Provider value={value}>{children}</PatchbayContext.Provider>
}

export function usePatchbay(): PatchbayValue {
  const value = useContext(PatchbayContext)
  if (!value) throw new Error('usePatchbay must be used inside <PatchbayProvider>')
  return value
}
