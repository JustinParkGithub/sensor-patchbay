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
import { EMPTY_GRAPH } from '../types'
import type { ChainNode, Connection, Graph, ModuleSpec, NodeSpecs } from '../types'
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
  /** Re-read modules, presets and the graph — after any preset-level change. */
  reloadAll: () => Promise<void>
  setPresets: (presets: string[]) => void
}

const PatchbayContext = createContext<PatchbayValue | null>(null)

export function PatchbayProvider({ children }: { children: ReactNode }) {
  const { toast, toastError } = useToastHandlers()
  const { preset: livePreset } = useLiveStatus()

  const [ready, setReady] = useState(false)
  const [modules, setModules] = useState<ModuleSpec[]>([])
  const [nodeSpecs, setNodeSpecs] = useState<NodeSpecs>({})
  const [presets, setPresets] = useState<string[]>([])
  const [presetName, setPresetName] = useState('')
  const [graph, setGraph] = useState<Graph>(EMPTY_GRAPH)
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
      portIndex,
      wired,
      armed,
      compatible,
      selected,
      clickJack,
      setChain,
      setEnabled,
      deleteConnection,
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
