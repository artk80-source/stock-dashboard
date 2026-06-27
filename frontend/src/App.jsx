import React, { useState, useEffect } from 'react';
import axios from 'axios';
import CatalystFeed from './components/CatalystFeed';
import StockDetail from './components/StockDetail';
import ProviderStatusBadge from './components/ProviderStatusBadge';
import './styles/theme.css';
import './App.css';

const API_BASE_URL = 'http://localhost:8000/api';

function App() {
  const [healthStatus, setHealthStatus] = useState('loading');
  const [selectedStock, setSelectedStock] = useState(null);
  const [appReady, setAppReady] = useState(false);

  // Health check on app startup
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await axios.get(`${API_BASE_URL}/health`, {
          timeout: 5000,
        });
        
        const { provider_status } = response.data;
        
        // Check if at least one provider is ok
        const hasHealthyProvider = Object.values(provider_status).some((s) => s === 'ok');
        
        if (hasHealthyProvider) {
          setHealthStatus('healthy');
          setAppReady(true);
        } else {
          setHealthStatus('degraded');
          setAppReady(true); // Still proceed but show warning
        }
      } catch (error) {
        console.error('Health check failed:', error);
        setHealthStatus('unhealthy');
        // Retry after 3 seconds if unhealthy
        setTimeout(checkHealth, 3000);
      }
    };

    checkHealth();
  }, []);

  // Render startup screen
  if (!appReady) {
    return (
      <div className="container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        <div className="health-check-screen">
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '40px', marginBottom: '20px' }}>⏳</div>
            <h2>Connecting to backend...</h2>
            <p style={{ color: 'var(--text-secondary)', marginTop: '10px' }}>
              Checking data providers
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (healthStatus === 'unhealthy') {
    return (
      <div className="container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        <div className="health-check-screen">
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '40px', marginBottom: '20px' }}>❌</div>
            <h2>Backend unavailable</h2>
            <p style={{ color: 'var(--text-secondary)', marginTop: '10px' }}>
              Please ensure the backend server is running on port 8000
            </p>
            <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '15px' }}>
              Run: <code style={{ color: 'var(--accent-cyan)' }}>python main.py</code> in the backend folder
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="container">
      {selectedStock ? (
        <StockDetail symbol={selectedStock} onClose={() => setSelectedStock(null)} />
      ) : (
        <>
          <CatalystFeed
            onViewDetails={(symbol) => setSelectedStock(symbol)}
            onTrackStock={(symbol) => console.log('Track:', symbol)}
          />
        </>
      )}

      <ProviderStatusBadge />

      {healthStatus === 'degraded' && (
        <div style={{
          position: 'fixed',
          top: '20px',
          left: '20px',
          background: 'var(--warm-bg)',
          border: '1px solid var(--warm-border)',
          borderRadius: 'var(--radius-md)',
          padding: '12px 16px',
          fontSize: 'var(--text-sm)',
          color: 'var(--warm)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          animation: 'slideIn 0.3s ease-out',
        }}>
          <span>⚠️</span>
          <span>Some providers are degraded</span>
        </div>
      )}
    </div>
  );
}

export default App;
