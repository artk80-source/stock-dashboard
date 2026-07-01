import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from '../api';
import axios from 'axios';

const API = API_BASE_URL;
const REFRESH = 60000;

const JUDGE_COLORS = {
  groq_70b:   '#10D982',
  groq_8b:    '#06B6D4',
  gemini:     '#3B82F6',
  cerebras:   '#8B5CF6',
  openrouter: '#F59E0B',
  mistral:    '#EC4899',
  rules:      '#9AA5BD',
  haiku:      '#FF9500',
  gpt4mini:   '#00A67E',
};

const judgeColor = (name) => JUDGE_COLORS[name] || '#6B7593';

function AccuracyBar({ value }) {
  const color = value >= 65 ? 'var(--gain)' : value >= 50 ? 'var(--warm)' : 'var(--loss)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--bg-elevated)', borderRadius: 3 }}>
        <div style={{ width: `${Math.min(value, 100)}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.6s ease' }} />
      </div>
      <span style={{ color, fontSize: '0.85em', fontWeight: 700, minWidth: 38 }}>{value.toFixed(1)}%</span>
    </div>
  );
}

function ScoreBoard({ scores }) {
  if (!scores?.length) {
    return (
      <div className="pf-empty" style={{ padding: '32px 0' }}>
        No council data yet — scores build after first automated trades.
        <br /><small style={{ color: 'var(--text-tertiary)', marginTop: 8, display: 'block' }}>Add API keys to .sim_config to activate LLM judges.</small>
      </div>
    );
  }

  return (
    <div className="council-score-grid">
      {scores.map((j) => (
        <div key={j.judge} className="council-judge-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <div className="council-judge-dot" style={{ background: judgeColor(j.judge) }} />
            <span style={{ color: 'var(--text-primary)', fontWeight: 700, fontSize: '0.95em' }}>{j.judge}</span>
            {j.total === 0 && <span className="council-badge-inactive">no data</span>}
          </div>
          <AccuracyBar value={j.accuracy} />
          <div className="council-judge-meta">
            <span>{j.total} trades</span>
            <span style={{ color: j.pnl_when_correct >= 0 ? 'var(--gain)' : 'var(--loss)' }}>
              ${j.pnl_when_correct >= 0 ? '+' : ''}{j.pnl_when_correct?.toLocaleString('en-US', { minimumFractionDigits: 0 })} when right
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function VotePills({ votes }) {
  if (!votes) return null;
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
      {Object.entries(votes).map(([judge, vote]) => {
        const color = vote === 'BUY' ? 'var(--gain)' : vote === 'SELL' ? 'var(--loss)' : 'var(--text-tertiary)';
        const bg    = vote === 'BUY' ? 'var(--gain-bg)' : vote === 'SELL' ? 'var(--loss-bg)' : 'var(--neutral-bg)';
        return (
          <span key={judge} style={{ background: bg, color, border: `1px solid ${color}22`, borderRadius: 4, padding: '2px 7px', fontSize: '0.72em', fontWeight: 600 }}>
            <span style={{ color: judgeColor(judge) }}>{judge}</span>:{vote}
          </span>
        );
      })}
    </div>
  );
}

function DecisionLog({ decisions }) {
  if (!decisions?.length) return <div className="pf-empty">No decisions logged yet.</div>;
  return (
    <div className="council-log">
      {decisions.map((d, i) => {
        const time = d.ts ? new Date(d.ts + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '-';
        const dec  = d.council_decision;
        const color = dec === 'BUY' ? 'var(--gain)' : dec === 'SELL' ? 'var(--loss)' : 'var(--text-tertiary)';
        const pnl   = d.outcome;
        return (
          <div key={i} className="council-log-row">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ color: 'var(--text-tertiary)', fontSize: '0.8em', minWidth: 44 }}>{time}</span>
              <strong style={{ color: 'var(--text-primary)', minWidth: 52 }}>{d.sym}</strong>
              <span style={{ color, fontWeight: 700, fontSize: '0.9em', minWidth: 38 }}>{dec}</span>
              {pnl !== null && pnl !== undefined && (
                <span style={{ color: pnl >= 0 ? 'var(--gain)' : 'var(--loss)', fontSize: '0.85em', fontWeight: 600 }}>
                  → {pnl >= 0 ? '+' : ''}${pnl.toFixed(0)}
                </span>
              )}
              {pnl === null && <span style={{ color: 'var(--text-tertiary)', fontSize: '0.8em' }}>→ open</span>}
            </div>
            <VotePills votes={d.votes} />
          </div>
        );
      })}
    </div>
  );
}

export default function CouncilTab() {
  const [scores, setScores]       = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetch = async () => {
    try {
      const [sRes, lRes] = await Promise.all([
        axios.get(`${API}/council/scores`, { timeout: 6000 }),
        axios.get(`${API}/council/log?limit=30`, { timeout: 6000 }),
      ]);
      setScores(sRes.data.judges || []);
      setDecisions(lRes.data.decisions || []);
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      console.error('Council fetch error:', e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetch(); const t = setInterval(fetch, REFRESH); return () => clearInterval(t); }, []);

  const totalTrades = scores.reduce((s, j) => Math.max(s, j.total_all || 0), 0);
  const bestJudge   = scores[0];

  return (
    <div className="pf-root">
      {!loading && scores.length > 0 && (
        <div className="council-summary-bar">
          <div className="council-summary-item">
            <span className="council-summary-label">Active Judges</span>
            <span className="council-summary-value">{scores.filter(j => j.total > 0).length} / {scores.length}</span>
          </div>
          <div className="council-summary-item">
            <span className="council-summary-label">Decisions Logged</span>
            <span className="council-summary-value">{totalTrades}</span>
          </div>
          {bestJudge && (
            <div className="council-summary-item">
              <span className="council-summary-label">Best Judge</span>
              <span className="council-summary-value" style={{ color: judgeColor(bestJudge.judge) }}>
                {bestJudge.judge} ({bestJudge.accuracy.toFixed(0)}%)
              </span>
            </div>
          )}
          {lastUpdate && (
            <div className="council-summary-item" style={{ marginLeft: 'auto' }}>
              <span className="council-summary-label">Updated</span>
              <span className="council-summary-value" style={{ color: 'var(--text-tertiary)' }}>{lastUpdate}</span>
            </div>
          )}
        </div>
      )}

      <div className="pf-section-title" style={{ marginTop: 0 }}>
        Judge Accuracy — rolling 30 trades
      </div>
      {loading ? <div className="pf-skeleton" style={{ height: 120, borderRadius: 10 }} /> : <ScoreBoard scores={scores} />}

      <div className="pf-section-title" style={{ marginTop: 24 }}>
        Recent Decisions
        <small style={{ color: 'var(--text-tertiary)', fontWeight: 400, marginLeft: 8, fontSize: '0.8em' }}>
          Council vote shown per judge — outcome fills in after trade closes
        </small>
      </div>
      {loading ? <div className="pf-skeleton" style={{ height: 200, borderRadius: 10 }} /> : <DecisionLog decisions={decisions} />}
    </div>
  );
}
