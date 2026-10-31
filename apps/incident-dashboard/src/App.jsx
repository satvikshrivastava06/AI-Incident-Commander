import { useState, useEffect } from 'react'
import ServiceMap from './ServiceMap.jsx'

const INCIDENT_ENGINE_URL = 'http://localhost:8007'
const API_KEY = import.meta.env.VITE_API_KEY

const SEVERITY_COLORS = {
  critical: '#dc2626',
  high: '#f97316',
  medium: '#eab308',
  low: '#65a30d',
}

function AccuracyPanel() {
  const [accuracy, setAccuracy] = useState(null)

  useEffect(() => {
    async function fetchAccuracy() {
      try {
        const response = await fetch(`${INCIDENT_ENGINE_URL}/accuracy`, {
          headers: { 'X-API-Key': API_KEY },
        })
        if (response.ok) {
          setAccuracy(await response.json())
        }
      } catch { /* silently ignore when engine is down */ }
    }
    fetchAccuracy()
    const id = setInterval(fetchAccuracy, 10000)
    return () => clearInterval(id)
  }, [])

  if (!accuracy) return null

  return (
    <div style={{
      border: '1px solid #e5e7eb', borderRadius: 8, padding: 16,
      marginBottom: 24, display: 'flex', gap: 32
    }}>
      <div>
        <div style={{ color: '#6b7280', fontSize: 12 }}>Total Predictions</div>
        <div style={{ fontSize: 24, fontWeight: 700 }}>{accuracy.total_predictions}</div>
      </div>
      <div>
        <div style={{ color: '#6b7280', fontSize: 12 }}>Correct</div>
        <div style={{ fontSize: 24, fontWeight: 700 }}>{accuracy.correct_predictions}</div>
      </div>
      <div>
        <div style={{ color: '#6b7280', fontSize: 12 }}>Accuracy</div>
        <div style={{ fontSize: 24, fontWeight: 700 }}>
          {accuracy.accuracy != null ? `${(accuracy.accuracy * 100).toFixed(1)}%` : 'N/A'}
        </div>
      </div>
    </div>
  )
}

function IncidentRow({ incident }) {
  const color = SEVERITY_COLORS[incident.severity] || '#6b7280'
  return (
    <tr>
      <td style={{ padding: '8px 12px' }}>
        <span style={{
          display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
          backgroundColor: color, marginRight: 8
        }} />
        {incident.severity}
      </td>
      <td style={{ padding: '8px 12px', fontWeight: 600 }}>{incident.service_name}</td>
      <td style={{ padding: '8px 12px' }}>{incident.title}</td>
      <td style={{ padding: '8px 12px' }}>{incident.status}</td>
      <td style={{ padding: '8px 12px', color: '#6b7280' }}>
        {new Date(incident.detected_at).toLocaleString()}
      </td>
    </tr>
  )
}

function App() {
  const [incidents, setIncidents] = useState([])
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  useEffect(() => {
    async function fetchIncidents() {
      try {
        // CHANGED: now sends X-API-Key.
        const response = await fetch(`${INCIDENT_ENGINE_URL}/incidents`, {
          headers: { 'X-API-Key': API_KEY },
        })
        if (!response.ok) {
          throw new Error(`Incident Engine returned ${response.status}`)
        }
        const data = await response.json()
        setIncidents(data)
        setError(null)
        setLastUpdated(new Date())
      } catch (err) {
        setError(err.message)
      }
    }

    fetchIncidents()
    const intervalId = setInterval(fetchIncidents, 5000)
    return () => clearInterval(intervalId)
  }, [])

  return (
    <div style={{ fontFamily: 'sans-serif', maxWidth: 900, margin: '40px auto', padding: '0 16px' }}>
      <h1>AI Incident Commander</h1>
      <p style={{ color: '#6b7280' }}>
        {lastUpdated ? `Last updated ${lastUpdated.toLocaleTimeString()}` : 'Loading...'}
      </p>

      {error && (
        <div style={{ color: '#dc2626', marginBottom: 16 }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      <AccuracyPanel />

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ textAlign: 'left', borderBottom: '2px solid #e5e7eb' }}>
            <th style={{ padding: '8px 12px' }}>Severity</th>
            <th style={{ padding: '8px 12px' }}>Service</th>
            <th style={{ padding: '8px 12px' }}>Title</th>
            <th style={{ padding: '8px 12px' }}>Status</th>
            <th style={{ padding: '8px 12px' }}>Detected</th>
          </tr>
        </thead>
        <tbody>
          {incidents.length === 0 && !error && (
            <tr><td colSpan={5} style={{ padding: 16, color: '#6b7280' }}>No incidents yet.</td></tr>
          )}
          {incidents.map(incident => (
            <IncidentRow key={incident.id} incident={incident} />
          ))}
        </tbody>
      </table>

      <div style={{ marginTop: 40 }}>
        <ServiceMap />
      </div>
    </div>
  )
}

export default App