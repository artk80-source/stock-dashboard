#!/usr/bin/env python3
"""
Tech Simulation Monitor
Runs automatically every weekday evening via cron.
Checks stop-losses, momentum shifts, and major moves.
Sends macOS notifications if action is needed.
"""

import subprocess
import json
import sys
import datetime
import os
sys.path.insert(0, os.path.dirname(__file__))
from sim_notify import (
    notify_macos, send_email, send_whatsapp, send_ntfy,
    build_email_report, build_whatsapp_summary
)

# ── Portfolio positions ─────────────────────────────────────
POSITIONS = {
    "CRM":  {"entry": 158.37, "stop": 145.70, "target": 251.53, "shares": 157, "name": "Salesforce"},
    "ADBE": {"entry": 202.73, "stop": 186.51, "target": 282.27, "shares": 108, "name": "Adobe"},
    "MSFT": {"entry": 372.97, "stop": 343.13, "target": 561.11, "shares": 67,  "name": "Microsoft"},
    "NOW":  {"entry": 98.34,  "stop": 90.47,  "target": 141.48, "shares": 183, "name": "ServiceNow"},
}
CASH = 10255.86
START_VALUE = 100_000.00

# ── Alert thresholds ────────────────────────────────────────
STOP_LOSS_WARNING_PCT = 0.04   # Warn when within 4% of stop-loss
STRONG_MOVE_PCT       = 0.05   # Alert on +/-5% single-day move
TAKE_PROFIT_PCT       = 0.80   # Alert when 80% of the way to target

# ── Notification helper ─────────────────────────────────────
def notify(title, message, urgent=False):
    sound = "Sosumi" if urgent else "default"
    script = f'''display notification "{message}" with title "{title}" sound name "{sound}"'''
    subprocess.run(["osascript", "-e", script], capture_output=True)
    log(f"[NOTIFY] {title}: {message}")

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"{ts}  {msg}"
    print(line)
    with open("/tmp/sim_monitor.log", "a") as f:
        f.write(line + "\n")

# ── Fetch price from backend ────────────────────────────────
def get_price(ticker):
    try:
        import urllib.request
        url = f"http://localhost:8000/api/stock/{ticker}/analysis"
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
        day = data.get("data", {}).get("day_trade", {})
        return {
            "price":          day.get("price"),
            "change_percent": day.get("change_percent"),
            "volume":         day.get("volume"),
            "avg_volume":     day.get("avg_volume"),
        }
    except Exception as e:
        log(f"[ERROR] Could not fetch {ticker}: {e}")
        return None

# ── Main monitor logic ───────────────────────────────────────
def run():
    log("=" * 55)
    log("SIMULATION MONITOR — Daily Check")
    log("=" * 55)

    # Check backend is up
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8000/api/health", timeout=5)
    except Exception:
        notify("⚠️ Sim Monitor", "Backend is DOWN — run simstart in terminal", urgent=True)
        log("[ERROR] Backend unreachable. Exiting.")
        sys.exit(1)

    portfolio_value = CASH
    alerts = []
    summary_lines = []

    for ticker, pos in POSITIONS.items():
        data = get_price(ticker)
        if not data or data["price"] is None:
            log(f"[SKIP] {ticker} — no data")
            continue

        price        = data["price"]
        change_pct   = data["change_percent"] or 0
        entry        = pos["entry"]
        stop         = pos["stop"]
        target       = pos["target"]
        shares       = pos["shares"]
        name         = pos["name"]

        position_value = shares * price
        portfolio_value += position_value
        pnl_pct = ((price - entry) / entry) * 100
        dist_to_stop_pct = ((price - stop) / price) * 100
        progress_to_target = (price - entry) / (target - entry) * 100

        log(f"{ticker}  ${price:.2f}  day:{change_pct:+.2f}%  P&L:{pnl_pct:+.2f}%  dist_stop:{dist_to_stop_pct:.1f}%")

        # ── CRITICAL: Stop-loss HIT ──────────────────────────
        if price <= stop:
            msg = f"{ticker} ({name}) STOP-LOSS HIT at ${price:.2f}! Entry was ${entry:.2f}. EXIT NOW."
            alerts.append(("🔴 STOP-LOSS HIT", msg, True))

        # ── WARNING: Approaching stop-loss ───────────────────
        elif dist_to_stop_pct <= STOP_LOSS_WARNING_PCT * 100:
            msg = f"{ticker} is ${price - stop:.2f} away from stop-loss (${stop:.2f}). Watch closely."
            alerts.append(("⚠️ Stop-Loss Warning", msg, False))

        # ── ALERT: Big single-day move ────────────────────────
        if abs(change_pct) >= STRONG_MOVE_PCT * 100:
            direction = "UP" if change_pct > 0 else "DOWN"
            msg = f"{ticker} moved {change_pct:+.1f}% today. Run 'sim' for full analysis."
            alerts.append((f"📈 Big Move {direction}", msg, abs(change_pct) > 8))

        # ── ALERT: Near take-profit target ───────────────────
        if progress_to_target >= TAKE_PROFIT_PCT * 100:
            msg = f"{ticker} is {progress_to_target:.0f}% of the way to target ${target:.0f}. Consider partial take-profit."
            alerts.append(("💰 Near Target", msg, False))

        summary_lines.append(
            f"{ticker}: ${price:.2f} ({pnl_pct:+.1f}%)"
        )

    # ── Portfolio summary notification ────────────────────────
    total_pnl = portfolio_value - START_VALUE
    total_pnl_pct = (total_pnl / START_VALUE) * 100
    log(f"Portfolio: ${portfolio_value:,.2f}  P&L: {total_pnl_pct:+.2f}%")

    # ── Build positions data dict for reports ─────────────────
    positions_data = {}
    for ticker, pos in POSITIONS.items():
        d = get_price(ticker)
        if d and d["price"]:
            positions_data[ticker] = {
                "name":           pos["name"],
                "price":          d["price"],
                "entry":          pos["entry"],
                "stop":           pos["stop"],
                "target":         pos["target"],
                "change_percent": d["change_percent"],
            }

    # ── macOS notification (urgent alerts) ────────────────────
    for title, msg, urgent in alerts:
        notify_macos(title, msg, urgent=urgent)

    if not alerts:
        notify_macos("📊 Sim Daily Update",
            f"Portfolio: ${portfolio_value:,.2f} ({total_pnl_pct:+.1f}%)")

    # ── Email report ──────────────────────────────────────────
    subject = f"📊 Tech Sim Report — ${portfolio_value:,.0f} ({total_pnl_pct:+.1f}%) — {datetime.date.today()}"
    html, plain = build_email_report(positions_data, portfolio_value, START_VALUE, alerts)
    send_email(subject, html, plain)

    # ── WhatsApp summary ──────────────────────────────────────
    wa_msg = build_whatsapp_summary(positions_data, portfolio_value, START_VALUE, alerts)
    send_whatsapp(wa_msg)

    # ── ntfy.sh push notification ─────────────────────────────
    pnl_sign  = "+" if total_pnl_pct >= 0 else ""
    ntfy_icon = "chart_with_upwards_trend" if total_pnl_pct >= 0 else "chart_with_downwards_trend"
    ntfy_pri  = "urgent" if any(u for _, _, u in alerts) else "default"
    ntfy_title = f"Tech Sim — ${portfolio_value:,.0f} ({pnl_sign}{total_pnl_pct:.2f}%)"
    ntfy_body  = "\n".join(
        f"{t}: ${d['price']:.2f}  P&L: {((d['price']-d['entry'])/d['entry']*100):+.1f}%  Day: {d.get('change_percent',0):+.1f}%"
        for t, d in positions_data.items()
    )
    if alerts:
        ntfy_body += "\n\n⚠️ ALERTS:\n" + "\n".join(f"{a[0]}: {a[1]}" for a in alerts)
    send_ntfy(ntfy_title, ntfy_body, priority=ntfy_pri, tags=ntfy_icon)

    log("Monitor run complete.")
    return portfolio_value

if __name__ == "__main__":
    run()
