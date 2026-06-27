import { useState, useEffect } from 'react'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js'
import './StockCard.css'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
)

function StockCard({ stock, onRemove }) {
  const [stockData, setStockData] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [news, setNews] = useState([])
  const [period, setPeriod] = useState('1mo')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchStockData()
  }, [stock.ticker])

  useEffect(() => {
    fetchHistory()
  }, [period, stock.ticker])

  const fetchStockData = async () => {
    try {
      const [stockRes, analysisRes, newsRes] = await Promise.all([
        fetch(`http://localhost:8000/api/stock/${stock.ticker}`),
        fetch(`http://localhost:8000/api/stock/${stock.ticker}/analysis`),
        fetch(`http://localhost:8000/api/stock/${stock.ticker}/news`)
      ])

      const stockInfo = await stockRes.json()
      const analysisInfo = await analysisRes.json()
      const newsInfo = await newsRes.json()

      setStockData(stockInfo)
      setAnalysis(analysisInfo)
      setNews(newsInfo.news || [])
      setLoading(false)
    } catch (error) {
      console.error('Error fetching stock data:', error)
      setLoading(false)
    }
  }

  const fetchHistory = async () => {
    try {
      const res = await fetch(`http://localhost:8000/api/stock/${stock.ticker}/history?period=${period}`)
      const data = await res.json()
      setStockData(prev => ({
        ...prev,
        historyDates: data.dates,
        historyPrices: data.prices
      }))
    } catch (error) {
      console.error('Error fetching history:', error)
    }
  }

  if (loading || !stockData || !analysis) {
    return <div className="stock-card loading">Loading...</div>
  }

  const isPositive = (analysis.dayTrade.intradayChangePercent || 0) >= 0
  const chartData = {
    labels: stockData.historyDates || [],
    datasets: [{
      label: `${stock.ticker} Price`,
      data: stockData.historyPrices || [],
      borderColor: isPositive ? '#10b981' : '#ef4444',
      backgroundColor: isPositive ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
      tension: 0.1,
      fill: true
    }]
  }

  return (
    <div className="stock-card">
      <div className="stock-card-header">
        <div>
          <h3>{stock.ticker}</h3>
          <p className="company-name">{stock.name}</p>
        </div>
        <button className="remove-btn" onClick={() => onRemove()}>×</button>
      </div>

      <div className="stock-price-section">
        <div className="current-price">${analysis.dayTrade.currentPrice?.toFixed(2) || 'N/A'}</div>
        <div className={`price-change ${isPositive ? 'positive' : 'negative'}`}>
          {isPositive ? '▲' : '▼'} {Math.abs(analysis.dayTrade.intradayChange || 0).toFixed(2)} ({analysis.dayTrade.intradayChangePercent?.toFixed(2) || 0}%)
        </div>
      </div>

      <div className="chart-section">
        <div className="period-buttons">
          {['1d', '5d', '1mo', '3mo', '6mo', '1y'].map(p => (
            <button 
              key={p} 
              className={`period-btn ${period === p ? 'active' : ''}`}
              onClick={() => setPeriod(p)}
            >
              {p}
            </button>
          ))}
        </div>
        <div className="chart-container">
          <Line data={chartData} options={{
            responsive: true,
            maintainAspectRatio: true,
            plugins: { legend: { display: false } }
          }} />
        </div>
      </div>

      <div className="analysis-section">
        <div className="analysis-column">
          <h4>Day Trade</h4>
          <div className="kpi-grid">
            <div className="kpi">
              <span className="label">Open</span>
              <span className="value">${analysis.dayTrade.open?.toFixed(2) || 'N/A'}</span>
            </div>
            <div className="kpi">
              <span className="label">High</span>
              <span className="value">${analysis.dayTrade.dayHigh?.toFixed(2) || 'N/A'}</span>
            </div>
            <div className="kpi">
              <span className="label">Low</span>
              <span className="value">${analysis.dayTrade.dayLow?.toFixed(2) || 'N/A'}</span>
            </div>
            <div className="kpi">
              <span className="label">Prev Close</span>
              <span className="value">${analysis.dayTrade.previousClose?.toFixed(2) || 'N/A'}</span>
            </div>
            <div className="kpi">
              <span className="label">Volume</span>
              <span className="value">{(analysis.dayTrade.currentVolume / 1e6)?.toFixed(2) || 'N/A'}M</span>
            </div>
            <div className="kpi">
              <span className="label">Vol Ratio</span>
              <span className="value">{analysis.dayTrade.volumeRatio?.toFixed(2) || 'N/A'}%</span>
            </div>
          </div>
        </div>

        <div className="analysis-column">
          <h4>Long Term</h4>
          <div className="kpi-grid">
            <div className="kpi">
              <span className="label">P/E Ratio</span>
              <span className="value">{analysis.longTerm.pe?.toFixed(2) || 'N/A'}</span>
            </div>
            <div className="kpi">
              <span className="label">52W High</span>
              <span className="value">${analysis.longTerm['52WeekHigh']?.toFixed(2) || 'N/A'}</span>
            </div>
            <div className="kpi">
              <span className="label">52W Low</span>
              <span className="value">${analysis.longTerm['52WeekLow']?.toFixed(2) || 'N/A'}</span>
            </div>
            <div className="kpi">
              <span className="label">Div Yield</span>
              <span className="value">{analysis.longTerm.dividendYield?.toFixed(2) || 'N/A'}%</span>
            </div>
            <div className="kpi">
              <span className="label">Target Price</span>
              <span className="value">${analysis.longTerm.targetPrice?.toFixed(2) || 'N/A'}</span>
            </div>
            <div className="kpi">
              <span className="label">YTD Change</span>
              <span className="value">{analysis.longTerm.ytdChange?.toFixed(2) || 'N/A'}%</span>
            </div>
          </div>
        </div>
      </div>

      <div className="news-section">
        <h4>News</h4>
        <div className="news-list">
          {news.length > 0 ? news.map((item, idx) => (
            <a key={idx} href={item.link} target="_blank" rel="noreferrer" className="news-item">
              <div className="news-title">{item.title}</div>
              <div className="news-meta">{item.publisher} • {item.publishDate}</div>
            </a>
          )) : <p className="no-news">No news available</p>}
        </div>
      </div>
    </div>
  )
}

export default StockCard
