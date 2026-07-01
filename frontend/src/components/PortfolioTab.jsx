import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from '../api';
import axios from 'axios';

const API = API_BASE_URL;
const REFRESH = 30000; // 30s

const pct = (v) => `${v >= 0 ? '+' : ''}${v?.toFixed(2)}%`;
const usd = (v) => `${v >= 0 ? '+' : ''}$${Math.abs(v ?? 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

function EquityCard({ data, loading }) {
  if (loading) return <div className="pf-card pf-skeleton" />;
  if (!data) return null;
  const positive = data.total_pnl >= 0;
  return (
    <div className="pf-card">
      <div className="pf-card-header">
        <span className="pf-strategy-label">{data.strategy}</span>
        <span className="pf-badge" style={{ background: positive ? 'var(--gain-bg)' : 'var(--loss-bg)', color: positive ? 'var(--gain)' : 'var(--loss)', border: `1px solid ${positive ? 'var(--gain-border)' : 'rgba(255,92,92,0.35)'}` }}>
          {positive ? '▲' : '▼'} {pct(data.total_pnl_pct)}
        </span>
      </div>
      <div className="pf-equity">${data.equity?.toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
      <div className="pf-meta-row">
        <span className="pf-meta">Start <strong>${data.start?.toLocaleString()}</strong></span>
        <span className="pf-meta" style={{ color: positive ? 'var(--gain)' : 'var(--loss)' }}>
          Total P&L <strong>{usd(data.total_pnl)}</strong>
        </span>
      </div>
      <div className="pf-meta-row">
        <span className="pf-meta">Cash <strong>${data.cash?.toLocaleString('en-US', { minimumFractionDigits: 0 })}</strong></span>
        <span className="pf-meta">Trades <strong>{data.total_trades}</strong></span>
        {data.today_pnl !== undefined && (
          <span className="pf-meta" style={{ color: data.today_pnl >= 0 ? 'var(--gain)' : 'var(--loss)' }}>
            Today <strong>{usd(data.today_pnl)}</strong> ({data.today_trades} trades)
          </span>
        )}
      </div>
    </div>
  );
}

function PositionsTable({ positions, emptyMsg }) {
  if (!positions?.length) return <div className="pf-empty">{emptyMsg || 'No open positions'}</div>;
  return (
    <div className="pf-table-wrap">
      <table className="pf-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th className="col-shares">Shares</th>
            <th className="col-entry">Entry</th>
            <th>Now</th>
            <th className="col-value">Value</th>
            <th>P&amp;L</th>
            <th className="col-stop">Stop</th>
            <th>Target</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.sym} className={p.pnl >= 0 ? 'row-gain' : 'row-loss'}>
              <td><strong>{p.sym}</strong></td>
              <td className="col-shares">{p.shares}</td>
              <td className="col-entry">${p.entry}</td>
              <td>${p.price}</td>
              <td className="col-value">${p.value?.toLocaleString('en-US', { minimumFractionDigits: 0 })}</td>
              <td style={{ color: p.pnl >= 0 ? 'var(--gain)' : 'var(--loss)', fontWeight: 700 }}>
                {usd(p.pnl)}<br /><small>{pct(p.pnl_pct)}</small>
              </td>
              <td className="col-stop" style={{ color: 'var(--loss)' }}>${p.stop}</td>
              <td style={{ color: 'var(--gain)', fontWeight: 600 }}>${p.target}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RecentTrades({ trades }) {
  if (!trades?.length) return null;
  return (
    <div className="pf-section">
      <div className="pf-section-title">Recent Closed Trades</div>
      <div className="pf-table-wrap">
        <table className="pf-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Symbol</th>
              <th className="col-side">Side</th>
              <th>P&amp;L</th>
              <th className="col-reason">Reason</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={i} className={t.pnl >= 0 ? 'row-gain' : 'row-loss'}>
                <td style={{ color: 'var(--text-secondary)' }}>{t.date?.slice(5)}</td>
                <td><strong>{t.symbol || t.sym}</strong></td>
                <td className="col-side" style={{ color: 'var(--text-secondary)' }}>{t.action}</td>
                <td style={{ color: t.pnl >= 0 ? 'var(--gain)' : 'var(--loss)', fontWeight: 700 }}>
                  {usd(t.pnl)} <small>({pct(t.pnl_pct)})</small>
                </td>
                <td className="col-reason" style={{ color: 'var(--text-secondary)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {t.exit_reason || t.strategy || '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StrategyPanel({ url, title }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetch = async () => {
    try {
      const r = await axios.get(url, { timeout: 10000 });
      setData(r.data);
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      console.error(title, e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetch(); const t = setInterval(fetch, REFRESH); return () => clearInterval(t); }, []);

  return (
    <div className="pf-strategy-panel">
      <div className="pf-section-title" style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span>{title}</span>
        {lastUpdate && <span style={{ fontSize: '0.75em', color: 'var(--text-tertiary)', fontWeight: 400 }}>Updated {lastUpdate}</span>}
      </div>
      <EquityCard data={data} loading={loading} />
      {data && (
        <>
          <div className="pf-section-title" style={{ marginTop: 16 }}>Open Positions ({data.positions?.length ?? 0})</div>
          <PositionsTable positions={data.positions} />
          <RecentTrades trades={data.recent_trades} />
        </>
      )}
    </div>
  );
}

function AboutSection() {
  return (
    <div style={{
      maxWidth: 720,
      margin: '48px auto 0',
      padding: '0 20px',
      color: 'var(--text-secondary)',
      lineHeight: 1.8,
      fontSize: '1em',
    }}>
      <p style={{ color: 'var(--text-primary)', fontWeight: 700, fontSize: '1.1em', marginBottom: 12 }}>
        What is this?
      </p>
      <p>
        This is a paper trading simulator running two parallel strategies on real market data —
        no real money is at risk. Every trade decision is logged, tracked, and evaluated so we
        can learn what actually works before committing capital.
      </p>

      <p style={{ marginTop: 20, color: 'var(--text-primary)', fontWeight: 700 }}>
        Two strategies
      </p>
      <p>
        <strong style={{ color: 'var(--text-primary)' }}>Day Trade</strong> — fast in-and-out trades within the same session.
        Target: 6–8 round trips per day in volatile tech stocks, aiming for +1% per trade with a tight 0.5% stop loss.
        Positions are always closed before market close.
      </p>
      <p style={{ marginTop: 10 }}>
        <strong style={{ color: 'var(--text-primary)' }}>Swing / Long</strong> — positions held for days or weeks,
        entered on strong technical setups. Higher profit targets, more patience required.
      </p>

      <p style={{ marginTop: 20, color: 'var(--text-primary)', fontWeight: 700 }}>
        How decisions are made
      </p>
      <p>
        Every entry and exit is evaluated by an <strong style={{ color: 'var(--accent-cyan)' }}>LLM Council</strong> —
        multiple AI models running in parallel, each seeing the same market data (price, RSI, MACD, news)
        and voting independently: <strong>BUY</strong>, <strong>SELL</strong>, or <strong>HOLD</strong>.
        The majority vote wins. After each trade closes, the outcome is recorded and the models
        that were right gain higher vote weight for future decisions.
      </p>
      <p style={{ marginTop: 10 }}>
        Models currently active: <span style={{ color: 'var(--gain)' }}>Rule engine</span> (always on),
        with <span style={{ color: 'var(--accent-cyan)' }}>Groq · Gemini · Cerebras · Mistral</span> joining
        once their free API keys are configured. All free-tier, no billing.
      </p>

      <p style={{ marginTop: 20, color: 'var(--text-primary)', fontWeight: 700 }}>
        The goal
      </p>
      <p>
        Run this for several weeks. Let the council accumulate enough trade history to show which
        model predicts market moves most accurately. Once we have a consistent edge —
        $200–500 profit days in sim — we switch to a real broker and let the winning model trade live.
      </p>

      <p style={{ marginTop: 24, fontSize: '0.85em', color: 'var(--text-tertiary)', borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
        Sim Trader · Paper mode · Data from Yahoo Finance · Decisions by AI council · Built July 2026
      </p>
    </div>
  );
}

export default function PortfolioTab() {
  return (
    <div className="pf-root">
      <div className="pf-grid">
        <StrategyPanel url={`${API}/portfolio/day`}   title="Day Trade" />
        <StrategyPanel url={`${API}/portfolio/swing`} title="Swing / Long" />
      </div>
      <AboutSection />
    </div>
  );
}
