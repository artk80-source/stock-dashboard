"""
Alpha Vantage data provider for sentiment analysis
"""
import os
import asyncio
import httpx
from datetime import datetime
from typing import Optional, Dict, Any, List
from .base import DataProvider
import logging

logger = logging.getLogger(__name__)


class AlphaVantageProvider(DataProvider):
    """Alpha Vantage API provider for news sentiment"""
    
    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        self.base_url = "https://www.alphavantage.co/query"
    
    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Alpha Vantage doesn't provide quotes in free tier, skip"""
        return None
    
    async def get_news(self, symbol: Optional[str] = None, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Get news sentiment from Alpha Vantage"""
        if not self.api_key:
            logger.warning("Alpha Vantage API key not configured")
            return None
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                params = {
                    "function": "NEWS_SENTIMENT",
                    "tickers": symbol.upper() if symbol else "AAPL",
                    "limit": limit,
                    "apikey": self.api_key
                }
                
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if "feed" not in data:
                    logger.warning(f"Alpha Vantage: {data.get('Note', 'No feed in response')}")
                    return None
                
                news_list = []
                for item in data.get("feed", [])[:limit]:
                    try:
                        # Parse sentiment score from overall_sentiment_score
                        sentiment_str = item.get("overall_sentiment_score", "0")
                        try:
                            sentiment = float(sentiment_str)
                        except:
                            sentiment = 0.0
                        
                        news_list.append({
                            "title": item.get("title", ""),
                            "source": item.get("source", ""),
                            "url": item.get("url", ""),
                            "image": None,
                            "sentiment": sentiment,  # Range: -1.0 to 1.0
                            "published_at": item.get("time_published", ""),
                            "summary": item.get("summary", "")
                        })
                    except Exception as e:
                        logger.warning(f"Error parsing Alpha Vantage news item: {e}")
                        continue
                
                return news_list if news_list else None
        except Exception as e:
            logger.error(f"Alpha Vantage news error: {e}")
            return None
    
    async def get_fundamentals(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Alpha Vantage fundamentals not used, yfinance handles this"""
        return None
