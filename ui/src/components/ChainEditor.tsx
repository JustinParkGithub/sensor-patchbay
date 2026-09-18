import { useEffect, useMemo, useState } from 'react'
import { ParamField } from './ParamField'
import { usePatchbay } from '../state/PatchbayProvider'
import { isChoiceSpec } from '../types'
import type { ChainNode, Connection, NodeSpec, ParamValue } from '../types'

/** The default parameter set the engine would use for a freshly added node. */
function defaultParams(spec: NodeSpec): Record<string, ParamValue> {
  return Object.fromEntries(
    Object.entries(spec).map(([key, param]) => [
      key,
      isChoiceSpec(param) ? (param.choices[0] ?? '') : param[0],
    ]),
  )
}

/**
 * The transform chain on one cable: source → node → node → sink.
 *
 * Every edit rewrites the whole chain and PUTs it, which the engine applies on
 * its next tick — no restart, no reconnect.
 */
export function ChainEditor({ connection }: { connection: Connection }) {
  const { nodeSpecs, setChain } = usePatchbay()
  const types = useMemo(() => Object.keys(nodeSpecs), [nodeSpecs])
  const [newType, setNewType] = useState('')

  useEffect(() => {
    setNewType((current) => (current && types.includes(current) ? current : (types[0] ?? '')))
  }, [types])

  const replace = (chain: ChainNode[]) => void setChain(connection.id, chain)

  const updateNode = (index: number, node: ChainNode) =>
    replace(connection.chain.map((existing, i) => (i === index ? node : existing)))

  const removeNode = (index: number) =>
    replace(connection.chain.filter((_, i) => i !== index))

  const moveNode = (index: number, delta: number) => {
    const target = index + delta
    if (target < 0 || target >= connection.chain.length) return
    const chain = [...connection.chain]
    const [a, b] = [chain[index]!, chain[target]!]
    chain[index] = b
    chain[target] = a
    replace(chain)
  }

  const addNode = () => {
    const spec = nodeSpecs[newType]
    if (!spec) return
    replace([...connection.chain, { type: newType, params: defaultParams(spec) }])
  }

  return (
    <div className="chain-wrap">
      <div className="chain-label">
        transform chain <span>source → … → sink</span>
      </div>
      <div id="chainList">
        {connection.chain.length === 0 ? (
          <div className="node empty">pass-through — no transform</div>
        ) : (
          connection.chain.map((node, index) => (
            <ChainNodeCard
              key={index}
              node={node}
              spec={nodeSpecs[node.type] ?? {}}
              onChange={(next) => updateNode(index, next)}
              onMove={(delta) => moveNode(index, delta)}
              onRemove={() => removeNode(index)}
            />
          ))
        )}
      </div>
      <div className="chain-add">
        <select id="nodeType" value={newType} onChange={(e) => setNewType(e.target.value)}>
          {types.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        <button id="addNode" type="button" onClick={addNode}>
          + add node
        </button>
      </div>
    </div>
  )
}

function ChainNodeCard({
  node,
  spec,
  onChange,
  onMove,
  onRemove,
}: {
  node: ChainNode
  spec: NodeSpec
  onChange: (node: ChainNode) => void
  onMove: (delta: number) => void
  onRemove: () => void
}) {
  const params = Object.entries(spec)

  return (
    <div className="node">
      <div className="nh">
        <span className="nt">{node.type}</span>
        <span className="nord">
          <button type="button" onClick={() => onMove(-1)}>
            ↑
          </button>
          <button type="button" onClick={() => onMove(+1)}>
            ↓
          </button>
          <button type="button" onClick={onRemove}>
            ✕
          </button>
        </span>
      </div>
      {params.length > 0 && (
        <div className="params">
          {params.map(([name, paramSpec]) => (
            <ParamField
              key={name}
              name={name}
              spec={paramSpec}
              value={node.params[name]}
              onCommit={(value) =>
                onChange({ ...node, params: { ...node.params, [name]: value } })
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}
