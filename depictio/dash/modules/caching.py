"""
Dashboard data caching utilities with parquet-first strategy.

This module provides caching functionality for dashboard data including:
- Parquet file generation and management
- Redis caching integration
- Configuration-based data generation
- Memory fallback caching
"""

import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from depictio.api.v1.configs.logging_init import logger

# Global in-memory cache as fallback for when file locking fails
_MEMORY_CACHE: dict[str, tuple[Any, float]] = {}


def get_parquet_file_path(config=None):
    """Get the parquet file path for a given configuration."""
    if config is None:
        from depictio.dash.layouts.dashboard_content import DATA_CONFIG

        config = DATA_CONFIG

    config_hash = get_config_hash(config)

    # Use the depictio/cache directory that works in both Docker and local environments
    import tempfile

    # Try to use project cache directory first, fall back to temp if permission denied
    try:
        parquet_dir = Path("depictio/cache/parquet")
        parquet_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Fall back to system temp directory
        cache_root = Path(tempfile.gettempdir()) / "depictio_parquet_cache"
        cache_root.mkdir(exist_ok=True)
        parquet_dir = cache_root

    return parquet_dir / f"dashboard_data_{config_hash}.parquet"


def generate_and_save_parquet(config=None):
    """Generate DataFrame and save as parquet file."""
    if config is None:
        from depictio.dash.layouts.dashboard_content import DATA_CONFIG

        config = DATA_CONFIG

    parquet_path = get_parquet_file_path(config)

    # Check if parquet file already exists
    if parquet_path.exists():
        logger.info(f"📦 PARQUET: File already exists at {parquet_path}")
        return parquet_path

    logger.info(f"🔧 PARQUET GENERATION: Creating {config['rows']:,} rows of data...")

    # Use deterministic seed based on config to ensure identical data
    process_seed = hash(str(sorted(config.items()))) % 2**31
    random.seed(process_seed)

    # Generate date range - limit to max 365 days to avoid timestamp overflow
    max_days = min(365, config["rows"])
    start_date = datetime.now() - timedelta(days=max_days)

    # Generate dates - if we have more rows than days, repeat the date pattern
    if config["rows"] <= max_days:
        dates = [start_date + timedelta(days=i) for i in range(config["rows"])]
    else:
        # Create a repeating pattern of dates for large datasets
        base_dates = [start_date + timedelta(days=i % max_days) for i in range(config["rows"])]
        dates = base_dates

    # Generate random data using polars
    data = {
        "date": dates,
        "category": [random.choice(config["categories"]) for _ in range(config["rows"])],
    }

    # Generate metrics based on configuration
    for metric_key, metric_config in config["metrics"].items():
        if metric_config["format"] == "int":
            data[metric_key] = [
                random.randint(metric_config["min"], metric_config["max"])
                for _ in range(config["rows"])
            ]
        else:
            data[metric_key] = [
                random.uniform(metric_config["min"], metric_config["max"])
                for _ in range(config["rows"])
            ]

    df = pl.DataFrame(data)
    df_size_mb = df.estimated_size("mb")

    # Save to parquet with compression
    df.write_parquet(parquet_path, compression="snappy")
    file_size_mb = parquet_path.stat().st_size / (1024 * 1024)

    logger.info(
        f"✅ PARQUET SAVED: {parquet_path.name} - DataFrame: {df.shape} ({df_size_mb:.1f}MB), "
        f"File: {file_size_mb:.1f}MB (compression: {df_size_mb / file_size_mb:.1f}x)"
    )

    return parquet_path


def get_config_hash(config):
    """Generate a hash of the config to detect changes."""
    import hashlib
    import json

    config_str = json.dumps(config, sort_keys=True)
    return hashlib.md5(config_str.encode()).hexdigest()


def get_cached_dataframe(config=None):
    """
    Get cached DataFrame using parquet-first strategy with Redis caching.

    Strategy:
    1. Check Redis cache first (fastest access)
    2. If not cached, check for pre-generated parquet file
    3. Load parquet file and cache in Redis
    4. If no parquet file exists, generate and save it first

    Args:
        config: Data configuration dict, defaults to DATA_CONFIG

    Returns:
        pl.DataFrame: Cached or loaded DataFrame
    """
    import time

    from depictio.api.cache import SimpleCache, get_cache

    if config is None:
        from depictio.dash.layouts.dashboard_content import DATA_CONFIG

        config = DATA_CONFIG

    # Get cache instance
    cache: SimpleCache = get_cache()

    # Generate cache key based on config
    current_config_hash = get_config_hash(config)
    cache_key = f"dashboard:dataframe:{current_config_hash}"
    lock_key = f"{cache_key}:loading"

    # Step 1: Check Redis cache first
    cached_df = cache.get(cache_key)
    if cached_df is not None:
        # Ensure we return a polars DataFrame
        if hasattr(cached_df, "to_pandas"):
            df = cached_df
        else:
            df = pl.from_pandas(cached_df)
        df_size_mb = df.estimated_size("mb")
        logger.info(f"🚀 REDIS CACHE: Hit! Loaded DataFrame {df.shape} ({df_size_mb:.1f}MB)")
        return df

    # Step 2: Check if another process is loading data
    if cache.exists(lock_key):
        logger.info("🔄 PARQUET LOADING: Another process loading data, waiting...")
        max_wait = 10  # Optimized for small datasets (1000 rows)
        wait_time = 0
        while wait_time < max_wait and cache.exists(lock_key):
            time.sleep(0.1)  # Much faster polling for small files
            wait_time += 0.1
            # Check if data became available in cache
            cached_df = cache.get(cache_key)
            if cached_df is not None:
                if hasattr(cached_df, "to_pandas"):
                    df = cached_df
                else:
                    df = pl.from_pandas(cached_df)
                df_size_mb = df.estimated_size("mb")
                logger.info(
                    f"🔄 REDIS CACHE: Loaded from other process! {df.shape} ({df_size_mb:.1f}MB)"
                )
                return df

    # Step 3: Load from parquet file or generate if needed
    try:
        # Set lock to prevent duplicate loading
        cache.set(lock_key, str(time.time()), ttl=120)  # 2 minute lock for large files

        parquet_path = get_parquet_file_path(config)

        # Check if parquet file exists
        if parquet_path.exists():
            # Load existing parquet file
            logger.info(f"📦 PARQUET LOADING: Loading from {parquet_path.name}")
            df = pl.read_parquet(parquet_path)
            file_size_mb = parquet_path.stat().st_size / (1024 * 1024)
            df_size_mb = df.estimated_size("mb")
            logger.info(
                f"📦 PARQUET LOADED: {df.shape} ({df_size_mb:.1f}MB from {file_size_mb:.1f}MB file)"
            )
        else:
            # Generate and save parquet file first
            logger.info("🔧 PARQUET: No existing file found, generating new one...")
            generate_and_save_parquet(config)

            # Load the newly created parquet file
            df = pl.read_parquet(parquet_path)
            file_size_mb = parquet_path.stat().st_size / (1024 * 1024)
            df_size_mb = df.estimated_size("mb")
            logger.info(
                f"📦 PARQUET GENERATED & LOADED: {df.shape} ({df_size_mb:.1f}MB from {file_size_mb:.1f}MB file)"
            )

        # Step 4: Cache in Redis for faster subsequent access
        cache.set(cache_key, df, ttl=1800)  # Cache for 30 minutes
        logger.info(f"✅ REDIS CACHED: DataFrame stored for faster access ({df_size_mb:.1f}MB)")

        return df

    except Exception as e:
        logger.error(f"❌ PARQUET LOADING: Failed to load data: {e}")
        # Return a minimal fallback dataset
        return pl.DataFrame(
            {
                "date": [datetime.now()],
                "category": ["Error"],
                "users": [0],
                "revenue": [0],
                "conversion_rate": [0],
                "sessions": [0],
            }
        )
    finally:
        # Always clear the lock
        if cache.exists(lock_key):
            try:
                cache._redis.delete(f"{cache.cache_config.cache_key_prefix}{lock_key}")
            except Exception as e:
                logger.error(f"❌ REDIS CACHE: Failed to release lock {lock_key}: {e}")


def generate_dummy_dataframe(config=None):
    """
    DEPRECATED: Use get_cached_dataframe() instead.
    This function is kept for backward compatibility.
    """
    logger.warning(
        "⚠️ generate_dummy_dataframe() is deprecated. Use get_cached_dataframe() instead."
    )
    return get_cached_dataframe(config)
