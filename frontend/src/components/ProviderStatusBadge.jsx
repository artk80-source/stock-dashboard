import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/theme.css';

/**
 * ProviderStatusBadge - Shows provider health status in footer
 * Only visible if any provider is degraded or down
 * Fetches from /api/health endpoint
 */
const ProviderStatusBadge = () => {
  const [providerStatus, setProviderStatus] = useState(null);
  const [showBadge, setShowBadge] = useState(false);

  useEffect(() => {
    // Fetch health status initially
    const checkHealth = async () => {
      try {
        const response = await axios.get('http://localhost:8000/api/health');
        if (response.data?.provider_status) {
          const status = response.data.provider_status;
          // Only show badge if any provider is not "ok"
          const hasIssues = Object.values(status).some((s) => s !== 'ok');
          setProviderStatus(status);
          setShowBadge(hasIssues);
        }
      } catch (error) {
        console.error('Error fetching health status:', error);
      }
    };

    checkHealth();

    // Check health every 30 seconds
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  if (!showBadge || !providerStatus) {
    return null;
  }

  const getDegradedProviders = () => {
    return Object.entries(providerStatus)
      .filter(([_, status]) => status !== 'ok')
      .map(([provider, status]) => `${provider}: ${status}`)
      .join(', ');
  };

  return (
    <div className="provider-status-badge">
      <span>⚠️</span>
      <span title={getDegradedProviders()}>
        {Object.values(providerStatus).filter((s) => s !== 'ok').length} provider
        {Object.values(providerStatus).filter((s) => s !== 'ok').length !== 1 ? 's' : ''} degraded
      </span>
    </div>
  );
};

export default ProviderStatusBadge;
