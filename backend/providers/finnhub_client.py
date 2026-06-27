import logging
import os
import time
from typing import Optional, Dict, List, Any
import finnhub
from providers.base import DataProvider, Quote, NewsItem, Fundamentals
from cache import cache, FINNHUB_QUOTE_TTL, FINNHUB_NEWS_TTL

logger = logging.getLogger(__name__)


class FinnhubClient(DataProvider):
    """Finnhub provider implementation."""
    
    def __init__(self):
        self.name = "finnhub"
        self.api_key = os.getenv("FINNHUB_API_KEY")
        self.enabled = bool(self.api_key)
        if self.enabled:
            self.client = finnhub.Client(api_key=self.api_key)
    
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch quote from Finnhub."""
        if not self.enabled:
            return None
        
        cache_key = f"finnhub_quote_{symbol}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            data = self.client.quote(symbol.upper())
            
            quote = Quote(
                symbol=symbol.upper(),
                price=data.get('c'),
                change=data.get('d'),
                changePercent=data.get('dp'),
                volume=int(data.get('v', 0)) if data.get('v') else None,
                marketCap=None,  # Finnhub doesn't provide in quote
                pe=None,
                dividend=None,
                fiftyTwoWeekHigh=data.get('h52'),
                fiftyTwoWeekLow=data.get('l52'),
                previousClose=data.get('pc')
            )
            
            cache.set(cache_key, quote, FINNHUB_QUOTE_TTL)
            return quote
        except Exception as e:
            logger.error(f"Finnhub get_quote error for {symbol}: {str(e)}")
            return None
    
    def get_news(self, symbol: Optional[str] = None, limit: int = 10) -> List[NewsItem]:
        """Fetch news from Finnhub."""
        if not self.enabled:
            return []
        
        cache_key = f"finnhub_news_{symbol}" if symbol else "finnhub_news_general"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            if symbol:
                raw_news = self.client.company_news(symbol.upper(), _from="2024-01-01", to="2026-12-31")
            else:
                # General market news
                raw_news = self.client.general_news("general", min_id=0)
            
            news_items = []
            for item in raw_news[:limit]:
                try:
                    news_items.append(NewsItem(
                        title=item.get('headline', ''),
                        url=item.get('url', ''),
                        source=item.get('source', ''),
                        datetime=str(item.get('datetime', '')),
                        sentiment=None,  # Finnhub doesn't provide sentiment in news
                        summary=item.get('summary')
                    ))
                except Exception as e:
                    logger.warning(f"Failed to parse Finnhub news item: {str(e)}")
                    continue
            
            cache.set(cache_key, news_items, FINNHUB_NEWS_TTL)
            return news_items
        except Exception as e:
            logger.error(f"Finnhub get_news error: {str(e)}")
            return []
    
    def get_fundamentals(self, symbol: str) -> Optional[Fundamentals]:
        """Fetch company profile from Finnhub."""
        if not self.enabled:
            return None
        
        try:
            profile = self.client.company_profile2(symbol=symbol.upper())
            
            return Fundamentals(
                symbol=symbol.upper(),
                companyName=profile.get('name'),
                pe=None,  # Finnhub profile doesn't include P/E
                marketCap=profile.get('marketCapitalization'),
                dividendYield=None,
                fiftyTwoWeekHigh=None,
                fiftyTwoWeekLow=None,
                targetPrice=None
            )
        except Exception as e:
            logger.error(f"Finnhub get_fundamentals error for {symbol}: {str(e)}")
            return None
    
    def get_news_sentiment(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get news sentiment for a symbol from Finnhub."""
        if not self.enabled:
            return None
        
        try:
            data = self.client.news_sentiment(symbol.upper())
            return {
                "symbol": symbol.upper(),
                "sentiment": data.get('sentiment'),
                "articles": data.get('data', [])
            }
        except Exception as e:
            logger.error(f"Finnhub get_news_sentiment error for {symbol}: {str(e)}")
            return None
    
    def health_check(self) -> Dict[str, Any]:
        """Check if Finnhub API is accessible."""
        if not self.enabled:
            return {"status": "skipped", "reason": "FINNHUB_API_KEY not configured"}
        
        try:
            start = time.time()
            _ = self.client.quote("AAPL")
            response_time = (time.time() - start) * 1000
            return {"status": "ok", "response_time_ms": response_time}
        except Exception as e:
            return {"status": "error", "error": str(e)}
