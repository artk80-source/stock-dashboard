import logging
import yfinance as yf
from typing import Optional, Dict, List, Any
from providers.base import DataProvider, Quote, NewsItem, Fundamentals
from cache import cache, YFINANCE_FUNDAMENTALS_TTL

logger = logging.getLogger(__name__)


class YFinanceClient(DataProvider):
    """yfinance provider implementation."""
    
    def __init__(self):
        self.name = "yfinance"
    
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch quote from yfinance."""
        try:
            ticker = yf.Ticker(symbol.upper())
            info = ticker.info if hasattr(ticker, 'info') else {}
            data = ticker.history(period="1d")
            
            if data.empty:
                return None
            
            current_price = data['Close'].iloc[-1] if len(data) > 0 else info.get('currentPrice')
            previous_close = info.get('previousClose', current_price)
            change = current_price - previous_close if (current_price and previous_close) else None
            change_percent = (change / previous_close * 100) if (change and previous_close and previous_close > 0) else None
            
            return Quote(
                symbol=symbol.upper(),
                price=float(current_price) if current_price else None,
                change=float(change) if change else None,
                changePercent=float(change_percent) if change_percent else None,
                volume=int(data['Volume'].iloc[-1]) if len(data) > 0 else None,
                marketCap=info.get('marketCap'),
                pe=info.get('trailingPE'),
                dividend=info.get('dividendRate'),
                fiftyTwoWeekHigh=info.get('fiftyTwoWeekHigh'),
                fiftyTwoWeekLow=info.get('fiftyTwoWeekLow'),
                previousClose=previous_close
            )
        except Exception as e:
            logger.error(f"yfinance get_quote error for {symbol}: {str(e)}")
            return None
    
    def get_news(self, symbol: Optional[str] = None, limit: int = 10) -> List[NewsItem]:
        """yfinance doesn't have general market news API, only company news."""
        if not symbol:
            return []
        
        try:
            ticker = yf.Ticker(symbol.upper())
            raw_news = ticker.news if hasattr(ticker, 'news') else []
            
            news_items = []
            for item in raw_news[:limit]:
                try:
                    news_items.append(NewsItem(
                        title=item.get('title', ''),
                        url=item.get('link', ''),
                        source=item.get('publisher', ''),
                        datetime=item.get('provenance', item.get('pubDate', '')),
                        sentiment=None,  # yfinance doesn't provide sentiment
                        summary=None
                    ))
                except Exception as e:
                    logger.warning(f"Failed to parse news item: {str(e)}")
                    continue
            
            return news_items
        except Exception as e:
            logger.error(f"yfinance get_news error for {symbol}: {str(e)}")
            return []
    
    def get_fundamentals(self, symbol: str) -> Optional[Fundamentals]:
        """Fetch fundamentals from yfinance."""
        cache_key = f"yf_fundamentals_{symbol}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            ticker = yf.Ticker(symbol.upper())
            info = ticker.info if hasattr(ticker, 'info') else {}
            
            fundamentals = Fundamentals(
                symbol=symbol.upper(),
                companyName=info.get('longName'),
                pe=info.get('trailingPE'),
                marketCap=info.get('marketCap'),
                dividendYield=info.get('dividendYield'),
                fiftyTwoWeekHigh=info.get('fiftyTwoWeekHigh'),
                fiftyTwoWeekLow=info.get('fiftyTwoWeekLow'),
                targetPrice=info.get('targetPrice')
            )
            
            cache.set(cache_key, fundamentals, YFINANCE_FUNDAMENTALS_TTL)
            return fundamentals
        except Exception as e:
            logger.error(f"yfinance get_fundamentals error for {symbol}: {str(e)}")
            return None
    
    def get_news_sentiment(self, symbol: str) -> Optional[Dict[str, Any]]:
        """yfinance doesn't provide sentiment analysis."""
        return None
    
    def health_check(self) -> Dict[str, Any]:
        """Check if yfinance API is accessible."""
        try:
            ticker = yf.Ticker("AAPL")
            _ = ticker.info
            return {"status": "ok", "response_time_ms": 0}
        except Exception as e:
            return {"status": "error", "error": str(e)}
