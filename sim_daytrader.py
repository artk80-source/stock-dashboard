#!/usr/bin/env python3
"""
Day Trade Simulation Engine — sim_daytrader.py
Budget: $25,000 | Leverage: 2× default | Timeframe: 5-min charts
Stock selection: Yahoo Finance news (dynamic — NOT the swing watchlist)
Self-learning: adapts news threshold, entry strategy, overnight hold rules
Reports: ntfy push (summary) + Gmail email (full log + CSV attachment)

Cron schedule (add to crontab):
  00 13 * * 1-5  python3 /Users/artk80/project_VS/sim_daytrader.py scan   # 16:00 IDT — news pre-scan
  10 13 * * 1-5  python3 /Users/artk80/project_VS/sim_daytrader.py enter  # 16:10 IDT — news-based entry
  45 13 * * 1-5  python3 /Users/artk80/project_VS/sim_daytrader.py open   # 16:45 IDT — ORB/candle entry
  */30 14-19 * * 1-5  python3 /Users/artk80/project_VS/sim_daytrader.py check  # every 30min — auto-exit + re-entry
  45 19 * * 1-5  python3 /Users/artk80/project_VS/sim_daytrader.py close  # 22:45 IDT — EOD close all

Manual:
  python3 sim_daytrader.py scan    pre-market: scan news, send ntfy with picks
  python3 sim_daytrader.py enter   after open: 5-min signal check, paper buy
  python3 sim_daytrader.py open    16:45: ORB + VWAP + candlestick entry (FOCUS_UNIVERSE)
  python3 sim_daytrader.py check   every 30min: auto-sell at target/stop, re-scan for entries
  python3 sim_daytrader.py close   end-of-day: close all, ntfy confirmation
"""

import json
import datetime
import os
import sys
import time
import urllib.request
import base64
import io

sys.path.insert(0, os.path.dirname(__file__))
from sim_notify import send_email, send_ntfy, notify_macos

DAY_PICKS_PATH = os.path.join(os.path.dirname(__file__), "day_picks.json")

def get_today_universe():
    """
    Returns today's trading universe.
    Priority: day_picks.json (from sim_scanner.py) → fallback: FOCUS_UNIVERSE.
    """
    today = datetime.date.today().isoformat()
    if os.path.exists(DAY_PICKS_PATH):
        try:
            with open(DAY_PICKS_PATH) as f:
                data = json.load(f)
            if data.get("date") == today and data.get("picks"):
                tickers = [p["ticker"] for p in data["picks"]]
                log(f"[UNIVERSE] Using today's scanner picks: {', '.join(tickers)}")
                return tickers
        except Exception:
            pass
    log(f"[UNIVERSE] No scanner picks for today — using FOCUS_UNIVERSE ({len(FOCUS_UNIVERSE)} stocks)")
    return FOCUS_UNIVERSE

DAY_LEDGER_PATH = os.path.join(os.path.dirname(__file__), "day_ledger.json")
LOG_PATH        = "/tmp/sim_daytrader.log"

# ── Universe — broader than swing watchlist, news-driven discovery ──
DAY_UNIVERSE = [
    # Mega-cap tech
    "AAPL","MSFT","NVDA","GOOG","META","AMZN","TSLA","AVGO",
    # Enterprise software
    "CRM","ADBE","NOW","INTU","WDAY","SNPS","CDNS","ORCL","IBM",
    # Semiconductors
    "AMD","QCOM","MU","ADI","NXPI","TXN","KLAC","LRCX","AMAT","MRVL",
    # Cybersecurity / cloud
    "CRWD","PANW","FTNT","PLTR","ANET","NET","ZS","OKTA",
    # Hardware / infrastructure
    "VRT","MSI","KEYS","AKAM","ZBRA","HPE","DELL","STX",
    # Consumer / media tech
    "NFLX","SPOT","UBER","ROKU",
    # ETFs (for market regime context)
    "QQQ","TQQQ",
]

# ── Focus universe: 15 most liquid S&P 500 tech stocks ───────────────
# All have daily volume > 5M, clear intraday moves, diverse price tiers
# Scanned every 30 min for ORB / VWAP / candlestick entries (~90 sec total)
FOCUS_UNIVERSE = [
    "NVDA", "AAPL", "MSFT", "META", "AMZN",
    "GOOG", "TSLA", "AVGO", "AMD",  "QCOM",
    "ORCL", "CRM",  "ADBE", "NFLX", "PLTR",
]

# ── News keyword scoring ──────────────────────────────────────────────
NEWS_CATEGORIES = {
    "earnings_beat":   (["beat", "beats", "exceeded", "surpassed", "tops estimates",
                         "record revenue", "record earnings", "blowout"], 4),
    "earnings_miss":   (["miss", "missed", "disappoints", "below estimates",
                         "fell short", "weak results"], -3),
    "upgrade":         (["upgrade", "upgraded", "outperform", "overweight",
                         "buy rating", "strong buy", "raises to buy"], 3),
    "downgrade":       (["downgrade", "downgraded", "underperform", "underweight",
                         "sell rating", "reduces to sell"], -3),
    "ma_deal":         (["acquisition", "merger", "acquires", "takeover",
                         "buyout", "deal worth", "to buy"], 5),
    "fda":             (["FDA", "approval", "approved", "clearance",
                         "regulatory", "drug approval"], 4),
    "guidance_raise":  (["raises guidance", "raised guidance", "above guidance",
                         "raises outlook", "raised forecast", "raises full-year"], 3),
    "guidance_cut":    (["cuts guidance", "lowers guidance", "below guidance",
                         "lowered outlook", "reduces forecast"], -3),
    "target_raise":    (["price target", "target raised", "raises target",
                         "raises price target", "increases target"], 2),
    "partnership":     (["partnership", "collaboration", "strategic agreement",
                         "new contract", "major deal"], 2),
    "ai_catalyst":     (["AI chip", "AI revenue", "AI deal", "AI partnership",
                         "artificial intelligence contract"], 2),
    "buyback":         (["buyback", "share repurchase", "repurchase program"], 1),
    "layoffs":         (["layoff", "layoffs", "job cuts", "restructuring",
                         "headcount reduction"], -1),
    "legal_risk":      (["lawsuit", "investigation", "SEC probe", "antitrust",
                         "regulatory fine"], -2),
}

# ── Learning defaults ─────────────────────────────────────────────────
DAY_LEARNING_DEFAULTS = {
    "news_score_threshold":  4,      # minimum composite score to trade
    "min_volume_ratio":      3.0,    # minimum pre-market volume vs 10-day avg
    "momentum_rsi_max":      55,     # RSI upper bound for momentum entry
    "reversal_rsi_max":      35,     # RSI threshold for reversal entry
    "overnight_enabled":     True,   # allow overnight holds
    "overnight_min_gain_pct":2.0,    # minimum unrealized gain to hold overnight
    "leverage":              2.0,    # buying power multiplier
    "max_daily_loss_pct":    6.0,    # stop trading day if equity drops this %
    "stats": {
        "total_closed":        0,
        "wins":                0,
        "losses":              0,
        "avg_gain_pct":        0.0,
        "avg_loss_pct":        0.0,
        "avg_hold_minutes":    0.0,
        "max_daily_loss_days": 0,
        "by_strategy": {
            "momentum": {"count": 0, "wins": 0, "total_gain": 0.0},
            "reversal": {"count": 0, "wins": 0, "total_gain": 0.0},
        },
        "by_hold": {
            "same_day":  {"count": 0, "wins": 0, "total_gain": 0.0},
            "overnight": {"count": 0, "wins": 0, "total_gain": 0.0},
        },
        "by_news_category": {},
    },
    "adjustments": [],
    "last_updated": None,
}

# ── Logging ───────────────────────────────────────────────────────────
def log(msg):
    ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"{ts}  [DAY] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

# ── Ledger helpers ────────────────────────────────────────────────────
def load_ledger():
    if not os.path.exists(DAY_LEDGER_PATH):
        ledger = {
            "equity":         25000.0,
            "start_value":    25000.0,
            "cash":           25000.0,
            "leverage":       2.0,
            "open_positions": {},
            "trades":         [],
            "daily_pnl":      {},
            "learning":       json.loads(json.dumps(DAY_LEARNING_DEFAULTS)),
        }
        save_ledger(ledger)
        log("Created new day_ledger.json with $25,000 starting capital")
    with open(DAY_LEDGER_PATH) as f:
        return json.load(f)

def save_ledger(ledger):
    with open(DAY_LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)

def ensure_learning(ledger):
    if "learning" not in ledger:
        ledger["learning"] = json.loads(json.dumps(DAY_LEARNING_DEFAULTS))
    for k, v in DAY_LEARNING_DEFAULTS.items():
        if k not in ledger["learning"]:
            ledger["learning"][k] = v

def get_thresholds(ledger):
    L = ledger.get("learning", DAY_LEARNING_DEFAULTS)
    return {
        "news_score":   L.get("news_score_threshold",  4),
        "volume_ratio": L.get("min_volume_ratio",      3.0),
        "momentum_rsi": L.get("momentum_rsi_max",      55),
        "reversal_rsi": L.get("reversal_rsi_max",      35),
        "overnight":    L.get("overnight_enabled",     True),
        "overnight_min":L.get("overnight_min_gain_pct",2.0),
        "leverage":     L.get("leverage",              2.0),
        "max_loss":     L.get("max_daily_loss_pct",    6.0),
    }

# ── 5-min RSI + MACD ──────────────────────────────────────────────────
def _ema(values, period):
    k = 2 / (period + 1)
    r = [sum(values[:period]) / period]
    for v in values[period:]:
        r.append(v * k + r[-1] * (1 - k))
    return r

def calc_5min(ticker):
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period="5d", interval="5m", prepost=False)
        if len(data) < 50:
            return None
        closes = data["Close"].tolist()
        volumes = data["Volume"].tolist()

        # RSI(14)
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains  = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        ag = sum(gains[:14]) / 14
        al = sum(losses[:14]) / 14
        for i in range(14, len(gains)):
            ag = (ag * 13 + gains[i]) / 14
            al = (al * 13 + losses[i]) / 14
        rsi = 100 if al == 0 else round(100 - (100 / (1 + ag / al)), 2)

        # MACD(12,26,9)
        e12  = _ema(closes, 12)
        e26  = _ema(closes, 26)
        macd = [a - b for a, b in zip(e12[14:], e26)]
        sig  = _ema(macd, 9)
        hist = round(macd[-1] - sig[-1], 4)

        price = round(closes[-1], 2)
        avg_vol_5min = sum(volumes[-78:]) / 78 if len(volumes) >= 78 else sum(volumes) / len(volumes)

        return {
            "price":    price,
            "rsi":      rsi,
            "macd":     round(macd[-1], 4),
            "signal":   round(sig[-1], 4),
            "histogram":hist,
            "volume":   int(volumes[-1]),
            "avg_volume_5min": int(avg_vol_5min),
        }
    except Exception as e:
        log(f"[5MIN] {ticker} failed: {e}")
        return None

# ── Candlestick pattern detector (5-min OHLC) ────────────────────────
def detect_candles(ticker):
    """
    Detect candlestick patterns on the last 2 bars of today's 5-min data.
    Returns dict with patterns list, candle_score (+/-), vol_ratio vs today avg.
    Patterns: HAMMER, DOJI, ENGULF_BULL, ENGULF_BEAR, PIN_BULL, PIN_BEAR
    """
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period="3d", interval="5m", prepost=False)
        if len(data) < 3:
            return None
        today = datetime.date.today().isoformat()
        td    = data[data.index.strftime("%Y-%m-%d") == today]
        if len(td) < 2:
            return None

        curr = td.iloc[-1]
        prev = td.iloc[-2]
        o_c, h_c, l_c, c_c, v_c = curr["Open"], curr["High"], curr["Low"], curr["Close"], curr["Volume"]
        o_p, h_p, l_p, c_p       = prev["Open"], prev["High"], prev["Low"], prev["Close"]

        body_c   = abs(c_c - o_c)
        range_c  = h_c - l_c if (h_c - l_c) > 0 else 0.001
        low_sh   = min(o_c, c_c) - l_c
        high_sh  = h_c - max(o_c, c_c)

        patterns = []
        score    = 0

        # Hammer: long lower shadow ≥ 2× body, small upper shadow, bullish reversal
        if low_sh >= 2 * body_c and body_c < range_c * 0.35 and high_sh < body_c:
            patterns.append("HAMMER"); score += 2

        # Doji: body < 5% of range (indecision — wait for next bar confirmation)
        elif body_c < range_c * 0.05:
            patterns.append("DOJI"); score += 0

        # Bullish Engulfing: green engulfs prior red
        if c_c > o_c and c_p < o_p and o_c <= c_p and c_c >= o_p:
            patterns.append("ENGULF_BULL"); score += 2

        # Bearish Engulfing: red engulfs prior green
        elif c_c < o_c and c_p > o_p and o_c >= c_p and c_c <= o_p:
            patterns.append("ENGULF_BEAR"); score -= 2

        # Bullish Pin Bar: lower tail > 60% of range, close in upper half
        if low_sh > range_c * 0.60 and c_c > l_c + range_c * 0.50:
            patterns.append("PIN_BULL"); score += 1

        # Bearish Pin Bar: upper tail > 60% of range, close in lower half
        elif high_sh > range_c * 0.60 and c_c < l_c + range_c * 0.50:
            patterns.append("PIN_BEAR"); score -= 1

        # Volume surge on this bar vs today's average
        today_vols  = td["Volume"].tolist()
        avg_v_today = sum(today_vols[:-1]) / max(len(today_vols) - 1, 1)
        vol_ratio   = round(v_c / avg_v_today, 2) if avg_v_today > 0 else 1.0

        return {
            "patterns":     patterns,
            "candle_score": score,
            "vol_ratio":    vol_ratio,
            "is_green":     c_c > o_c,
            "curr":         {"o": round(o_c, 2), "h": round(h_c, 2),
                             "l": round(l_c, 2), "c": round(c_c, 2)},
        }
    except Exception as e:
        log(f"[CANDLES] {ticker}: {e}")
        return None


# ── VWAP + Opening Range Breakout ─────────────────────────────────────
def calc_vwap_orb(ticker):
    """
    VWAP for today + Opening Range = first 3 bars (16:30-16:44 ET / 23:30-23:44 IDT).
    Returns vwap, orb_high, orb_low, orb_break ('UP'/'DOWN'/'INSIDE'), above_vwap.
    """
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period="3d", interval="5m", prepost=False)
        if len(data) < 3:
            return None
        today = datetime.date.today().isoformat()
        td    = data[data.index.strftime("%Y-%m-%d") == today]
        if len(td) < 3:
            return None

        # VWAP = Σ(typical_price × volume) / Σ(volume)
        tp   = (td["High"] + td["Low"] + td["Close"]) / 3
        vwap = round(float((tp * td["Volume"]).sum() / td["Volume"].sum()), 2) \
               if td["Volume"].sum() > 0 else None

        # Opening Range: first 3 × 5-min bars
        orb      = td.iloc[:3]
        orb_high = round(float(orb["High"].max()), 2)
        orb_low  = round(float(orb["Low"].min()), 2)
        price    = round(float(td["Close"].iloc[-1]), 2)

        if price > orb_high:
            orb_break = "UP"
        elif price < orb_low:
            orb_break = "DOWN"
        else:
            orb_break = "INSIDE"

        return {
            "vwap":       vwap,
            "orb_high":   orb_high,
            "orb_low":    orb_low,
            "orb_break":  orb_break,
            "above_vwap": (price > vwap) if vwap else None,
            "price":      price,
        }
    except Exception as e:
        log(f"[VWAP/ORB] {ticker}: {e}")
        return None


# ── Dynamic target % by price tier ────────────────────────────────────
def dynamic_target_pct(price, candle_score=0, orb_break=None):
    """
    Target must be >= 2.5% to maintain >1:1.5 R:R against the 1.5% intraday stop.
    Higher-priced stocks get a slightly lower % (same dollar move per position).
    """
    if price >= 300:
        base = 2.5
    elif price >= 150:
        base = 2.5
    elif price >= 80:
        base = 3.0
    else:
        base = 3.5

    # Strong signal → hold for more
    if candle_score >= 2 or orb_break == "UP":
        base = round(base * 1.2, 2)

    return round(min(base, 5.0), 2)


# ── Open signal composite scorer ──────────────────────────────────────
def score_open_signal(ticker, ind, candles, orb):
    """
    Score stock for open entry. Returns (score, reasons).
    score >= 4 → enter  |  score >= 6 → enter at full leverage
    """
    score   = 0
    reasons = []

    if not ind:
        return 0, ["no 5-min data"]

    # RSI: momentum zone (40-60) or oversold reversal
    if 40 <= ind["rsi"] <= 60:
        score += 1
        reasons.append(f"RSI {ind['rsi']} momentum")
    elif ind["rsi"] < 38:
        score += 2
        reasons.append(f"RSI {ind['rsi']} oversold reversal")

    # MACD histogram positive = upward momentum
    if ind["histogram"] > 0:
        score += 2
        reasons.append(f"MACD hist +{ind['histogram']:.3f}")

    # Candlestick patterns
    if candles:
        cs = candles["candle_score"]
        if cs >= 2:
            score += cs
            reasons.append(f"Candles: {' + '.join(candles['patterns']) if candles['patterns'] else 'bullish'}")
        elif cs > 0:
            score += 1
            reasons.append(f"Candle signal: {' '.join(candles['patterns'])}")
        if candles["vol_ratio"] >= 1.5:
            score += 1
            reasons.append(f"Volume surge {candles['vol_ratio']:.1f}×")

    # ORB breakout above opening range
    if orb:
        if orb["orb_break"] == "UP":
            score += 2
            reasons.append(f"ORB breakout ↑ (range {orb['orb_low']:.2f}–{orb['orb_high']:.2f})")
        if orb["above_vwap"]:
            score += 1
            reasons.append(f"Above VWAP ${orb['vwap']:.2f}")

    return score, reasons


# ── Pre-market data ───────────────────────────────────────────────────
def get_premarket(ticker):
    try:
        import yfinance as yf
        tk   = yf.Ticker(ticker)
        hist = tk.history(period="2d", interval="1m", prepost=True)
        if hist.empty:
            return None
        now_et = datetime.datetime.utcnow() - datetime.timedelta(hours=4)
        today  = now_et.strftime("%Y-%m-%d")
        open_t = now_et.replace(hour=9, minute=30, second=0, microsecond=0).time()

        pre_rows  = hist[(hist.index.strftime("%Y-%m-%d") == today) &
                         (hist.index.time < open_t)]
        prev_rows = hist[hist.index.strftime("%Y-%m-%d") < today]

        if pre_rows.empty or prev_rows.empty:
            return None

        pre_price  = float(pre_rows["Close"].iloc[-1])
        pre_volume = int(pre_rows["Volume"].sum())
        prev_close = float(prev_rows["Close"].iloc[-1])
        gap_pct    = round((pre_price - prev_close) / prev_close * 100, 2)

        # 10-day average daily volume for ratio
        hist10 = tk.history(period="15d")
        avg_vol = int(hist10["Volume"].mean()) if not hist10.empty else 1

        return {
            "price":       round(pre_price, 2),
            "prev_close":  round(prev_close, 2),
            "gap_pct":     gap_pct,
            "pre_volume":  pre_volume,
            "avg_volume":  avg_vol,
            "volume_ratio":round(pre_volume / (avg_vol / 78), 2) if avg_vol > 0 else 0,
        }
    except Exception as e:
        log(f"[PREMARKET] {ticker}: {e}")
        return None

# ── News scoring ──────────────────────────────────────────────────────
def score_news(ticker):
    """
    Fetch Yahoo Finance news for ticker, score by keyword + age.
    Returns (composite_score, best_headline, category, age_hours, publisher)
    """
    try:
        import yfinance as yf
        articles = yf.Ticker(ticker).news or []
        best_score = 0
        best_title = ""
        best_cat   = ""
        best_age   = 999
        best_pub   = ""

        for item in articles[:8]:
            c = item.get("content", {})
            title = c.get("title", "")
            summary = c.get("summary", "")
            text  = (title + " " + summary).lower()
            pub_str = c.get("pubDate", "")
            publisher = ""
            prov = c.get("provider", {})
            if isinstance(prov, dict):
                publisher = prov.get("displayName", "")

            # Parse age
            try:
                pub_dt = datetime.datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                age_h = (now_utc - pub_dt).total_seconds() / 3600
            except Exception:
                age_h = 999

            if age_h > 48:
                continue  # too old

            # Keyword scoring
            article_score = 0
            matched_cat   = ""
            for cat, (keywords, points) in NEWS_CATEGORIES.items():
                for kw in keywords:
                    if kw.lower() in text:
                        article_score += points
                        if points > 0 and not matched_cat:
                            matched_cat = cat
                        break

            if article_score <= 0:
                continue

            # Age bonus
            if age_h < 4:
                article_score += 2
            elif age_h < 12:
                article_score += 1
            elif age_h > 24:
                article_score -= 1

            if article_score > best_score:
                best_score = article_score
                best_title = title
                best_cat   = matched_cat
                best_age   = round(age_h, 1)
                best_pub   = publisher

        return {
            "score":     best_score,
            "title":     best_title,
            "category":  best_cat,
            "age_hours": best_age,
            "publisher": best_pub,
        }
    except Exception as e:
        log(f"[NEWS] {ticker}: {e}")
        return {"score": 0, "title": "", "category": "", "age_hours": 999, "publisher": ""}

# ── Find best candidates ──────────────────────────────────────────────
def find_candidates(th):
    """
    Scan DAY_UNIVERSE for stocks with strong news + pre-market setup.
    Returns list of dicts sorted by composite score, best first.
    """
    candidates = []
    log(f"Scanning {len(DAY_UNIVERSE)} stocks for news catalysts...")
    for ticker in DAY_UNIVERSE:
        news = score_news(ticker)
        if news["score"] < th["news_score"]:
            continue

        pm = get_premarket(ticker)
        # Composite: news score + volume bonus + gap bonus
        composite = news["score"]
        vol_note  = ""
        gap_note  = ""

        if pm:
            if pm["volume_ratio"] >= th["volume_ratio"]:
                composite += 2
                vol_note = f"vol {pm['volume_ratio']:.1f}×avg"
            if abs(pm["gap_pct"]) >= 3:
                composite += 2
                gap_note = f"gap {pm['gap_pct']:+.1f}%"
            elif abs(pm["gap_pct"]) >= 1.5:
                composite += 1
                gap_note = f"gap {pm['gap_pct']:+.1f}%"

        log(f"  {ticker}: news={news['score']} composite={composite} | {news['category']} | {vol_note} {gap_note} | '{news['title'][:50]}'")
        candidates.append({
            "ticker":    ticker,
            "composite": composite,
            "news":      news,
            "pm":        pm,
            "vol_note":  vol_note,
            "gap_note":  gap_note,
        })

    candidates.sort(key=lambda x: x["composite"], reverse=True)
    return candidates

# ── Execute paper buy ─────────────────────────────────────────────────
def execute_buy(ledger, ticker, price, ind, strategy, news, target_pct=None):
    th        = get_thresholds(ledger)
    buying_pw = ledger["equity"] * th["leverage"]
    deployed  = sum(p["shares"] * p["entry"] for p in ledger["open_positions"].values())
    available = min(buying_pw - deployed, ledger["cash"])
    to_spend  = min(12_000, max(available, 0))  # up to $12k per focus trade

    if to_spend < 500:
        log(f"[TRADE] {ticker} — insufficient funds (${to_spend:.0f} available)")
        return None

    shares    = int(to_spend / price)
    cost      = round(shares * price, 2)
    stop      = round(price * 0.985, 2)             # 1.5% tight intraday stop
    tpct      = target_pct or dynamic_target_pct(price)
    target    = round(price * (1 + tpct / 100), 2)  # dynamic by price tier
    entry_time = datetime.datetime.now().isoformat()

    ledger["open_positions"][ticker] = {
        "name":        ticker,
        "entry":       price,
        "stop":        stop,
        "target":      target,
        "target_pct":  tpct,
        "shares":      shares,
        "strategy":    strategy,
        "news_cat":    news.get("category", ""),
        "news_score":  news.get("score", 0),
        "entry_time":  entry_time,
        "held_overnight": False,
        "trailing_stop":  None,   # activated once gain > 1%
    }
    ledger["cash"] = round(ledger["cash"] - cost, 2)

    tr = {
        "date":         datetime.date.today().isoformat(),
        "time":         datetime.datetime.now().strftime("%H:%M"),
        "action":       "BUY",
        "ticker":       ticker,
        "shares":       shares,
        "price":        price,
        "cost":         cost,
        "strategy":     strategy,
        "news_cat":     news.get("category", ""),
        "news_score":   news.get("score", 0),
        "news_title":   news.get("title", ""),
        "rsi_5m":       ind["rsi"] if ind else None,
        "macd_h_5m":    ind["histogram"] if ind else None,
        "stop":         stop,
        "target":       target,
    }
    ledger["trades"].append(tr)
    log(f"[TRADE] BUY {shares}×{ticker} @ ${price:.2f} = ${cost:.2f} [{strategy}] RSI={ind['rsi'] if ind else '?'}")
    return tr

# ── Execute paper sell ────────────────────────────────────────────────
def execute_sell(ledger, ticker, price, reason, exit_ind=None):
    if ticker not in ledger["open_positions"]:
        log(f"[WARN] {ticker} not in open positions")
        return None

    pos       = ledger["open_positions"].pop(ticker)
    shares    = pos["shares"]
    proceeds  = round(shares * price, 2)
    cost      = shares * pos["entry"]
    pnl       = round(proceeds - cost, 2)
    pnl_pct   = round(pnl / cost * 100, 2)
    ledger["cash"] = round(ledger["cash"] + proceeds, 2)

    # Calculate hold time in minutes
    try:
        entry_dt  = datetime.datetime.fromisoformat(pos["entry_time"])
        hold_min  = int((datetime.datetime.now() - entry_dt).total_seconds() / 60)
    except Exception:
        hold_min  = 0

    hold_type = "overnight" if pos.get("held_overnight") else "same_day"

    tr = {
        "date":         datetime.date.today().isoformat(),
        "time":         datetime.datetime.now().strftime("%H:%M"),
        "action":       "SELL",
        "ticker":       ticker,
        "shares":       shares,
        "price":        price,
        "proceeds":     proceeds,
        "pnl":          pnl,
        "pnl_pct":      pnl_pct,
        "reason":       reason,
        "strategy":     pos.get("strategy", ""),
        "news_cat":     pos.get("news_cat", ""),
        "hold_minutes": hold_min,
        "hold_type":    hold_type,
        "exit_rsi_5m":  exit_ind["rsi"] if exit_ind else None,
        "exit_macd_h":  exit_ind["histogram"] if exit_ind else None,
    }
    ledger["trades"].append(tr)
    log(f"[TRADE] SELL {shares}×{ticker} @ ${price:.2f} P&L=${pnl:+.2f} ({pnl_pct:+.1f}%) [{reason}] held={hold_min}min")

    update_learning(ledger, tr)
    return tr

# ── Check overnight hold conditions ──────────────────────────────────
def check_overnight(ledger, ticker, current_price, ind):
    """Returns True if position should be held overnight."""
    th  = get_thresholds(ledger)
    pos = ledger["open_positions"].get(ticker)
    if not pos or not th["overnight"]:
        return False

    pnl_pct = (current_price - pos["entry"]) / pos["entry"] * 100
    cond1 = pnl_pct >= th["overnight_min"]     # profitable enough
    cond2 = ind and ind["histogram"] > 0        # MACD still positive
    cond3 = pnl_pct < 10                        # not already overbought

    result = cond1 and cond2 and cond3
    log(f"[OVERNIGHT] {ticker}: gain={pnl_pct:+.1f}% MACD={'pos' if (ind and ind['histogram']>0) else 'neg'} → {'HOLD' if result else 'CLOSE'}")
    return result

# ── Self-learning engine ──────────────────────────────────────────────
def update_learning(ledger, sell_trade):
    ensure_learning(ledger)
    L     = ledger["learning"]
    stats = L["stats"]
    pnl   = sell_trade["pnl_pct"]
    won   = pnl > 0
    strat = sell_trade.get("strategy", "momentum")
    hold  = sell_trade.get("hold_type", "same_day")
    cat   = sell_trade.get("news_cat", "unknown")
    mins  = sell_trade.get("hold_minutes", 0)

    n = stats["total_closed"]
    stats["total_closed"] += 1
    if won:
        stats["wins"] += 1
        stats["avg_gain_pct"] = round(
            (stats["avg_gain_pct"] * (stats["wins"] - 1) + pnl) / stats["wins"], 2)
    else:
        stats["losses"] += 1
        stats["avg_loss_pct"] = round(
            (stats["avg_loss_pct"] * (stats["losses"] - 1) + pnl) / stats["losses"], 2)
    stats["avg_hold_minutes"] = round(
        (stats["avg_hold_minutes"] * n + mins) / (n + 1), 1)

    # Strategy breakdown
    if strat in stats["by_strategy"]:
        g = stats["by_strategy"][strat]
        g["count"] += 1
        if won: g["wins"] += 1
        g["total_gain"] = round(g["total_gain"] + pnl, 2)

    # Hold-type breakdown
    if hold in stats["by_hold"]:
        h = stats["by_hold"][hold]
        h["count"] += 1
        if won: h["wins"] += 1
        h["total_gain"] = round(h["total_gain"] + pnl, 2)

    # News category breakdown
    if cat:
        if cat not in stats["by_news_category"]:
            stats["by_news_category"][cat] = {"count": 0, "wins": 0, "total_gain": 0.0}
        c = stats["by_news_category"][cat]
        c["count"] += 1
        if won: c["wins"] += 1
        c["total_gain"] = round(c["total_gain"] + pnl, 2)

    L["last_updated"] = datetime.date.today().isoformat()

    if stats["total_closed"] < 5:
        log(f"[LEARN] {stats['total_closed']}/5 trades before adapting thresholds")
        return

    adj = []
    win_rate = stats["wins"] / stats["total_closed"]

    # Rule 1 — Strategy preference: if momentum < 40% wins, require MACD for momentum
    mom = stats["by_strategy"]["momentum"]
    rev = stats["by_strategy"]["reversal"]
    if mom["count"] >= 5:
        mom_wr = mom["wins"] / mom["count"]
        if mom_wr < 0.40 and L["momentum_rsi_max"] > 50:
            L["momentum_rsi_max"] -= 5
            msg = f"Momentum RSI ceiling {L['momentum_rsi_max']+5} → {L['momentum_rsi_max']} (momentum win rate {mom_wr:.0%})"
            adj.append(msg); log(f"[LEARN] {msg}")
        elif mom_wr > 0.70 and L["momentum_rsi_max"] < 60:
            L["momentum_rsi_max"] += 3
            msg = f"Momentum RSI ceiling {L['momentum_rsi_max']-3} → {L['momentum_rsi_max']} (momentum win rate {mom_wr:.0%} — easing)"
            adj.append(msg); log(f"[LEARN] {msg}")

    if rev["count"] >= 5:
        rev_wr = rev["wins"] / rev["count"]
        if rev_wr > 0.70 and L["reversal_rsi_max"] < 40:
            L["reversal_rsi_max"] += 3
            msg = f"Reversal RSI threshold → {L['reversal_rsi_max']} (reversal win rate {rev_wr:.0%} — catching more entries)"
            adj.append(msg); log(f"[LEARN] {msg}")

    # Rule 2 — News score threshold
    if stats["total_closed"] >= 8:
        if win_rate < 0.40 and L["news_score_threshold"] < 6:
            L["news_score_threshold"] += 1
            msg = f"News score threshold {L['news_score_threshold']-1} → {L['news_score_threshold']} (overall win rate {win_rate:.0%})"
            adj.append(msg); log(f"[LEARN] {msg}")
        elif win_rate > 0.72 and L["news_score_threshold"] > 3:
            L["news_score_threshold"] -= 1
            msg = f"News score threshold {L['news_score_threshold']+1} → {L['news_score_threshold']} (win rate {win_rate:.0%} — easing filter)"
            adj.append(msg); log(f"[LEARN] {msg}")

    # Rule 3 — Overnight holds: disable if consistently losing
    ov = stats["by_hold"]["overnight"]
    if ov["count"] >= 5:
        ov_wr = ov["wins"] / ov["count"]
        if ov_wr < 0.35 and L["overnight_enabled"]:
            L["overnight_enabled"] = False
            msg = f"Overnight holds DISABLED — win rate only {ov_wr:.0%} on {ov['count']} trades"
            adj.append(msg); log(f"[LEARN] {msg}")
        elif ov_wr > 0.70 and not L["overnight_enabled"]:
            L["overnight_enabled"] = True
            msg = f"Overnight holds RE-ENABLED — win rate improved to {ov_wr:.0%}"
            adj.append(msg); log(f"[LEARN] {msg}")
        if ov["count"] >= 3 and ov_wr > 0.65:
            L["overnight_min_gain_pct"] = max(1.0, L["overnight_min_gain_pct"] - 0.5)
            msg = f"Overnight gain threshold → {L['overnight_min_gain_pct']}% (overnight performing well)"
            adj.append(msg)

    # Rule 4 — Leverage: reduce if max daily loss hit frequently
    if stats.get("max_daily_loss_days", 0) >= 3 and L["leverage"] > 1.5:
        L["leverage"] = round(L["leverage"] - 0.5, 1)
        msg = f"Leverage {L['leverage']+0.5}× → {L['leverage']}× (too many max-loss days)"
        adj.append(msg); log(f"[LEARN] {msg}")

    if adj:
        L["adjustments"].append({
            "date":          datetime.date.today().isoformat(),
            "changes":       adj,
            "win_rate":      round(win_rate, 3),
            "total_closed":  stats["total_closed"],
        })

def build_learning_summary(ledger):
    ensure_learning(ledger)
    L     = ledger["learning"]
    stats = L["stats"]
    n     = stats["total_closed"]

    if n == 0:
        ntfy = ["", "LEARNING ENGINE", "  No closed day trades yet — building baseline..."]
        html = "<p style='color:#64748b;font-style:italic;'>No closed day trades yet — learning starts after first sell.</p>"
        return ntfy, html

    win_rate = stats["wins"] / n
    conf     = "🔴 LOW" if n < 5 else ("🟡 MEDIUM" if n < 15 else "🟢 HIGH")

    # Best and worst news category
    cats = stats["by_news_category"]
    cat_lines = []
    for cat, data in sorted(cats.items(), key=lambda x: x[1]["total_gain"], reverse=True):
        if data["count"] > 0:
            wr  = data["wins"] / data["count"]
            avg = data["total_gain"] / data["count"]
            cat_lines.append(f"  {cat.replace('_',' ').title()}: {data['wins']}/{data['count']} ({wr:.0%}) avg {avg:+.1f}%")

    strat_lines = []
    for s, label in [("momentum","Momentum"), ("reversal","Reversal")]:
        d = stats["by_strategy"][s]
        if d["count"] > 0:
            wr  = d["wins"] / d["count"]
            avg = d["total_gain"] / d["count"]
            strat_lines.append(f"  {label}: {d['wins']}/{d['count']} ({wr:.0%}) avg {avg:+.1f}%")

    hold_lines = []
    for h, label in [("same_day","Same-day close"), ("overnight","Overnight hold")]:
        d = stats["by_hold"][h]
        if d["count"] > 0:
            wr  = d["wins"] / d["count"]
            avg = d["total_gain"] / d["count"]
            hold_lines.append(f"  {label}: {d['wins']}/{d['count']} ({wr:.0%}) avg {avg:+.1f}%")

    last_adj = ""
    if L["adjustments"]:
        a = L["adjustments"][-1]
        last_adj = f"Last adapt ({a['date']}): " + "; ".join(a["changes"])

    ntfy = [
        "", "🧠 DAY TRADING LEARNING ENGINE",
        f"  Confidence: {conf} ({n} closed trades)",
        f"  Win rate: {stats['wins']}/{n} ({win_rate:.0%}) | Avg gain: {stats['avg_gain_pct']:+.1f}% | Avg loss: {stats['avg_loss_pct']:+.1f}%",
        f"  Avg hold: {stats['avg_hold_minutes']:.0f} min | Overnight holds: {'enabled' if L['overnight_enabled'] else 'DISABLED'}",
        f"  Thresholds → News≥{L['news_score_threshold']} | Vol≥{L['min_volume_ratio']}× | Lev={L['leverage']}× | Overnight min gain {L['overnight_min_gain_pct']}%",
        "  — Strategy —",
    ] + strat_lines + ["  — Hold type —"] + hold_lines + ["  — By news category —"] + cat_lines[:5]

    if last_adj:
        ntfy.append(f"  ⚙️  {last_adj}")

    rows_html = ""
    for cat, data in sorted(cats.items(), key=lambda x: x[1]["total_gain"], reverse=True):
        if data["count"] > 0:
            wr  = data["wins"] / data["count"]
            avg = data["total_gain"] / data["count"]
            color = "#16a34a" if avg > 0 else "#dc2626"
            rows_html += f"""<tr>
              <td style='padding:5px 10px;'>{cat.replace('_',' ').title()}</td>
              <td style='padding:5px 10px;text-align:center;'>{data['count']}</td>
              <td style='padding:5px 10px;text-align:center;'>{wr:.0%}</td>
              <td style='padding:5px 10px;text-align:right;color:{color};font-weight:bold;'>{avg:+.1f}%</td>
            </tr>"""

    html = f"""
<div style="background:#f0fdf4;border-left:4px solid #22c55e;border-radius:6px;padding:16px 20px;margin-top:20px;">
  <h3 style="margin:0 0 10px;color:#15803d;font-size:15px;">🧠 Day Trade Learning Engine</h3>
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;font-size:13px;">
    <span><b>Confidence:</b> {conf}</span>
    <span><b>Win rate:</b> {stats['wins']}/{n} ({win_rate:.0%})</span>
    <span><b>Avg gain:</b> {stats['avg_gain_pct']:+.1f}%</span>
    <span><b>Avg loss:</b> {stats['avg_loss_pct']:+.1f}%</span>
    <span><b>Avg hold:</b> {stats['avg_hold_minutes']:.0f} min</span>
  </div>
  <table style="width:100%;font-size:13px;border-collapse:collapse;">
    <tr style="background:#dcfce7;">
      <th style="padding:6px 10px;text-align:left;">News Category</th>
      <th style="padding:6px 10px;text-align:center;">Trades</th>
      <th style="padding:6px 10px;text-align:center;">Win rate</th>
      <th style="padding:6px 10px;text-align:right;">Avg P&amp;L</th>
    </tr>{rows_html}
  </table>
  <div style="margin-top:10px;padding-top:10px;border-top:1px solid #bbf7d0;font-size:12px;color:#15803d;">
    <b>Active thresholds:</b> News≥{L['news_score_threshold']} | Vol≥{L['min_volume_ratio']}× |
    Leverage={L['leverage']}× | Overnight={'enabled (min +' + str(L['overnight_min_gain_pct']) + '%)' if L['overnight_enabled'] else 'DISABLED'}
    {"<br><b>Last adjustment:</b> " + last_adj if last_adj else ""}
  </div>
</div>"""
    return ntfy, html

# ── Build day CSV attachment ──────────────────────────────────────────
def _build_day_csv(trades):
    import csv
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["Date","Time","Action","Ticker","Shares","Price","Total ($)",
                "Strategy","News Category","News Score","RSI 5m","MACD Hist 5m",
                "P&L ($)","P&L %","Hold (min)","Hold Type","Reason","News Headline"])
    for tr in trades:
        cost = tr.get("cost") or tr.get("proceeds", 0)
        w.writerow([
            tr["date"], tr.get("time",""), tr["action"], tr["ticker"],
            tr["shares"], f"{tr['price']:.2f}", f"{cost:.2f}",
            tr.get("strategy",""), tr.get("news_cat",""), tr.get("news_score",""),
            tr.get("rsi_5m","") or tr.get("exit_rsi_5m",""),
            tr.get("macd_h_5m","") or tr.get("exit_macd_h",""),
            f"{tr['pnl']:+.2f}" if "pnl" in tr else "",
            f"{tr['pnl_pct']:+.1f}%" if "pnl_pct" in tr else "",
            tr.get("hold_minutes",""), tr.get("hold_type",""),
            tr.get("reason",""), tr.get("news_title","")[:80],
        ])
    return buf.getvalue()

# ── Notification builders ─────────────────────────────────────────────
def send_day_report(ledger, trades_today, candidates, alerts, mode="close"):
    """Send end-of-day email (full log + CSV) + ntfy (summary)."""
    now_str  = datetime.datetime.now().strftime("%b %d, %Y %H:%M IDT")
    date_str = datetime.date.today().isoformat()
    today_sells = [t for t in trades_today if t["action"] == "SELL"]
    today_buys  = [t for t in trades_today if t["action"] == "BUY"]

    day_pnl = sum(t["pnl"] for t in today_sells)
    equity  = ledger["equity"]
    day_pnl_pct = (day_pnl / equity * 100) if equity else 0
    all_time_pnl = ledger.get("cash", 25000) + sum(
        p["shares"] * p["entry"] for p in ledger["open_positions"].values()
    ) - ledger["start_value"]

    pnl_emoji = "📈" if day_pnl >= 0 else "📉"
    pnl_sign  = "+" if day_pnl >= 0 else ""

    learn_ntfy, learn_html = build_learning_summary(ledger)

    # ── ntfy body (compact) ───────────────────────────────────────
    ntfy_lines = [
        f"{pnl_emoji} Day P&L: {pnl_sign}${day_pnl:,.2f} ({pnl_sign}{day_pnl_pct:.1f}%)",
        "",
    ] + _budget_lines(ledger) + [
        "",
        f"📊 Trades today: {len(today_buys)} buys | {len(today_sells)} sells",
        "",
    ]
    if today_sells:
        ntfy_lines.append("TODAY'S CLOSED TRADES")
        for tr in today_sells:
            sign  = "+" if tr["pnl"] >= 0 else ""
            dot   = "🟢" if tr["pnl"] >= 0 else "🔴"
            ntfy_lines.append(
                f"{dot} {tr['ticker']} {sign}${tr['pnl']:,.0f} ({sign}{tr['pnl_pct']:.1f}%)"
                f" [{tr.get('strategy','')}] {tr.get('hold_minutes',0)}min | {tr.get('reason','')}"
            )

    if ledger["open_positions"]:
        ntfy_lines += ["", "OPEN POSITIONS (held overnight)"]
        for t, p in ledger["open_positions"].items():
            ntfy_lines.append(f"🔵 {t} {p['shares']}sh @ ${p['entry']:.2f} | stop ${p['stop']:.2f}")

    if candidates:
        ntfy_lines += ["", f"TOP CANDIDATES SCANNED TODAY"]
        for c in candidates[:3]:
            ntfy_lines.append(
                f"  {c['ticker']}: score={c['composite']} | {c['news']['category'].replace('_',' ')} | {c['vol_note']} {c['gap_note']}"
            )

    ntfy_lines += learn_ntfy

    if alerts:
        ntfy_lines += ["", "ALERTS"]
        ntfy_lines += [f"⚠️ {a}" for a in alerts]

    # ── Email HTML ────────────────────────────────────────────────
    trade_rows = ""
    for tr in ledger["trades"]:
        action  = tr["action"]
        pnl_str = f"{tr['pnl']:+.2f}" if "pnl" in tr else "—"
        bg      = "#f0fdf4" if action == "BUY" else ("#fef2f2" if tr.get("pnl_pct", 0) < 0 else "#f0fdf4")
        color   = "#16a34a" if action == "BUY" else ("#dc2626" if tr.get("pnl_pct", 0) < 0 else "#16a34a")
        cost    = tr.get("cost") or tr.get("proceeds", 0)
        trade_rows += f"""
        <tr style="background:{bg};">
          <td style="padding:8px 10px;color:#64748b;font-size:12px;">{tr['date']}</td>
          <td style="padding:8px 10px;color:#64748b;font-size:11px;">{tr.get('time','')}</td>
          <td style="padding:8px 10px;font-weight:bold;color:{color};">{action}</td>
          <td style="padding:8px 10px;font-weight:bold;">{tr['ticker']}</td>
          <td style="padding:8px 10px;text-align:right;">{tr['shares']}</td>
          <td style="padding:8px 10px;text-align:right;">${tr['price']:.2f}</td>
          <td style="padding:8px 10px;text-align:right;font-weight:bold;">${cost:,.2f}</td>
          <td style="padding:8px 10px;text-align:center;font-size:11px;">{tr.get('strategy','')}</td>
          <td style="padding:8px 10px;font-size:11px;color:#64748b;">{tr.get('news_cat','').replace('_',' ')}</td>
          <td style="padding:8px 10px;text-align:center;">{tr.get('rsi_5m','') or tr.get('exit_rsi_5m','') or '—'}</td>
          <td style="padding:8px 10px;text-align:right;color:{color};">{pnl_str}</td>
          <td style="padding:8px 10px;text-align:center;font-size:11px;">{tr.get('hold_minutes','—')}</td>
          <td style="padding:8px 10px;font-size:11px;color:#94a3b8;">{tr.get('reason','') or tr.get('news_title','')[:40]}</td>
        </tr>"""

    news_rows = ""
    for c in (candidates or [])[:8]:
        score = c["composite"]
        bg    = "#f0fdf4" if score >= 6 else ("#fffbeb" if score >= 4 else "#f8fafc")
        news_rows += f"""
        <tr style="background:{bg};">
          <td style="padding:7px 10px;font-weight:bold;">{c['ticker']}</td>
          <td style="padding:7px 10px;text-align:center;font-weight:bold;">{score}</td>
          <td style="padding:7px 10px;">{c['news']['category'].replace('_',' ').title()}</td>
          <td style="padding:7px 10px;font-size:11px;">{c['news']['title'][:60]}</td>
          <td style="padding:7px 10px;text-align:center;">{c['news']['age_hours']:.0f}h ago</td>
          <td style="padding:7px 10px;text-align:center;">{c['vol_note'] or '—'}</td>
          <td style="padding:7px 10px;text-align:center;">{c['gap_note'] or '—'}</td>
        </tr>"""

    pnl_color = "#16a34a" if day_pnl >= 0 else "#dc2626"

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Calibri,Arial,sans-serif;background:#f8fafc;padding:24px;color:#1e293b;">
<div style="max-width:900px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);">
  <div style="background:linear-gradient(135deg,#0f172a,#064e3b);padding:28px 32px;">
    <h1 style="color:#fff;margin:0;font-size:22px;">📊 Day Trade Report</h1>
    <p style="color:#94a3b8;margin:6px 0 0;">{now_str} &nbsp;|&nbsp; Capital: $25,000 &nbsp;|&nbsp; Leverage: {ledger['learning'].get('leverage',2.0)}×</p>
  </div>
  <div style="padding:24px 32px;">

    {_budget_html(ledger)}

    <!-- Summary cards -->
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px;">
      <div style="background:#f1f5f9;border-radius:10px;padding:14px 20px;flex:1;min-width:140px;text-align:center;">
        <div style="font-size:11px;color:#64748b;">Today P&L</div>
        <div style="font-size:24px;font-weight:bold;color:{pnl_color};">{pnl_sign}${day_pnl:,.2f}</div>
        <div style="color:{pnl_color};font-size:12px;">{pnl_sign}{day_pnl_pct:.2f}%</div>
      </div>
      <div style="background:#f1f5f9;border-radius:10px;padding:14px 20px;flex:1;min-width:140px;text-align:center;">
        <div style="font-size:11px;color:#64748b;">Cash Available</div>
        <div style="font-size:24px;font-weight:bold;">${ledger['cash']:,.2f}</div>
        <div style="color:#64748b;font-size:12px;">of $25,000 capital</div>
      </div>
      <div style="background:#f1f5f9;border-radius:10px;padding:14px 20px;flex:1;min-width:140px;text-align:center;">
        <div style="font-size:11px;color:#64748b;">Trades Today</div>
        <div style="font-size:24px;font-weight:bold;">{len(today_buys)}B / {len(today_sells)}S</div>
        <div style="color:#64748b;font-size:12px;">buys / sells</div>
      </div>
      <div style="background:#f1f5f9;border-radius:10px;padding:14px 20px;flex:1;min-width:140px;text-align:center;">
        <div style="font-size:11px;color:#64748b;">All-time P&L</div>
        <div style="font-size:24px;font-weight:bold;color:{'#16a34a' if all_time_pnl>=0 else '#dc2626'};">{'+' if all_time_pnl>=0 else ''}${all_time_pnl:,.2f}</div>
        <div style="color:#64748b;font-size:12px;">{'+' if all_time_pnl>=0 else ''}{all_time_pnl/ledger['start_value']*100:.2f}%</div>
      </div>
    </div>

    <!-- Trade log -->
    <h3 style="margin:0 0 10px;color:#1e293b;">📋 Complete Trade Log</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
      <thead>
        <tr style="background:#1e293b;color:#fff;">
          <th style="padding:8px 10px;text-align:left;">Date</th>
          <th style="padding:8px 10px;text-align:left;">Time</th>
          <th style="padding:8px 10px;text-align:left;">Action</th>
          <th style="padding:8px 10px;text-align:left;">Ticker</th>
          <th style="padding:8px 10px;text-align:right;">Shares</th>
          <th style="padding:8px 10px;text-align:right;">Price</th>
          <th style="padding:8px 10px;text-align:right;">Total</th>
          <th style="padding:8px 10px;text-align:center;">Strategy</th>
          <th style="padding:8px 10px;text-align:left;">Category</th>
          <th style="padding:8px 10px;text-align:center;">RSI 5m</th>
          <th style="padding:8px 10px;text-align:right;">P&amp;L</th>
          <th style="padding:8px 10px;text-align:center;">Hold</th>
          <th style="padding:8px 10px;text-align:left;">Note</th>
        </tr>
      </thead>
      <tbody>{trade_rows}</tbody>
    </table>

    <!-- News scanned today -->
    {"" if not candidates else f'''
    <h3 style="margin:24px 0 10px;color:#1e293b;">📰 News Scanned Today</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
      <thead>
        <tr style="background:#334155;color:#fff;">
          <th style="padding:7px 10px;text-align:left;">Ticker</th>
          <th style="padding:7px 10px;text-align:center;">Score</th>
          <th style="padding:7px 10px;text-align:left;">Category</th>
          <th style="padding:7px 10px;text-align:left;">Headline</th>
          <th style="padding:7px 10px;text-align:center;">Age</th>
          <th style="padding:7px 10px;text-align:center;">Volume</th>
          <th style="padding:7px 10px;text-align:center;">Gap</th>
        </tr>
      </thead>
      <tbody>{news_rows}</tbody>
    </table>'''}

    {learn_html}

  </div>
</div>
</body></html>"""

    plain = f"Day Trade Report — {now_str}\nDay P&L: {pnl_sign}${day_pnl:,.2f} ({pnl_sign}{day_pnl_pct:.1f}%)\n\n"
    plain += "\n".join(ntfy_lines)

    # CSV attachment — full trade history
    csv_str  = _build_day_csv(ledger["trades"])
    csv_b64  = base64.b64encode(csv_str.encode("utf-8")).decode("ascii")
    filename = f"day_trades_{date_str}.csv"
    attachments = [{"filename": filename, "content": csv_b64}]

    wins = len([t for t in today_sells if t.get("pnl", 0) > 0])
    subject = (f"📊 Day Trade — {pnl_sign}${day_pnl:,.2f} ({pnl_sign}{day_pnl_pct:.1f}%)"
               f" | {wins}/{len(today_sells)} wins | {date_str}")
    send_email(subject, html, plain, attachments=attachments)
    log(f"[REPORT] Email sent — {len(ledger['trades'])} total trades + CSV")

    # ntfy
    ntfy_title = f"{'📈' if day_pnl>=0 else '📉'} Day Trade | {pnl_sign}${day_pnl:,.0f} | {date_str}"
    send_ntfy(ntfy_title, "\n".join(ntfy_lines),
              priority="default", tags="chart_with_upwards_trend" if day_pnl >= 0 else "chart_with_downwards_trend")

def _budget_lines(ledger):
    """Return budget summary lines for every notification."""
    th         = get_thresholds(ledger)
    equity     = ledger["equity"]
    cash       = ledger["cash"]
    lev        = th["leverage"]
    buying_pw  = equity * lev
    deployed   = sum(p["shares"] * p["entry"] for p in ledger["open_positions"].values())
    available  = round(buying_pw - deployed, 2)
    open_pos   = len(ledger["open_positions"])
    all_pnl    = round(equity - ledger["start_value"], 2)
    pnl_sign   = "+" if all_pnl >= 0 else ""
    return [
        f"💼 BUDGET  Equity: ${equity:,.2f} | Cash: ${cash:,.2f} | Leverage: {lev}×",
        f"   Buying power: ${buying_pw:,.2f} | Available: ${available:,.2f} | Open: {open_pos} position(s)",
        f"   All-time P&L: {pnl_sign}${all_pnl:,.2f} ({pnl_sign}{all_pnl/ledger['start_value']*100:.2f}%)",
    ]

def _budget_html(ledger):
    """Return budget summary HTML card for every email."""
    th        = get_thresholds(ledger)
    equity    = ledger["equity"]
    cash      = ledger["cash"]
    lev       = th["leverage"]
    buying_pw = equity * lev
    deployed  = sum(p["shares"] * p["entry"] for p in ledger["open_positions"].values())
    available = round(buying_pw - deployed, 2)
    all_pnl   = round(equity - ledger["start_value"], 2)
    pnl_color = "#16a34a" if all_pnl >= 0 else "#dc2626"
    pnl_sign  = "+" if all_pnl >= 0 else ""
    return f"""
<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 20px;margin-bottom:20px;display:flex;gap:20px;flex-wrap:wrap;">
  <div style="text-align:center;flex:1;min-width:110px;">
    <div style="font-size:11px;color:#64748b;">Equity</div>
    <div style="font-size:20px;font-weight:bold;">${equity:,.2f}</div>
  </div>
  <div style="text-align:center;flex:1;min-width:110px;">
    <div style="font-size:11px;color:#64748b;">Cash</div>
    <div style="font-size:20px;font-weight:bold;">${cash:,.2f}</div>
  </div>
  <div style="text-align:center;flex:1;min-width:110px;">
    <div style="font-size:11px;color:#64748b;">Leverage</div>
    <div style="font-size:20px;font-weight:bold;">{lev}×</div>
  </div>
  <div style="text-align:center;flex:1;min-width:110px;">
    <div style="font-size:11px;color:#64748b;">Buying Power</div>
    <div style="font-size:20px;font-weight:bold;">${buying_pw:,.2f}</div>
  </div>
  <div style="text-align:center;flex:1;min-width:110px;">
    <div style="font-size:11px;color:#64748b;">Available</div>
    <div style="font-size:20px;font-weight:bold;">${available:,.2f}</div>
  </div>
  <div style="text-align:center;flex:1;min-width:110px;">
    <div style="font-size:11px;color:#64748b;">All-time P&L</div>
    <div style="font-size:20px;font-weight:bold;color:{pnl_color};">{pnl_sign}${all_pnl:,.2f}</div>
    <div style="font-size:11px;color:{pnl_color};">{pnl_sign}{all_pnl/ledger['start_value']*100:.2f}%</div>
  </div>
</div>"""

def send_scan_alert(candidates, th, ledger):
    """Send pre-market ntfy + email when strong candidates are found."""
    if not candidates:
        log("[SCAN] No candidates above threshold — no alert sent")
        return

    now_str  = datetime.datetime.now().strftime("%H:%M IDT")
    date_str = datetime.date.today().strftime("%b %d")
    top      = candidates[0]

    lines = [
        f"🔍 Day Trade Scan | {date_str} {now_str}",
        f"Found {len(candidates)} candidate(s) above score {th['news_score']}",
        "",
    ] + _budget_lines(ledger) + ["", "TOP PICKS"]
    for c in candidates[:3]:
        pm_str = ""
        if c["pm"]:
            pm_str = f" | gap {c['pm']['gap_pct']:+.1f}% | vol {c['pm']['volume_ratio']:.1f}×"
        lines.append(
            f"{'🟢' if c['composite']>=7 else '🟡'} #{candidates.index(c)+1} {c['ticker']}"
            f"  score={c['composite']}"
            f"  [{c['news']['category'].replace('_',' ')}]"
            f"  {c['news']['age_hours']:.0f}h ago{pm_str}"
        )
        lines.append(f"   \"{c['news']['title'][:70]}\"")
        lines.append("")

    lines += [
        "STRATEGY",
        f"  RSI entry (momentum): 40 – {th['momentum_rsi']} on 5-min",
        f"  RSI entry (reversal): < {th['reversal_rsi']} on 5-min",
        "  Wait 10 min after open for first candle signal",
        "  Stop-loss: 2% | Target: 4% | Max per trade: $10,000",
    ]

    title = f"🔍 Day Scan | {top['ticker']} score={top['composite']} | {date_str} {now_str}"
    send_ntfy(title, "\n".join(lines), priority="high", tags="mag")

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Calibri,Arial,sans-serif;background:#f8fafc;padding:20px;color:#1e293b;">
<div style="max-width:680px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);">
  <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);padding:24px 28px;">
    <h1 style="color:#fff;margin:0;font-size:20px;">🔍 Pre-Market Day Trade Scan</h1>
    <p style="color:#94a3b8;margin:6px 0 0;">{date_str} {now_str} &nbsp;|&nbsp; {len(candidates)} candidate(s)</p>
  </div>
  <div style="padding:20px 28px;">
    {_budget_html(ledger)}
    <div style="font-family:monospace;font-size:13px;line-height:1.9;">
      {"".join(f"<div style='padding:5px 0;border-bottom:1px solid #f1f5f9;'>{l}</div>" for l in lines)}
    </div>
  </div>
</div></body></html>"""

    subject = f"🔍 Day Scan: {top['ticker']} (score {top['composite']}) — {now_str}"
    send_email(subject, html, "\n".join(lines))
    log(f"[SCAN] Alert sent — top pick: {top['ticker']} score={top['composite']}")

# ── Main modes ────────────────────────────────────────────────────────
def run_scan():
    """Pre-market: scan news + pre-market data, send picks via ntfy + email."""
    log("=" * 55)
    log(f"DAY SCAN — {datetime.date.today()}")
    log("=" * 55)
    ledger = load_ledger()
    ensure_learning(ledger)
    th = get_thresholds(ledger)

    candidates = find_candidates(th)
    if candidates:
        log(f"Top candidate: {candidates[0]['ticker']} (score {candidates[0]['composite']})")
    else:
        log("No candidates above threshold today")

    send_scan_alert(candidates, th, ledger)
    save_ledger(ledger)

def run_enter():
    """
    ~10 min after market open: check 5-min RSI/MACD on top candidates,
    execute paper buy if signal aligns.
    """
    log("=" * 55)
    log(f"DAY ENTER — {datetime.date.today()}")
    log("=" * 55)
    ledger = load_ledger()
    ensure_learning(ledger)
    th      = get_thresholds(ledger)

    # Check max daily loss guard
    today   = datetime.date.today().isoformat()
    day_pnl = sum(t.get("pnl", 0) for t in ledger["trades"]
                  if t["date"] == today and t["action"] == "SELL")
    if day_pnl < -(ledger["equity"] * th["max_loss"] / 100):
        log(f"[GUARD] Max daily loss reached (${day_pnl:.2f}) — no new entries today")
        send_ntfy("⛔ Day Trade", f"Max daily loss reached ({day_pnl:+.2f}) — trading stopped for today",
                  priority="urgent", tags="no_entry")
        return

    candidates = find_candidates(th)
    trades_today = []

    # Check up to 5 candidates — stops once 2 positions are open.
    # Expanding beyond top-2 lets us find clean technicals when the
    # highest-news stocks are already overbought from their gap.
    for c in candidates[:5]:
        ticker = c["ticker"]
        if ticker in ledger["open_positions"]:
            continue
        if len(ledger["open_positions"]) >= 2:
            break

        ind = calc_5min(ticker)
        if not ind:
            log(f"  {ticker}: no 5-min data")
            continue

        log(f"  {ticker}: 5-min RSI={ind['rsi']} MACD_h={ind['histogram']} price=${ind['price']:.2f}")

        strategy = None
        if (40 <= ind["rsi"] <= th["momentum_rsi"]) and ind["histogram"] > 0:
            strategy = "momentum"
            log(f"  {ticker}: MOMENTUM ENTRY — RSI {ind['rsi']} pullback, MACD hist positive")
        elif ind["rsi"] < th["reversal_rsi"] and ind["histogram"] > 0:
            strategy = "reversal"
            log(f"  {ticker}: REVERSAL ENTRY — RSI {ind['rsi']} oversold + MACD hist turning")
        else:
            log(f"  {ticker}: skip — RSI {ind['rsi']} MACD_h {ind['histogram']:+.3f} not aligned")

        if strategy:
            tr = execute_buy(ledger, ticker, ind["price"], ind, strategy, c["news"])
            if tr:
                trades_today.append(tr)
                send_ntfy(
                    f"🛒 Day Buy: {ticker}",
                    f"{strategy.upper()} | ${ind['price']:.2f} | {tr['shares']}sh | ${tr['cost']:,.0f}\n"
                    f"RSI={ind['rsi']} MACD_h={ind['histogram']:+.3f}\n"
                    f"Stop: ${tr['stop']:.2f} (-2%) | Target: ${tr['target']:.2f} (+4%)\n"
                    f"News ({c['news']['age_hours']:.0f}h ago): {c['news']['title'][:60]}",
                    priority="high", tags="shopping_cart"
                )

    save_ledger(ledger)
    if not trades_today:
        log("[ENTER] No entries made — signals not aligned")

def run_close():
    """End of day: close all open positions, check overnight conditions, send report."""
    log("=" * 55)
    log(f"DAY CLOSE — {datetime.date.today()}")
    log("=" * 55)
    ledger = load_ledger()
    ensure_learning(ledger)
    th = get_thresholds(ledger)

    trades_today = [t for t in ledger["trades"]
                    if t["date"] == datetime.date.today().isoformat()]
    alerts   = []
    held_ov  = []

    for ticker in list(ledger["open_positions"].keys()):
        ind = calc_5min(ticker)
        price = ind["price"] if ind else ledger["open_positions"][ticker]["entry"]

        if check_overnight(ledger, ticker, price, ind) and th["overnight"]:
            ledger["open_positions"][ticker]["held_overnight"] = True
            held_ov.append(ticker)
            pnl_pct = (price - ledger["open_positions"][ticker]["entry"]) / ledger["open_positions"][ticker]["entry"] * 100
            log(f"[OVERNIGHT] {ticker} kept overnight: price=${price:.2f} gain={pnl_pct:+.1f}%")
            alerts.append(f"{ticker} held overnight — {pnl_pct:+.1f}% gain, MACD positive")
        else:
            tr = execute_sell(ledger, ticker, price, "end_of_day", exit_ind=ind)
            if tr:
                trades_today.append(tr)

    # Update equity
    open_value = sum(p["shares"] * p["entry"] for p in ledger["open_positions"].values())
    ledger["equity"] = round(ledger["cash"] + open_value, 2)

    # Record daily P&L
    today = datetime.date.today().isoformat()
    day_sells = [t for t in trades_today if t["action"] == "SELL"]
    ledger["daily_pnl"][today] = round(sum(t.get("pnl", 0) for t in day_sells), 2)

    # Check max daily loss for learning stats
    day_pnl = ledger["daily_pnl"][today]
    if day_pnl < -(ledger["start_value"] * th["max_loss"] / 100):
        ledger["learning"]["stats"]["max_daily_loss_days"] = \
            ledger["learning"]["stats"].get("max_daily_loss_days", 0) + 1

    save_ledger(ledger)

    # Send ntfy-only quick confirmation — full report comes at 23:15 inside swing monitor
    today_sells = [t for t in trades_today if t["action"] == "SELL"]
    day_pnl_val = ledger["daily_pnl"].get(today, 0)
    pnl_sign    = "+" if day_pnl_val >= 0 else ""
    ntfy_lines  = [
        f"{'📈' if day_pnl_val>=0 else '📉'} Day positions closed | {pnl_sign}${day_pnl_val:,.2f}",
        "",
    ] + _budget_lines(ledger)
    if held_ov:
        ntfy_lines += ["", f"🔵 Held overnight: {', '.join(held_ov)}"]
    if today_sells:
        ntfy_lines += ["", "TRADES CLOSED"]
        for tr in today_sells:
            sign = "+" if tr["pnl"] >= 0 else ""
            ntfy_lines.append(f"{'🟢' if tr['pnl']>=0 else '🔴'} {tr['ticker']} {sign}${tr['pnl']:,.0f} ({sign}{tr['pnl_pct']:.1f}%) [{tr.get('strategy','')}]")
    ntfy_lines.append("")
    ntfy_lines.append("📧 Full combined report coming at 23:15 IDT")
    send_ntfy(
        f"{'📈' if day_pnl_val>=0 else '📉'} Day Close | {pnl_sign}${day_pnl_val:,.0f} | {today}",
        "\n".join(ntfy_lines),
        priority="default",
        tags="white_check_mark"
    )
    log("[CLOSE] ntfy sent — full email report will be included in swing monitor at 23:15")

def get_day_summary():
    """
    Called by sim_monitor.py and sim_premarket.py to embed day trade status
    in the combined daily report. Returns (ntfy_lines, html_block, plain_text).
    """
    if not os.path.exists(DAY_LEDGER_PATH):
        return ["", "📊 DAY TRADE  No day ledger found."], "", ""

    ledger      = load_ledger()
    ensure_learning(ledger)
    today       = datetime.date.today().isoformat()
    th          = get_thresholds(ledger)
    equity      = ledger["equity"]
    cash        = ledger["cash"]
    lev         = th["leverage"]
    buying_pw   = equity * lev
    deployed    = sum(p["shares"] * p["entry"] for p in ledger["open_positions"].values())
    available   = round(buying_pw - deployed, 2)
    all_pnl     = round(equity - ledger["start_value"], 2)
    pnl_sign    = "+" if all_pnl >= 0 else ""
    day_pnl_val = ledger.get("daily_pnl", {}).get(today, 0)
    day_sign    = "+" if day_pnl_val >= 0 else ""

    today_trades = [t for t in ledger["trades"] if t["date"] == today]
    today_sells  = [t for t in today_trades if t["action"] == "SELL"]
    today_buys   = [t for t in today_trades if t["action"] == "BUY"]

    # ── ntfy lines ────────────────────────────────────────────────
    ntfy = [
        "",
        "━━━ DAY TRADE PORTFOLIO ━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💼 Equity: ${equity:,.2f} | Cash: ${cash:,.2f} | Leverage: {lev}×",
        f"   Buying power: ${buying_pw:,.2f} | Available: ${available:,.2f}",
        f"   Today P&L: {day_sign}${day_pnl_val:,.2f} | All-time: {pnl_sign}${all_pnl:,.2f} ({pnl_sign}{all_pnl/ledger['start_value']*100:.2f}%)",
        f"   Trades today: {len(today_buys)} buys / {len(today_sells)} sells",
    ]
    if today_sells:
        ntfy.append("   Today's closed trades:")
        for tr in today_sells:
            s = "+" if tr["pnl"] >= 0 else ""
            ntfy.append(f"   {'🟢' if tr['pnl']>=0 else '🔴'} {tr['ticker']} {s}${tr['pnl']:,.0f} ({s}{tr['pnl_pct']:.1f}%) [{tr.get('strategy','')}] {tr.get('hold_minutes',0)}min")
    if ledger["open_positions"]:
        ntfy.append("   Open overnight positions:")
        for t, p in ledger["open_positions"].items():
            ntfy.append(f"   🔵 {t} {p['shares']}sh @ ${p['entry']:.2f} | stop ${p['stop']:.2f}")

    # ── HTML block ────────────────────────────────────────────────
    day_pnl_color = "#16a34a" if day_pnl_val >= 0 else "#dc2626"
    all_pnl_color = "#16a34a" if all_pnl >= 0 else "#dc2626"

    trade_rows = ""
    for tr in today_trades:
        cost  = tr.get("cost") or tr.get("proceeds", 0)
        pnl_s = f"{tr['pnl']:+.2f}" if "pnl" in tr else "—"
        bg    = "#f0fdf4" if tr["action"] == "BUY" else ("#fef2f2" if tr.get("pnl_pct", 0) < 0 else "#f0fdf4")
        col   = "#16a34a" if tr["action"] == "BUY" else ("#dc2626" if tr.get("pnl_pct", 0) < 0 else "#16a34a")
        trade_rows += f"""<tr style="background:{bg};">
          <td style="padding:7px 10px;">{tr.get('time','')}</td>
          <td style="padding:7px 10px;font-weight:bold;color:{col};">{tr['action']}</td>
          <td style="padding:7px 10px;font-weight:bold;">{tr['ticker']}</td>
          <td style="padding:7px 10px;text-align:right;">{tr['shares']}</td>
          <td style="padding:7px 10px;text-align:right;">${tr['price']:.2f}</td>
          <td style="padding:7px 10px;text-align:right;">${cost:,.2f}</td>
          <td style="padding:7px 10px;text-align:center;font-size:11px;">{tr.get('strategy','')}</td>
          <td style="padding:7px 10px;text-align:center;">{tr.get('rsi_5m','') or tr.get('exit_rsi_5m','') or '—'}</td>
          <td style="padding:7px 10px;text-align:right;color:{col};font-weight:bold;">{pnl_s}</td>
          <td style="padding:7px 10px;text-align:center;font-size:11px;">{tr.get('hold_minutes','—')}</td>
        </tr>"""

    open_rows = ""
    for t, p in ledger["open_positions"].items():
        open_rows += f"""<tr style="background:#eff6ff;">
          <td style="padding:7px 10px;font-weight:bold;">{t}</td>
          <td style="padding:7px 10px;text-align:right;">{p['shares']}</td>
          <td style="padding:7px 10px;text-align:right;">${p['entry']:.2f}</td>
          <td style="padding:7px 10px;text-align:right;">${p['stop']:.2f}</td>
          <td style="padding:7px 10px;text-align:right;">${p['target']:.2f}</td>
          <td style="padding:7px 10px;font-size:11px;">{p.get('strategy','')}</td>
          <td style="padding:7px 10px;font-size:11px;">{p.get('news_cat','').replace('_',' ')}</td>
        </tr>"""

    no_trades_msg = "<p style='color:#94a3b8;font-style:italic;padding:10px 0;'>No day trades today.</p>" if not today_trades else ""

    html = f"""
<div style="background:#fff;border:2px solid #22c55e;border-radius:12px;padding:20px 24px;margin-top:28px;">
  <h2 style="margin:0 0 14px;color:#15803d;font-size:17px;border-bottom:1px solid #dcfce7;padding-bottom:10px;">
    📊 Day Trade Portfolio — {today}
  </h2>

  <!-- Budget cards -->
  <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
    <div style="background:#f0fdf4;border-radius:8px;padding:12px 16px;flex:1;min-width:110px;text-align:center;">
      <div style="font-size:11px;color:#64748b;">Equity</div>
      <div style="font-size:18px;font-weight:bold;">${equity:,.2f}</div>
    </div>
    <div style="background:#f0fdf4;border-radius:8px;padding:12px 16px;flex:1;min-width:110px;text-align:center;">
      <div style="font-size:11px;color:#64748b;">Cash</div>
      <div style="font-size:18px;font-weight:bold;">${cash:,.2f}</div>
    </div>
    <div style="background:#f0fdf4;border-radius:8px;padding:12px 16px;flex:1;min-width:110px;text-align:center;">
      <div style="font-size:11px;color:#64748b;">Leverage</div>
      <div style="font-size:18px;font-weight:bold;">{lev}×</div>
    </div>
    <div style="background:#f0fdf4;border-radius:8px;padding:12px 16px;flex:1;min-width:110px;text-align:center;">
      <div style="font-size:11px;color:#64748b;">Buying Power</div>
      <div style="font-size:18px;font-weight:bold;">${buying_pw:,.2f}</div>
    </div>
    <div style="background:#f0fdf4;border-radius:8px;padding:12px 16px;flex:1;min-width:110px;text-align:center;">
      <div style="font-size:11px;color:#64748b;">Today P&L</div>
      <div style="font-size:18px;font-weight:bold;color:{day_pnl_color};">{day_sign}${day_pnl_val:,.2f}</div>
    </div>
    <div style="background:#f0fdf4;border-radius:8px;padding:12px 16px;flex:1;min-width:110px;text-align:center;">
      <div style="font-size:11px;color:#64748b;">All-time P&L</div>
      <div style="font-size:18px;font-weight:bold;color:{all_pnl_color};">{pnl_sign}${all_pnl:,.2f}</div>
      <div style="font-size:11px;color:{all_pnl_color};">{pnl_sign}{all_pnl/ledger['start_value']*100:.2f}%</div>
    </div>
  </div>

  {no_trades_msg}
  {"" if not today_trades else f'''
  <h4 style="margin:0 0 8px;color:#334155;">Today's Trades</h4>
  <table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:14px;">
    <thead><tr style="background:#166534;color:#fff;">
      <th style="padding:7px 10px;">Time</th>
      <th style="padding:7px 10px;">Action</th>
      <th style="padding:7px 10px;">Ticker</th>
      <th style="padding:7px 10px;text-align:right;">Shares</th>
      <th style="padding:7px 10px;text-align:right;">Price</th>
      <th style="padding:7px 10px;text-align:right;">Total</th>
      <th style="padding:7px 10px;text-align:center;">Strategy</th>
      <th style="padding:7px 10px;text-align:center;">RSI 5m</th>
      <th style="padding:7px 10px;text-align:right;">P&amp;L</th>
      <th style="padding:7px 10px;text-align:center;">Hold</th>
    </tr></thead>
    <tbody>{trade_rows}</tbody>
  </table>'''}

  {"" if not ledger["open_positions"] else f'''
  <h4 style="margin:0 0 8px;color:#1d4ed8;">Held Overnight 🔵</h4>
  <table style="width:100%;border-collapse:collapse;font-size:12px;">
    <thead><tr style="background:#1d4ed8;color:#fff;">
      <th style="padding:7px 10px;">Ticker</th>
      <th style="padding:7px 10px;text-align:right;">Shares</th>
      <th style="padding:7px 10px;text-align:right;">Entry</th>
      <th style="padding:7px 10px;text-align:right;">Stop</th>
      <th style="padding:7px 10px;text-align:right;">Target</th>
      <th style="padding:7px 10px;">Strategy</th>
      <th style="padding:7px 10px;">News</th>
    </tr></thead>
    <tbody>{open_rows}</tbody>
  </table>'''}
</div>"""

    plain = "\n".join(ntfy)
    return ntfy, html, plain

def run_open():
    """
    16:45 IDT — scan FOCUS_UNIVERSE after first 15 min of trading.
    Uses ORB + VWAP + candlestick patterns + RSI/MACD.
    Enters up to 2 positions. Target: 1-3% intraday. End of day in cash.
    """
    log("=" * 55)
    log(f"DAY OPEN SCAN — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log("=" * 55)
    ledger = load_ledger()
    ensure_learning(ledger)
    th    = get_thresholds(ledger)
    today = datetime.date.today().isoformat()

    today_universe = get_today_universe()
    # Max 3 focus positions open at once (budget: ~$12k each × 3 = $36k on 2× leverage)
    open_focus = [t for t in ledger["open_positions"] if t in today_universe]
    slots      = 3 - len(open_focus)
    if slots <= 0:
        msg = f"Focus slots full: {', '.join(open_focus)} already open."
        log(msg)
        send_ntfy("📊 Open Scan", msg, priority="low", tags="calendar")
        return

    # Check daily loss limit
    day_pnl = ledger.get("daily_pnl", {}).get(today, 0)
    if day_pnl < -(ledger["start_value"] * th["max_loss"] / 100):
        msg = f"Max daily loss reached (${day_pnl:.0f}) — no new open trades."
        log(msg)
        send_ntfy("🛑 Day Limit", msg, priority="high", tags="stop_sign")
        return

    candidates = []
    for ticker in today_universe:
        if ticker in ledger["open_positions"]:
            log(f"  {ticker}: already open — skip")
            continue

        ind     = calc_5min(ticker)
        candles = detect_candles(ticker)
        orb     = calc_vwap_orb(ticker)

        if not ind:
            log(f"  {ticker}: no 5-min data")
            continue

        score, reasons = score_open_signal(ticker, ind, candles, orb)
        tpct = dynamic_target_pct(
            ind["price"],
            candle_score=candles["candle_score"] if candles else 0,
            orb_break=orb["orb_break"] if orb else None,
        )

        log(f"  {ticker}: score={score} RSI={ind['rsi']} MACD_h={ind['histogram']:+.3f}"
            f" candles={candles['patterns'] if candles else []} "
            f" ORB={orb['orb_break'] if orb else '?'} target={tpct}%")

        if score >= 4:
            candidates.append({
                "ticker":  ticker, "score": score, "ind": ind,
                "candles": candles, "orb": orb, "tpct": tpct, "reasons": reasons,
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    new_trades = []
    alerts     = []
    for c in candidates[:slots]:
        ticker = c["ticker"]
        ind    = c["ind"]
        price  = ind["price"]
        news_dummy = {"category": "price_action", "score": c["score"],
                      "title": " | ".join(c["reasons"][:3])}
        tr = execute_buy(ledger, ticker, price, ind,
                         strategy="open_orb", news=news_dummy, target_pct=c["tpct"])
        if tr:
            new_trades.append(tr)
            alerts.append(
                f"{'🟢' if c['score']>=6 else '🔵'} {ticker} @ ${price:.2f} | "
                f"target +{c['tpct']}% | score {c['score']} | "
                + " | ".join(c["reasons"][:3])
            )
            orb_str = f"ORB {c['orb']['orb_break']} " if c["orb"] else ""
            vwap_str = (f"VWAP ${c['orb']['vwap']:.2f} ({'✅' if c['orb']['above_vwap'] else '❌'})"
                        if c["orb"] and c["orb"]["vwap"] else "")
            log(f"[OPEN] ENTERED {ticker} score={c['score']} {orb_str}{vwap_str} "
                f"candles={c['candles']['patterns'] if c['candles'] else []}")

    # Update equity
    open_value      = sum(p["shares"] * p["entry"] for p in ledger["open_positions"].values())
    ledger["equity"] = round(ledger["cash"] + open_value, 2)
    save_ledger(ledger)

    # ── ntfy ──────────────────────────────────────────────────────
    if not new_trades:
        no_entry_lines = [
            f"🔍 Open scan complete — no entries ({len(candidates)} candidates below threshold)",
            "",
        ] + _budget_lines(ledger) + [""]
        for ticker in FOCUS_UNIVERSE:
            ind     = calc_5min(ticker)
            candles = detect_candles(ticker)
            orb     = calc_vwap_orb(ticker)
            if not ind:
                continue
            score, _ = score_open_signal(ticker, ind, candles, orb)
            no_entry_lines.append(
                f"  {ticker}: RSI {ind['rsi']} MACD {'▲' if ind['histogram']>0 else '▼'}"
                f" ORB {orb['orb_break'] if orb else '?'} score={score}"
                + (f" candles: {' '.join(candles['patterns'])}" if candles and candles['patterns'] else "")
            )
        send_ntfy("🔍 Open Scan | No entries", "\n".join(no_entry_lines),
                  priority="low", tags="mag")
    else:
        lines = [
            f"🚀 Open scan | {len(new_trades)} trade(s) entered",
            "",
        ] + _budget_lines(ledger) + [""]
        lines += alerts
        lines += ["", "⏱️ check runs every 30 min — auto-sell at target/stop"]
        send_ntfy(f"🚀 Open scan | {len(new_trades)} entered",
                  "\n".join(lines), priority="urgent", tags="rocket")


def run_check():
    """Every 30 min: check positions vs target/stop/trailing, auto-sell if hit.
    Also re-scans FOCUS_UNIVERSE for new opportunities."""
    log("=" * 55)
    log(f"DAY CHECK — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log("=" * 55)
    ledger = load_ledger()
    ensure_learning(ledger)

    today      = datetime.date.today().isoformat()
    th         = get_thresholds(ledger)
    auto_sells = []
    lines      = [
        f"📊 Day Check | {datetime.datetime.now().strftime('%H:%M IDT')}",
        "",
    ] + _budget_lines(ledger) + [""]

    # ── 1. Review all open positions: target / stop / trailing ────
    for ticker in list(ledger["open_positions"].keys()):
        pos  = ledger["open_positions"][ticker]
        ind  = calc_5min(ticker)
        if not ind:
            lines.append(f"⬜ {ticker} — no data")
            continue

        price    = ind["price"]
        pnl_pct  = round((price - pos["entry"]) / pos["entry"] * 100, 2)
        pnl_usd  = round((price - pos["entry"]) * pos["shares"], 2)
        tgt_pct  = pos.get("target_pct", dynamic_target_pct(price))
        dot      = "🟢" if pnl_pct > 0.3 else ("🔴" if pnl_pct < -0.8 else "🟡")

        log(f"[CHECK] {ticker}: ${price:.2f} P&L={pnl_pct:+.1f}% RSI={ind['rsi']} "
            f"MACD_h={ind['histogram']:+.3f} target=${pos['target']:.2f} stop=${pos['stop']:.2f}")

        # ── Trailing stop: activate once gain > 1%, trail by 0.4%
        if pnl_pct >= 1.0:
            trail_price = round(price * 0.996, 2)   # trail 0.4% below current
            if pos.get("trailing_stop") is None or trail_price > pos["trailing_stop"]:
                pos["trailing_stop"] = trail_price
                log(f"[TRAIL] {ticker}: trailing stop set to ${trail_price:.2f}")

        # ── Auto-sell conditions ───────────────────────────────────
        sell_reason = None
        if price >= pos["target"]:
            sell_reason = f"target_hit_{tgt_pct}pct"
        elif pos.get("trailing_stop") and price <= pos["trailing_stop"]:
            sell_reason = "trailing_stop"
        elif price <= pos["stop"]:
            sell_reason = "stop_loss"
        # Bearish reversal: MACD turns negative + price falling after gain
        elif pnl_pct > 0.5 and ind["histogram"] < 0 and ind["rsi"] > 65:
            sell_reason = "overbought_reversal"

        if sell_reason:
            tr = execute_sell(ledger, ticker, price, sell_reason, exit_ind=ind)
            if tr:
                auto_sells.append(tr)
                sign = "+" if tr["pnl"] >= 0 else ""
                emoji = "🟢" if tr["pnl"] >= 0 else "🔴"
                lines.append(
                    f"{emoji} AUTO-SELL {ticker} @ ${price:.2f}"
                    f" | {sign}${tr['pnl']:,.0f} ({sign}{tr['pnl_pct']:.1f}%)"
                    f" | {sell_reason.replace('_',' ')}"
                )
                log(f"[CHECK] AUTO-SELL {ticker} reason={sell_reason} P&L={sign}${tr['pnl']:.0f}")
        else:
            dist_stop = round((price - pos["stop"]) / price * 100, 2)
            dist_tgt  = round((pos["target"] - price) / price * 100, 2)
            trail_str = f" | trail ${pos['trailing_stop']:.2f}" if pos.get("trailing_stop") else ""
            lines.append(
                f"{dot} {ticker}  ${price:.2f}  P&L: {'+' if pnl_pct>=0 else ''}{pnl_pct:.1f}%"
                f" (${pnl_usd:+.0f})"
                f"  |  stop dist {dist_stop:.1f}%  target in {dist_tgt:.1f}%{trail_str}"
                f"  |  RSI {ind['rsi']}  MACD {'▲' if ind['histogram']>0 else '▼'}"
            )

    # ── Update equity after sells ─────────────────────────────────
    if auto_sells:
        open_val        = sum(p["shares"] * p["entry"] for p in ledger["open_positions"].values())
        ledger["equity"] = round(ledger["cash"] + open_val, 2)
        day_sells = [t for t in ledger["trades"]
                     if t["date"] == today and t["action"] == "SELL"]
        ledger["daily_pnl"][today] = round(sum(t.get("pnl", 0) for t in day_sells), 2)
        save_ledger(ledger)

    # ── 2. Re-scan today's universe for new opportunities ─────────
    today_universe = get_today_universe()
    open_focus = [t for t in ledger["open_positions"] if t in today_universe]
    slots      = 3 - len(open_focus)
    if slots > 0:
        lines += ["", f"🔍 Scanning {len(today_universe)} picks for new entries..."]
        day_pnl = ledger.get("daily_pnl", {}).get(today, 0)
        if day_pnl < -(ledger["start_value"] * th["max_loss"] / 100):
            lines.append("🛑 Max daily loss — no new entries")
        else:
            for ticker in today_universe:
                if ticker in ledger["open_positions"]:
                    continue
                ind     = calc_5min(ticker)
                candles = detect_candles(ticker)
                orb     = calc_vwap_orb(ticker)
                if not ind:
                    continue
                score, reasons = score_open_signal(ticker, ind, candles, orb)
                tpct = dynamic_target_pct(
                    ind["price"],
                    candle_score=candles["candle_score"] if candles else 0,
                    orb_break=orb["orb_break"] if orb else None,
                )
                lines.append(
                    f"  {ticker}: score={score} RSI={ind['rsi']}"
                    f" ORB {orb['orb_break'] if orb else '?'}"
                    + (f" {' '.join(candles['patterns'])}" if candles and candles["patterns"] else "")
                )
                if score >= 5 and slots > 0:
                    news_d = {"category": "price_action", "score": score,
                              "title": " | ".join(reasons[:2])}
                    tr = execute_buy(ledger, ticker, ind["price"], ind,
                                     strategy="check_reentry", news=news_d, target_pct=tpct)
                    if tr:
                        slots -= 1
                        sign = "+" if tr["pnl"] >= 0 else "" if "pnl" in tr else ""
                        lines.append(
                            f"  🚀 NEW ENTRY {ticker} @ ${ind['price']:.2f}"
                            f" target +{tpct}% score={score}"
                        )
            open_val        = sum(p["shares"] * p["entry"] for p in ledger["open_positions"].values())
            ledger["equity"] = round(ledger["cash"] + open_val, 2)
            save_ledger(ledger)

    if not ledger["open_positions"] and not auto_sells:
        lines.append("✅ No open positions — all in cash")

    priority = "urgent" if auto_sells else "default"
    tags     = "white_check_mark" if not auto_sells else ("chart_with_upwards_trend"
                if any(t["pnl"] >= 0 for t in auto_sells) else "chart_with_downwards_trend")
    send_ntfy(
        f"📊 Day Check | {datetime.datetime.now().strftime('%H:%M')} | "
        + (f"{len(auto_sells)} exits" if auto_sells else "monitoring"),
        "\n".join(lines), priority=priority, tags=tags
    )

# ── Entry point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")

    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "scan":
        run_scan()
    elif mode == "enter":
        run_enter()
    elif mode == "open":
        run_open()
    elif mode == "close":
        run_close()
    elif mode == "check":
        run_check()
    else:
        print(f"Unknown mode '{mode}'. Use: scan | enter | open | close | check")
        sys.exit(1)
