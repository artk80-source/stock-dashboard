# Stock Market Dashboard

A full-stack stock market dashboard that tracks a watchlist of companies, surfaces positive news catalysts, and shows per-stock price history, day-trade/long-term metrics, and recent news with a simple sentiment score.

## Tech stack

- **Backend**: FastAPI (Python), [yfinance](https://github.com/ranaroussi/yfinance) for market data
- **Frontend**: React + Vite, axios, Chart.js (`react-chartjs-2`)
- **TradingView integration**: MCP server (`.mcp.json`) for reading/controlling a live TradingView Desktop chart

## Features

- **Dashboard** (homepage) — grid of all companies in `backend/watchlist.csv` with live price and % change. Click a card to open the detail view.
- **Catalyst Feed** — scans a tracked set of tickers for recent positive news, scored with a lightweight keyword-based sentiment heuristic, filterable by category (Earnings, Upgrades, M&A, FDA).
- **Stock Detail** — price chart (1D/5D/1M/3M/6M/1Y), day-trade metrics (open, day high/low, prev close, intraday %, volume vs avg), long-term metrics (P/E, market cap, 52-week range, dividend yield, analyst target, YTD return), and recent news with sentiment.
- **Health check** — `/api/health` reports yfinance connectivity; the UI shows a connecting/degraded screen if the backend or data provider is unavailable.

## Project structure

```
backend/
  main.py              # FastAPI app and all API routes
  cache.py              # simple in-memory cache helper
  watchlist.csv         # editable list of tracked companies (name, ticker)
  providers/            # alternate data provider clients (yfinance, finnhub, alpha vantage)
  strategy_advisor.py    # CLI that ranks watchlist stocks from live data
  requirements.txt
frontend/
  src/
    App.jsx              # tab nav (Dashboard / Catalyst Feed) + health check + stock detail modal
    components/
      Dashboard.jsx        # watchlist grid homepage
      CatalystFeed.jsx      # positive news feed
      StockDetail.jsx       # per-stock chart + metrics + news modal
      ProviderStatusBadge.jsx
    styles/theme.css       # design tokens and shared component styles
sim_monitor.py         # portfolio stop-loss/momentum monitor (reads prices from the backend)
sim_notify.py           # email (Resend), WhatsApp, ntfy, and macOS notification senders
.sim_config             # credentials for sim_notify.py (gitignored, not committed)
.mcp.json               # registers the TradingView MCP server
```

## Running locally

**Backend** (FastAPI on port 8000):

```bash
cd backend
python3 -m venv venv          # first time only
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

## Editing the watchlist

Edit `backend/watchlist.csv` (columns: `name,ticker`) to change which companies appear on the Dashboard. Restart the backend to pick up changes.

## TradingView MCP

`.mcp.json` registers a TradingView MCP server, giving an MCP-aware AI assistant tools to read and control a live TradingView Desktop chart (symbols, indicators, drawings, Pine Script, screenshots).

TradingView Desktop must be launched with Chrome DevTools Protocol enabled, since opening it normally does not expose this:

```bash
killall TradingView 2>/dev/null
/Applications/TradingView.app/Contents/MacOS/TradingView --remote-debugging-port=9222
```

Verify it's reachable:

```bash
curl -s http://localhost:9222/json/version
```

## Portfolio monitor (`sim_monitor.py`)

A standalone script (independent of the dashboard) that checks a hardcoded set of positions against stop-loss/target levels and day-over-day moves, using prices from the backend's `/api/stock/{symbol}` endpoint. On alert conditions (or as a daily summary) it sends notifications via macOS, email (Resend), WhatsApp (CallMeBot), and ntfy.sh — configured through `.sim_config` (gitignored; copy `.sim_config` and fill in your own credentials, never commit it).

```bash
./venv/bin/python sim_monitor.py   # run from backend/, or point PYTHONPATH at it
```

Intended to run on a schedule (e.g. a weekday-evening cron job).

## Strategy advisor (`backend/strategy_advisor.py`)

CLI that fetches live quotes, analysis metrics, and catalyst news from the running backend and prints a ranked, plain-English report of which watchlist stocks look most interesting right now. Rule-based heuristic, not financial advice.

```bash
cd backend
./venv/bin/python strategy_advisor.py --top 5
```

## Notes

- Sentiment scoring is a simple keyword heuristic, not a trained model — good enough for surfacing likely-positive headlines, not for real trading decisions.
- Data is sourced from Yahoo Finance via `yfinance` and is subject to its rate limits and occasional missing fields for less-covered tickers.
