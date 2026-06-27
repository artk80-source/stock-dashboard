"""
FastAPI backend for Stock Market Dashboard
Fetches financial data from Yahoo Finance using yfinance 1.2.0+
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import yfinance as yf
from datetime import datetime, timedelta
import time
import logging
import csv
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory cache with 60-second TTL
cache = {}
CACHE_TTL = 60

def get_cached(key):
    if key in cache:
        data, timestamp = cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return data
    return None

def set_cached(key, data):
    cache[key] = (data, time.time())

app = FastAPI(
    title="Stock Market Dashboard API",
    description="API for fetching stock market data from Yahoo Finance",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    """Health check endpoint"""
    try:
        ticker = yf.Ticker("AAPL")
        data = ticker.history(period="1d")
        yfinance_status = "ok" if not data.empty else "error"
    except Exception as e:
        logger.error(f"yfinance health check failed: {str(e)}")
        yfinance_status = "error"

    return {"status": "ok", "provider_status": {"yfinance": yfinance_status}}

# Tickers tracked for the catalyst feed
CATALYST_UNIVERSE = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "MU", "WDC"]

POSITIVE_KEYWORDS = {
    "beat": 0.2, "beats": 0.2, "surge": 0.25, "surges": 0.25, "soar": 0.25, "soars": 0.25,
    "upgrade": 0.2, "upgrades": 0.2, "outperform": 0.15, "buy": 0.1, "record": 0.15,
    "raise": 0.15, "raises": 0.15, "raised": 0.15, "growth": 0.1, "profit": 0.1,
    "rally": 0.15, "jump": 0.15, "jumps": 0.15, "gain": 0.1, "gains": 0.1,
    "strong": 0.1, "approval": 0.2, "approved": 0.2, "merger": 0.15, "acquire": 0.15,
    "acquisition": 0.15, "partnership": 0.1,
}

CATEGORY_KEYWORDS = {
    "Earnings": ["earnings", "eps", "revenue", "quarter", "beat", "guidance"],
    "Upgrades": ["upgrade", "outperform", "price target", "rating", "buy rating"],
    "M&A": ["merger", "acquire", "acquisition", "buyout", "deal"],
    "FDA": ["fda", "approval", "clinical", "trial", "drug"],
}


def score_sentiment(text: str) -> float:
    """Lightweight keyword-based positive sentiment score, 0.0-1.0."""
    text_lower = text.lower()
    score = 0.4
    for keyword, weight in POSITIVE_KEYWORDS.items():
        if keyword in text_lower:
            score += weight
    return round(min(score, 1.0), 2)


def categorize(text: str) -> str:
    text_lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return category
    return "Other"


def safe_round(value, digits=2):
    """Round a numeric value, converting NaN/None to None for JSON safety."""
    if value is None:
        return None
    try:
        if value != value:  # NaN check
            return None
        return round(value, digits)
    except TypeError:
        return None


def parse_pub_date(pub_date: str):
    """Parse yfinance's ISO 8601 pubDate (e.g. '2026-06-25T23:13:47Z') to epoch seconds."""
    if not pub_date:
        return None
    try:
        return datetime.strptime(pub_date, "%Y-%m-%dT%H:%M:%SZ").timestamp()
    except (TypeError, ValueError):
        return None


def time_ago_from_timestamp(ts) -> str:
    if ts is None:
        return "recently"
    try:
        published = datetime.fromtimestamp(ts)
    except (TypeError, ValueError, OSError):
        return "recently"

    diff = datetime.now() - published
    minutes = int(diff.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


@app.get("/api/catalysts")
def get_catalysts(lookback_hours: int = 2, min_sentiment: float = 0.3, limit: int = 20):
    """Scan tracked tickers for recent positive news catalysts."""
    cache_key = f"catalysts_{lookback_hours}_{min_sentiment}_{limit}"
    cached_data = get_cached(cache_key)
    if cached_data:
        return cached_data

    cutoff = time.time() - (lookback_hours * 3600)
    catalysts = []

    for symbol in CATALYST_UNIVERSE:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info if hasattr(ticker, 'info') else {}
            history = ticker.history(period="5d").dropna(subset=['Close'])

            current_price = history['Close'].iloc[-1] if len(history) > 0 else None
            previous_close = info.get('previousClose', current_price)
            change = (current_price - previous_close) if (current_price and previous_close) else None
            change_percent = (change / previous_close * 100) if (change and previous_close) else None

            current_volume = history['Volume'].iloc[-1] if len(history) > 0 else None
            avg_volume = history['Volume'].mean() if len(history) > 0 else None
            volume_vs_avg = safe_round(current_volume / avg_volume) if (current_volume and avg_volume) else None

            raw_news = ticker.news if hasattr(ticker, 'news') else []
            for item in raw_news[:5]:
                content = item.get('content', item)
                title = content.get('title', '')
                if not title:
                    continue

                published_ts = parse_pub_date(content.get('pubDate'))
                if published_ts is not None and published_ts < cutoff:
                    continue

                sentiment = score_sentiment(title)
                if sentiment < min_sentiment:
                    continue

                link = content.get('canonicalUrl') or content.get('clickThroughUrl') or {}

                catalysts.append({
                    "symbol": symbol,
                    "company_name": info.get('longName', symbol),
                    "price": safe_round(current_price),
                    "change": safe_round(change),
                    "change_percent": safe_round(change_percent),
                    "exchange": info.get('exchange', 'NASDAQ'),
                    "headline": title,
                    "sentiment": sentiment,
                    "category": categorize(title),
                    "time_ago": time_ago_from_timestamp(published_ts),
                    "url": link.get('url', ''),
                    "volume_vs_avg": volume_vs_avg,
                    "day_low": safe_round(info.get('dayLow')),
                    "day_high": safe_round(info.get('dayHigh')),
                    "pe_ratio": safe_round(info.get('trailingPE')),
                    "ytd_return": None,
                })
        except Exception as e:
            logger.error(f"catalyst scan error for {symbol}: {str(e)}")
            continue

    catalysts.sort(key=lambda c: c['sentiment'], reverse=True)
    result = {"data": catalysts[:limit]}
    set_cached(cache_key, result)
    return result


@app.get("/api/watchlist")
def get_watchlist():
    """Read watchlist from CSV file"""
    watchlist_path = "/Users/artk80/project_VS/backend/watchlist.csv"
    watchlist = []
    
    try:
        if os.path.exists(watchlist_path):
            with open(watchlist_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    watchlist.append({
                        "name": row.get("name", ""),
                        "ticker": row.get("ticker", "").upper()
                    })
        else:
            # Create sample watchlist if it doesn't exist
            sample_data = [
                {"name": "Apple", "ticker": "AAPL"},
                {"name": "Microsoft", "ticker": "MSFT"},
                {"name": "NVIDIA", "ticker": "NVDA"}
            ]
            with open(watchlist_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=["name", "ticker"])
                writer.writeheader()
                writer.writerows(sample_data)
            watchlist = sample_data
    except Exception as e:
        return {"error": str(e), "watchlist": []}
    
    return {"watchlist": watchlist}


@app.get("/api/stock/{symbol}")
def get_stock(symbol: str):
    """Get current stock price and basic info"""
    try:
        ticker = yf.Ticker(symbol.upper())
        info = ticker.info if hasattr(ticker, 'info') else {}
        data = ticker.history(period="1d")
        
        current_price = data['Close'].iloc[-1] if len(data) > 0 else info.get('currentPrice', 0)
        previous_close = info.get('previousClose', current_price)
        change = current_price - previous_close
        change_percent = (change / previous_close * 100) if previous_close > 0 else 0
        
        return {
            "symbol": symbol.upper(),
            "name": info.get('longName', symbol),
            "price": round(current_price, 2),
            "change": round(change, 2),
            "changePercent": round(change_percent, 2),
            "marketCap": info.get('marketCap'),
            "pe": info.get('trailingPE'),
            "dividend": info.get('dividendRate'),
            "52WeekHigh": info.get('fiftyTwoWeekHigh'),
            "52WeekLow": info.get('fiftyTwoWeekLow'),
        }
    except Exception as e:
        return {"error": str(e)}, 400

@app.get("/api/stock/{symbol}/history")
def get_stock_history(symbol: str, period: str = "1mo"):
    """Get historical price data"""
    valid_periods = ["1d", "5d", "1mo", "3mo", "6mo", "1y"]
    if period not in valid_periods:
        period = "1mo"
    
    cache_key = f"history_{symbol}_{period}"
    cached_data = get_cached(cache_key)
    if cached_data:
        return cached_data
    
    try:
        ticker = yf.Ticker(symbol.upper())
        data = ticker.history(period=period).dropna(subset=['Close'])

        date_keys = data.index.strftime("%Y-%m-%d").tolist()
        closes = data['Close'].round(2).tolist()

        result = {"data": dict(zip(date_keys, ({"close": c} for c in closes)))}
        set_cached(cache_key, result)
        return result
    except Exception as e:
        return {"error": str(e)}, 400

@app.get("/api/stock/{symbol}/analysis")
def get_stock_analysis(symbol: str):
    """Get day-trade and long-term analysis metrics"""
    cache_key = f"analysis_{symbol}"
    cached_data = get_cached(cache_key)
    if cached_data:
        return cached_data
    
    try:
        ticker = yf.Ticker(symbol.upper())
        info = ticker.info if hasattr(ticker, 'info') else {}

        # Get current day data (drop the in-progress/NaN row if market hasn't closed)
        today = ticker.history(period="1d").dropna(subset=['Close'])
        recent = ticker.history(period="5d").dropna(subset=['Close'])

        current_price = today['Close'].iloc[-1] if len(today) > 0 else None
        open_price = today['Open'].iloc[-1] if len(today) > 0 else None
        day_high = today['High'].iloc[-1] if len(today) > 0 else None
        day_low = today['Low'].iloc[-1] if len(today) > 0 else None
        current_volume = today['Volume'].iloc[-1] if len(today) > 0 else None
        avg_volume = recent['Volume'].mean() if len(recent) > 0 else None
        previous_close = info.get('previousClose', current_price)

        change = (current_price - previous_close) if (current_price and previous_close) else None
        change_percent = (change / previous_close * 100) if (change and previous_close) else None

        # YTD calculation
        ytd_start = yf.Ticker(symbol.upper()).history(
            start=f"{datetime.now().year}-01-01", end=datetime.now().strftime("%Y-%m-%d")
        ).dropna(subset=['Open'])
        ytd_change = None
        if len(ytd_start) > 0 and current_price:
            ytd_open = ytd_start['Open'].iloc[0]
            ytd_change = ((current_price - ytd_open) / ytd_open * 100) if ytd_open > 0 else None

        dividend_yield = info.get('dividendYield')

        result = {
            "data": {
                "day_trade": {
                    "price": safe_round(current_price),
                    "open": safe_round(open_price),
                    "day_high": safe_round(day_high),
                    "day_low": safe_round(day_low),
                    "previous_close": safe_round(previous_close),
                    "change_percent": safe_round(change_percent),
                    "volume": int(current_volume) if current_volume else None,
                    "avg_volume": int(avg_volume) if avg_volume else None,
                },
                "long_term": {
                    "pe_ratio": safe_round(info.get('trailingPE')),
                    "market_cap": info.get('marketCap'),
                    "fifty_two_week_low": safe_round(info.get('fiftyTwoWeekLow')),
                    "fifty_two_week_high": safe_round(info.get('fiftyTwoWeekHigh')),
                    "dividend_yield": safe_round(dividend_yield * 100) if dividend_yield else None,
                    "analyst_target": safe_round(info.get('targetMeanPrice')),
                    "ytd_return": safe_round(ytd_change),
                },
            }
        }
        set_cached(cache_key, result)
        return result
    except Exception as e:
        return {"error": str(e)}, 400

@app.get("/api/stock/{symbol}/news")
def get_stock_news(symbol: str):
    """Get news for stock - yfinance 1.2.0 has unreliable news, parse defensively"""
    cache_key = f"news_{symbol}"
    cached_data = get_cached(cache_key)
    if cached_data:
        return cached_data
    
    try:
        ticker = yf.Ticker(symbol.upper())
        news_list = []

        try:
            raw_news = ticker.news if hasattr(ticker, 'news') else []

            if raw_news and isinstance(raw_news, list):
                for item in raw_news[:10]:
                    try:
                        content = item.get('content', item)
                        title = content.get('title', 'No title')
                        published_ts = parse_pub_date(content.get('pubDate'))
                        provider = content.get('provider', {})
                        link = content.get('canonicalUrl') or content.get('clickThroughUrl') or {}

                        news_list.append({
                            "headline": title,
                            "source": provider.get('displayName', 'Unknown'),
                            "published_date": time_ago_from_timestamp(published_ts),
                            "sentiment": score_sentiment(title),
                            "url": link.get('url', ''),
                        })
                    except Exception:
                        continue
        except Exception:
            pass

        result = {"data": news_list}
        set_cached(cache_key, result)
        return result
    except Exception as e:
        return {"data": []}

@app.get("/api/search/{query}")
def search_stocks(query: str):
    """Search for a stock"""
    try:
        ticker = yf.Ticker(query.upper())
        info = ticker.info if hasattr(ticker, 'info') else {}
        return {
            "symbol": query.upper(),
            "name": info.get('longName', query),
            "exchange": info.get('exchange', 'N/A'),
        }
    except Exception as e:
        return {"error": str(e)}, 400

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
