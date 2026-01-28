"""
Simple Redis caching for DataFrames.

Provides persistent caching across page refreshes using Redis,
with fallback to in-memory caching.
"""

import pickle
import time
from typing import Any, Optional, cast

import polars as pl

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.configs.settings_models import Settings

# Optional Redis import - graceful degradation if not available
try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    REDIS_AVAILABLE = False


class SimpleCache:
    """Simple Redis cache with memory fallback for DataFrames."""

    def __init__(self):
        self.settings = Settings()
        self.cache_config = self.settings.cache

        # Redis connection
        self._redis = None
        self._redis_available = False

        # Memory fallback
        self._memory_cache = {}

        # Try to connect to Redis
        self._init_redis()

    def _init_redis(self):
        """Initialize Redis connection."""
        if not self.cache_config.enable_redis_cache or not REDIS_AVAILABLE:
            return

        try:
            self._redis = redis.Redis(
                host=self.cache_config.redis_host,
                port=self.cache_config.redis_port,
                password=self.cache_config.redis_password,
                decode_responses=False,
            )
            self._redis.ping()
            self._redis_available = True
        except Exception as e:
            logger.warning(f"❌ Redis connection failed: {e}")
            self._redis_available = False

    def set(self, key: str, data: Any, ttl: Optional[int] = None) -> bool:
        """Cache data with optional TTL."""
        if ttl is None:
            ttl = (
                self.cache_config.dataframe_ttl
                if isinstance(data, pl.DataFrame)
                else self.cache_config.default_ttl
            )

        cache_key = f"{self.cache_config.cache_key_prefix}{key}"

        # Try Redis first
        if self._redis_available:
            try:
                serialized = pickle.dumps(data)
                self._redis.setex(cache_key, ttl, serialized)
                return True
            except Exception as e:
                logger.warning(f"❌ Redis cache failed: {key} - {e}")

        # Fallback to memory
        self._memory_cache[key] = {"data": data, "cached_at": time.time(), "ttl": ttl}
        return True

    def get(self, key: str) -> Optional[Any]:
        """Get cached data."""
        cache_key = f"{self.cache_config.cache_key_prefix}{key}"

        # Try Redis first
        if self._redis_available:
            try:
                data = self._redis.get(cache_key)
                if data is not None:
                    return pickle.loads(data)  # type: ignore[arg-type]
            except Exception as e:
                logger.warning(f"❌ Redis get failed: {key} - {e}")

        # Check memory cache
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if time.time() - entry["cached_at"] <= entry["ttl"]:
                return entry["data"]
            else:
                del self._memory_cache[key]

        return None

    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        cache_key = f"{self.cache_config.cache_key_prefix}{key}"

        # Check Redis
        if self._redis_available:
            try:
                return bool(self._redis.exists(cache_key))
            except Exception:
                pass

        # Check memory with TTL
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if time.time() - entry["cached_at"] <= entry["ttl"]:
                return True
            else:
                del self._memory_cache[key]

        return False


# Global cache instance
_cache: Optional[SimpleCache] = None


def get_cache() -> SimpleCache:
    """Get the global cache instance."""
    global _cache
    if _cache is None:
        _cache = SimpleCache()
    return cast(SimpleCache, _cache)


# Simple convenience functions
def cache_dataframe(key: str, df: pl.DataFrame, ttl: Optional[int] = None) -> bool:
    """Cache a DataFrame."""
    return get_cache().set(key, df, ttl)


def get_cached_dataframe(key: str) -> Optional[pl.DataFrame]:
    """Get a cached DataFrame."""
    return get_cache().get(key)


def cached_dataframe_exists(key: str) -> bool:
    """Check if DataFrame is cached."""
    return get_cache().exists(key)


def get_cache_stats() -> dict[str, Any]:
    """Get basic cache stats."""
    cache = get_cache()
    stats = {
        "redis_available": cache._redis_available,
        "memory_keys": len(cache._memory_cache),
        "redis_keys": 0,
        "redis_memory_used_mb": 0.0,
        "memory_size_mb": 0.0,
    }

    # Get Redis stats if available
    if cache._redis_available and cache._redis is not None:
        try:
            # Count Redis keys with our prefix
            pattern = f"{cache.cache_config.cache_key_prefix}*"
            keys_result = cache._redis.keys(pattern)
            # Redis.keys() returns a list synchronously when decode_responses=False
            # Cast to list for type checker (redis-py returns list, not Awaitable, in sync mode)
            if isinstance(keys_result, list):
                stats["redis_keys"] = len(keys_result)
            else:
                stats["redis_keys"] = 0

            # Get Redis memory usage
            info = cache._redis.info()
            stats["redis_memory_used_mb"] = info.get("used_memory", 0) / (1024 * 1024)
        except Exception:
            # Redis stats failed, but connection might still work
            pass

    return stats
