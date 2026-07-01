#!/usr/bin/env python3
"""
sim_scanner.py — Daily stock picker for day trading
Scans ~70 S&P 500 tech stocks, selects 3-4 best candidates for the day.
Saves to day_picks.json → read by sim_daytrader.py run_open() / run_check()

Cron:
  15 13 * * 1-5  python3 /Users/artk80/project_VS/sim_scanner.py premarket  # 16:15 IDT
  45 13 * * 1-5  python3 /Users/artk80/project_VS/sim_scanner.py open        # 16:45 IDT

Manual (with TradingView confirmation by Claude):
  python3 sim_scanner.py premarket   pre-market: volume + gap + RSI filter
  python3 sim_scanner.py open        post-open:  ORB + candle + MACD live scan

TradingView confirmation (when Claude is present at ~16:30):
  Claude reads day_picks.json candidates and verifies on TradingView charts.
  Updates day_picks.json with confirmed=True and visual_note per pick.
"""

import json
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from sim_notify import send_ntfy, send_email

DAY_PICKS_PATH = os.path.join(os.path.dirname(__file__), "day_picks.json")
LOG_PATH       = "/tmp/sim_scanner.log"

# ── Full S&P 500 tech universe — ~70 liquid stocks ────────────────────
SP500_TECH = [
    # Mega-cap (highest priority — most liquid)
    "AAPL", "MSFT", "NVDA", "META", "GOOG", "AMZN", "TSLA", "AVGO",
    # Semiconductors
    "AMD", "QCOM", "MU", "ADI", "NXPI", "TXN", "KLAC", "LRCX", "AMAT",
    "MRVL", "ON", "SWKS", "MPWR",
    # Enterprise software / cloud
    "CRM", "ADBE", "NOW", "INTU", "WDAY", "SNPS", "CDNS", "ORCL", "IBM",
    "PANW", "CRWD", "FTNT", "OKTA", "ZS", "NET", "DDOG", "SNOW",
    # AI / infra
    "PLTR", "ANET", "VRT", "MDB",
    # Hardware / networking
    "MSI", "KEYS", "AKAM", "HPE", "DELL", "STX",
    # Consumer tech
    "NFLX", "SPOT", "UBER", "ABNB", "ROKU", "TTD",
    # Fintech
    "COIN", "SQ", "PYPL",
]

# Never trade these (swing portfolio positions — avoid overlap)
SWING_POSITIONS = {"CRM", "ADBE", "MSFT", "NOW", "ORCL"}

# Minimum daily volume (shares) — ensures liquidity
MIN_DAILY_VOLUME = 3_000_000

# Max picks per day
MAX_PICKS = 4


def log(msg):
    ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"{ts}  [SCAN] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def load_picks():
    if not os.path.exists(DAY_PICKS_PATH):
        return {}
    with open(DAY_PICKS_PATH) as f:
        return json.load(f)


def save_picks(data):
    with open(DAY_PICKS_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ── Score a stock pre-market (gap + volume + daily RSI) ──────────────
def score_premarket(ticker):
    try:
        import yfinance as yf
        tk   = yf.Ticker(ticker)
        hist = tk.history(period="60d")
        if hist.empty or len(hist) < 35:
            return None

        # Daily volume check
        avg_vol = int(hist["Volume"].mean())
        if avg_vol < MIN_DAILY_VOLUME:
            return None

        closes = hist["Close"].tolist()

        # Daily RSI(14) — Wilder smoothing
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains  = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        ag = sum(gains[:14]) / 14
        al = sum(losses[:14]) / 14
        for i in range(14, len(gains)):
            ag = (ag * 13 + gains[i]) / 14
            al = (al * 13 + losses[i]) / 14
        rsi = round(100 if al == 0 else 100 - (100 / (1 + ag / al)), 1)

        # Daily MACD(12,26,9)
        def ema(vals, p):
            k = 2 / (p + 1)
            r = [sum(vals[:p]) / p]
            for v in vals[p:]:
                r.append(v * k + r[-1] * (1 - k))
            return r

        e12   = ema(closes, 12)
        e26   = ema(closes, 26)
        macd  = [a - b for a, b in zip(e12[14:], e26)]
        sig   = ema(macd, 9)
        hist_val = round(macd[-1] - sig[-1], 4)

        # Pre-market gap
        prev_close = round(float(hist["Close"].iloc[-1]), 2)
        price      = prev_close   # will be updated if pre-market data available
        gap_pct    = 0.0
        pre_vol_ratio = 0.0

        try:
            intra = tk.history(period="1d", interval="1m", prepost=True)
            if not intra.empty:
                now_et  = datetime.datetime.utcnow() - datetime.timedelta(hours=4)
                open_t  = now_et.replace(hour=9, minute=30, second=0).time()
                pre     = intra[intra.index.time < open_t]
                if not pre.empty:
                    price         = round(float(pre["Close"].iloc[-1]), 2)
                    pre_vol       = int(pre["Volume"].sum())
                    gap_pct       = round((price - prev_close) / prev_close * 100, 2)
                    avg_5min_vol  = avg_vol / 78
                    pre_vol_ratio = round(pre_vol / max(avg_5min_vol, 1), 2)
        except Exception:
            pass

        # ── Composite score ────────────────────────────────────────
        score   = 0
        reasons = []

        # RSI: best range for day trade — not overbought, not in freefall
        if 35 <= rsi <= 60:
            score += 2
            reasons.append(f"RSI {rsi} ✓")
        elif rsi < 35:
            score += 1
            reasons.append(f"RSI {rsi} (oversold)")
        elif rsi > 70:
            score -= 1
            reasons.append(f"RSI {rsi} (overbought ⚠️)")

        # MACD daily: positive momentum is bullish context
        if hist_val > 0:
            score += 2
            reasons.append(f"MACD hist +{hist_val:.3f} ↑")
        elif hist_val > -0.5:
            score += 1
            reasons.append(f"MACD hist {hist_val:.3f} (near zero)")

        # Pre-market gap: gap up = catalyst, but not too much (>5% = too risky)
        if 0.5 <= gap_pct <= 5.0:
            score += 2
            reasons.append(f"Gap +{gap_pct:.1f}% ↑")
        elif -5.0 <= gap_pct <= -0.5:
            score += 1
            reasons.append(f"Gap {gap_pct:.1f}% ↓ (reversal candidate)")
        elif abs(gap_pct) > 5:
            score -= 1
            reasons.append(f"Gap {gap_pct:+.1f}% (too extreme ⚠️)")

        # Pre-market volume surge
        if pre_vol_ratio >= 2.0:
            score += 2
            reasons.append(f"Pre-mkt vol {pre_vol_ratio:.1f}× avg")
        elif pre_vol_ratio >= 1.2:
            score += 1
            reasons.append(f"Pre-mkt vol {pre_vol_ratio:.1f}× avg")

        # Average daily volume bonus (more liquid = cleaner moves)
        if avg_vol >= 30_000_000:
            score += 1
            reasons.append(f"Vol {avg_vol//1_000_000}M/day (mega liquid)")
        elif avg_vol >= 10_000_000:
            score += 0
        else:
            score -= 0   # still OK if above MIN threshold

        return {
            "ticker":        ticker,
            "score":         score,
            "price":         price,
            "rsi":           rsi,
            "macd_hist":     hist_val,
            "gap_pct":       gap_pct,
            "pre_vol_ratio": pre_vol_ratio,
            "avg_daily_vol": avg_vol,
            "reasons":       reasons,
            "confirmed":     False,
            "tv_note":       "",
        }
    except Exception as e:
        log(f"  {ticker}: error — {e}")
        return None


# ── Score a stock post-open (5-min ORB + VWAP + candles) ─────────────
def score_open(ticker):
    """
    Post-open scoring using live 5-min data.
    Imports detect_candles, calc_vwap_orb, score_open_signal from sim_daytrader.
    """
    try:
        from sim_daytrader import (detect_candles, calc_vwap_orb,
                                   score_open_signal, calc_5min, dynamic_target_pct)

        ind     = calc_5min(ticker)
        candles = detect_candles(ticker)
        orb     = calc_vwap_orb(ticker)

        if not ind:
            return None

        score, reasons = score_open_signal(ticker, ind, candles, orb)
        tpct = dynamic_target_pct(
            ind["price"],
            candle_score=candles["candle_score"] if candles else 0,
            orb_break=orb["orb_break"] if orb else None,
        )

        return {
            "ticker":        ticker,
            "score":         score,
            "price":         ind["price"],
            "rsi":           ind["rsi"],
            "macd_hist":     ind["histogram"],
            "gap_pct":       0.0,
            "pre_vol_ratio": 0.0,
            "avg_daily_vol": 0,
            "target_pct":    tpct,
            "orb_break":     orb["orb_break"] if orb else "?",
            "vwap":          orb["vwap"] if orb else None,
            "candle_patterns": candles["patterns"] if candles else [],
            "reasons":       reasons,
            "confirmed":     False,
            "tv_note":       "",
        }
    except Exception as e:
        log(f"  {ticker}: open score error — {e}")
        return None


# ── Price-tier diversity helper ───────────────────────────────────────
def ensure_diversity(picks):
    """
    Ensure picks cover at least 2 different price tiers so we don't
    put all budget into one price range.
    Tiers: cheap (<$80), mid ($80-$200), expensive (>$200)
    """
    def tier(p):
        price = p.get("price", 0)
        if price >= 200: return "expensive"
        if price >= 80:  return "mid"
        return "cheap"

    tiers = [tier(p) for p in picks]
    return len(set(tiers)) >= 2


# ── Main scan ─────────────────────────────────────────────────────────
def run_scan(mode="premarket"):
    log("=" * 55)
    log(f"SCANNER — {mode.upper()} — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log("=" * 55)

    today     = datetime.date.today().isoformat()
    universe  = [t for t in SP500_TECH if t not in SWING_POSITIONS]
    results   = []

    log(f"Scanning {len(universe)} stocks ({mode} mode)...")

    for ticker in universe:
        if mode == "premarket":
            result = score_premarket(ticker)
        else:
            result = score_open(ticker)

        if result and result["score"] >= 2:
            results.append(result)
            log(f"  ✓ {ticker}: score={result['score']} "
                f"RSI={result['rsi']} MACD_h={result['macd_hist']:+.3f} "
                f"| {' | '.join(result['reasons'][:3])}")

    results.sort(key=lambda x: x["score"], reverse=True)

    # Select top picks with price diversity
    picks = []
    for r in results:
        if len(picks) >= MAX_PICKS:
            break
        # Prefer diversity but don't sacrifice top picks for it
        picks.append(r)

    log(f"\n{'='*30} TOP {len(picks)} PICKS {'='*30}")
    for i, p in enumerate(picks, 1):
        log(f"  #{i} {p['ticker']:6s} score={p['score']} "
            f"${p['price']:.2f} RSI={p['rsi']} | {' | '.join(p['reasons'][:2])}")

    # ── Save to day_picks.json ─────────────────────────────────────
    data = {
        "date":         today,
        "mode":         mode,
        "scanned":      len(universe),
        "selected_at":  datetime.datetime.now().isoformat(),
        "tv_confirmed": False,   # set to True after TradingView review by Claude
        "picks":        picks,
        "all_candidates": results[:10],   # top 10 for Claude to review on TradingView
    }
    save_picks(data)
    log(f"\nSaved {len(picks)} picks to day_picks.json")

    # ── ntfy ──────────────────────────────────────────────────────
    ntfy_lines = [
        f"🔭 Scanner | {mode} | {today}",
        f"Scanned {len(universe)} stocks → {len(picks)} picks",
        "",
    ]
    for i, p in enumerate(picks, 1):
        candles_str = (" " + " ".join(p.get("candle_patterns", []))) if p.get("candle_patterns") else ""
        orb_str     = f" ORB {p['orb_break']}" if p.get("orb_break") else ""
        ntfy_lines.append(
            f"#{i} {p['ticker']} ${p['price']:.2f} | score {p['score']}"
            f" | RSI {p['rsi']}{orb_str}{candles_str}"
        )
        ntfy_lines.append(f"   {' | '.join(p['reasons'][:2])}")

    if not data["tv_confirmed"]:
        ntfy_lines += [
            "",
            "⚠️  Awaiting TradingView confirmation by Claude",
            "   Open Claude at 16:30 IDT to visually confirm picks",
        ]

    send_ntfy(
        f"🔭 Scanner | {len(picks)} picks | {today}",
        "\n".join(ntfy_lines),
        priority="default",
        tags="telescope"
    )

    return picks


# ── TradingView confirmation (called by Claude interactively) ─────────
def confirm_pick(ticker, tv_note, confirmed=True):
    """
    Called after Claude checks TradingView charts.
    Updates day_picks.json with visual confirmation.
    """
    data = load_picks()
    if data.get("date") != datetime.date.today().isoformat():
        log("day_picks.json is from a different day — re-scan needed")
        return

    for pick in data["picks"]:
        if pick["ticker"] == ticker:
            pick["confirmed"]  = confirmed
            pick["tv_note"]    = tv_note
            break

    all_confirmed = all(p["confirmed"] for p in data["picks"])
    if all_confirmed:
        data["tv_confirmed"] = True

    save_picks(data)
    log(f"[TV] {ticker}: confirmed={confirmed} | {tv_note}")


def add_pick(ticker, tv_note):
    """Add a stock found on TradingView that wasn't in the automated scan."""
    data = load_picks()
    if data.get("date") != datetime.date.today().isoformat():
        return

    # Check not already in picks
    if any(p["ticker"] == ticker for p in data["picks"]):
        log(f"{ticker} already in picks")
        return

    try:
        from sim_daytrader import calc_5min, detect_candles, calc_vwap_orb, dynamic_target_pct
        ind     = calc_5min(ticker)
        candles = detect_candles(ticker)
        orb     = calc_vwap_orb(ticker)
        price   = ind["price"] if ind else 0
        tpct    = dynamic_target_pct(price) if ind else 1.5
        pick = {
            "ticker":   ticker, "score": 9,
            "price":    price,
            "rsi":      ind["rsi"] if ind else None,
            "macd_hist":ind["histogram"] if ind else None,
            "reasons":  [f"TradingView manual add — {tv_note}"],
            "confirmed":True, "tv_note": tv_note,
            "target_pct": tpct,
            "orb_break":  orb["orb_break"] if orb else "?",
            "candle_patterns": candles["patterns"] if candles else [],
        }
        data["picks"].append(pick)
        if len(data["picks"]) > MAX_PICKS:
            data["picks"] = data["picks"][:MAX_PICKS]
        save_picks(data)
        log(f"[TV] Added {ticker} to picks: {tv_note}")
    except Exception as e:
        log(f"[TV] add_pick {ticker}: {e}")


def get_picks_for_today():
    """
    Returns today's pick tickers. Falls back to FOCUS_UNIVERSE if no picks for today.
    Used by sim_daytrader.py run_open() and run_check().
    """
    from sim_daytrader import FOCUS_UNIVERSE
    data = load_picks()
    if not data or data.get("date") != datetime.date.today().isoformat():
        log("No picks for today — falling back to FOCUS_UNIVERSE")
        return FOCUS_UNIVERSE
    tickers = [p["ticker"] for p in data.get("picks", [])]
    if not tickers:
        return FOCUS_UNIVERSE
    log(f"Today's picks: {', '.join(tickers)}")
    return tickers


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")

    mode = sys.argv[1] if len(sys.argv) > 1 else "premarket"
    if mode in ("premarket", "open"):
        run_scan(mode)
    else:
        print(f"Unknown mode '{mode}'. Use: premarket | open")
        sys.exit(1)
