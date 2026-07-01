import { useState, useEffect } from 'react'
import { API_BASE_URL } from '../api';
import axios from 'axios'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js'
import './StockChart.css'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
)

const API_BASE_URL = API_BASE_URL

function StockChart({ symbol }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('3mo')

  useEffect(() => {
    const fetchHistory = async () => {
      setLoading(true)
      try {
        const response = await axios.get(`${API_BASE_URL}/stock/${symbol}/history?period=${period}`)
        const history = response.data

        const labels = history.map(h => h.date)
        const prices = history.map(h => h.close)

        setData({
          labels,
          datasets: [
            {
              label: `${symbol} Price`,
              data: prices,
              borderColor: '#667eea',
              backgroundColor: 'rgba(102, 126, 234, 0.1)',
              borderWidth: 2,
              tension: 0.1,
              fill: true,
              pointRadius: 0,
              pointHoverRadius: 6,
            }
          ]
        })
      } catch (err) {
        console.error('Error fetching chart data:', err)
      } finally {
        setLoading(false)
      }
    }

    fetchHistory()
  }, [symbol, period])

  if (loading) {
    return <div className="chart-loading">Loading chart data...</div>
  }

  if (!data) {
    return <div className="chart-error">Unable to load chart data</div>
  }

  return (
    <div className="stock-chart">
      <div className="chart-controls">
        <button 
          className={period === '1mo' ? 'active' : ''} 
          onClick={() => setPeriod('1mo')}
        >
          1M
        </button>
        <button 
          className={period === '3mo' ? 'active' : ''} 
          onClick={() => setPeriod('3mo')}
        >
          3M
        </button>
        <button 
          className={period === '6mo' ? 'active' : ''} 
          onClick={() => setPeriod('6mo')}
        >
          6M
        </button>
        <button 
          className={period === '1y' ? 'active' : ''} 
          onClick={() => setPeriod('1y')}
        >
          1Y
        </button>
      </div>
      <div className="chart-container">
        <Line data={data} options={{
          responsive: true,
          maintainAspectRatio: true,
          plugins: {
            legend: {
              display: true,
              position: 'top'
            }
          },
          scales: {
            y: {
              beginAtZero: false
            }
          }
        }} />
      </div>
    </div>
  )
}

export default StockChart
