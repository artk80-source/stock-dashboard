from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Quote:
    """Standardized quote data across all providers."""
    symbol: str
    price: Optional[float]
    change: Optional[float]
    changePercent: Optional[float]
    volume: Optional[int]
    marketCap: Optional[int]
    pe: Optional[float]
    dividend: Optional[float]
    fiftyTwoWeekHigh: Optional[float]
    fiftyTwoWeekLow: Optional[float]
    previousClose: Optional[float]


@dataclass
class NewsItem:
    """Standardized news item across all providers."""
    title: str
    url: Optional[str]
    source: Optional[str]
    datetime: Optional[str]
    sentiment: Optional[float]  # -1 to 1 range
    summary: Optional[str]


@dataclass
class Fundamentals:
    """Standardized fundamental data."""
    symbol: str
    companyName: Optional[str]
    pe: Optional[float]
    marketCap: Optional[int]
    dividendYield: Optional[float]
    fiftyTwoWeekHigh: Optional[float]
    fiftyTwoWeekLow: Optional[float]
    targetPrice: Optional[float]


class DataProvider(ABC):
    """Abstract base class for data providers."""
    
    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch current stock quote."""
        pass
    
    @abstractmethod
    def get_news(self, symbol: Optional[str] = None, limit: int = 10) -> List[NewsItem]:
        """Fetch news items. If symbol is None, fetch general market news."""
        pass
    
    @abstractmethod
    def get_fundamentals(self, symbol: str) -> Optional[Fundamentals]:
        """Fetch fundamental company data."""
        pass
    
    @abstractmethod
    def get_news_sentiment(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch sentiment analysis for news related to a symbol."""
        pass
    
    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Check provider health and connectivity."""
        pass
