import time
from typing import Any, Optional, Dict
from threading import Lock


class TTLCache:
    """In-memory TTL cache with per-key expiration times."""
    
    def __init__(self):
        self._cache: Dict[str, tuple] = {}
        self._lock = Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if it exists and hasn't expired."""
        with self._lock:
            if key not in self._cache:
                return None
            value, expiry_time, ttl = self._cache[key]
            if time.time() > expiry_time:
                del self._cache[key]
                return None
            return value
    
    def set(self, key: str, value: Any, ttl: int) -> None:
        """Set value with expiry time (TTL in seconds)."""
        with self._lock:
            self._cache[key] = (value, time.time() + ttl, ttl)
    
    def delete(self, key: str) -> None:
        """Delete a key from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    def clear(self) -> None:
        """Clear entire cache."""
        with self._lock:
            self._cache.clear()
    
    def cleanup_expired(self) -> None:
        """Remove expired entries."""
        with self._lock:
            current_time = time.time()
            expired_keys = [
                k for k, (_, expiry, _) in self._cache.items()
                if current_time > expiry
            ]
            for key in expired_keys:
                del self._cache[key]


# Global cache instance
cache = TTLCache()

# Cache TTLs
FINNHUB_QUOTE_TTL = 60  # 60 seconds
FINNHUB_NEWS_TTL = 60  # 60 seconds
ALPHA_VANTAGE_SENTIMENT_TTL = 3600  # 1 hour (free tier limit)
YFINANCE_FUNDAMENTALS_TTL = 300  # 5 minutes
