#!/usr/bin/env python3
"""
sim_trader_live.py — Autonomous intraday day-trading agent

Target: 6-8 round-trip trades per day.
Strategy: fast cycling — enter on signal, exit at 1.0% profit or 0.5% stop,
          immediately re-scan for next entry.

Config:
  POLL_INTERVAL = 2 min   (fast enough to catch 5-min bar signals)
  MAX_POSITIONS = 3        (3 simultaneous → 6-9 trades/day cycling)
  TARGET_PCT    = 0.8%     (quick lock — don't be greedy)
  STOP_PCT      = 0.5%     (cut fast — preserve capital)

Priority universe: volatile tech stocks (ATR > 1.5% daily)

Usage:
    python3 sim_trader_live.py            # live, runs until 15:50 ET
    python3 sim_trader_live.py --once     # one tick then exit
    python3 sim_trader_live.py --dry      # decide but don't execute
"""

from __future__ import annotations
import datetime, json, os, sys, time, warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from sim_daytrader import (
    load_ledger, save_ledger, get_thresholds, ensure_learning,
    calc_5min, detect_candles, calc_vwap_orb,
    score_open_signal, execute_buy, execute_sell, send_ntfy, log,
)
from llm_council import council_decide, record_outcome, scoreboard as council_scoreboard

# ── Trading parameters ────────────────────────────────────────────────────────

POLL_INTERVAL   = 2 * 60       # 2 minutes
MAX_POSITIONS   = 3            # concurrent positions
TARGET_PCT      = 1.0          # % gain → sell  (2:1 R:R vs 0.5% stop)
STOP_PCT        = 0.5          # % loss → sell
STRONG_TARGET   = 1.5          # on ORB breakout or strong candles
FORCE_CLOSE_MIN = (15, 50)     # ET: force-close everything

DRY_RUN = "--dry"  in sys.argv
ONCE    = "--once" in sys.argv

# ── Volatile-first universe ───────────────────────────────────────────────────
# Sorted by typical intraday ATR (most volatile first).
# The scanner checks these in order — hot movers get first shot.

VOLATILE_FIRST = [
    "MSTR","SMCI","RIVN","ARM","TSLA","NVDA","PLTR","AMD","AVGO",
    "META","ROKU","MRVL","VRT","CRWD","NET","DDOG","SNOW","ZS",
    "SHOP","UBER","NFLX","GOOGL","AMZN","MSFT","AAPL","ORCL",
    "CRM","ADBE","NOW","WDAY","INTU","QCOM","NXPI","MU","KLAC",
    "AMAT","LRCX","ANET","IBM","TXN","ADI","MSI","SNPS","CDNS",
    "AKAM","KEYS","OKTA","PANW","STX","LCID",
]

# ── Market hours ──────────────────────────────────────────────────────────────

def _et_now() -> datetime.datetime:
    return datetime.datetime.utcnow() - datetime.timedelta(hours=4)

def is_market_open() -> bool:
    now = _et_now()
    if now.weekday() >= 5:
        return False
    return datetime.time(9, 30) <= now.time() < datetime.time(16, 0)

def should_force_close() -> bool:
    return _et_now().time() >= datetime.time(*FORCE_CLOSE_MIN)

# ── LLM council shim ─────────────────────────────────────────────────────────
# council_decide() runs all available judges in parallel and returns majority vote.

def llm_decide(sym: str, rsi: float, macd_h: float, price: float,
               gap_pct: float, news: str, in_pos: bool,
               pnl_pct: float, rules: str,
               trade_id: str = "") -> tuple[str, str]:
    dec, reason, _ = council_decide(
        sym=sym, price=price, rsi=rsi, macd_h=macd_h,
        gap_pct=gap_pct, news=news, in_pos=in_pos, pnl_pct=pnl_pct,
        target_pct=TARGET_PCT, stop_pct=STOP_PCT, trade_id=trade_id,
    )
    return dec, reason

# ── Rule engine ───────────────────────────────────────────────────────────────

def rules_entry(rsi: float, macd_h: float) -> str:
    if rsi > 70:
        return "HOLD"
    if (38 <= rsi <= 58) and macd_h > 0:
        return "BUY"
    if rsi < 35 and macd_h > 0:
        return "BUY"
    return "HOLD"

def rules_exit(pnl_pct: float, rsi: float, macd_h: float, entry_macd_h: float = 0) -> str:
    if pnl_pct >= TARGET_PCT:
        return "SELL"
    if pnl_pct <= -STOP_PCT:
        return "SELL"
    if pnl_pct > 0.3 and macd_h < 0:   # protect small gain
        return "SELL"
    if rsi > 75:
        return "SELL"
    return "HOLD"

# ── Gap helper ────────────────────────────────────────────────────────────────

def get_gap(sym: str) -> float:
    try:
        import yfinance as yf
        h = yf.Ticker(sym).history(period="2d")
        if len(h) >= 2:
            return round((float(h["Open"].iloc[-1]) - float(h["Close"].iloc[-2]))
                         / float(h["Close"].iloc[-2]) * 100, 2)
    except Exception:
        pass
    return 0.0

def get_news_title(sym: str) -> str:
    try:
        import yfinance as yf
        news = yf.Ticker(sym).news
        if news:
            return news[0].get("content", {}).get("title", "")[:80]
    except Exception:
        pass
    return ""

# ── Target calculator (fast-cycle mode) ──────────────────────────────────────

def fast_target(price: float, orb_break: str = None, candle_score: int = 0) -> float:
    if orb_break == "UP" or candle_score >= 2:
        return STRONG_TARGET
    return TARGET_PCT

# ── One tick ─────────────────────────────────────────────────────────────────

def run_tick(ledger: dict, dry: bool = False) -> list[str]:
    """One poll cycle: exit checks → entry scan. Returns action strings."""
    th = get_thresholds(ledger)
    today = _et_now().strftime("%Y-%m-%d")
    actions = []

    day_pnl = sum(t.get("pnl", 0) for t in ledger["trades"]
                  if t["date"] == today and t["action"] == "SELL")
    max_loss_hit = day_pnl <= -(ledger.get("equity", 25000) * th["max_loss"] / 100)

    # ── 1. Exit checks ────────────────────────────────────────────────
    for sym in list(ledger["open_positions"].keys()):
        pos = ledger["open_positions"][sym]
        ind = calc_5min(sym)
        if not ind:
            continue

        price   = ind["price"]
        rsi     = ind["rsi"]
        macd_h  = ind["histogram"]
        pnl_pct = (price - pos["entry"]) / pos["entry"] * 100

        # Hard stop / target — no LLM override
        if price <= pos["stop"]:
            reason = f"סטופ ${pos['stop']:.2f}"
        elif price >= pos["target"]:
            reason = f"יעד ${pos['target']:.2f} (+{TARGET_PCT}%)"
        else:
            rule = rules_exit(pnl_pct, rsi, macd_h)
            dec, reason = llm_decide(sym, rsi, macd_h, price,
                                     0, "", True, pnl_pct, rule)
            if dec != "SELL":
                log(f"  HOLD {sym}: ${price:.2f} P&L={pnl_pct:+.1f}% RSI={rsi:.0f} — {reason}")
                continue

        if not dry:
            trade_id = pos.get("trade_id", "")
            votes    = pos.get("council_votes", {})
            tr = execute_sell(ledger, sym, price, reason, exit_ind=ind)
            if tr:
                if trade_id:
                    record_outcome(trade_id, tr["pnl"], votes)
                emoji = "💰" if tr["pnl"] >= 0 else "🔴"
                actions.append(
                    f"SELL {sym} @ ${price:.2f}  "
                    f"P&L {tr['pnl']:+.0f}$ ({tr['pnl_pct']:+.1f}%)  [{reason}]"
                )
                send_ntfy(
                    f"{emoji} SELL {sym}",
                    f"${price:.2f} | {tr['pnl']:+.0f}$ ({tr['pnl_pct']:+.1f}%)\n"
                    f"RSI={rsi:.0f} | {reason}\n"
                    f"יום P&L: {day_pnl + tr['pnl']:+.0f}$",
                    priority="default", tags="money_with_wings" if tr["pnl"] >= 0 else "x",
                )
        else:
            actions.append(f"[DRY] SELL {sym} @ ${price:.2f}  P&L={pnl_pct:+.1f}%")

    # ── 2. Entry scan — volatile stocks first ─────────────────────────
    if max_loss_hit:
        log(f"  [GUARD] הפסד יומי מקסימלי — אין כניסות חדשות")
        return actions

    open_count = len(ledger["open_positions"])
    if open_count >= MAX_POSITIONS:
        return actions

    for sym in VOLATILE_FIRST:
        if open_count >= MAX_POSITIONS:
            break
        if sym in ledger["open_positions"]:
            continue

        ind = calc_5min(sym)
        if not ind:
            continue

        rsi, macd_h, price = ind["rsi"], ind["histogram"], ind["price"]

        # Pre-filter: skip overbought or falling
        if rsi > 70 or (macd_h < 0 and rsi > 50):
            continue

        # Skip if not enough cash for a real position
        available_cash = ledger["cash"]
        if available_cash < 2000:
            continue

        rule = rules_entry(rsi, macd_h)
        if rule == "HOLD":
            continue

        candles = detect_candles(sym)
        orb     = calc_vwap_orb(sym)
        score, _ = score_open_signal(sym, ind, candles, orb)

        # Need minimum signal quality
        if score < 3:
            continue

        gap      = get_gap(sym)
        news     = get_news_title(sym)
        trade_id = f"{sym}_{_et_now().strftime('%Y%m%d_%H%M%S')}"
        dec, reason, c_votes = council_decide(
            sym=sym, price=price, rsi=rsi, macd_h=macd_h,
            gap_pct=gap, news=news, in_pos=False, pnl_pct=0.0,
            target_pct=TARGET_PCT, stop_pct=STOP_PCT, trade_id=trade_id,
        )
        if dec != "BUY":
            continue

        strategy = "momentum" if rsi >= 38 else "reversal"
        orb_break = orb["orb_break"] if orb else None
        candle_score = candles["candle_score"] if candles else 0
        tpct = fast_target(price, orb_break, candle_score)

        # Override execute_buy's stop/target with our fast-cycle values
        news_stub = {"category": "live", "score": score,
                     "title": news or f"{sym} {strategy}", "age_hours": 0}

        if not dry:
            tr = execute_buy(ledger, sym, price, ind, strategy, news_stub, target_pct=tpct)
            if tr:
                # Patch stop to 0.5% (execute_buy uses 1.5%)
                new_stop = round(price * (1 - STOP_PCT / 100), 2)
                new_tgt  = round(price * (1 + tpct / 100), 2)
                ledger["open_positions"][sym]["stop"]          = new_stop
                ledger["open_positions"][sym]["target"]        = new_tgt
                ledger["open_positions"][sym]["target_pct"]    = tpct
                ledger["open_positions"][sym]["trade_id"]      = trade_id
                ledger["open_positions"][sym]["council_votes"] = c_votes

                open_count += 1
                actions.append(
                    f"BUY {tr['shares']}×{sym} @ ${price:.2f} = ${tr['cost']:,.0f}  "
                    f"[{strategy}] RSI={rsi:.0f} MACD_h={macd_h:+.3f}  "
                    f"stop=${new_stop:.2f} target=${new_tgt:.2f} (+{tpct}%)"
                )
                signal_note = reason if not reason.startswith("rules (LLM") else strategy.upper()
                send_ntfy(
                    f"🛒 BUY {sym}",
                    f"${price:.2f} | {tr['shares']}sh | ${tr['cost']:,.0f}\n"
                    f"RSI={rsi:.0f} MACD_h={macd_h:+.3f} | {signal_note}\n"
                    f"Stop: ${new_stop:.2f} (-{STOP_PCT}%) | Target: ${new_tgt:.2f} (+{tpct}%)",
                    priority="high", tags="shopping_cart",
                )
        else:
            actions.append(
                f"[DRY] BUY {sym} @ ${price:.2f}  "
                f"[{strategy}] RSI={rsi:.0f} MACD_h={macd_h:+.3f}  {reason}"
            )

    return actions

# ── Force close ───────────────────────────────────────────────────────────────

def force_close_all(ledger: dict, dry: bool = False):
    syms = list(ledger["open_positions"].keys())
    if not syms:
        return
    log("[EOD] סוגר את כל הפוזיציות לפני סגירת שוק")
    for sym in syms:
        ind = calc_5min(sym)
        price = ind["price"] if ind else ledger["open_positions"][sym]["entry"]
        if not dry:
            tr = execute_sell(ledger, sym, price, "force_close_eod", exit_ind=ind)
            if tr:
                send_ntfy(
                    f"🔔 EOD {sym}",
                    f"${price:.2f} | P&L {tr['pnl']:+.0f}$ ({tr['pnl_pct']:+.1f}%)",
                    priority="default", tags="bell",
                )
        else:
            log(f"  [DRY] סגירה {sym} @ ${price:.2f}")

# ── Summary ntfy ─────────────────────────────────────────────────────────────

def send_daily_summary(ledger: dict):
    today = _et_now().strftime("%Y-%m-%d")
    trades = [t for t in ledger["trades"] if t["date"] == today and t["action"] == "SELL"]
    if not trades:
        return
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    wins  = sum(1 for t in trades if t.get("pnl", 0) >= 0)
    losses = len(trades) - wins
    score_lines = council_scoreboard()
    send_ntfy(
        f"📊 יום נגמר | {len(trades)} עסקאות | P&L {total_pnl:+.0f}$",
        f"✅ {wins} רווח | ❌ {losses} הפסד\n"
        f"Win rate: {wins/len(trades)*100:.0f}%\n"
        f"הון: ${ledger.get('equity', 25000):,.0f}\n\n"
        f"{score_lines}",
        priority="default", tags="chart_with_upwards_trend" if total_pnl >= 0 else "chart_with_downwards_trend",
    )

# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    mode = "[DRY]" if DRY_RUN else "[LIVE]"
    log(f"=== sim_trader_live {mode} ===")
    log(f"    LLM: Council mode (rules + all configured API judges)")
    log(f"    Poll: {POLL_INTERVAL//60}min | Positions: {MAX_POSITIONS} | Target: +{TARGET_PCT}% | Stop: -{STOP_PCT}%")
    log(f"    מניות: חדות ראשון ({len(VOLATILE_FIRST)} ביקום)")

    if not is_market_open():
        log("  שוק סגור — ממתין לפתיחה")
        if ONCE:
            return
        while not is_market_open():
            time.sleep(60)

    ledger = load_ledger()
    ensure_learning(ledger)
    tick = 0

    while True:
        et = _et_now()
        if not is_market_open():
            log(f"  שוק נסגר {et.strftime('%H:%M ET')} — סיום")
            break

        tick += 1
        log(f"\n── Tick {tick} | {et.strftime('%H:%M ET')} ──")

        if should_force_close():
            force_close_all(ledger, dry=DRY_RUN)
            if not DRY_RUN:
                import yfinance as yf
                eq = ledger["cash"] + sum(
                    p["shares"] * p["entry"]
                    for p in ledger["open_positions"].values()
                )
                ledger["equity"] = round(eq, 2)
                save_ledger(ledger)
                send_daily_summary(ledger)
            log("  סגירת EOD — סיום")
            break

        try:
            actions = run_tick(ledger, dry=DRY_RUN)
        except Exception as e:
            log(f"  [ERROR] {e}")
            actions = []

        if actions:
            for a in actions:
                log(f"  ★ {a}")

        # Recalculate equity and save after any action
        if actions and not DRY_RUN:
            try:
                import yfinance as yf
                eq = ledger["cash"]
                for sym, p in ledger["open_positions"].items():
                    try:
                        px = float(yf.Ticker(sym).history(period="1d", interval="5m")["Close"].iloc[-1])
                    except Exception:
                        px = p["entry"]
                    eq += px * p["shares"]
                ledger["equity"] = round(eq, 2)
            except Exception:
                pass
            save_ledger(ledger)

        # Status line when holding
        open_pos = ledger["open_positions"]
        if open_pos:
            for sym, p in open_pos.items():
                ind = calc_5min(sym)
                px = ind["price"] if ind else p["entry"]
                pnl = round((px - p["entry"]) / p["entry"] * 100, 2)
                log(f"  ○ {sym}: ${px:.2f}  P&L={pnl:+.1f}%  stop=${p['stop']:.2f}  target=${p['target']:.2f}")
        else:
            log(f"  ○ אין פוזיציות — סורק כניסות בטיק הבא")

        today = et.strftime("%Y-%m-%d")
        trades_today = [t for t in ledger["trades"] if t["date"] == today and t["action"] == "SELL"]
        if trades_today:
            pnl_today = sum(t.get("pnl", 0) for t in trades_today)
            log(f"  📊 היום: {len(trades_today)} עסקאות | P&L יומי: {pnl_today:+.0f}$")

        if ONCE:
            if not DRY_RUN:
                save_ledger(ledger)
            log("=== --once: סיום ===")
            break

        log(f"  שינה {POLL_INTERVAL//60} דקות...")
        time.sleep(POLL_INTERVAL)

    if not DRY_RUN:
        save_ledger(ledger)
    log("=== sim_trader_live done ===")


if __name__ == "__main__":
    main()
