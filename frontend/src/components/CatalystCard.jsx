import React from 'react';
import '../styles/theme.css';

/**
 * CatalystCard - Displays a single catalyst/news card
 * Shows company info, sentiment, headline, metrics, and action buttons
 */
const CatalystCard = ({
  symbol,
  companyName,
  price,
  change,
  changePercent,
  exchange,
  avatarColor = 'teal',
  headline,
  url,
  sentiment,
  timeAgo,
  stats = {},
  onViewDetails,
  onTrackStock,
}) => {
  // Determine sentiment class (hot/warm/neutral)
  const getSentimentClass = (score) => {
    if (score >= 0.7) return 'hot';
    if (score >= 0.3) return 'warm';
    return 'neutral';
  };

  // Determine sentiment badge class and text
  const getSentimentBadge = (score) => {
    if (score >= 0.7) {
      return { class: 'strong', text: `+${score.toFixed(2)} bullish` };
    }
    if (score >= 0.3) {
      return { class: 'medium', text: `+${score.toFixed(2)} positive` };
    }
    return { class: 'neutral', text: `${score.toFixed(2)} neutral` };
  };

  const sentimentBadge = getSentimentBadge(sentiment);
  const sentimentClass = getSentimentClass(sentiment);
  const changeClass = changePercent >= 0 ? 'up' : 'down';
  const changeIcon = changePercent >= 0 ? '▲' : '▼';

  return (
    <div className={`card ${sentimentClass}`}>
      <div className="card-top">
        <div className="company">
          <div className={`avatar ${avatarColor}`}>
            {symbol.substring(0, 4).toUpperCase()}
          </div>
          <div>
            <p className="company-name">{companyName}</p>
            <p className="company-meta">
              <span className="price">${price?.toFixed(2)}</span>
              <span className={`change-pill ${changeClass}`}>
                {changeIcon} {Math.abs(changePercent).toFixed(2)}%
              </span>
              <span>· {exchange}</span>
            </p>
          </div>
        </div>

        <div className="badges">
          <span className={`sentiment-badge ${sentimentBadge.class}`}>
            {sentimentBadge.text}
          </span>
          <p className="time-ago">{timeAgo}</p>
        </div>
      </div>

      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="headline"
          style={{ display: 'block', textDecoration: 'none', color: 'inherit' }}
        >
          {headline}
        </a>
      ) : (
        <p className="headline">{headline}</p>
      )}

      <div className="stats-bar">
        {stats.volVsAvg && (
          <div className="stat-cell">
            <p className="stat-label">Vol vs avg</p>
            <p className={`stat-value ${stats.volVsAvg >= 1 ? 'up' : ''}`}>
              {stats.volVsAvg.toFixed(1)}×
            </p>
          </div>
        )}
        {stats.dayRange && (
          <div className="stat-cell">
            <p className="stat-label">Day range</p>
            <p className="stat-value">{stats.dayRange}</p>
          </div>
        )}
        {stats.pe && (
          <div className="stat-cell">
            <p className="stat-label">P/E</p>
            <p className="stat-value">{stats.pe}</p>
          </div>
        )}
        {stats.ytd && (
          <div className="stat-cell">
            <p className="stat-label">YTD</p>
            <p className={`stat-value ${stats.ytd >= 0 ? 'up' : 'down'}`}>
              {stats.ytd >= 0 ? '+' : ''}{stats.ytd}%
            </p>
          </div>
        )}
      </div>

      <div className="actions">
        <button
          className="btn primary"
          onClick={() => onViewDetails && onViewDetails(symbol)}
        >
          View details
        </button>
        <button
          className="btn"
          onClick={() => onTrackStock && onTrackStock(symbol)}
        >
          Track stock
        </button>
      </div>
    </div>
  );
};

export default CatalystCard;
