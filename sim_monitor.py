#!/usr/bin/env python3
"""
Tech Simulation Monitor — Auto-Trading Engine
Runs every weekday at 23:15 IDT (15 min after US market close).
Reads/writes portfolio state from sim_ledger.json.
Signals: RSI + MACD calculated from yfinance history.
Auto-trades: RSI<30 → cash buy | RSI<30 + MACD hist>0 → margin buy
"""

import json
import datetime
import os
import sys
import urllib.request
import base64
import io

sys.path.insert(0, os.path.dirname(__file__))
from sim_notify import notify_macos, send_email, send_ntfy, build_email_report

LEDGER_PATH   = os.path.join(os.path.dirname(__file__), "sim_ledger.json")
CONFIG_PATH   = os.path.join(os.path.dirname(__file__), ".sim_config")

WATCHLIST = [
    # Original 20
    "NVDA","AVGO","MSFT","AAPL","ORCL","PLTR","ANET","VRT",
    "MU","AMD","KLAC","LRCX","AMAT","QCOM","NOW","CRWD",
    "IBM","ADBE","CRM","TXN",
    # Added June 30 — 8 new approved
    "SNPS","WDAY","INTU","ADI","NXPI","MSI","AKAM","KEYS",
    # Added June 30 — 6 on AVOID (above target / overvalued)
    "CSCO","INTC","CDNS","FTNT","PANW","MRVL",
    # 3x NASDAQ ETF — buy signal same as stocks (RSI<30)
    "TQQQ",
]
# Market-wide indicators — RSI/MACD reported every night, never auto-bought
MONITOR_ONLY = {"SPY", "QQQ"}
AVOID         = {
    # Original avoids — above analyst target or heavy selling
    "AMAT","LRCX","KLAC","AMD","TXN",
    # New avoids — above analyst target or extreme valuation
    "CSCO",   # +8% upside, up 54% YTD — limited room
    "INTC",   # -25% upside, no earnings, up 249% YTD
    "CDNS",   # only +4% upside at PE 87
    "FTNT",   # -27% upside — 27% above analyst target
    "PANW",   # -5% upside, PE 286
    "MRVL",   # -10% upside, up 221% YTD
}
MAX_POSITIONS = 8
STOP_WARN_PCT = 0.04
STRONG_MOVE   = 0.05

# ── Learning defaults (overridden by ledger["learning"] at runtime) ──
LEARNING_DEFAULTS = {
    "rsi_threshold":       30,      # buy when RSI < this
    "stop_pct":            0.08,    # stop-loss distance from entry
    "cash_per_pos":        15_000,  # max cash per position
    "margin_per_pos":      25_000,  # max margin per position
    "stats": {
        "total_closed": 0, "wins": 0, "losses": 0,
        "avg_gain_pct": 0.0, "avg_loss_pct": 0.0, "avg_days_held": 0.0,
        "stop_loss_count": 0, "target_count": 0,
        "by_signal": {
            "rsi_only":       {"count": 0, "wins": 0, "total_gain": 0.0},
            "double_confirm": {"count": 0, "wins": 0, "total_gain": 0.0},
        },
        "by_regime": {
            "bear":    {"count": 0, "wins": 0, "total_gain": 0.0},
            "neutral": {"count": 0, "wins": 0, "total_gain": 0.0},
            "bull":    {"count": 0, "wins": 0, "total_gain": 0.0},
        },
    },
    "adjustments": [],
    "last_updated": None,
}

def ensure_learning(ledger):
    """Initialise learning section if missing or incomplete."""
    if "learning" not in ledger:
        ledger["learning"] = json.loads(json.dumps(LEARNING_DEFAULTS))
        log("[LEARN] Initialised learning section")
    # back-fill any missing keys from LEARNING_DEFAULTS
    for k, v in LEARNING_DEFAULTS.items():
        if k not in ledger["learning"]:
            ledger["learning"][k] = v

def get_thresholds(ledger):
    """Return adaptive thresholds from learning section (or defaults)."""
    L = ledger.get("learning", LEARNING_DEFAULTS)
    return {
        "rsi":    L.get("rsi_threshold",   30),
        "stop":   L.get("stop_pct",        0.08),
        "cash":   L.get("cash_per_pos",    15_000),
        "margin": L.get("margin_per_pos",  25_000),
    }

# ── Logging ───────────────────────────────────────────────────
def log(msg):
    ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"{ts}  {msg}"
    print(line)
    with open("/tmp/sim_monitor.log", "a") as f:
        f.write(line + "\n")

# ── Ledger helpers ────────────────────────────────────────────
def load_ledger():
    with open(LEDGER_PATH) as f:
        return json.load(f)

def save_ledger(ledger):
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)

# ── Technical indicators from yfinance history ────────────────
def _ema(values, period):
    k      = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result

def calc_indicators(ticker):
    try:
        import yfinance as yf
        closes = yf.Ticker(ticker).history(period="4mo")["Close"].tolist()
        if len(closes) < 40:
            return None

        # RSI(14) — Wilder smoothing
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains  = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        avg_g  = sum(gains[:14]) / 14
        avg_l  = sum(losses[:14]) / 14
        for i in range(14, len(gains)):
            avg_g = (avg_g * 13 + gains[i]) / 14
            avg_l = (avg_l * 13 + losses[i]) / 14
        rsi = 100 if avg_l == 0 else round(100 - (100 / (1 + avg_g / avg_l)), 2)

        # MACD(12,26,9)
        e12       = _ema(closes, 12)
        e26       = _ema(closes, 26)
        macd_line = [a - b for a, b in zip(e12[14:], e26)]
        signal    = _ema(macd_line, 9)
        histogram = round(macd_line[-1] - signal[-1], 4)

        return {"rsi": rsi, "macd": round(macd_line[-1], 4),
                "signal": round(signal[-1], 4), "histogram": histogram}
    except Exception as e:
        log(f"[INDICATOR] {ticker} failed: {e}")
        return None

# ── Fetch live price from backend ─────────────────────────────
def get_price(ticker):
    try:
        url = f"http://localhost:8000/api/stock/{ticker}/analysis"
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
        day = data.get("data", {}).get("day_trade", {})
        lt  = data.get("data", {}).get("long_term", {})
        return {
            "price":          day.get("price"),
            "change_percent": day.get("change_percent"),
            "volume":         day.get("volume"),
            "avg_volume":     day.get("avg_volume"),
            "analyst_target": lt.get("analyst_target"),
        }
    except Exception as e:
        log(f"[PRICE] {ticker} failed: {e}")
        return None

# ── Execute a paper buy ───────────────────────────────────────
def execute_buy(ledger, ticker, price, indicators, using_margin=False, spy_rsi=None):
    th = get_thresholds(ledger)
    if using_margin:
        deployed = sum(p["shares"] * price for p in ledger["positions"].values())
        avail    = ledger["equity"] * ledger["leverage"] - deployed
        to_spend = min(th["margin"], max(avail, 0))
    else:
        to_spend = min(th["cash"], ledger["cash"])

    if to_spend < 1000:
        log(f"[TRADE] {ticker} — insufficient funds (${to_spend:.0f})")
        return None

    shares  = int(to_spend / price)
    cost    = round(shares * price, 2)
    stop    = round(price * (1 - th["stop"]), 2)
    pd      = get_price(ticker)
    target  = pd["analyst_target"] if pd and pd["analyst_target"] else round(price * 1.40, 2)

    signal_type = "double_confirm" if (indicators["histogram"] > 0) else "rsi_only"
    if spy_rsi is not None:
        regime = "bear" if spy_rsi < 40 else ("bull" if spy_rsi > 60 else "neutral")
    else:
        regime = "unknown"

    ledger["positions"][ticker] = {
        "name": ticker, "entry": price, "stop": stop,
        "target": target, "shares": shares,
    }
    if not using_margin:
        ledger["cash"] = round(ledger["cash"] - cost, 2)

    tr = {
        "date":        datetime.date.today().isoformat(),
        "action":      "BUY",
        "ticker":      ticker,
        "shares":      shares,
        "price":       price,
        "cost":        cost,
        "margin":      using_margin,
        "rsi":         indicators["rsi"],
        "macd_h":      indicators["histogram"],
        "signal_type": signal_type,
        "spy_rsi":     spy_rsi,
        "regime":      regime,
    }
    ledger["trades"].append(tr)
    mode = "MARGIN" if using_margin else "CASH"
    log(f"[TRADE] BUY {shares}x {ticker} @ ${price:.2f} = ${cost:.2f} [{mode}] RSI={indicators['rsi']} signal={signal_type} regime={regime}")
    return tr

# ── Execute a paper sell ──────────────────────────────────────
def execute_sell(ledger, ticker, price, reason, exit_indicators=None):
    pos      = ledger["positions"].pop(ticker)
    shares   = pos["shares"]
    proceeds = round(shares * price, 2)
    cost     = shares * pos["entry"]
    pnl      = round(proceeds - cost, 2)
    pnl_pct  = round(pnl / cost * 100, 2)
    ledger["cash"] = round(ledger["cash"] + proceeds, 2)

    # Find the matching BUY trade to get learning context
    buy_tr = next(
        (t for t in reversed(ledger["trades"])
         if t["action"] == "BUY" and t["ticker"] == ticker), None
    )
    entry_date  = buy_tr["date"] if buy_tr else datetime.date.today().isoformat()
    signal_type = buy_tr.get("signal_type", "rsi_only") if buy_tr else "rsi_only"
    regime      = buy_tr.get("regime", "unknown") if buy_tr else "unknown"
    entry_rsi   = buy_tr.get("rsi") if buy_tr else None
    days_held   = (datetime.date.today() - datetime.date.fromisoformat(entry_date)).days

    tr = {
        "date":        datetime.date.today().isoformat(),
        "action":      "SELL",
        "ticker":      ticker,
        "shares":      shares,
        "price":       price,
        "proceeds":    proceeds,
        "pnl":         pnl,
        "pnl_pct":     pnl_pct,
        "reason":      reason,
        "days_held":   days_held,
        "entry_rsi":   entry_rsi,
        "signal_type": signal_type,
        "regime":      regime,
        "exit_rsi":    exit_indicators["rsi"] if exit_indicators else None,
        "exit_macd_h": exit_indicators["histogram"] if exit_indicators else None,
    }
    ledger["trades"].append(tr)
    log(f"[TRADE] SELL {shares}x {ticker} @ ${price:.2f} P&L=${pnl:+.2f} ({pnl_pct:+.1f}%) [{reason}] held={days_held}d")

    update_learning(ledger, tr)
    return tr

# ── Self-learning engine ──────────────────────────────────────
def update_learning(ledger, sell_trade):
    """Update stats from a closed trade and adapt thresholds if evidence warrants it."""
    ensure_learning(ledger)
    L     = ledger["learning"]
    stats = L["stats"]
    pnl   = sell_trade["pnl_pct"]
    won   = pnl > 0
    sig   = sell_trade.get("signal_type", "rsi_only")
    regime= sell_trade.get("regime", "neutral")
    days  = sell_trade.get("days_held", 0)

    # ── Update rolling stats ───────────────────────────────────
    n = stats["total_closed"]
    stats["total_closed"] += 1
    if won:
        stats["wins"] += 1
        stats["avg_gain_pct"] = (stats["avg_gain_pct"] * sum(
            1 for t in ledger["trades"] if t["action"]=="SELL" and t.get("pnl_pct",0) > 0
        ) + pnl) / (stats["wins"])
    else:
        stats["losses"] += 1
        stats["avg_loss_pct"] = (stats["avg_loss_pct"] * (stats["losses"]-1) + pnl) / stats["losses"]
    stats["avg_days_held"] = (stats["avg_days_held"] * n + days) / (n + 1)
    if sell_trade.get("reason") == "stop_loss":
        stats["stop_loss_count"] += 1
    elif sell_trade.get("reason") == "target":
        stats["target_count"] += 1

    # Signal-type breakdown
    if sig in stats["by_signal"]:
        g = stats["by_signal"][sig]
        g["count"] += 1
        if won: g["wins"] += 1
        g["total_gain"] = round(g["total_gain"] + pnl, 2)

    # Market-regime breakdown
    if regime in stats["by_regime"]:
        r = stats["by_regime"][regime]
        r["count"] += 1
        if won: r["wins"] += 1
        r["total_gain"] = round(r["total_gain"] + pnl, 2)

    L["last_updated"] = datetime.date.today().isoformat()

    # ── Adaptive threshold logic (needs ≥5 closed trades) ─────
    if stats["total_closed"] < 5:
        log(f"[LEARN] {stats['total_closed']}/5 closed trades needed before adapting thresholds")
        return

    adj = []
    win_rate = stats["wins"] / stats["total_closed"]

    # Rule 1 — RSI threshold: tighten if rsi_only win rate is weak
    rsi_only = stats["by_signal"]["rsi_only"]
    if rsi_only["count"] >= 3:
        rsi_wr = rsi_only["wins"] / rsi_only["count"]
        if rsi_wr < 0.40 and L["rsi_threshold"] > 26:
            old = L["rsi_threshold"]
            L["rsi_threshold"] -= 1
            msg = f"RSI threshold {old} → {L['rsi_threshold']} (rsi_only win rate {rsi_wr:.0%} < 40%)"
            adj.append(msg); log(f"[LEARN] {msg}")
        elif rsi_wr > 0.75 and L["rsi_threshold"] < 32:
            old = L["rsi_threshold"]
            L["rsi_threshold"] += 1
            msg = f"RSI threshold {old} → {L['rsi_threshold']} (rsi_only win rate {rsi_wr:.0%} > 75% — easing entry)"
            adj.append(msg); log(f"[LEARN] {msg}")

    # Rule 2 — Stop-loss: widen if >40% of exits are stop-losses
    if stats["total_closed"] >= 8:
        stop_rate = stats["stop_loss_count"] / stats["total_closed"]
        if stop_rate > 0.40 and L["stop_pct"] < 0.12:
            old = L["stop_pct"]
            L["stop_pct"] = round(L["stop_pct"] + 0.005, 3)
            msg = f"Stop-loss {old:.1%} → {L['stop_pct']:.1%} ({stop_rate:.0%} of closes were stops)"
            adj.append(msg); log(f"[LEARN] {msg}")
        elif stop_rate < 0.15 and L["stop_pct"] > 0.06:
            old = L["stop_pct"]
            L["stop_pct"] = round(L["stop_pct"] - 0.005, 3)
            msg = f"Stop-loss {old:.1%} → {L['stop_pct']:.1%} (only {stop_rate:.0%} stopped out — tightening)"
            adj.append(msg); log(f"[LEARN] {msg}")

    # Rule 3 — Position size: scale with win rate (±$2k, bounded $10k–$22k cash)
    if stats["total_closed"] >= 10:
        if win_rate > 0.70 and L["cash_per_pos"] < 22_000:
            L["cash_per_pos"]   += 2_000
            L["margin_per_pos"] += 3_000
            msg = f"Position size ↑ cash=${L['cash_per_pos']:,} margin=${L['margin_per_pos']:,} (win rate {win_rate:.0%})"
            adj.append(msg); log(f"[LEARN] {msg}")
        elif win_rate < 0.40 and L["cash_per_pos"] > 10_000:
            L["cash_per_pos"]   -= 2_000
            L["margin_per_pos"] -= 3_000
            msg = f"Position size ↓ cash=${L['cash_per_pos']:,} margin=${L['margin_per_pos']:,} (win rate {win_rate:.0%})"
            adj.append(msg); log(f"[LEARN] {msg}")

    if adj:
        L["adjustments"].append({
            "date": datetime.date.today().isoformat(),
            "changes": adj,
            "win_rate": round(win_rate, 3),
            "total_closed": stats["total_closed"],
        })

def build_learning_summary(ledger):
    """Return (ntfy_lines, html_block) for the nightly report."""
    ensure_learning(ledger)
    L     = ledger["learning"]
    stats = L["stats"]
    n     = stats["total_closed"]

    if n == 0:
        ntfy = ["", "LEARNING ENGINE", "  No closed trades yet — building baseline..."]
        html = "<p style='color:#64748b;font-style:italic;'>No closed trades yet — learning starts after first sell.</p>"
        return ntfy, html

    win_rate = stats["wins"] / n
    conf     = "🔴 LOW" if n < 5 else ("🟡 MEDIUM" if n < 15 else "🟢 HIGH")
    conf_note= f"({n} trades)" if n < 15 else f"({n} trades — statistically reliable)"

    sig_lines = []
    for sig, label in [("rsi_only","RSI-only"), ("double_confirm","Double-confirm")]:
        g = stats["by_signal"][sig]
        if g["count"] > 0:
            wr  = g["wins"] / g["count"]
            avg = g["total_gain"] / g["count"]
            sig_lines.append(f"  {label}: {g['wins']}/{g['count']} wins ({wr:.0%}) avg {avg:+.1f}%")

    reg_lines = []
    for reg, label in [("bull","Bull (SPY>60)"), ("neutral","Neutral"), ("bear","Bear (SPY<40)")]:
        r = stats["by_regime"][reg]
        if r["count"] > 0:
            wr  = r["wins"] / r["count"]
            avg = r["total_gain"] / r["count"]
            reg_lines.append(f"  {label}: {r['wins']}/{r['count']} ({wr:.0%}) avg {avg:+.1f}%")

    last_adj = ""
    if L["adjustments"]:
        a = L["adjustments"][-1]
        last_adj = f"Last adapt ({a['date']}): " + "; ".join(a["changes"])

    ntfy = [
        "", "LEARNING ENGINE",
        f"  Confidence: {conf} {conf_note}",
        f"  Win rate: {stats['wins']}/{n} ({win_rate:.0%})  |  Avg gain: {stats['avg_gain_pct']:+.1f}%  |  Avg loss: {stats['avg_loss_pct']:+.1f}%",
        f"  Avg hold: {stats['avg_days_held']:.0f}d  |  Stops: {stats['stop_loss_count']}  |  Targets: {stats['target_count']}",
        f"  Thresholds → RSI<{L['rsi_threshold']} | Stop={L['stop_pct']:.1%} | Cash/pos=${L['cash_per_pos']:,} | Margin/pos=${L['margin_per_pos']:,}",
    ] + sig_lines + reg_lines
    if last_adj:
        ntfy.append(f"  ⚙️  {last_adj}")

    html = f"""
<div style="background:#f0f9ff;border-left:4px solid #0ea5e9;border-radius:6px;padding:16px 20px;margin-top:20px;">
  <h3 style="margin:0 0 10px;color:#0369a1;font-size:15px;">🧠 Learning Engine</h3>
  <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:10px;">
    <span><b>Confidence:</b> {conf} {conf_note}</span>
    <span><b>Win rate:</b> {stats['wins']}/{n} ({win_rate:.0%})</span>
    <span><b>Avg gain:</b> {stats['avg_gain_pct']:+.1f}%</span>
    <span><b>Avg loss:</b> {stats['avg_loss_pct']:+.1f}%</span>
    <span><b>Avg hold:</b> {stats['avg_days_held']:.0f} days</span>
  </div>
  <table style="width:100%;font-size:13px;border-collapse:collapse;">
    <tr style="background:#e0f2fe;">
      <th style="padding:6px 10px;text-align:left;">Signal type</th>
      <th style="padding:6px 10px;text-align:center;">Trades</th>
      <th style="padding:6px 10px;text-align:center;">Win rate</th>
      <th style="padding:6px 10px;text-align:right;">Avg P&amp;L</th>
    </tr>
    {"".join(
        f"<tr><td style='padding:5px 10px;'>{label}</td><td style='padding:5px 10px;text-align:center;'>{stats['by_signal'][sig]['count']}</td>"
        f"<td style='padding:5px 10px;text-align:center;'>{(stats['by_signal'][sig]['wins']/stats['by_signal'][sig]['count']):.0%}" if stats['by_signal'][sig]['count'] else
        f"<tr><td style='padding:5px 10px;'>{label}</td><td colspan='3' style='padding:5px 10px;color:#94a3b8;'>no data</td>"
        for sig, label in [("rsi_only","RSI-only"), ("double_confirm","Double-confirm")]
    )}
  </table>
  <div style="margin-top:10px;padding-top:10px;border-top:1px solid #bae6fd;font-size:12px;color:#0369a1;">
    <b>Active thresholds:</b> RSI&lt;{L['rsi_threshold']} | Stop={L['stop_pct']:.1%} | Cash/pos=${L['cash_per_pos']:,} | Margin/pos=${L['margin_per_pos']:,}
    {"<br><b>Last adjustment:</b> " + last_adj if last_adj else ""}
  </div>
</div>"""
    return ntfy, html

# ── Dynamic leverage decision ─────────────────────────────────
def decide_leverage(position_indicators, ledger):
    """
    Recalculate leverage each session based on RSI/MACD signals.
    1.0x → all MACD negative (no margin)
    1.25x → mixed/weak signals
    1.5x → some MACD turning positive
    2.0x → majority MACD positive + RSI recovering (40-55)
    """
    if not position_indicators:
        return 1.0, "No signal data — holding flat"

    n          = len(position_indicators)
    pos_macd   = sum(1 for i in position_indicators.values() if i and i["histogram"] > 0)
    avg_rsi    = sum(i["rsi"] for i in position_indicators.values() if i) / n
    near_stop  = any(i.get("near_stop") for i in position_indicators.values() if i)

    if near_stop:
        lev, reason = 1.0, "Position near stop-loss — capital preservation"
    elif pos_macd == 0 and avg_rsi < 40:
        lev, reason = 1.0, f"All MACD negative + avg RSI {avg_rsi:.0f} — no margin"
    elif pos_macd == 0:
        lev, reason = 1.25, f"All MACD negative, RSI neutral ({avg_rsi:.0f}) — minimal margin"
    elif pos_macd >= n // 2 and avg_rsi > 50:
        lev, reason = 2.0, f"{pos_macd}/{n} MACD positive + RSI {avg_rsi:.0f} — high conviction"
    elif pos_macd >= 1:
        lev, reason = 1.5, f"{pos_macd}/{n} MACD turning positive — moderate margin"
    else:
        lev, reason = 1.25, f"Mixed signals (RSI {avg_rsi:.0f}) — cautious"

    prev = ledger.get("leverage", 1.5)
    if lev != prev:
        log(f"[LEVERAGE] {prev}x → {lev}x | {reason}")
    else:
        log(f"[LEVERAGE] Unchanged at {lev}x | {reason}")
    return lev, reason

# ── User-friendly ntfy body ───────────────────────────────────
def build_ntfy_body(positions_data, portfolio_value, start_value, cash, leverage, alerts, new_trades, leverage_reason, market_indicators=None):
    pnl      = portfolio_value - start_value
    pnl_pct  = (pnl / start_value) * 100
    sign     = "+" if pnl >= 0 else ""
    emoji    = "📈" if pnl >= 0 else "📉"
    buying_pw= start_value * leverage

    lines = [
        f"{emoji} Portfolio: ${portfolio_value:,.2f} | P&L: {sign}${pnl:,.2f} ({sign}{pnl_pct:.2f}%)",
        f"💵 Cash: ${cash:,.2f} | Leverage: {leverage}x | Buying power: ${buying_pw:,.0f}",
        f"⚖️  Leverage reason: {leverage_reason}",
        "",
        "POSITIONS",
    ]
    for t, d in positions_data.items():
        price    = d["price"]
        entry    = d["entry"]
        shares   = d["shares"]
        value    = shares * price
        invested = shares * entry
        p_pnl    = value - invested
        p_pct    = (price - entry) / entry * 100
        day_pct  = d.get("change_percent", 0) or 0
        dot      = "🟢" if p_pct >= 0 else ("🔴" if p_pct < -4 else "🟡")
        lines.append(
            f"{dot} {t}  {shares}sh × ${price:.2f} = ${value:,.0f}"
            f"  |  P&L: {'+' if p_pnl>=0 else ''}${p_pnl:,.0f} ({'+' if p_pct>=0 else ''}{p_pct:.1f}%)"
            f"  |  Day: {'+' if day_pct>=0 else ''}{day_pct:.1f}%"
        )

    if new_trades:
        lines += ["", "TRADES TODAY"]
        for tr in new_trades:
            if tr["action"] == "BUY":
                mode = "margin" if tr.get("margin") else "cash"
                lines.append(f"🛒 BUY {tr['shares']}x {tr['ticker']} @ ${tr['price']:.2f} (${tr['cost']:,.0f}) [{mode}] RSI={tr['rsi']}")
            else:
                lines.append(f"🔴 SELL {tr['shares']}x {tr['ticker']} @ ${tr['price']:.2f} | P&L: ${tr['pnl']:+,.0f}")

    if market_indicators:
        lines += ["", "MARKET PULSE (monitor only)"]
        for ticker, ind in market_indicators.items():
            rsi   = ind["rsi"]
            hist  = ind["histogram"]
            price = ind.get("price", 0)
            dot   = "🔴" if rsi < 35 else ("🟡" if rsi < 45 else "🟢")
            trend = "▲" if hist > 0 else "▼"
            lines.append(f"{dot} {ticker} ${price:.2f} | RSI={rsi:.1f} | MACD {trend}{abs(hist):.2f}")

    if alerts:
        lines += ["", "ALERTS"]
        for title, msg, urgent in alerts:
            lines.append(f"{'🔴' if urgent else '⚠️'} {title}: {msg}")

    return "\n".join(lines)

# ── Trade log email ──────────────────────────────────────────
def _build_csv(trades):
    """Build CSV string of all trades for email attachment."""
    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date","Action","Ticker","Name","Shares","Price","Total ($)","Type","RSI","MACD Hist","P&L ($)","Note"])
    for tr in trades:
        cost  = tr.get("cost") or tr.get("proceeds", 0)
        rsi   = f"{tr['rsi']:.2f}" if tr.get("rsi") is not None else ""
        macd  = f"{tr['macd_h']:.4f}" if tr.get("macd_h") is not None else ""
        pnl   = f"{tr['pnl']:+.2f}" if tr.get("pnl") is not None else ""
        mtype = "Margin" if tr.get("margin") else "Cash"
        writer.writerow([
            tr["date"], tr["action"], tr["ticker"],
            tr.get("name", tr["ticker"]),
            tr["shares"], f"{tr['price']:.2f}", f"{cost:.2f}",
            mtype, rsi, macd, pnl, tr.get("note","")
        ])
    return buf.getvalue()

def send_trade_log(ledger, portfolio_value):
    trades  = ledger.get("trades", [])
    rows_html = ""
    total_invested = 0
    total_proceeds = 0

    for tr in trades:
        action  = tr["action"]
        ticker  = tr["ticker"]
        name    = tr.get("name", ticker)
        date    = tr["date"]
        shares  = tr["shares"]
        price   = tr["price"]
        cost    = tr.get("cost") or tr.get("proceeds", 0)
        margin  = "Margin" if tr.get("margin") else "Cash"
        rsi     = f"{tr['rsi']:.1f}" if tr.get("rsi") else "—"
        note    = tr.get("note", "")
        pnl     = tr.get("pnl")
        pnl_str = f"${pnl:+,.2f}" if pnl is not None else "—"
        bg      = "#f0fdf4" if action == "BUY" else "#fef2f2"
        color   = "#16a34a" if action == "BUY" else "#dc2626"

        if action == "BUY":
            total_invested += cost
        else:
            total_proceeds += cost

        rows_html += f"""
        <tr style="background:{bg};">
          <td style="padding:9px 12px;color:#64748b;font-size:12px;">{date}</td>
          <td style="padding:9px 12px;font-weight:bold;color:{color};">{action}</td>
          <td style="padding:9px 12px;font-weight:bold;">{ticker}</td>
          <td style="padding:9px 12px;color:#475569;">{name}</td>
          <td style="padding:9px 12px;text-align:right;">{shares}</td>
          <td style="padding:9px 12px;text-align:right;">${price:.2f}</td>
          <td style="padding:9px 12px;text-align:right;font-weight:bold;">${cost:,.2f}</td>
          <td style="padding:9px 12px;text-align:center;">{margin}</td>
          <td style="padding:9px 12px;text-align:center;">{rsi}</td>
          <td style="padding:9px 12px;color:#64748b;font-size:11px;">{pnl_str}</td>
          <td style="padding:9px 12px;color:#94a3b8;font-size:11px;">{note}</td>
        </tr>"""

    pnl_total = portfolio_value - ledger["start_value"]
    pnl_color = "#16a34a" if pnl_total >= 0 else "#dc2626"
    pnl_sign  = "+" if pnl_total >= 0 else ""
    date_str  = datetime.datetime.now().strftime("%B %d, %Y %H:%M IDT")

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Calibri,Arial,sans-serif;background:#f8fafc;padding:24px;color:#1e293b;">
<div style="max-width:860px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);">
  <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);padding:28px 32px;">
    <h1 style="color:#fff;margin:0;font-size:22px;">📋 Trade Log — Full History</h1>
    <p style="color:#94a3b8;margin:6px 0 0;">Generated {date_str} &nbsp;|&nbsp; Start: $100,000.00</p>
  </div>
  <div style="padding:24px 32px;">
    <div style="display:flex;gap:24px;margin-bottom:24px;flex-wrap:wrap;">
      <div style="background:#f1f5f9;border-radius:10px;padding:16px 24px;flex:1;min-width:160px;text-align:center;">
        <div style="font-size:12px;color:#64748b;">Portfolio Value</div>
        <div style="font-size:26px;font-weight:bold;">${portfolio_value:,.2f}</div>
        <div style="color:{pnl_color};font-weight:bold;">{pnl_sign}${pnl_total:,.2f} ({pnl_sign}{pnl_total/ledger['start_value']*100:.2f}%)</div>
      </div>
      <div style="background:#f1f5f9;border-radius:10px;padding:16px 24px;flex:1;min-width:160px;text-align:center;">
        <div style="font-size:12px;color:#64748b;">Total Trades</div>
        <div style="font-size:26px;font-weight:bold;">{len(trades)}</div>
        <div style="color:#64748b;font-size:12px;">{sum(1 for t in trades if t['action']=='BUY')} buys / {sum(1 for t in trades if t['action']=='SELL')} sells</div>
      </div>
      <div style="background:#f1f5f9;border-radius:10px;padding:16px 24px;flex:1;min-width:160px;text-align:center;">
        <div style="font-size:12px;color:#64748b;">Cash Remaining</div>
        <div style="font-size:26px;font-weight:bold;">${ledger['cash']:,.2f}</div>
        <div style="color:#64748b;font-size:12px;">Leverage: {ledger['leverage']}x</div>
      </div>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="background:#1e293b;color:#fff;">
          <th style="padding:10px 12px;text-align:left;">Date</th>
          <th style="padding:10px 12px;text-align:left;">Action</th>
          <th style="padding:10px 12px;text-align:left;">Ticker</th>
          <th style="padding:10px 12px;text-align:left;">Name</th>
          <th style="padding:10px 12px;text-align:right;">Shares</th>
          <th style="padding:10px 12px;text-align:right;">Price</th>
          <th style="padding:10px 12px;text-align:right;">Total</th>
          <th style="padding:10px 12px;text-align:center;">Type</th>
          <th style="padding:10px 12px;text-align:center;">RSI</th>
          <th style="padding:10px 12px;text-align:right;">P&amp;L</th>
          <th style="padding:10px 12px;text-align:left;">Note</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</div>
</body></html>"""

    plain = f"Trade Log — {date_str}\nPortfolio: ${portfolio_value:,.2f} ({pnl_sign}{pnl_total/ledger['start_value']*100:.2f}%)\n\n"
    plain += f"{'Date':<12} {'Action':<6} {'Ticker':<6} {'Shares':>6} {'Price':>8} {'Total':>10} {'RSI':>6} {'Note'}\n"
    plain += "-" * 80 + "\n"
    for tr in trades:
        cost = tr.get("cost") or tr.get("proceeds", 0)
        rsi  = f"{tr['rsi']:.1f}" if tr.get("rsi") else "  —"
        plain += f"{tr['date']:<12} {tr['action']:<6} {tr['ticker']:<6} {tr['shares']:>6} ${tr['price']:>7.2f} ${cost:>9,.2f} {rsi:>6}  {tr.get('note','')}\n"

    # Build CSV attachment
    csv_str      = _build_csv(trades)
    csv_b64      = base64.b64encode(csv_str.encode("utf-8")).decode("ascii")
    filename     = f"trade_log_{datetime.date.today().isoformat()}.csv"
    attachments  = [{"filename": filename, "content": csv_b64}]

    subject = f"📋 Trade Log — {len(trades)} trades | Portfolio ${portfolio_value:,.0f} ({pnl_sign}{pnl_total/ledger['start_value']*100:.2f}%)"
    send_email(subject, html, plain, attachments=attachments)
    log(f"[TRADE LOG] Sent — {len(trades)} trades + CSV attachment ({filename})")

# ── Main ──────────────────────────────────────────────────────
def run():
    log("=" * 55)
    log(f"SIMULATION MONITOR — {datetime.date.today()}")
    log("=" * 55)

    try:
        urllib.request.urlopen("http://localhost:8000/api/health", timeout=5)
    except Exception:
        notify_macos("⚠️ Sim Monitor", "Backend is DOWN — run simstart", urgent=True)
        log("[ERROR] Backend unreachable. Exiting.")
        sys.exit(1)

    ledger          = load_ledger()
    ensure_learning(ledger)          # initialise learning block if first run
    alerts          = []
    new_trades      = []
    positions_data  = {}
    position_inds   = {}   # RSI/MACD per current position for leverage calc
    portfolio_value = ledger["cash"]

    # ── 1. Review current positions ───────────────────────────
    for ticker, pos in list(ledger["positions"].items()):
        data = get_price(ticker)
        if not data or data["price"] is None:
            log(f"[SKIP] {ticker} — no price data")
            continue

        price    = data["price"]
        entry    = pos["entry"]
        stop     = pos["stop"]
        target   = pos["target"]
        shares   = pos["shares"]
        pnl_pct  = (price - entry) / entry * 100
        day_pct  = data.get("change_percent") or 0
        dist_stop= (price - stop) / price * 100
        progress = (price - entry) / (target - entry) * 100 if target > entry else 0

        # Collect indicators for this position (for leverage decision)
        ind = calc_indicators(ticker)
        if ind:
            ind["near_stop"] = dist_stop <= STOP_WARN_PCT * 100
            position_inds[ticker] = ind

        log(f"{ticker}  ${price:.2f}  day:{day_pct:+.2f}%  P&L:{pnl_pct:+.2f}%  stop_dist:{dist_stop:.1f}%"
            + (f"  RSI={ind['rsi']} MACD_h={ind['histogram']}" if ind else ""))

        # Stop-loss hit → auto-sell (pass exit indicators for learning)
        if price <= stop:
            tr = execute_sell(ledger, ticker, price, "STOP-LOSS", exit_indicators=ind)
            new_trades.append(tr)
            alerts.append(("🔴 STOP-LOSS", f"{ticker} sold @ ${price:.2f} | P&L: ${tr['pnl']:+.2f}", True))
            portfolio_value += tr["proceeds"]
            continue

        portfolio_value += shares * price
        positions_data[ticker] = {**pos, "price": price, "change_percent": day_pct}

        if dist_stop <= STOP_WARN_PCT * 100:
            alerts.append(("⚠️ Stop Warning", f"{ticker} ${price-stop:.2f} from stop (${stop:.2f})", False))
        if abs(day_pct) >= STRONG_MOVE * 100:
            alerts.append((f"📊 Big Move {'UP' if day_pct>0 else 'DOWN'}", f"{ticker} {day_pct:+.1f}% today", abs(day_pct) > 8))
        if progress >= 80:
            alerts.append(("💰 Near Target", f"{ticker} {progress:.0f}% to target ${target:.0f}", False))

    # ── 1b. Dynamic leverage decision ────────────────────────
    new_leverage, lev_reason = decide_leverage(position_inds, ledger)
    if new_leverage != ledger.get("leverage"):
        alerts.append(("⚖️ Leverage Changed", f"{ledger.get('leverage')}x → {new_leverage}x | {lev_reason}", False))
    ledger["leverage"] = new_leverage

    # ── 2. Scan watchlist for buy signals ─────────────────────
    # Current SPY RSI for regime tagging on buys
    spy_rsi_now = market_indicators.get("SPY", {}).get("rsi")
    th          = get_thresholds(ledger)   # adaptive thresholds from learning

    slots = MAX_POSITIONS - len(ledger["positions"])
    if slots > 0:
        log(f"Scanning watchlist — {slots} slot(s) open (RSI threshold: <{th['rsi']})")
        for ticker in WATCHLIST:
            if ticker in AVOID or ticker in ledger["positions"]:
                continue
            if len(ledger["positions"]) >= MAX_POSITIONS:
                break

            ind = calc_indicators(ticker)
            if ind is None:
                continue
            log(f"  {ticker}: RSI={ind['rsi']} MACD_hist={ind['histogram']}")

            if ind["rsi"] < th["rsi"]:          # use adaptive RSI threshold
                pd = get_price(ticker)
                if not pd or not pd["price"]:
                    continue
                price = pd["price"]
                # Double-confirm (RSI<threshold + MACD hist>0) → margin buy
                # Single confirm → cash only
                double_confirm = ind["histogram"] > 0
                use_margin     = double_confirm and ledger["cash"] < th["cash"]
                if use_margin:
                    orig_leverage       = ledger["leverage"]
                    ledger["leverage"]  = max(ledger["leverage"], 1.5)
                tr = execute_buy(ledger, ticker, price, ind, using_margin=use_margin,
                                 spy_rsi=spy_rsi_now)
                if use_margin:
                    ledger["leverage"] = orig_leverage  # restore after buy
                if tr:
                    new_trades.append(tr)
                    mode = "MARGIN" if use_margin else "CASH"
                    alerts.append(("🛒 Auto-Buy", f"{tr['shares']}x {ticker} @ ${price:.2f} [{mode}] RSI={ind['rsi']}", False))
                    positions_data[ticker] = {
                        "name": ticker, "price": price, "entry": price,
                        "shares": tr["shares"],
                        "stop": ledger["positions"][ticker]["stop"],
                        "target": ledger["positions"][ticker]["target"],
                        "change_percent": pd.get("change_percent", 0),
                    }

    # ── 3. Market-wide indicators (monitor only — no auto-buy) ──
    market_indicators = {}
    for ticker in MONITOR_ONLY:
        ind = calc_indicators(ticker)
        pd  = get_price(ticker)
        if ind and pd:
            market_indicators[ticker] = {**ind, "price": pd["price"]}
            rsi_warn = ind["rsi"] < 38
            log(f"  {ticker}: ${pd['price']:.2f}  RSI={ind['rsi']}  MACD_h={ind['histogram']}"
                + ("  ⚠️ OVERSOLD" if ind["rsi"] < 35 else ""))
            if ind["rsi"] < 35:
                alerts.append(("📉 Market Oversold", f"{ticker} RSI={ind['rsi']} — broad market weakness, positions may follow", False))

    # ── 4. Save ledger ────────────────────────────────────────
    save_ledger(ledger)

    # ── 4. Summary — recalculate from ledger state ────────────
    portfolio_value = ledger["cash"] + sum(
        pos["shares"] * positions_data.get(t, {}).get("price", pos["entry"])
        for t, pos in ledger["positions"].items()
    )
    total_pnl     = portfolio_value - ledger["start_value"]
    total_pnl_pct = (total_pnl / ledger["start_value"]) * 100
    log(f"Portfolio: ${portfolio_value:,.2f}  P&L: {total_pnl_pct:+.2f}%")

    # ── 5. Notifications ──────────────────────────────────────
    urgent = any(u for _, _, u in alerts)
    if urgent:
        notify_macos("🔴 Sim Alert", alerts[0][1], urgent=True)
    else:
        notify_macos("📊 Sim Update", f"${portfolio_value:,.0f} ({total_pnl_pct:+.2f}%)")

    # Build learning summary
    learn_ntfy, learn_html = build_learning_summary(ledger)

    subject    = f"📊 Tech Sim — ${portfolio_value:,.0f} ({'+' if total_pnl_pct>=0 else ''}{total_pnl_pct:.2f}%) — {datetime.date.today()}"
    html, plain = build_email_report(positions_data, portfolio_value, ledger["start_value"], alerts)
    html  += learn_html   # append learning block to email HTML
    plain += "\n" + "\n".join(learn_ntfy)
    send_email(subject, html, plain)

    ntfy_body  = build_ntfy_body(positions_data, portfolio_value, ledger["start_value"],
                               ledger["cash"], ledger["leverage"], alerts, new_trades, lev_reason,
                               market_indicators=market_indicators)
    ntfy_body += "\n" + "\n".join(learn_ntfy)
    now_str    = datetime.datetime.now().strftime("%b %d %Y %H:%M IDT")
    ntfy_title = f"📊 Close Report | {now_str} | ${portfolio_value:,.0f}"
    ntfy_tag   = "chart_with_upwards_trend" if total_pnl_pct >= 0 else "chart_with_downwards_trend"
    send_ntfy(ntfy_title, ntfy_body, priority="urgent" if urgent else "default", tags=ntfy_tag)

    # ── Trade log — email only (not ntfy) ─────────────────────
    send_trade_log(ledger, portfolio_value)

    log("Monitor run complete.")

if __name__ == "__main__":
    run()
