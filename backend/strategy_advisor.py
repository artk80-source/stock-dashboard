"""
Strategy advisor CLI.

Fetches live data from the running dashboard backend (watchlist quotes,
analysis metrics, and catalyst news) and prints a ranked report of which
watchlist stocks currently look most interesting, with a plain-English
reason for each.

This is a simple rule-based heuristic over public market data, not a
trained model and not financial advice. Use it as a starting point for
your own research.

Usage:
    ./venv/bin/python strategy_advisor.py [--top N]
"""

import argparse
import sys

import requests

API_BASE_URL = "http://localhost:8000/api"


def clamp(value, low=-1.0, high=1.0):
    return max(low, min(high, value))


def fetch_json(path, params=None):
    resp = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_watchlist():
    return fetch_json("/watchlist").get("watchlist", [])


def get_catalysts_by_symbol():
    catalysts = fetch_json("/catalysts", params={"lookback_hours": 24, "min_sentiment": 0.3, "limit": 50}).get("data", [])
    by_symbol = {}
    for c in catalysts:
        existing = by_symbol.get(c["symbol"])
        if existing is None or c["sentiment"] > existing["sentiment"]:
            by_symbol[c["symbol"]] = c
    return by_symbol


def get_analysis(symbol):
    try:
        return fetch_json(f"/stock/{symbol}/analysis").get("data", {})
    except Exception:
        return {}


def score_stock(symbol, analysis, catalyst):
    day = analysis.get("day_trade", {})
    long_term = analysis.get("long_term", {})

    change_percent = day.get("change_percent") or 0
    ytd_return = long_term.get("ytd_return") or 0
    volume = day.get("volume") or 0
    avg_volume = day.get("avg_volume") or 0

    momentum_score = clamp(change_percent / 5)
    ytd_score = clamp(ytd_return / 20)
    volume_score = clamp((volume / avg_volume - 1)) if avg_volume else 0
    catalyst_score = catalyst["sentiment"] if catalyst else 0

    composite = (0.3 * momentum_score) + (0.2 * ytd_score) + (0.2 * volume_score) + (0.3 * catalyst_score)

    reasons = []
    if catalyst:
        reasons.append(f"positive news catalyst (sentiment {catalyst['sentiment']:.2f}): \"{catalyst['headline'][:80]}\"")
    if abs(change_percent) >= 1:
        direction = "up" if change_percent > 0 else "down"
        reasons.append(f"intraday {direction} {abs(change_percent):.2f}%")
    if avg_volume and volume / avg_volume >= 1.3:
        reasons.append(f"volume {volume / avg_volume:.1f}x average — unusual activity")
    if ytd_return:
        reasons.append(f"YTD {'+' if ytd_return >= 0 else ''}{ytd_return:.1f}%")
    if not reasons:
        reasons.append("no notable momentum or catalyst right now")

    if composite > 0.3:
        action = "WATCH FOR BUY"
    elif composite > 0.1:
        action = "MILD INTEREST"
    elif composite < -0.2:
        action = "WEAK / AVOID"
    else:
        action = "NEUTRAL"

    return {
        "symbol": symbol,
        "price": day.get("price"),
        "composite": composite,
        "action": action,
        "reasons": reasons,
    }


def main():
    parser = argparse.ArgumentParser(description="Rank watchlist stocks by current opportunity signal.")
    parser.add_argument("--top", type=int, default=10, help="Number of stocks to show (default: 10)")
    args = parser.parse_args()

    try:
        watchlist = get_watchlist()
        catalysts_by_symbol = get_catalysts_by_symbol()
    except requests.exceptions.ConnectionError:
        print("Could not reach the backend at http://localhost:8000 — is main.py running?")
        sys.exit(1)

    results = []
    for entry in watchlist:
        symbol = entry["ticker"]
        analysis = get_analysis(symbol)
        if not analysis:
            continue
        results.append(score_stock(symbol, analysis, catalysts_by_symbol.get(symbol)))

    results.sort(key=lambda r: r["composite"], reverse=True)

    print("\n=== Stock Opportunity Report ===")
    print("Rule-based heuristic over live data — informational only, not financial advice.\n")

    for r in results[: args.top]:
        price_str = f"${r['price']:.2f}" if r["price"] else "N/A"
        print(f"{r['symbol']:<6} {price_str:>10}  score {r['composite']:+.2f}  [{r['action']}]")
        for reason in r["reasons"]:
            print(f"        - {reason}")
        print()


if __name__ == "__main__":
    main()
