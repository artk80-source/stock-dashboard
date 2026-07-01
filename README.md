# Stock Market Dashboard

A full-stack stock market dashboard that tracks a watchlist of tech companies, surfaces positive news catalysts, runs a multi-LLM trading council, and simulates day-trading and swing-trading portfolios.

## Tech stack

- **Backend**: FastAPI (Python), [yfinance](https://github.com/ranaroussi/yfinance) for market data
- **Frontend**: React + Vite, axios, Chart.js (`react-chartjs-2`)
- **TradingView integration**: MCP server (`.mcp.json`) for reading/controlling a live TradingView Desktop chart
- **LLM council**: Groq, Cerebras, Gemini, OpenRouter (free tiers) + a deterministic rules engine

## Features

- **Dashboard** — grid of all companies in `backend/watchlist.csv` with live price and % change. Click a card to open the detail view.
- **Catalyst Feed** — scans the watchlist for recent positive news, scored with a keyword-based sentiment heuristic, filterable by category (Earnings, Upgrades, M&A, FDA).
- **Stock Detail** — price chart (1D/5D/1M/3M/6M/1Y), day-trade metrics (open, day high/low, prev close, intraday %, volume vs avg), long-term metrics (P/E, market cap, 52-week range, dividend yield, analyst target, YTD return), and recent news with sentiment.
- **Portfolio tab** — live view of the day-trading ledger (`day_ledger.json`) and swing portfolio (`sim_ledger.json`): positions, P&L, cash.
- **Council tab** — shows the latest LLM council vote per ticker (BUY/SELL/HOLD per judge, weighted majority, accuracy scores).
- **Health check** — `/api/health` reports yfinance connectivity; the UI shows a connecting/degraded screen if the backend or data provider is unavailable.

## Project structure

```
backend/
  main.py              # FastAPI app and all API routes
  cache.py             # simple in-memory cache helper
  watchlist.csv        # editable list of tracked companies (name, ticker)
  providers/           # alternate data provider clients (yfinance, finnhub, alpha vantage)
  strategy_advisor.py  # CLI that ranks watchlist stocks from live data
  requirements.txt

frontend/
  src/
    api.js             # shared API base URL
    App.jsx            # tab nav + health check + stock detail modal
    components/
      Dashboard.jsx        # watchlist grid homepage
      CatalystFeed.jsx     # positive news feed
      StockDetail.jsx      # per-stock chart + metrics + news modal
      PortfolioTab.jsx     # day + swing portfolio P&L view
      CouncilTab.jsx       # LLM council votes and accuracy scores
      ProviderStatusBadge.jsx
    styles/theme.css   # design tokens and shared component styles

# Simulation scripts (run independently of the dashboard UI)
sim_monitor.py         # swing portfolio monitor: stop-loss/target/momentum alerts
sim_premarket.py       # pre-market scanner: gaps, stop proximity, movers (runs ~5 min before open)
sim_scanner.py         # daily stock picker: scans ~70 S&P 500 tech stocks, saves picks to day_picks.json
sim_daytrader.py       # day trading engine: news-based + ORB/candle entry, auto-exit, 30-min checks
sim_trader_live.py     # autonomous intraday agent: 6-8 round trips/day, 2-min polling
sim_tv.py              # resilient TradingView CDP bridge: auto-reconnect, circuit breaker, screenshots
llm_council.py         # multi-LLM council: parallel judges → weighted majority vote → outcome tracking

# State files (generated at runtime)
sim_ledger.json        # swing portfolio positions, cash, P&L
day_ledger.json        # day trading portfolio state
day_picks.json         # today's scanner picks (written by sim_scanner.py)
llm_council_log.jsonl  # per-trade council decisions and outcomes
llm_scores.json        # rolling accuracy scores per LLM judge

.sim_config            # credentials: Resend API key, ntfy topic, WhatsApp — gitignored, never commit
.mcp.json              # registers the TradingView MCP server
```

## Running locally

**Backend** (FastAPI on port 8000):

```bash
cd backend
python3 -m venv venv                         # first time only
./venv/bin/pip install -r requirements.txt   # first time only
./venv/bin/python main.py
```

**Frontend** (Vite on port 5173):

```bash
cd frontend
npm install   # first time only
npm run dev
```

Then open http://localhost:5173. The frontend expects the backend at `http://localhost:8000`.

## API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/health` | Health check + yfinance provider status |
| `GET /api/watchlist` | List of tracked companies from `watchlist.csv` |
| `GET /api/stock/{symbol}` | Current price/change snapshot |
| `GET /api/stock/{symbol}/history?period=` | Historical close prices (`1d`,`5d`,`1mo`,`3mo`,`6mo`,`1y`) |
| `GET /api/stock/{symbol}/analysis` | Day-trade and long-term metrics |
| `GET /api/stock/{symbol}/news` | Recent news with a sentiment score |
| `GET /api/catalysts?lookback_hours=&min_sentiment=&limit=` | Recent positive-news catalysts across the tracked universe |
| `GET /api/search/{query}` | Basic symbol lookup |
| `GET /api/portfolio/day` | Day trading ledger from `day_ledger.json` |
| `GET /api/portfolio/swing` | Swing portfolio from `sim_ledger.json` |
| `GET /api/council/scores` | LLM judge accuracy scores from `llm_scores.json` |
| `GET /api/council/log` | Recent council trade log from `llm_council_log.jsonl` |

## Editing the watchlist

Edit `backend/watchlist.csv` (columns: `name,ticker`) to change which companies appear on the Dashboard. Restart the backend to pick up changes.

## TradingView MCP

`.mcp.json` registers a TradingView MCP server, giving an MCP-aware AI assistant tools to read and control a live TradingView Desktop chart (symbols, indicators, drawings, Pine Script, screenshots).

TradingView Desktop must be launched with Chrome DevTools Protocol enabled:

```bash
killall TradingView 2>/dev/null
/Applications/TradingView.app/Contents/MacOS/TradingView --remote-debugging-port=9222
```

Verify it's reachable:

```bash
curl -s http://localhost:9222/json/version
```

`sim_tv.py` wraps this with auto-reconnect, a circuit breaker, and helper functions used by the simulation scripts.

## Simulation scripts

All sim scripts run independently of the dashboard. They share `.sim_config` for credentials (never committed) and write their state to JSON files in the project root.

**Cron schedule (IDT times):**

```
# Pre-market and open
15 13 * * 1-5   python3 sim_premarket.py         # 16:15 — pre-market briefing
15 13 * * 1-5   python3 sim_scanner.py premarket  # 16:15 — stock picker pre-market pass
45 13 * * 1-5   python3 sim_scanner.py open       # 16:45 — stock picker post-open pass

# Intraday checks (day trading)
00 13 * * 1-5   python3 sim_daytrader.py scan     # 16:00 — news pre-scan
10 13 * * 1-5   python3 sim_daytrader.py enter    # 16:10 — news-based entry
45 13 * * 1-5   python3 sim_daytrader.py open     # 16:45 — ORB/candle entry
*/30 14-19 * * 1-5  python3 sim_daytrader.py check  # every 30 min — auto-exit + re-entry
45 19 * * 1-5   python3 sim_daytrader.py close    # 22:45 — EOD close all

# Evening swing monitor
15 20 * * 1-5   python3 sim_monitor.py            # 23:15 — swing portfolio check
```

**Manual runs:**

```bash
python3 sim_scanner.py premarket    # pre-market stock pick
python3 sim_scanner.py open         # post-open stock pick
python3 sim_monitor.py              # swing portfolio check now
python3 llm_council.py NVDA         # ask the council about a ticker
```

## LLM Council (`llm_council.py`)

Runs multiple LLM judges in parallel — each receives identical market data and returns BUY / SELL / HOLD with a confidence score. A weighted majority vote decides the final signal. After each trade closes, outcomes are logged and accuracy scores update automatically.

**Free judges (no cost):**
- `rules` — deterministic rule engine, always active
- `groq_70b` — Llama 3.3 70B via Groq (6,000 req/day free)
- `groq_8b` — Llama 3.1 8B via Groq (ultra fast)
- `cerebras` — Llama 3.1 70B via Cerebras (generous free tier)
- `gemini` — Gemini 2.0 Flash via AI Studio (1,500 req/day free)
- `openrouter` — free Llama/Mistral/Gemma models

API keys go in `.sim_config` (gitignored).

## Portfolio monitor (`sim_monitor.py`)

Checks swing positions (from `sim_ledger.json`) against stop-loss/target levels and day moves. Sends alerts via macOS notification, email (Resend), WhatsApp (CallMeBot), and ntfy.sh. Intended as a nightly cron job.

## Strategy advisor (`backend/strategy_advisor.py`)

CLI that fetches live quotes, analysis metrics, and catalyst news from the running backend and prints a ranked report of which watchlist stocks look most interesting right now.

```bash
cd backend
./venv/bin/python strategy_advisor.py --top 5
```

## Notes

- Sentiment scoring is a simple keyword heuristic, not a trained model.
- Data is sourced from Yahoo Finance via `yfinance` and is subject to its rate limits and occasional missing fields for less-covered tickers.
- Nothing here is financial advice. All simulation scripts use paper-trading only.
