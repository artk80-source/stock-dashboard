#!/usr/bin/env python3
"""
Notification module — Resend (email) + ntfy.sh push + WhatsApp
Reads credentials from .sim_config (never hardcoded)
"""

import configparser
import urllib.request
import urllib.parse
import json
import os
import subprocess
from datetime import datetime

CONFIG_PATH = os.path.join(os.path.dirname(__file__), ".sim_config")

def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    return cfg

# ── macOS native notification (always works, no setup) ───────
def notify_macos(title, message, urgent=False):
    sound = "Sosumi" if urgent else "Glass"
    script = f'display notification "{message}" with title "{title}" sound name "{sound}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)

# ── Email via Resend API (no Gmail changes needed) ────────────
def send_email(subject, html_body, plain_body, attachments=None):
    """
    attachments: list of dicts with keys 'filename' and 'content' (base64 string)
    e.g. [{"filename": "trades.csv", "content": "<base64>"}]
    """
    cfg     = load_config()
    to_addr = cfg.get("email", "gmail_address", fallback="").strip()
    api_key = cfg.get("email", "resend_api_key", fallback="").strip()

    if not to_addr or not api_key or "PASTE" in api_key:
        print("[EMAIL] Not configured — skipping")
        return False

    try:
        body = {
            "from":    "Tech Sim <onboarding@resend.dev>",
            "to":      [to_addr],
            "subject": subject,
            "html":    html_body,
            "text":    plain_body,
        }
        if attachments:
            body["attachments"] = attachments

        payload = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            method="POST"
        )
        req.add_header("Authorization",  f"Bearer {api_key}")
        req.add_header("Content-Type",   "application/json")
        req.add_header("User-Agent",     "TechSim/1.0 (Python)")

        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
        attach_note = f" + {len(attachments)} attachment(s)" if attachments else ""
        print(f"[EMAIL] Sent via Resend → {to_addr}{attach_note} (id: {result.get('id','?')})")
        return True
    except Exception as e:
        print(f"[EMAIL] Failed: {e}")
        return False

# ── WhatsApp via CallMeBot ────────────────────────────────────
def send_whatsapp(message):
    cfg     = load_config()
    phone   = cfg.get("whatsapp", "phone_number",      fallback="").strip()
    api_key = cfg.get("whatsapp", "callmebot_api_key", fallback="").strip()

    if not phone or not api_key or "PASTE" in api_key:
        print("[WHATSAPP] Not configured — skipping")
        return False

    try:
        encoded = urllib.parse.quote(message)
        url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded}&apikey={api_key}"
        with urllib.request.urlopen(url, timeout=10) as r:
            status = r.status
        print(f"[WHATSAPP] Sent (HTTP {status})")
        return True
    except Exception as e:
        print(f"[WHATSAPP] Failed: {e}")
        return False

# ── ntfy.sh push notification ─────────────────────────────────
def send_ntfy(title, message, priority="default", tags="chart_with_upwards_trend"):
    cfg   = load_config()
    topic = cfg.get("ntfy", "topic", fallback="").strip()

    if not topic:
        print("[NTFY] Not configured — skipping")
        return False

    try:
        url  = f"https://ntfy.sh/{topic}"
        data = message.encode("utf-8")
        req  = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Title",        title.encode("utf-8").decode("latin-1", errors="replace"))
        req.add_header("Priority",     priority)
        req.add_header("Tags",         tags)
        req.add_header("Content-Type", "text/plain; charset=utf-8")
        with urllib.request.urlopen(req, timeout=10) as r:
            status = r.status
        print(f"[NTFY] Sent to ntfy.sh/{topic} (HTTP {status})")
        return True
    except Exception as e:
        print(f"[NTFY] Failed: {e}")
        return False

# ── Build the daily email report (HTML) ──────────────────────
def build_email_report(positions_data, portfolio_value, start_value, alerts):
    date_str  = datetime.now().strftime("%A, %B %d %Y")
    total_pnl = portfolio_value - start_value
    pnl_pct   = (total_pnl / start_value) * 100
    pnl_color = "#16a34a" if total_pnl >= 0 else "#dc2626"
    pnl_sign  = "+" if total_pnl >= 0 else ""

    rows = ""
    for t, d in positions_data.items():
        price     = d.get("price", 0)
        entry     = d.get("entry", 0)
        pct       = ((price - entry) / entry) * 100
        color     = "#16a34a" if pct >= 0 else "#dc2626"
        sign      = "+" if pct >= 0 else ""
        day_pct   = d.get("change_percent", 0) or 0
        day_color = "#16a34a" if day_pct >= 0 else "#dc2626"
        stop_dist = ((price - d.get("stop", 0)) / price) * 100
        rows += f"""
        <tr>
          <td style="padding:10px 14px;font-weight:bold;">{t}</td>
          <td style="padding:10px 14px;">{d.get('name','')}</td>
          <td style="padding:10px 14px;">${price:.2f}</td>
          <td style="padding:10px 14px;color:{day_color};font-weight:bold;">{day_pct:+.2f}%</td>
          <td style="padding:10px 14px;color:{color};font-weight:bold;">{sign}{pct:.2f}%</td>
          <td style="padding:10px 14px;">{stop_dist:.1f}%</td>
        </tr>"""

    alert_rows = ""
    for title, msg, urgent in alerts:
        bg = "#fef2f2" if urgent else "#fffbeb"
        alert_rows += f'<div style="background:{bg};border-left:4px solid {"#dc2626" if urgent else "#f59e0b"};padding:10px 14px;margin:6px 0;border-radius:4px;"><strong>{title}</strong><br>{msg}</div>'

    if not alert_rows:
        alert_rows = '<div style="color:#6b7280;padding:8px 0;">No alerts today — all positions within range.</div>'

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Calibri,Arial,sans-serif;background:#f8fafc;padding:24px;color:#1e293b;">
<div style="max-width:640px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);">
  <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);padding:28px 32px;">
    <h1 style="color:#fff;margin:0;font-size:22px;">📊 Tech Sim — Daily Report</h1>
    <p style="color:#94a3b8;margin:6px 0 0;">{date_str}</p>
  </div>
  <div style="padding:24px 32px;">
    <div style="background:#f1f5f9;border-radius:10px;padding:18px 24px;margin-bottom:24px;text-align:center;">
      <div style="font-size:13px;color:#64748b;margin-bottom:4px;">PORTFOLIO VALUE</div>
      <div style="font-size:32px;font-weight:bold;color:#0f172a;">${portfolio_value:,.2f}</div>
      <div style="font-size:18px;color:{pnl_color};font-weight:bold;margin-top:4px;">{pnl_sign}${total_pnl:,.2f} ({pnl_sign}{pnl_pct:.2f}%)</div>
      <div style="font-size:12px;color:#94a3b8;margin-top:4px;">Started at $100,000.00</div>
    </div>
    <h3 style="margin:0 0 12px;color:#334155;">Positions</h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="background:#f1f5f9;color:#475569;">
          <th style="padding:8px 14px;text-align:left;">Ticker</th>
          <th style="padding:8px 14px;text-align:left;">Name</th>
          <th style="padding:8px 14px;text-align:left;">Price</th>
          <th style="padding:8px 14px;text-align:left;">Today</th>
          <th style="padding:8px 14px;text-align:left;">P&amp;L</th>
          <th style="padding:8px 14px;text-align:left;">Stop Dist.</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    <h3 style="margin:22px 0 10px;color:#334155;">Alerts</h3>
    {alert_rows}
    <div style="margin-top:24px;padding-top:18px;border-top:1px solid #e2e8f0;font-size:12px;color:#94a3b8;text-align:center;">
      Run <code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;">sim</code> in terminal for full AI analysis &amp; recommendations.
    </div>
  </div>
</div>
</body></html>"""

    plain = f"""Tech Sim Daily Report — {date_str}
Portfolio: ${portfolio_value:,.2f} ({pnl_sign}{pnl_pct:.2f}%)

POSITIONS:
""" + "\n".join(
        f"  {t}: ${d.get('price',0):.2f}  P&L: {((d.get('price',0)-d.get('entry',0))/d.get('entry',1)*100):+.1f}%  Today: {d.get('change_percent',0):+.2f}%"
        for t, d in positions_data.items()
    ) + ("\n\nALERTS:\n" + "\n".join(f"  {a[0]}: {a[1]}" for a in alerts) if alerts else "\n\nNo alerts today.")

    return html, plain

# ── Short WhatsApp summary ────────────────────────────────────
def build_whatsapp_summary(positions_data, portfolio_value, start_value, alerts):
    pnl     = portfolio_value - start_value
    pnl_pct = (pnl / start_value) * 100
    sign    = "📈" if pnl >= 0 else "📉"
    lines   = [
        f"{sign} *Tech Sim Daily Report*",
        f"Portfolio: *${portfolio_value:,.0f}* ({'+' if pnl>=0 else ''}{pnl_pct:.2f}%)",
        ""
    ]
    for t, d in positions_data.items():
        p   = d.get("price", 0)
        e   = d.get("entry", 0)
        pct = ((p - e) / e) * 100
        day = d.get("change_percent", 0) or 0
        em  = "🔴" if pct < -4 else ("🟡" if pct < 0 else "🟢")
        lines.append(f"{em} {t}: ${p:.2f}  P&L:{'+' if pct>=0 else ''}{pct:.1f}%  Day:{'+' if day>=0 else ''}{day:.1f}%")

    if alerts:
        lines.append("")
        lines.append("⚠️ *ALERTS:*")
        for title, msg, urgent in alerts:
            prefix = "🔴" if urgent else "⚠️"
            lines.append(f"{prefix} {title}: {msg}")

    lines += ["", "Run `sim` in terminal for full AI analysis."]
    return "\n".join(lines)
