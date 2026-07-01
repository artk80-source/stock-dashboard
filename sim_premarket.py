#!/usr/bin/env python3
"""
Tech Simulation — Pre-Market Scanner
Runs at 16:25 IDT (5 min before US market open at 16:30 IDT).
Captures the full pre-market session as a briefing before open.
Sends ntfy push + email report with gaps, stop-loss proximity, movers.
"""

import sys
import os
import json
import datetime
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from sim_notify import send_ntfy, send_email, notify_macos
try:
    from sim_daytrader import get_day_summary as _get_day_summary
except Exception:
    _get_day_summary = None

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "sim_ledger.json")
AVOID       = {
    "AMAT","LRCX","KLAC","AMD","TXN",
    "CSCO","INTC","CDNS","FTNT","PANW","MRVL",
}
WATCHLIST   = [
    "NVDA","AVGO","MSFT","AAPL","ORCL","PLTR","ANET","VRT",
    "MU","QCOM","NOW","CRWD","IBM","ADBE","CRM",
    "SNPS","WDAY","INTU","ADI","NXPI","MSI","AKAM","KEYS",
    "TQQQ",
]
MONITOR_ONLY = {"SPY", "QQQ"}

def log(msg):
    ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"{ts}  [PRE] {msg}"
    print(line)
    with open("/tmp/sim_monitor.log", "a") as f:
        f.write(line + "\n")

def get_premarket(ticker):
    """Fetch pre-market price, prev close, and volume via yfinance."""
    try:
        import yfinance as yf
        tk   = yf.Ticker(ticker)
        hist = tk.history(period="2d", interval="1m", prepost=True)
        if hist.empty:
            return None

        now_et = datetime.datetime.utcnow() - datetime.timedelta(hours=4)
        market_open_today = now_et.replace(hour=9, minute=30, second=0, microsecond=0)

        # Pre-market rows: today's data before 09:30 ET
        today_str   = now_et.strftime("%Y-%m-%d")
        pre_rows    = hist[
            (hist.index.strftime("%Y-%m-%d") == today_str) &
            (hist.index.time < market_open_today.time())
        ]
        # Previous close: last bar from yesterday
        prev_rows   = hist[hist.index.strftime("%Y-%m-%d") < today_str]

        if pre_rows.empty or prev_rows.empty:
            return None

        pre_price  = float(pre_rows["Close"].iloc[-1])
        pre_volume = int(pre_rows["Volume"].sum())
        prev_close = float(prev_rows["Close"].iloc[-1])
        gap_pct    = (pre_price - prev_close) / prev_close * 100

        return {
            "pre_price":  round(pre_price, 2),
            "prev_close": round(prev_close, 2),
            "gap_pct":    round(gap_pct, 2),
            "pre_volume": pre_volume,
        }
    except Exception as e:
        log(f"{ticker} failed: {e}")
        return None

def run():
    now_str = datetime.datetime.now().strftime("%H:%M IDT")
    date_str = datetime.date.today().strftime("%b %d, %Y")

    log("=" * 50)
    log(f"PRE-MARKET SCAN — {date_str} @ {now_str}")
    log("=" * 50)

    with open(LEDGER_PATH) as f:
        ledger = json.load(f)

    positions  = ledger["positions"]
    alerts     = []
    lines      = [
        f"🌅 Pre-Market Scan | {date_str} {now_str}",
        f"Market opens in ~30 min (16:30 IDT)",
        "",
        "YOUR POSITIONS",
    ]

    urgent = False

    # ── Scan current positions ────────────────────────────────
    for ticker, pos in positions.items():
        data = get_premarket(ticker)
        if not data:
            lines.append(f"⬜ {ticker}  — no pre-market data")
            log(f"{ticker}: no data")
            continue

        pre   = data["pre_price"]
        prev  = data["prev_close"]
        gap   = data["gap_pct"]
        vol   = data["pre_volume"]
        stop  = pos["stop"]
        entry = pos["entry"]
        shares= pos["shares"]
        value = shares * pre
        dist_stop = (pre - stop) / pre * 100
        pnl_pct   = (pre - entry) / entry * 100

        gap_arrow = "▲" if gap >= 0 else "▼"
        dot = "🟢" if gap >= 0 else ("🔴" if gap < -3 else "🟡")

        log(f"{ticker}: pre=${pre:.2f} prev=${prev:.2f} gap={gap:+.2f}% vol={vol:,} stop_dist={dist_stop:.1f}%")

        line = (
            f"{dot} {ticker}  ${pre:.2f} ({gap_arrow}{abs(gap):.2f}% gap)"
            f"  |  Value: ${value:,.0f}"
            f"  |  P&L: {'+' if pnl_pct>=0 else ''}{pnl_pct:.1f}%"
            f"  |  Stop dist: {dist_stop:.1f}%"
            f"  |  Vol: {vol/1000:.0f}K"
        )
        lines.append(line)

        # Critical: near stop-loss in pre-market
        if pre <= stop:
            alerts.append(f"🔴 {ticker} PRE-MARKET BELOW STOP-LOSS! ${pre:.2f} ≤ ${stop:.2f}")
            urgent = True
        elif dist_stop < 3:
            alerts.append(f"⚠️ {ticker} only {dist_stop:.1f}% from stop (${stop:.2f}) in pre-market")

        # Big gap down
        if gap < -4:
            alerts.append(f"🔴 {ticker} gapping DOWN {gap:.2f}% — watch at open")
            urgent = True
        elif gap < -2:
            alerts.append(f"⚠️ {ticker} gapping down {gap:.2f}%")

        # Big gap up — take-profit opportunity
        if gap > 4:
            alerts.append(f"💰 {ticker} gapping UP {gap:.2f}% — consider partial take-profit")

    # ── Watchlist pre-market movers ───────────────────────────
    movers = []
    for ticker in WATCHLIST:
        if ticker in positions or ticker in AVOID:
            continue
        data = get_premarket(ticker)
        if not data:
            continue
        gap = data["gap_pct"]
        pre = data["pre_price"]
        if abs(gap) >= 2:
            arrow = "▲" if gap >= 0 else "▼"
            movers.append((abs(gap), f"{'🟢' if gap>0 else '🔴'} {ticker} ${pre:.2f} {arrow}{abs(gap):.2f}%"))
            log(f"WATCHLIST {ticker}: gap={gap:+.2f}%")

    if movers:
        movers.sort(reverse=True)
        lines += ["", "WATCHLIST MOVERS (≥2% gap)"]
        lines += [m[1] for m in movers[:5]]

    # ── Market-wide pulse (SPY/QQQ — pre-market gap only) ────
    market_lines = []
    for ticker in sorted(MONITOR_ONLY):
        data = get_premarket(ticker)
        if not data:
            continue
        gap  = data["gap_pct"]
        pre  = data["pre_price"]
        dot  = "🟢" if gap >= 0 else ("🔴" if gap < -1.5 else "🟡")
        arrow= "▲" if gap >= 0 else "▼"
        market_lines.append(f"{dot} {ticker}  ${pre:.2f} ({arrow}{abs(gap):.2f}% gap)")
        if gap < -2:
            alerts.append(f"⚠️ {ticker} pre-market gap DOWN {gap:.2f}% — broad market weakness")
            urgent = True
    if market_lines:
        lines += ["", "MARKET PULSE (SPY / QQQ)"]
        lines += market_lines

    # ── Alerts section ────────────────────────────────────────
    if alerts:
        lines += ["", "⚠️ ALERTS"]
        lines += alerts

    if not alerts:
        lines.append("")
        lines.append("✅ All clear — no critical pre-market alerts")

    # ── Day trade section (overnight positions + today's candidates) ─
    day_ntfy, day_html, day_plain = [], "", ""
    if _get_day_summary:
        try:
            day_ntfy, day_html, day_plain = _get_day_summary()
        except Exception:
            pass

    # ── Send ntfy ─────────────────────────────────────────────
    ntfy_title = f"🌅 Pre-Market | {date_str} {now_str}"
    ntfy_body  = "\n".join(lines) + "\n" + "\n".join(day_ntfy)
    priority   = "urgent" if urgent else "default"
    tags       = "sunrise" if not urgent else "warning"
    send_ntfy(ntfy_title, ntfy_body, priority=priority, tags=tags)

    # ── Send email ────────────────────────────────────────────
    subject    = f"🌅 Pre-Market Briefing — {date_str} {now_str}"
    plain_body = ntfy_body + "\n" + day_plain
    html_body  = _build_premarket_html(lines, alerts, date_str, now_str, urgent) + day_html
    send_email(subject, html_body, plain_body)

    # ── macOS notification ────────────────────────────────────
    if urgent:
        notify_macos("🔴 Pre-Market Alert", alerts[0] if alerts else "Check positions now!", urgent=True)
    else:
        notify_macos("🌅 Pre-Market", f"{now_str} — market opens in 5 min")

    log("Pre-market scan complete.")


def _build_premarket_html(lines, alerts, date_str, now_str, urgent):
    alert_color  = "#dc2626" if urgent else "#f59e0b"
    alert_bg     = "#fef2f2" if urgent else "#fffbeb"
    rows_html    = ""
    for line in lines:
        if line.startswith("🟢"):
            rows_html += f'<div style="padding:6px 0;border-bottom:1px solid #f1f5f9;color:#16a34a;">{line}</div>'
        elif line.startswith("🔴"):
            rows_html += f'<div style="padding:6px 0;border-bottom:1px solid #f1f5f9;color:#dc2626;">{line}</div>'
        elif line.startswith("🟡") or line.startswith("⬜"):
            rows_html += f'<div style="padding:6px 0;border-bottom:1px solid #f1f5f9;color:#92400e;">{line}</div>'
        elif line.startswith("⚠️") or line.startswith("✅"):
            rows_html += f'<div style="padding:8px 0;font-weight:bold;">{line}</div>'
        elif line == "":
            rows_html += '<div style="height:10px;"></div>'
        else:
            rows_html += f'<div style="padding:4px 0;color:#475569;font-size:13px;">{line}</div>'

    alerts_html = ""
    for a in alerts:
        alerts_html += f'<div style="background:{alert_bg};border-left:4px solid {alert_color};padding:10px 14px;margin:6px 0;border-radius:4px;">{a}</div>'
    if not alerts_html:
        alerts_html = '<div style="color:#16a34a;padding:8px 0;">✅ No critical alerts — all positions safe pre-market.</div>'

    return f"""<!DOCTYPE html>
<html><body style="font-family:Calibri,Arial,sans-serif;background:#f8fafc;padding:24px;color:#1e293b;">
<div style="max-width:640px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);">
  <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);padding:28px 32px;">
    <h1 style="color:#fff;margin:0;font-size:22px;">🌅 Pre-Market Briefing</h1>
    <p style="color:#94a3b8;margin:6px 0 0;">{date_str} — {now_str} &nbsp;|&nbsp; Market opens in 5 min</p>
  </div>
  <div style="padding:24px 32px;">
    <div style="font-family:monospace;font-size:13px;line-height:1.8;">{rows_html}</div>
    <h3 style="margin:22px 0 10px;color:#334155;">Alerts</h3>
    {alerts_html}
    <div style="margin-top:24px;padding-top:18px;border-top:1px solid #e2e8f0;font-size:12px;color:#94a3b8;text-align:center;">
      Full close report arrives at 23:15 IDT after market close.
    </div>
  </div>
</div>
</body></html>"""

if __name__ == "__main__":
    run()
