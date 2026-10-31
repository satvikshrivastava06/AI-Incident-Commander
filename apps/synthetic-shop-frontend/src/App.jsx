import { useState } from 'react'

// The gateway is the ONLY backend address the frontend needs to know
// about -- it doesn't talk to auth/payment/inventory/recommendation
// directly. That's the whole point of the gateway pattern from Step 1.9.
const GATEWAY_URL = 'http://localhost:8005'

function App() {
  // useState gives this component "memory" that persists between
  // re-renders. Each call returns a [currentValue, setterFunction] pair.
  // Calling the setter triggers React to re-render with the new value.
  const [username, setUsername] = useState('demo_user')
  const [password, setPassword] = useState('demo_pass')
  const [itemId, setItemId] = useState('item_001')
  const [amount, setAmount] = useState(49.99)

  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [isLoading, setIsLoading] = useState(false)

  const handleCheckout = async () => {
    // Reset state before starting a new request, so old results/errors
    // don't linger on screen while a new checkout is in flight.
    setIsLoading(true)
    setError(null)
    setResult(null)

    try {
      const response = await fetch(`${GATEWAY_URL}/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          password,
          item_id: itemId,
          amount: Number(amount)
        })
      })

      if (!response.ok) {
        const errorBody = await response.json()
        throw new Error(errorBody.detail || `Request failed with status ${response.status}`)
      }

      const data = await response.json()
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div style={{ fontFamily: 'sans-serif', maxWidth: 480, margin: '40px auto' }}>
      <h1>Synthetic Shop</h1>
      <p>This is a fake storefront used to generate realistic traffic against our synthetic e-commerce system.</p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} style={{ width: '100%' }} />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ width: '100%' }}
          />
        </label>
        <label>
          Item ID
          <input value={itemId} onChange={(e) => setItemId(e.target.value)} style={{ width: '100%' }} />
        </label>
        <label>
          Amount ($)
          <input
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            style={{ width: '100%' }}
          />
        </label>
      </div>

      <button onClick={handleCheckout} disabled={isLoading}>
        {isLoading ? 'Processing...' : 'Checkout'}
      </button>

      {error && (
        <div style={{ color: 'red', marginTop: 16 }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {result && (
        <pre style={{ background: '#f4f4f4', padding: 12, marginTop: 16, overflowX: 'auto' }}>
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  )
}

export default App