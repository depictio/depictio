"""
Simple Redis caching for DataFrames.

Provides persistent caching across page refreshes using Redis,
with fallback to in-memory caching.
"""

import pickle
import time
from typing import Any, Optional

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
            if not REDIS_AVAILABLE:
                logger.info("📦 Redis module not available, using memory-only cache")
            return

        try:
            self._redis = redis.Redis(  # type: ignore
                host=self.cache_config.redis_host,
                port=self.cache_config.redis_port,
                password=self.cache_config.redis_password,
                decode_responses=False,
            )
            self._redis.ping()
            self._redis_available = True
            logger.info(
                f"✅ Redis connected: {self.cache_config.redis_host}:{self.cache_config.redis_port}"
            )
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
                if isinstance(data, pl.DataFrame):
                    logger.info(f"✅ Redis cached: {key} ({data.shape[0]}×{data.shape[1]})")
                return True
            except Exception as e:
                logger.warning(f"❌ Redis cache failed: {key} - {e}")

        # Fallback to memory
        self._memory_cache[key] = {"data": data, "cached_at": time.time(), "ttl": ttl}
        if isinstance(data, pl.DataFrame):
            logger.info(f"💾 Memory cached: {key} ({data.shape[0]}×{data.shape[1]})")
        return True

    def get(self, key: str) -> Optional[Any]:
        """Get cached data."""
        cache_key = f"{self.cache_config.cache_key_prefix}{key}"

        # Try Redis first
        if self._redis_available:
            try:
                data = self._redis.get(cache_key)
                if data:
                    result = pickle.loads(data)
                    if isinstance(result, pl.DataFrame):
                        logger.info(f"🚀 Redis hit: {key} ({result.shape[0]}×{result.shape[1]})")
                    return result
            except Exception as e:
                logger.warning(f"❌ Redis get failed: {key} - {e}")

        # Check memory cache
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if time.time() - entry["cached_at"] <= entry["ttl"]:
                result = entry["data"]
                if isinstance(result, pl.DataFrame):
                    logger.info(f"💾 Memory hit: {key} ({result.shape[0]}×{result.shape[1]})")
                return result
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
    # Cast to help type checker - we know _cache is not None after the check
    return _cache  # type: ignore


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
            keys = cache._redis.keys(pattern)
            stats["redis_keys"] = len(keys)

            # Get Redis memory usage
            info = cache._redis.info()
            stats["redis_memory_used_mb"] = info.get("used_memory", 0) / (1024 * 1024)
        except Exception:
            # Redis stats failed, but connection might still work
            pass

    return stats
