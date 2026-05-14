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

    def set_nx(self, key: str, data: Any, ttl: Optional[int] = None) -> bool:
        """Atomic "set if not exists" — Redis SETNX semantics.

        Returns True if the caller acquired the key (key was absent), False
        if another caller already holds it. Used as a distributed lock for
        deduping work across multiple Celery workers: only the first worker
        that runs ``set_nx(lock_key, ...)`` proceeds; others bail out.

        Falls back to a non-atomic check-then-set on the in-memory cache
        when Redis is unavailable — fine for single-process dev, not safe
        for production multi-worker setups without Redis.
        """
        if ttl is None:
            ttl = self.cache_config.default_ttl

        cache_key = f"{self.cache_config.cache_key_prefix}{key}"

        if self._redis_available and self._redis is not None:
            try:
                serialized = pickle.dumps(data)
                # SET with NX (only if absent) + EX (expiry in seconds).
                acquired = self._redis.set(cache_key, serialized, nx=True, ex=ttl)
                return bool(acquired)
            except Exception as e:
                logger.warning(f"Redis set_nx failed: {key} - {e}")

        # Memory fallback — racy but acceptable in single-process dev.
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if time.time() - entry["cached_at"] <= entry["ttl"]:
                return False
        self._memory_cache[key] = {"data": data, "cached_at": time.time(), "ttl": ttl}
        return True

    def delete(self, key: str) -> bool:
        """Delete a single cached entry by exact key.

        Returns True if a key was removed from either Redis or the in-memory
        fallback. Failures are logged but never raised — cache hiccups must
        not break callers.
        """
        cache_key = f"{self.cache_config.cache_key_prefix}{key}"
        removed = False

        if self._redis_available and self._redis is not None:
            try:
                deleted = self._redis.delete(cache_key)
                if isinstance(deleted, int) and deleted > 0:
                    removed = True
            except Exception as e:
                logger.warning(f"Redis delete failed: {key} - {e}")

        if key in self._memory_cache:
            del self._memory_cache[key]
            removed = True

        return removed

    def delete_pattern(self, pattern: str) -> int:
        """Delete every cached key whose unprefixed name contains ``pattern``.

        Returns the number of keys removed (Redis + memory). Used by the
        realtime-events path to invalidate every filter variant for a DC after
        a ``data_collection_updated`` event.
        """
        full_pattern = f"{self.cache_config.cache_key_prefix}*{pattern}*"
        removed = 0

        if self._redis_available and self._redis is not None:
            try:
                keys_result = self._redis.keys(full_pattern)
                if isinstance(keys_result, list) and keys_result:
                    self._redis.delete(*keys_result)
                    removed += len(keys_result)
            except Exception as e:
                logger.warning(f"Redis delete_pattern failed: {pattern} - {e}")

        for key in [k for k in self._memory_cache if pattern in k]:
            del self._memory_cache[key]
            removed += 1

        return removed

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


def invalidate_dataframe_cache_pattern(pattern: str) -> int:
    """Drop every cached DataFrame whose unprefixed key contains ``pattern``."""
    return get_cache().delete_pattern(pattern)


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
