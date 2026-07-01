import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from '../api';
import axios from 'axios';
import '../styles/theme.css';


const avatarColorMap = {
  MU: 'teal',
  WDC: 'amber',
  AVGO: 'purple',
  NVDA: 'blue',
  TSLA: 'teal',
  AAPL: 'amber',
  MSFT: 'purple',
  GOOGL: 'blue',
};

const getAvatarColor = (symbol) => {
  if (avatarColorMap[symbol]) return avatarColorMap[symbol];
  const hash = symbol.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
  const colors = ['teal', 'amber', 'purple', 'blue'];
  return colors[hash % colors.length];
};

/**
 * Dashboard - Main homepage showing a grid of all watchlist companies
 * with live price/change. Click a card to open the detail view.
 */
const Dashboard = ({ onViewDetails }) => {
  const [quotes, setQuotes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchDashboard = async () => {
    try {
      const watchlistRes = await axios.get(`${API_BASE_URL}/watchlist`);
      const watchlist = watchlistRes.data?.watchlist || [];

      const results = await Promise.all(
        watchlist.map(async (entry) => {
          try {
            const res = await axios.get(`${API_BASE_URL}/stock/${entry.ticker}`);
            return { ...entry, ...res.data };
          } catch {
            return { ...entry, symbol: entry.ticker, error: true };
          }
        })
      );

      setQuotes(results);
      setError(null);
    } catch (err) {
      console.error('Error fetching dashboard:', err);
      setError('Could not load watchlist. Please check if backend is running.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 60000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-secondary)' }}>
        Loading watchlist...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-secondary)' }}>
        {error}
      </div>
    );
  }

  return (
    <div>
      <div className="section-header">
        <h2>Dashboard</h2>
        <p>{quotes.length} companies in your watchlist</p>
      </div>

      <div className="dashboard-grid">
        {quotes.map((stock) => {
          const isPositive = (stock.changePercent || 0) >= 0;
          return (
            <div
              key={stock.ticker}
              className="card dashboard-card"
              onClick={() => onViewDetails(stock.ticker)}
            >
              <div className="company">
                <div className={`avatar ${getAvatarColor(stock.ticker)}`}>
                  {stock.ticker.slice(0, 4)}
                </div>
                <div>
                  <p className="company-name">{stock.ticker}</p>
                  <p className="company-meta">{stock.name || stock.ticker}</p>
                </div>
              </div>

              <div className="dashboard-card-footer">
                <span className="price">
                  {stock.error ? 'N/A' : `$${stock.price?.toFixed(2)}`}
                </span>
                {!stock.error && (
                  <span className={`change-pill ${isPositive ? 'up' : 'down'}`}>
                    {isPositive ? '▲' : '▼'} {Math.abs(stock.changePercent || 0).toFixed(2)}%
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default Dashboard;
