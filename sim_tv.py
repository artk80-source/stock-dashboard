#!/usr/bin/env python3
"""
sim_tv.py — TradingView process manager + CDP bridge

Provides resilient TV integration for sim scripts:
  - Health check  : fast HTTP ping to CDP endpoint
  - Auto-reconnect: retry with linear backoff before giving up
  - Auto-relaunch : kill + restart TV if retries fail
  - Circuit breaker: stops retrying for CIRCUIT_TTL seconds after total failure
                     (file-based so it persists across cron invocations)
  - @tv_optional  : decorator — wraps any TV-using function, returns None if TV down
  - tv_screenshot : CDP Page.captureScreenshot → PNG file
  - tv_set_symbol : CDP Page.navigate to a TV chart URL
  - tv_status     : returns active tab info dict

Usage in sim scripts:
    from sim_tv import ensure_connected, tv_screenshot, tv_set_symbol, tv_optional

    if ensure_connected():
        tv_set_symbol("MSFT")
        shot = tv_screenshot("msft_daily")

    @tv_optional
    def grab_chart(symbol):
        ...  # only runs if TV is alive; returns None otherwise
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import subprocess
import time
from functools import wraps
from pathlib import Path

import requests
import websockets

log = logging.getLogger("sim_tv")

# ── Constants ─────────────────────────────────────────────────────────────────

TV_APP       = "/Applications/TradingView.app/Contents/MacOS/TradingView"
CDP_PORT     = 9222
CDP_BASE     = f"http://localhost:{CDP_PORT}"
CIRCUIT_FILE = Path("/tmp/tv_circuit_open")
CIRCUIT_TTL  = 1800   # auto-reset after 30 min
LAUNCH_WAIT  = 20     # max seconds to wait for CDP after launch
SCREENSHOT_DIR = Path("/tmp/sim_tv_screenshots")

# ── Circuit Breaker ───────────────────────────────────────────────────────────

def _is_circuit_open() -> bool:
    """Return True if the circuit breaker is active (TV declared unavailable)."""
    if not CIRCUIT_FILE.exists():
        return False
    age = time.time() - CIRCUIT_FILE.stat().st_mtime
    if age > CIRCUIT_TTL:
        CIRCUIT_FILE.unlink(missing_ok=True)
        log.info("TV circuit breaker auto-reset after %ds", CIRCUIT_TTL)
        return False
    remaining = int(CIRCUIT_TTL - age)
    log.debug("TV circuit open — %ds until auto-reset", remaining)
    return True

def _open_circuit():
    CIRCUIT_FILE.touch()
    log.warning("TV circuit breaker OPEN — all TV ops will skip for %ds", CIRCUIT_TTL)

def reset_circuit():
    """Manually reset the circuit breaker (e.g. after confirming TV is alive)."""
    CIRCUIT_FILE.unlink(missing_ok=True)
    log.info("TV circuit breaker manually reset")

# ── Health Check ──────────────────────────────────────────────────────────────

def is_alive(timeout: float = 3.0) -> bool:
    """True if TradingView CDP REST endpoint responds."""
    try:
        r = requests.get(f"{CDP_BASE}/json/version", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False

# ── Launch ────────────────────────────────────────────────────────────────────

def _launch(kill_existing: bool = True) -> bool:
    """
    Start TradingView with CDP remote debugging enabled.
    Blocks until CDP is ready (up to LAUNCH_WAIT seconds).
    Returns True if CDP came up, False otherwise.
    """
    if kill_existing:
        subprocess.run(["pkill", "-f", "TradingView"], capture_output=True)
        time.sleep(2)

    try:
        subprocess.Popen(
            [TV_APP, f"--remote-debugging-port={CDP_PORT}", "--remote-allow-origins=*"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log.error("TradingView binary not found at %s", TV_APP)
        return False
    except Exception as exc:
        log.error("TradingView launch error: %s", exc)
        return False

    log.info("TradingView launched — waiting up to %ds for CDP on port %d…", LAUNCH_WAIT, CDP_PORT)
    for elapsed in range(LAUNCH_WAIT):
        time.sleep(1)
        if is_alive():
            log.info("CDP ready (took %ds)", elapsed + 1)
            return True

    log.error("TradingView started but CDP never responded in %ds", LAUNCH_WAIT)
    return False

# ── Connect / Ensure ──────────────────────────────────────────────────────────

def ensure_connected(max_retries: int = 2, allow_relaunch: bool = True) -> bool:
    """
    Guarantee TV CDP is reachable before performing an operation.

    Decision tree:
      1. Circuit open?  → return False immediately (fail fast, no delay)
      2. CDP alive?     → return True immediately   (fast path, ~50ms)
      3. Retry loop     → linear backoff: 3s, 6s per retry
      4. Relaunch once  → kill + restart TV, wait LAUNCH_WAIT seconds
      5. Total failure  → open circuit, return False

    Callers should treat False as "TV unavailable; skip TV work gracefully."
    """
    if _is_circuit_open():
        return False

    if is_alive():
        return True

    for attempt in range(1, max_retries + 1):
        delay = 3 * attempt
        log.warning("TV CDP down — retry %d/%d in %ds…", attempt, max_retries, delay)
        time.sleep(delay)
        if is_alive():
            log.info("TV reconnected on retry %d", attempt)
            return True

    if not allow_relaunch:
        log.warning("TV unreachable after %d retries; relaunch disabled — opening circuit", max_retries)
        _open_circuit()
        return False

    log.warning("All %d retries failed — relaunching TradingView…", max_retries)
    if _launch():
        reset_circuit()
        return True

    log.error("TradingView relaunch also failed — opening circuit breaker")
    _open_circuit()
    return False

# ── Decorator ─────────────────────────────────────────────────────────────────

def tv_optional(fn):
    """
    Decorator: runs fn only if TV is reachable; returns None otherwise.
    The sim script continues normally — TV is enrichment, not a hard dependency.

    Example:
        @tv_optional
        def grab_chart(symbol: str) -> Path:
            return tv_screenshot(symbol)
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not ensure_connected():
            log.warning("Skipping %s() — TV unavailable", fn.__name__)
            return None
        return fn(*args, **kwargs)
    return wrapper

# ── CDP Helpers (async internals) ─────────────────────────────────────────────

def _cdp_targets() -> list:
    try:
        r = requests.get(f"{CDP_BASE}/json/list", timeout=3)
        return r.json()
    except Exception:
        return []

def _chart_ws_url() -> str:
    """
    Find the CDP WebSocket URL for the chart renderer tab.
    TV Desktop renders charts in the 'new-tab' page target.
    Falls back to the first target with a WebSocket URL.
    """
    targets = _cdp_targets()
    for hint in ("new-tab", "chart", "layout"):
        for t in targets:
            if hint in t.get("url", "") and t.get("webSocketDebuggerUrl"):
                return t["webSocketDebuggerUrl"]
    for t in targets:
        if ws := t.get("webSocketDebuggerUrl"):
            return ws
    return None

async def _cdp_cmd(ws_url: str, method: str, params: dict = None) -> dict:
    """Send a CDP command, drain events until our response (id=1) arrives."""
    payload = json.dumps({"id": 1, "method": method, "params": params or {}})
    try:
        async with websockets.connect(ws_url, open_timeout=6) as ws:
            await ws.send(payload)
            for _ in range(20):
                raw = await asyncio.wait_for(ws.recv(), timeout=6)
                msg = json.loads(raw)
                if msg.get("id") == 1:
                    return msg.get("result", {})
    except Exception as exc:
        log.warning("CDP command %s failed: %s", method, exc)
    return {}

async def _eval(ws_url: str, expression: str):
    """Evaluate JS in the page, return the primitive result value."""
    result = await _cdp_cmd(
        ws_url, "Runtime.evaluate",
        {"expression": expression, "returnByValue": True},
    )
    return result.get("result", {}).get("value")

def _run(coro):
    """Bridge async CDP coroutines into sync caller context."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)

def _has_chart_api(ws_url: str) -> bool:
    """True if TV chart JS API (tvWidget) is loaded in this tab."""
    val = _run(_eval(ws_url, "typeof window.tvWidget !== 'undefined'"))
    return val is True

# ── Public Operations ─────────────────────────────────────────────────────────

def tv_wait_for_chart(timeout: int = 30) -> bool:
    """
    Block until the TV chart JS API (tvWidget) is loaded, or timeout.
    Returns True when the chart is ready.
    Call this before tv_set_symbol() if you're not sure a chart is open.
    """
    if not ensure_connected():
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws = _chart_ws_url()
        if ws and _has_chart_api(ws):
            log.info("TV chart API ready")
            return True
        time.sleep(2)
    log.warning("tv_wait_for_chart: timed out after %ds (no chart open in TV?)", timeout)
    return False

@tv_optional
def tv_screenshot(label: str = "chart") -> Path:
    """
    Capture the chart renderer tab as a PNG via CDP.
    Saves to /tmp/sim_tv_screenshots/tv_{label}_{timestamp}.png
    Returns the saved Path, or None on failure.
    """
    ws_url = _chart_ws_url()
    if not ws_url:
        log.warning("tv_screenshot: no chart CDP target found")
        return None

    SCREENSHOT_DIR.mkdir(exist_ok=True)
    out = SCREENSHOT_DIR / f"tv_{label}_{int(time.time())}.png"

    result = _run(_cdp_cmd(ws_url, "Page.captureScreenshot", {"format": "png"}))
    data = result.get("data")
    if not data:
        log.warning("tv_screenshot: empty response from CDP")
        return None

    out.write_bytes(base64.b64decode(data))
    log.info("Screenshot saved: %s", out)
    return out

@tv_optional
def tv_set_symbol(symbol: str, timeframe: str = "D") -> bool:
    """
    Change the active chart to a symbol + timeframe via the TV JS API.
    Requires a chart to be open — call tv_wait_for_chart() first if unsure.
    Returns True on success.
    """
    _TF = {"1": "1", "5": "5", "15": "15", "30": "30", "60": "60", "D": "D", "W": "W", "M": "M"}
    tv_tf = _TF.get(str(timeframe), "D")

    ws_url = _chart_ws_url()
    if not ws_url:
        return False
    if not _has_chart_api(ws_url):
        log.warning("tv_set_symbol: chart API not ready — open a chart layout in TV first")
        return False

    script = (
        f"(function(){{"
        f"try{{window.tvWidget.chart().setSymbol('{symbol}','{tv_tf}',function(){{}});return true;}}"
        f"catch(e){{return 'err:'+e.message;}}"
        f"}})()"
    )
    result = _run(_eval(ws_url, script))
    if result is True:
        log.info("TV chart → %s (%s)", symbol, tv_tf)
        time.sleep(2)
        return True
    log.warning("tv_set_symbol: JS returned %s", result)
    return False

@tv_optional
def tv_status() -> dict:
    """Active tab info + whether the chart JS API is loaded."""
    targets = _cdp_targets()
    if not targets:
        return None
    for t in targets:
        if "new-tab" in t.get("url", ""):
            ws = t.get("webSocketDebuggerUrl", "")
            return {
                "title": t.get("title", ""),
                "chart_api": _has_chart_api(ws) if ws else False,
            }
    t = targets[0]
    return {"title": t.get("title", ""), "chart_api": False}

def tv_health_report() -> str:
    """One-line TV status string for email reports. Never triggers reconnect."""
    if _is_circuit_open():
        age = time.time() - CIRCUIT_FILE.stat().st_mtime
        remaining = max(0, int(CIRCUIT_TTL - age))
        return f"TV: circuit open — retry in ~{remaining // 60}min"
    if is_alive():
        ws = _chart_ws_url()
        state = "chart ready" if (ws and _has_chart_api(ws)) else "no chart loaded"
        return f"TV: online ({state})"
    return "TV: offline"

# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    print("\n=== sim_tv self-test ===")
    print(f"  is_alive():       {is_alive()}")
    print(f"  circuit open:     {_is_circuit_open()}")
    print(f"  ensure_connected: {ensure_connected()}")
    print(f"  tv_status():      {tv_status()}")
    print(f"  health_report:    {tv_health_report()}")

    print("\n  Taking screenshot of chart tab…")
    shot = tv_screenshot("selftest")
    print(f"  screenshot:       {shot}")

    print("\n  Waiting for chart API (needs a layout open in TV)…")
    ready = tv_wait_for_chart(timeout=10)
    print(f"  chart_api ready:  {ready}")

    if ready:
        print("\n  Setting symbol to MSFT daily…")
        ok = tv_set_symbol("MSFT", "D")
        print(f"  set_symbol:       {ok}")

    print("\n=== done ===")
