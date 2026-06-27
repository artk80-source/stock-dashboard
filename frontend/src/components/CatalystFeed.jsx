import React, { useState, useEffect } from 'react';
import axios from 'axios';
import CatalystCard from './CatalystCard';
import '../styles/theme.css';

/**
 * CatalystFeed - Displays catalyst feed with live indicator
 * Polls /api/catalysts endpoint every 60 seconds
 * Shows header with live dot and last update time
 */
const CatalystFeed = ({ onViewDetails, onTrackStock }) => {
  const [catalysts, setCatalysts] = useState([]);
  const [isConnected, setIsConnected] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(new Date());
  const [selectedFilter, setSelectedFilter] = useState('all');
  const [loading, setLoading] = useState(true);

  // Map for avatar colors - consistent per ticker
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
    if (avatarColorMap[symbol]) {
      return avatarColorMap[symbol];
    }
    // Generate consistent color based on symbol hash
    const hash = symbol.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
    const colors = ['teal', 'amber', 'purple', 'blue'];
    return colors[hash % colors.length];
  };

  // Fetch catalysts from backend
  const fetchCatalysts = async () => {
    try {
      const response = await axios.get('http://localhost:8000/api/catalysts', {
        params: {
          lookback_hours: 24,
          min_sentiment: 0.3,
          limit: 20,
        },
      });

      const data = response.data?.data || [];
      setCatalysts(data);
      setIsConnected(true);
      setLastUpdated(new Date());
    } catch (error) {
      console.error('Error fetching catalysts:', error);
      setIsConnected(false);
      // Keep existing catalysts on error
    } finally {
      setLoading(false);
    }
  };

  // Initial fetch and set up polling
  useEffect(() => {
    fetchCatalysts();
    const interval = setInterval(fetchCatalysts, 60000); // Poll every 60s

    return () => clearInterval(interval);
  }, []);

  // Format time ago string
  const formatTimeAgo = () => {
    const now = new Date();
    const diff = now - lastUpdated;
    const minutes = Math.floor(diff / 60000);

    if (minutes === 0) return 'just now';
    if (minutes === 1) return '1m ago';
    if (minutes < 60) return `${minutes}m ago`;

    const hours = Math.floor(minutes / 60);
    if (hours === 1) return '1h ago';
    return `${hours}h ago`;
  };

  // Format last update time HH:MM
  const formatUpdateTime = () => {
    return lastUpdated.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  };

  const filters = ['All', 'Earnings', 'Upgrades', 'M&A', 'FDA'];

  const filteredCatalysts = selectedFilter === 'all'
    ? catalysts
    : catalysts.filter((c) => (c.category || '').toLowerCase() === selectedFilter);

  return (
    <div className="catalyst-feed-section">
      <div className="section-header">
        <div className="header-row">
          <h2>Catalyst feed</h2>
          <span className="updated-time">
            <span className={`live-dot ${!isConnected ? 'disconnected' : ''}`} />
            {isConnected ? 'Live' : 'Offline'} · updated {formatUpdateTime()}
          </span>
        </div>
        <p>
          Positive news from S&P 500 {catalysts.length > 0 && 'in the last 2 hours, sorted by sentiment score'}
        </p>
      </div>

      <div className="chips">
        {filters.map((filter) => (
          <span
            key={filter}
            className={`chip ${selectedFilter === filter.toLowerCase() ? 'active' : ''}`}
            onClick={() => setSelectedFilter(filter.toLowerCase())}
          >
            {filter}
          </span>
        ))}
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-secondary)' }}>
          Loading catalysts...
        </div>
      ) : filteredCatalysts.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-secondary)' }}>
          No catalysts found. {!isConnected && 'Please check if backend is running.'}
        </div>
      ) : (
        <div className="feed">
          {filteredCatalysts.map((catalyst, index) => (
            <CatalystCard
              key={`${catalyst.symbol}-${index}`}
              symbol={catalyst.symbol}
              companyName={catalyst.company_name || catalyst.symbol}
              price={catalyst.price || 0}
              change={catalyst.change || 0}
              changePercent={catalyst.change_percent || 0}
              exchange={catalyst.exchange || 'NASDAQ'}
              avatarColor={getAvatarColor(catalyst.symbol)}
              headline={catalyst.headline || catalyst.title || 'Market news'}
              url={catalyst.url}
              sentiment={catalyst.sentiment || 0.5}
              timeAgo={catalyst.time_ago || 'recently'}
              stats={{
                volVsAvg: catalyst.volume_vs_avg || 1.5,
                dayRange: `${catalyst.day_low || 0} – ${catalyst.day_high || 0}`,
                pe: catalyst.pe_ratio || 'N/A',
                ytd: catalyst.ytd_return || 0,
              }}
              onViewDetails={onViewDetails}
              onTrackStock={onTrackStock}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default CatalystFeed;
