import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from './api';
import axios from 'axios';
import Dashboard from './components/Dashboard';
import CatalystFeed from './components/CatalystFeed';
import StockDetail from './components/StockDetail';
import PortfolioTab from './components/PortfolioTab';
import CouncilTab from './components/CouncilTab';
import ProviderStatusBadge from './components/ProviderStatusBadge';
import './styles/theme.css';
import './App.css';


const TABS = [
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'council',   label: 'LLM Concilium' },
  { id: 'dashboard', label: 'Watchlist' },
];

function App() {
  const [healthStatus, setHealthStatus] = useState('loading');
  const [selectedStock, setSelectedStock] = useState(null);
  const [appReady, setAppReady]   = useState(false);
  const [activeTab, setActiveTab] = useState('portfolio');

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await axios.get(`${API_BASE_URL}/health`, { timeout: 5000 });
        const { provider_status } = response.data;
        const hasHealthy = Object.values(provider_status).some((s) => s === 'ok');
        setHealthStatus(hasHealthy ? 'healthy' : 'degraded');
        setAppReady(true);
      } catch {
        setHealthStatus('unhealthy');
        setTimeout(checkHealth, 3000);
      }
    };
    checkHealth();
  }, []);

  if (!appReady) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 40, marginBottom: 20 }}>⏳</div>
          <h2 style={{ color: 'var(--text-primary)' }}>Connecting...</h2>
          <p style={{ color: 'var(--text-secondary)', marginTop: 10 }}>Checking data providers</p>
        </div>
      </div>
    );
  }

  if (healthStatus === 'unhealthy') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 40, marginBottom: 20 }}>❌</div>
          <h2 style={{ color: 'var(--text-primary)' }}>Backend unavailable</h2>
          <p style={{ color: 'var(--text-secondary)', marginTop: 10 }}>Ensure backend is running on port 8000</p>
          <p style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 15 }}>
            Run: <code style={{ color: 'var(--accent-cyan)' }}>python main.py</code> in the backend folder
          </p>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-page)' }}>
      {/* Header */}
      <div style={{
        background: 'var(--bg-card)',
        borderBottom: '1px solid var(--border-subtle)',
        padding: '0',
        position: 'sticky',
        top: 0,
        zIndex: 100,
      }}>
        {/* Logo row */}
        <div style={{ maxWidth: 1200, margin: '0 auto', padding: '10px 16px 0', userSelect: 'none' }}>
          <div style={{ lineHeight: 1 }}>
            <span style={{
              fontSize: '1.15em',
              fontWeight: 800,
              letterSpacing: '-0.02em',
              background: 'linear-gradient(90deg, #3B82F6 0%, #06B6D4 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}>
              Sim Trader
            </span>
            <span style={{ fontSize: '0.65em', color: 'var(--text-tertiary)', fontWeight: 500, letterSpacing: '0.08em', marginLeft: 10 }}>
              PAPER · AI
            </span>
          </div>
        </div>
        {/* Tab row — 3 equal-width tabs, always fill full width */}
        <nav style={{ display: 'flex', width: '100%' }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab-btn ${activeTab === t.id ? 'active' : ''}`}
              style={{ flex: 1, textAlign: 'center' }}
              onClick={() => { setActiveTab(t.id); setSelectedStock(null); }}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Content */}
      <div style={{ padding: '24px 0 0' }}>
        {selectedStock ? (
          <div style={{ maxWidth: 800, margin: '0 auto', padding: '0 16px' }}>
            <StockDetail symbol={selectedStock} onClose={() => setSelectedStock(null)} />
          </div>
        ) : (
          <>
            {activeTab === 'portfolio' && <PortfolioTab />}
            {activeTab === 'council'   && <CouncilTab />}
            {activeTab === 'dashboard' && (
              <div style={{ maxWidth: 1200, margin: '0 auto', padding: '0 16px' }}>
                <Dashboard onViewDetails={(sym) => setSelectedStock(sym)} />
              </div>
            )}
          </>
        )}
      </div>

      <ProviderStatusBadge />

      {healthStatus === 'degraded' && (
        <div style={{
          position: 'fixed', top: 20, left: 20,
          background: 'var(--warm-bg)', border: '1px solid var(--warm-border)',
          borderRadius: 'var(--radius-md)', padding: '10px 14px',
          fontSize: 'var(--text-sm)', color: 'var(--warm)',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span>⚠️</span><span>Some providers degraded</span>
        </div>
      )}
    </div>
  );
}

export default App;
