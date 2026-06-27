import { useState } from 'react'
import './StockSearch.css'

function StockSearch({ onSearch, loading }) {
  const [symbol, setSymbol] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    if (symbol.trim()) {
      onSearch(symbol.trim().toUpperCase())
      setSymbol('')
    }
  }

  return (
    <form className="stock-search" onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="Enter stock symbol (e.g., AAPL, GOOGL, MSFT)"
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        disabled={loading}
        className="search-input"
        maxLength="5"
      />
      <button type="submit" disabled={loading} className="search-button">
        {loading ? 'Loading...' : 'Search'}
      </button>
    </form>
  )
}

export default StockSearch
