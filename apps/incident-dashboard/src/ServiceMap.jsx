import { useState, useEffect } from 'react'

const DEPENDENCY_GRAPH_URL = 'http://localhost:8006'
const INCIDENT_ENGINE_URL = 'http://localhost:8007'
const ROOTCAUSE_ENGINE_URL = 'http://localhost:8008'
const API_KEY = import.meta.env.VITE_API_KEY
const AUTH_HEADERS = { 'X-API-Key': API_KEY }

const IMPLICATION_THRESHOLD = 0.5

const WIDTH = 600
const HEIGHT = 500
const CENTER_X = WIDTH / 2
const CENTER_Y = HEIGHT / 2
const RADIUS = 180
const NODE_RADIUS = 28

function computeNodePositions(nodeNames) {
  const positions = {}
  const n = nodeNames.length || 1
  nodeNames.forEach((name, i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2
    positions[name] = {
      x: CENTER_X + RADIUS * Math.cos(angle),
      y: CENTER_Y + RADIUS * Math.sin(angle),
    }
  })
  return positions
}

function ServiceMap() {
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [implicated, setImplicated] = useState({})
  const [error, setError] = useState(null)

  useEffect(() => {
    async function fetchMapData() {
      try {
        // CHANGED: every fetch below now sends AUTH_HEADERS.
        const graphResponse = await fetch(`${DEPENDENCY_GRAPH_URL}/graph`, { headers: AUTH_HEADERS })
        if (!graphResponse.ok) throw new Error(`Dependency Graph returned ${graphResponse.status}`)
        const graphData = await graphResponse.json()
        setGraph(graphData)

        const openIncidentsResponse = await fetch(
          `${INCIDENT_ENGINE_URL}/incidents?status=open`, { headers: AUTH_HEADERS }
        )
        if (!openIncidentsResponse.ok) throw new Error(`Incident Engine returned ${openIncidentsResponse.status}`)
        const openIncidents = await openIncidentsResponse.json()

        const implicatedMap = {}
        for (const incident of openIncidents) {
          const rootcauseResponse = await fetch(`${ROOTCAUSE_ENGINE_URL}/rootcause/${incident.id}`, {
            method: 'POST',
            headers: AUTH_HEADERS,
          })
          if (!rootcauseResponse.ok) continue
          const rootcauseData = await rootcauseResponse.json()

          for (const cause of rootcauseData.probable_causes) {
            if (cause.probability >= IMPLICATION_THRESHOLD) {
              const existing = implicatedMap[cause.service_name] || []
              implicatedMap[cause.service_name] = [
                ...existing,
                `${incident.title}: ${cause.reasons.join('; ')} (p=${cause.probability})`,
              ]
            }
          }
        }
        setImplicated(implicatedMap)
        setError(null)
      } catch (err) {
        setError(err.message)
      }
    }

    fetchMapData()
    const intervalId = setInterval(fetchMapData, 10000)
    return () => clearInterval(intervalId)
  }, [])

  const positions = computeNodePositions(graph.nodes.map(n => n.id))

  return (
    <div>
      <h2>Service Map</h2>
      {error && (
        <div style={{ color: '#dc2626', marginBottom: 8 }}>
          <strong>Error:</strong> {error}
        </div>
      )}
      <svg width={WIDTH} height={HEIGHT} style={{ border: '1px solid #e5e7eb', borderRadius: 8 }}>
        <defs>
          <marker id="arrowhead" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L0,6 L9,3 z" fill="#9ca3af" />
          </marker>
        </defs>

        {graph.edges.map((edge, i) => {
          const from = positions[edge.source]
          const to = positions[edge.target]
          if (!from || !to) return null

          const dx = to.x - from.x
          const dy = to.y - from.y
          const distance = Math.sqrt(dx * dx + dy * dy) || 1
          const shortenBy = NODE_RADIUS + 4
          const endX = to.x - (dx / distance) * shortenBy
          const endY = to.y - (dy / distance) * shortenBy

          return (
            <line
              key={`edge-${i}`}
              x1={from.x} y1={from.y} x2={endX} y2={endY}
              stroke="#9ca3af"
              strokeWidth={Math.min(1 + edge.call_count / 10, 5)}
              markerEnd="url(#arrowhead)"
            >
              <title>{edge.source} → {edge.target}: {edge.call_count} calls, avg {edge.avg_latency_ms}ms</title>
            </line>
          )
        })}

        {graph.nodes.map(node => {
          const pos = positions[node.id]
          if (!pos) return null
          const isImplicated = Boolean(implicated[node.id])

          return (
            <g key={node.id}>
              <circle
                cx={pos.x} cy={pos.y} r={NODE_RADIUS}
                fill={isImplicated ? '#dc2626' : '#3b82f6'}
                stroke={isImplicated ? '#7f1d1d' : '#1e3a8a'}
                strokeWidth={2}
              >
                <title>
                  {node.id}
                  {isImplicated ? `\n\nIMPLICATED:\n${implicated[node.id].join('\n')}` : ''}
                </title>
              </circle>
              <text
                x={pos.x} y={pos.y} textAnchor="middle" dominantBaseline="middle"
                fontSize={10} fill="white" style={{ pointerEvents: 'none' }}
              >
                {node.id.length > 12 ? node.id.slice(0, 10) + '…' : node.id}
              </text>
            </g>
          )
        })}
      </svg>
      <p style={{ fontSize: 13, color: '#6b7280' }}>
        <span style={{ color: '#dc2626' }}>●</span> implicated in an open incident &nbsp;&nbsp;
        <span style={{ color: '#3b82f6' }}>●</span> normal &nbsp;&nbsp;
        Hover a node or edge for details.
      </p>
    </div>
  )
}

export default ServiceMap