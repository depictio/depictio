"""
Dashboard content management with pattern-matching background callbacks.

This module provides modular content management where each component
is rendered individually through pattern matching callbacks.
"""

import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import dash_mantine_components as dmc
import plotly.express as px
import polars as pl
from dash import ALL, MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import create_cache
from depictio.api.v1.configs.logging_init import logger

# ============================================================================
# DASHBOARD METADATA CONFIGURATION
# ============================================================================
# Central metadata location - the only input required to render components

# Data generation configuration
DATA_CONFIG = {
    "rows": 1000,  # 1K rows for fast development
    "categories": ["Category A", "Category B", "Category C", "Category D", "Category E"],
    "metrics": {
        "users": {"min": 1000, "max": 10000, "format": "int"},
        "revenue": {"min": 10000, "max": 100000, "format": "currency"},
        "conversion_rate": {"min": 1.5, "max": 8.5, "format": "percentage"},
        "sessions": {"min": 500, "max": 5000, "format": "int"},
    },
}

# Component dependency mapping - defines which components react to which data filters
COMPONENT_DEPENDENCIES = {
    "metric": [
        "revenue_range",
        "users_range",
        "category_filter",
        "date_range",
    ],  # Metrics affected by data filters
    "chart": [
        "revenue_range",
        "users_range",
        "category_filter",
        "date_range",
    ],  # Charts affected by all data filters
    "interactive": [],  # Interactive components don't depend on other controls
}

DASHBOARD_COMPONENTS = [
    # Interactive controls at the top
    {"type": "interactive", "index": 0, "title": "Dashboard Controls", "position": "top"},
    # 8 Metric cards (reduced for stability)
    {"type": "metric", "index": 0, "title": "Total Users", "metric_key": "users"},
    {"type": "metric", "index": 1, "title": "Revenue", "metric_key": "revenue"},
    {"type": "metric", "index": 2, "title": "Conversion Rate", "metric_key": "conversion_rate"},
    {"type": "metric", "index": 3, "title": "Active Sessions", "metric_key": "sessions"},
    {"type": "metric", "index": 4, "title": "New Users", "metric_key": "users"},
    {"type": "metric", "index": 5, "title": "Monthly Revenue", "metric_key": "revenue"},
    {"type": "metric", "index": 6, "title": "Daily Conversion", "metric_key": "conversion_rate"},
    {"type": "metric", "index": 7, "title": "Peak Sessions", "metric_key": "sessions"},
    # Commented out for reduced load - uncomment for benchmarking
    # {"type": "metric", "index": 8, "title": "Returning Users", "metric_key": "users"},
    # {"type": "metric", "index": 9, "title": "Avg Revenue", "metric_key": "revenue"},
    # {"type": "metric", "index": 10, "title": "Min Conversion", "metric_key": "conversion_rate"},
    # {"type": "metric", "index": 11, "title": "Session Duration", "metric_key": "sessions"},
    # {"type": "metric", "index": 12, "title": "Active Users", "metric_key": "users"},
    # {"type": "metric", "index": 13, "title": "Total Revenue", "metric_key": "revenue"},
    # {"type": "metric", "index": 14, "title": "Max Conversion", "metric_key": "conversion_rate"},
    # {"type": "metric", "index": 15, "title": "Live Sessions", "metric_key": "sessions"},
    # {"type": "metric", "index": 16, "title": "Guest Users", "metric_key": "users"},
    # {"type": "metric", "index": 17, "title": "Weekly Revenue", "metric_key": "revenue"},
    # {"type": "metric", "index": 18, "title": "Overall Rate", "metric_key": "conversion_rate"},
    # {"type": "metric", "index": 19, "title": "Total Sessions", "metric_key": "sessions"},
    # Additional 20 metrics (20-39) - commented for reduced load
    # {"type": "metric", "index": 20, "title": "Unique Visitors", "metric_key": "users"},
    # {"type": "metric", "index": 21, "title": "Gross Profit", "metric_key": "revenue"},
    # {"type": "metric", "index": 22, "title": "Bounce Rate", "metric_key": "conversion_rate"},
    # {"type": "metric", "index": 23, "title": "Avg Session Time", "metric_key": "sessions"},
    # {"type": "metric", "index": 24, "title": "Registered Users", "metric_key": "users"},
    # {"type": "metric", "index": 25, "title": "Net Revenue", "metric_key": "revenue"},
    # {"type": "metric", "index": 26, "title": "Cart Abandon Rate", "metric_key": "conversion_rate"},
    # {"type": "metric", "index": 27, "title": "Mobile Sessions", "metric_key": "sessions"},
    # {"type": "metric", "index": 28, "title": "Premium Users", "metric_key": "users"},
    # {"type": "metric", "index": 29, "title": "Subscription Rev", "metric_key": "revenue"},
    # {"type": "metric", "index": 30, "title": "Signup Rate", "metric_key": "conversion_rate"},
    # {"type": "metric", "index": 31, "title": "Desktop Sessions", "metric_key": "sessions"},
    # {"type": "metric", "index": 32, "title": "Trial Users", "metric_key": "users"},
    # {"type": "metric", "index": 33, "title": "Ad Revenue", "metric_key": "revenue"},
    # {"type": "metric", "index": 34, "title": "Retention Rate", "metric_key": "conversion_rate"},
    # {"type": "metric", "index": 35, "title": "API Sessions", "metric_key": "sessions"},
    # {"type": "metric", "index": 36, "title": "Enterprise Users", "metric_key": "users"},
    # {"type": "metric", "index": 37, "title": "Recurring Revenue", "metric_key": "revenue"},
    # {"type": "metric", "index": 38, "title": "Churn Rate", "metric_key": "conversion_rate"},
    # {"type": "metric", "index": 39, "title": "Bot Sessions", "metric_key": "sessions"},
    # 20 Chart components for benchmarking
    {
        "type": "chart",
        "index": 0,
        "title": "User Activity Scatter",
        "chart_type": "scatter",
        "x_col": "date",
        "y_col": "users",
    },
    {
        "type": "chart",
        "index": 1,
        "title": "Revenue by Category",
        "chart_type": "bar",
        "x_col": "category",
        "y_col": "revenue",
    },
    {
        "type": "chart",
        "index": 2,
        "title": "Conversion Distribution",
        "chart_type": "box",
        "x_col": "category",
        "y_col": "conversion_rate",
    },
    {
        "type": "chart",
        "index": 3,
        "title": "Sessions Timeline",
        "chart_type": "line",
        "x_col": "date",
        "y_col": "sessions",
    },
    # Commented out for reduced configuration (keeping 4 charts total)
    # {
    #     "type": "chart",
    #     "index": 4,
    #     "title": "User Revenue Correlation",
    #     "chart_type": "scatter",
    #     "x_col": "users",
    #     "y_col": "revenue",
    # },
    # {
    #     "type": "chart",
    #     "index": 5,
    #     "title": "Daily Metrics",
    #     "chart_type": "line",
    #     "x_col": "date",
    #     "y_col": "conversion_rate",
    # },
    # {
    #     "type": "chart",
    #     "index": 6,
    #     "title": "Category Analysis",
    #     "chart_type": "bar",
    #     "x_col": "category",
    #     "y_col": "sessions",
    # },
    # {
    #     "type": "chart",
    #     "index": 7,
    #     "title": "Revenue Trends",
    #     "chart_type": "line",
    #     "x_col": "date",
    #     "y_col": "revenue",
    # },
    # {
    #     "type": "chart",
    #     "index": 8,
    #     "title": "User Distribution",
    #     "chart_type": "box",
    #     "x_col": "category",
    #     "y_col": "users",
    # },
    # {
    #     "type": "chart",
    #     "index": 9,
    #     "title": "Session Distribution",
    #     "chart_type": "box",
    #     "x_col": "category",
    #     "y_col": "sessions",
    # },
    # {
    #     "type": "chart",
    #     "index": 10,
    #     "title": "Performance Matrix",
    #     "chart_type": "scatter",
    #     "x_col": "conversion_rate",
    #     "y_col": "sessions",
    # },
    # {
    #     "type": "chart",
    #     "index": 11,
    #     "title": "Overall Trends",
    #     "chart_type": "line",
    #     "x_col": "date",
    #     "y_col": "users",
    # },
    # # Additional 8 charts (12-19) for benchmarking
    # {
    #     "type": "chart",
    #     "index": 12,
    #     "title": "Daily Performance",
    #     "chart_type": "line",
    #     "x_col": "date",
    #     "y_col": "revenue",
    # },
    # {
    #     "type": "chart",
    #     "index": 13,
    #     "title": "Category Comparison",
    #     "chart_type": "bar",
    #     "x_col": "category",
    #     "y_col": "users",
    # },
    # {
    #     "type": "chart",
    #     "index": 14,
    #     "title": "Revenue Scatter",
    #     "chart_type": "scatter",
    #     "x_col": "users",
    #     "y_col": "revenue",
    # },
    # {
    #     "type": "chart",
    #     "index": 15,
    #     "title": "Session Analysis",
    #     "chart_type": "box",
    #     "x_col": "category",
    #     "y_col": "sessions",
    # },
    # {
    #     "type": "chart",
    #     "index": 16,
    #     "title": "Conversion Trends",
    #     "chart_type": "line",
    #     "x_col": "date",
    #     "y_col": "conversion_rate",
    # },
    # {
    #     "type": "chart",
    #     "index": 17,
    #     "title": "User Categories",
    #     "chart_type": "bar",
    #     "x_col": "category",
    #     "y_col": "users",
    # },
    # {
    #     "type": "chart",
    #     "index": 18,
    #     "title": "Performance Metrics",
    #     "chart_type": "scatter",
    #     "x_col": "sessions",
    #     "y_col": "revenue",
    # },
    # {
    #     "type": "chart",
    #     "index": 19,
    #     "title": "Monthly Overview",
    #     "chart_type": "line",
    #     "x_col": "date",
    #     "y_col": "sessions",
    # },
]


# ============================================================================
# DATA GENERATION UTILITIES
# ============================================================================

# Global in-memory cache as fallback for when file locking fails
_MEMORY_CACHE: dict[str, tuple[Any, float]] = {}


# Parquet-based data storage for sharing data between processes
def get_parquet_file_path(config=None):
    """Get the parquet file path for a given configuration."""
    if config is None:
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


def get_optimized_chart_data(df, chart_config):
    """
    Apply intelligent sampling based on chart type for optimal performance.

    Args:
        df: Full polars DataFrame
        chart_config: Chart configuration dict

    Returns:
        pl.DataFrame: Optimally sampled data for the chart type
    """
    chart_type = chart_config["chart_type"]
    original_size = len(df)

    # Define optimal sample sizes for different chart types
    sampling_strategy = {
        "scatter": {
            "max_sample": 10_000,
            "reason": "Visual density limit - more points don't improve clarity",
        },
        "box": {
            "max_sample": 50_000,
            "reason": "Statistical representation - need good quartile accuracy",
        },
        "violin": {
            "max_sample": 25_000,
            "reason": "Distribution shape - need sufficient density points",
        },
        "histogram": {
            "max_sample": 100_000,
            "reason": "Bin accuracy - need representative distribution",
        },
        "bar": {"max_sample": None, "reason": "Aggregated data - typically small result set"},
        "line": {"max_sample": None, "reason": "Time series - may need full temporal resolution"},
    }

    strategy = sampling_strategy.get(
        chart_type, {"max_sample": 10_000, "reason": "Default conservative sampling"}
    )
    max_sample = strategy["max_sample"]

    logger.info(f"📊 CHART DATA: Processing {original_size:,} rows for {chart_type} chart")

    # No sampling needed for small datasets or non-sampling chart types
    if max_sample is None or original_size <= max_sample:
        logger.warning(
            f"📊 CHART DATA: Using full dataset ({original_size:,} rows) for {chart_type} - {strategy['reason']}"
        )
        return df

    # Apply intelligent sampling using polars
    sampled_df = df.sample(n=max_sample, seed=42)  # Fixed seed for reproducible sampling

    logger.info(
        f"🎯 CHART SAMPLING: {chart_type} optimized from {original_size:,} → {max_sample:,} rows "
        f"({max_sample / original_size * 100:.1f}% sample) - {strategy['reason']}"
    )

    return sampled_df


# ============================================================================
# CENTRALIZED EVENT SYSTEM
# ============================================================================


def create_initial_event_state():
    """Create the initial state for the dashboard event store with data filtering controls."""
    return {
        "revenue_range": {
            "value": [
                DATA_CONFIG["metrics"]["revenue"]["min"],
                DATA_CONFIG["metrics"]["revenue"]["max"],
            ],
            "timestamp": time.time(),
            "changed": True,  # Mark as changed to trigger initial component rendering
        },
        "users_range": {
            "value": [
                DATA_CONFIG["metrics"]["users"]["min"],
                DATA_CONFIG["metrics"]["users"]["max"],
            ],
            "timestamp": time.time(),
            "changed": False,
        },
        "category_filter": {"value": ["all"], "timestamp": time.time(), "changed": False},
        "date_range": {"value": "all", "timestamp": time.time(), "changed": False},
    }


def should_component_update(component_type, event_state, trigger_id):
    """
    Determine if a component should update based on its dependencies and what changed.

    Args:
        component_type: Type of component ('metric', 'chart', 'interactive')
        event_state: Current state of all dashboard controls
        trigger_id: The ID that triggered the callback

    Returns:
        bool: True if component should update
    """
    logger.info(f"🔍 SHOULD_UPDATE: {component_type} - trigger_id={trigger_id}")
    logger.info(f"🔍 SHOULD_UPDATE: event_state={event_state}")

    if not event_state:
        logger.info(
            f"🔄 COMPONENT UPDATE: {component_type} updating - no event state (initial render)"
        )
        return True  # Initial render

    # Get dependencies for this component type
    dependencies = COMPONENT_DEPENDENCIES.get(component_type, [])
    logger.info(f"🔍 SHOULD_UPDATE: {component_type} dependencies = {dependencies}")

    # Check if any dependencies have changed
    for dep in dependencies:
        changed = event_state.get(dep, {}).get("changed", False)
        logger.info(f"🔍 SHOULD_UPDATE: {dep} changed = {changed}")
        if changed:
            logger.info(f"🔄 COMPONENT UPDATE: {component_type} updating due to {dep} change")
            return True

    # Check if this is initial load (trigger_id is None) - always render
    if trigger_id is None:
        logger.info(f"🔄 COMPONENT UPDATE: {component_type} updating - initial page load")
        return True  # Initial page load

    # Check if this is an initial component trigger (not event-driven)
    if trigger_id and not any(
        control in str(trigger_id)
        for control in ["data-filter-range", "data-filter-dropdown", "dashboard-event-store"]
    ):
        logger.info(f"🔄 COMPONENT UPDATE: {component_type} updating - component initialization")
        return True  # Component initialization

    logger.info(f"⏭️ COMPONENT SKIP: {component_type} skipping - no relevant changes")
    return False


def update_event_state(current_state, control_id, new_value):
    """
    Update the event state when a control changes.

    Args:
        current_state: Current event state
        control_id: ID of the control that changed
        new_value: New value of the control

    Returns:
        dict: Updated event state
    """
    if not current_state:
        current_state = create_initial_event_state()

    # Reset all changed flags
    updated_state = {}
    for key, state in current_state.items():
        updated_state[key] = {
            "value": state["value"],
            "timestamp": state["timestamp"],
            "changed": False,
        }

    # Update the changed control
    if control_id in updated_state:
        old_value = updated_state[control_id]["value"]
        if old_value != new_value:
            updated_state[control_id] = {
                "value": new_value,
                "timestamp": time.time(),
                "changed": True,
            }
            logger.info(f"🎛️ EVENT UPDATE: {control_id} changed from {old_value} → {new_value}")

    return updated_state


def get_current_config_from_events(event_state):
    """
    Generate a DATA_CONFIG based on current event state - always use base config for generation.
    Filtering happens post-generation.

    Args:
        event_state: Current dashboard event state

    Returns:
        dict: Base configuration for data generation (filtering applied separately)
    """
    # Always return base config - filtering happens in apply_data_filters()
    return DATA_CONFIG


def apply_data_filters(df, event_state, component_id="unknown"):
    """
    Apply data filters based on current event state to the DataFrame.

    Args:
        df: polars DataFrame to filter
        event_state: Current dashboard event state
        component_id: ID of component requesting filtering (for debugging)

    Returns:
        pl.DataFrame: Filtered DataFrame
    """
    if not event_state:
        return df

    logger.info(f"🔍 FILTER DEBUG [{component_id}]: Full event state = {event_state}")

    filtered_df = df

    # Apply revenue range filter using polars
    revenue_range = event_state.get("revenue_range", {}).get("value", [0, float("inf")])
    if revenue_range and len(revenue_range) == 2:
        min_revenue, max_revenue = revenue_range
        filtered_df = filtered_df.filter(
            (pl.col("revenue") >= min_revenue) & (pl.col("revenue") <= max_revenue)
        )
        logger.info(
            f"🔍 DATA FILTER [{component_id}]: Revenue range [{min_revenue:,} - {max_revenue:,}] → {len(filtered_df):,} rows"
        )

    # Apply users range filter using polars
    users_range = event_state.get("users_range", {}).get("value", [0, float("inf")])
    if users_range and len(users_range) == 2:
        min_users, max_users = users_range
        filtered_df = filtered_df.filter(
            (pl.col("users") >= min_users) & (pl.col("users") <= max_users)
        )
        logger.info(
            f"🔍 DATA FILTER [{component_id}]: Users range [{min_users:,} - {max_users:,}] → {len(filtered_df):,} rows"
        )

    # Apply category filter
    category_filter = event_state.get("category_filter", {}).get("value", ["all"])
    logger.info(
        f"🔍 FILTER DEBUG [{component_id}]: Category filter from event state = {category_filter}"
    )
    if category_filter and "all" not in category_filter:
        before_filter = len(filtered_df)
        filtered_df = filtered_df.filter(pl.col("category").is_in(category_filter))
        logger.info(
            f"🔍 DATA FILTER [{component_id}]: Categories {category_filter} → {before_filter:,} → {len(filtered_df):,} rows"
        )
        logger.info(
            f"🔍 FILTER DEBUG [{component_id}]: Unique categories in filtered data = {sorted(filtered_df['category'].unique().to_list())}"
        )

    # Apply date range filter
    date_range = event_state.get("date_range", {}).get("value", "all")
    if date_range != "all":
        # For demo, implement last N days filter using polars
        if date_range == "last_7_days":
            cutoff_date = datetime.now() - timedelta(days=7)
            filtered_df = filtered_df.filter(pl.col("date") >= cutoff_date)
            logger.info(f"🔍 DATA FILTER [{component_id}]: Last 7 days → {len(filtered_df):,} rows")
        elif date_range == "last_30_days":
            cutoff_date = datetime.now() - timedelta(days=30)
            filtered_df = filtered_df.filter(pl.col("date") >= cutoff_date)
            logger.info(
                f"🔍 DATA FILTER [{component_id}]: Last 30 days → {len(filtered_df):,} rows"
            )
        elif date_range == "last_90_days":
            cutoff_date = datetime.now() - timedelta(days=90)
            filtered_df = filtered_df.filter(pl.col("date") >= cutoff_date)
            logger.info(
                f"🔍 DATA FILTER [{component_id}]: Last 90 days → {len(filtered_df):,} rows"
            )

    total_filters_applied = len(df) - len(filtered_df)
    if total_filters_applied > 0:
        logger.info(
            f"📊 FILTERED DATA [{component_id}]: {len(df):,} → {len(filtered_df):,} rows ({total_filters_applied:,} filtered out)"
        )

    return filtered_df


def generate_dummy_dataframe(config=None):
    """
    DEPRECATED: Use get_cached_dataframe() instead.
    This function is kept for backward compatibility.
    """
    logger.warning(
        "⚠️ generate_dummy_dataframe() is deprecated. Use get_cached_dataframe() instead."
    )
    return get_cached_dataframe(config)


def format_metric_value(value, format_type):
    """Format metric value based on type with None handling."""
    if value is None:
        return "N/A"

    try:
        if format_type == "currency":
            return f"${value:,.0f}"
        elif format_type == "percentage":
            return f"{value:.1f}%"
        elif format_type == "int":
            return f"{value:,}"
        else:
            return str(value)
    except (ValueError, TypeError) as e:
        logger.warning(f"Error formatting value {value} with format {format_type}: {e}")
        return "Error"


def create_chart_figure(df, chart_config):
    """
    Create plotly figure based on chart configuration.

    Args:
        df: polars DataFrame (native Plotly support)
        chart_config: Chart configuration dict

    Returns:
        plotly.graph_objects.Figure: Generated chart
    """
    chart_type = chart_config["chart_type"]
    x_col = chart_config["x_col"]
    y_col = chart_config["y_col"]
    title = chart_config["title"]

    # Get height and theme from enhanced config or defaults
    height = chart_config.get("chart_height", 400)
    theme = chart_config.get("chart_theme", "plotly")

    logger.info(
        f"🔧 CHART GENERATION: Creating {chart_type} chart '{title}' (height={height}, theme={theme}) - using native Polars"
    )

    if chart_type == "scatter":
        fig = px.scatter(df, x=x_col, y=y_col, title=title, height=height, template=theme)
    elif chart_type == "bar":
        # Aggregate data for bar chart using polars directly
        agg_df = df.group_by(x_col).agg(pl.col(y_col).mean())
        fig = px.bar(agg_df, x=x_col, y=y_col, title=title, height=height, template=theme)
    elif chart_type == "box":
        fig = px.box(df, x=x_col, y=y_col, title=title, height=height, template=theme)
    elif chart_type == "line":
        fig = px.line(df, x=x_col, y=y_col, title=title, height=height, template=theme)
    else:
        # Default to scatter
        fig = px.scatter(df, x=x_col, y=y_col, title=title, height=height, template=theme)

    # Update layout for better appearance (conditional based on theme)
    layout_updates = {
        "font": dict(size=12),
        "margin": dict(l=40, r=40, t=60, b=40),
    }

    # Only apply transparent backgrounds for certain themes
    if theme in ["plotly", "plotly_white"]:
        layout_updates.update(
            {
                "plot_bgcolor": "rgba(0,0,0,0)",
                "paper_bgcolor": "rgba(0,0,0,0)",
            }
        )

    fig.update_layout(**layout_updates)

    logger.info(
        f"✅ CHART GENERATION: Created {chart_type} chart with {len(df)} data points (height={height}, theme={theme})"
    )

    return fig


# Removed complex state tracking - using simpler timeout-based loading indicator


def register_dashboard_content_callbacks(app):
    """Register dashboard content callbacks with pattern matching."""

    logger.info("🔧 DASHBOARD CONTENT: Registering pattern-matching background callbacks...")

    # Initialize Flask-Caching for simple caching
    flask_cache = create_cache(app.server)
    logger.info("✅ CACHE: Flask-Caching initialized for dashboard")

    # Cache dataframe loading for 15 minutes
    @flask_cache.memoize(timeout=900)
    def get_cached_dataframe_with_memoize():
        """Cached wrapper for dataframe loading."""
        logger.info("📊 CACHE: Loading dataframe (will be cached for 15 minutes)")
        return get_cached_dataframe()

    # Cache figure generation for 5 minutes
    @flask_cache.memoize(timeout=300)
    def create_cached_chart_figure(df_shape, config_str):
        """Cached wrapper for chart figure generation."""
        logger.info("📊 CACHE: Generating figure (will be cached for 5 minutes)")
        # Reconstruct the dataframe and config
        # In production, you'd want to pass serializable parameters
        df = get_cached_dataframe()
        import json

        config = json.loads(config_str)
        return create_chart_figure(df, config)

    # Main callback to create container structure
    @app.callback(
        Output("dashboard-content", "children"),
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
        ],
        prevent_initial_call="initial_duplicate",
    )
    def create_dashboard_containers(pathname, local_store):
        """
        Create the container structure for dashboard components.
        Each container will be populated by individual background callbacks.
        """

        logger.info(f"🚀 DASHBOARD CONTENT: Creating containers for {pathname}")

        # Only handle dashboard routes
        if not pathname or not pathname.startswith("/dashboard/"):
            logger.info("🔧 DASHBOARD CONTENT: Not a dashboard route, skipping")
            return html.Div()

        # Check if user is authenticated
        if not local_store or not local_store.get("access_token"):
            logger.info("🔧 DASHBOARD CONTENT: No authentication token, showing login prompt")
            return create_login_prompt()

        dashboard_id = pathname.split("/")[-1] if "/" in pathname else "unknown"

        # Use centralized metadata configuration
        components = DASHBOARD_COMPONENTS

        # Create container structure with unique IDs for pattern matching
        containers = []

        # Dashboard header with loading indicator
        containers.append(
            dmc.Group(
                justify="space-between",
                align="center",
                mb="xl",
                children=[
                    html.Div(
                        [
                            dmc.Title(
                                "Dashboard Analytics",
                                order=2,
                                mb="xs",
                            ),
                            dmc.Text(
                                f"Dashboard ID: {dashboard_id}",
                                size="sm",
                                c="gray",
                            ),
                        ]
                    ),
                    # Dashboard loading indicator
                    dmc.Badge(
                        id="dashboard-loading-indicator",
                        children=[
                            DashIconify(icon="svg-spinners:180-ring", width=16, className="mr-2"),
                            "Dashboard Updating...",
                        ],
                        color="blue",
                        variant="dot",
                        size="lg",
                        style={"display": "none"},  # Initially hidden
                    ),
                ],
            )
        )

        # Create interactive controls at the top
        for comp in components:
            if comp["type"] == "interactive" and comp.get("position") == "top":
                containers.append(
                    html.Div(
                        # dmc.Skeleton(height=120, radius="md"),  # Loading skeleton disabled for performance test
                        html.Div(
                            "Loading interactive...",
                            style={"height": "120px", "textAlign": "center", "paddingTop": "50px"},
                        ),
                        id={"type": "interactive-component", "index": comp["index"]},
                    )
                )

        # Create grid for metric cards
        metric_containers = []
        for comp in components:
            if comp["type"] == "metric":
                # Create empty container with pattern-matching ID and LoadingOverlay
                metric_containers.append(
                    dmc.GridCol(
                        dmc.Box(
                            [
                                html.Div(
                                    # dmc.Skeleton(height=150, radius="md"),  # Loading skeleton disabled for performance test
                                    html.Div(
                                        "Loading metric...",
                                        style={
                                            "height": "150px",
                                            "textAlign": "center",
                                            "paddingTop": "60px",
                                        },
                                    ),
                                    id={"type": "metric-card", "index": comp["index"]},
                                ),
                            ],
                            pos="relative",
                        ),
                        span={"base": 12, "sm": 6, "lg": 3},
                    )
                )

        if metric_containers:
            containers.append(
                dmc.Grid(
                    children=metric_containers,
                    gutter="md",
                    mb="xl",
                )
            )

        # Create containers for other component types
        for comp in components:
            if comp["type"] == "chart":
                containers.append(
                    html.Div(
                        # dmc.Skeleton(height=400, radius="md"),  # Loading skeleton disabled for performance test
                        html.Div(
                            "Loading chart...",
                            style={"height": "400px", "textAlign": "center", "paddingTop": "180px"},
                        ),
                        id={"type": "chart-component", "index": comp["index"]},
                    )
                )

        logger.info(f"✅ DASHBOARD CONTENT: Created {len(components)} component containers")

        # Add event store for centralized state management
        containers.extend(
            [
                dcc.Store(id="dashboard-event-store", data=create_initial_event_state()),
                dcc.Store(
                    id="loading-completion-tracker", data={"components_loaded": 0, "timestamp": 0}
                ),
                html.Div(id="dummy-event-output"),  # Dummy output for event callbacks
            ]
        )

        return html.Div(containers)

    # Individual MATCH callback for each metric card
    @app.callback(
        Output({"type": "metric-card", "index": MATCH}, "children"),
        [
            Input({"type": "metric-card", "index": MATCH}, "id"),
            Input("dashboard-event-store", "data"),  # Listen to event changes
        ],
        State("local-store", "data"),
        prevent_initial_call="initial_duplicate",
        background=True,  # Background execution for each individual metric
    )
    def render_single_metric_card(component_id, event_state, local_store):
        """
        Render a single metric card - each card has its own callback.
        This is called individually for EACH metric card component.
        """

        # Safely extract metric index with error handling
        if not component_id or "index" not in component_id:
            logger.error(f"❌ METRIC CARD: Invalid component_id: {component_id}")
            return html.Div("Component Error")

        metric_index = component_id["index"]
        logger.info(f"🔄 METRIC CARD {metric_index}: Individual rendering (background)")

        # Check if this component should update based on event changes
        from dash import callback_context

        ctx = callback_context
        trigger_id = ctx.triggered[0]["prop_id"] if ctx.triggered else None

        logger.info(f"🔍 METRIC CARD {metric_index}: Trigger ID = {trigger_id}")
        logger.info(f"🔍 METRIC CARD {metric_index}: Event state = {event_state}")

        # For debugging: always update when event store changes until we fix the changed flag issue
        if trigger_id == "dashboard-event-store.data":
            logger.info(f"🔄 METRIC CARD {metric_index}: Updating due to event store change")
        else:
            # Use centralized logic to determine if update is needed for other triggers
            if not should_component_update("metric", event_state, trigger_id):
                logger.info(f"⏭️ METRIC CARD {metric_index}: Skipping update - no relevant changes")
                from dash import no_update

                # Keep current state when skipping update
                return no_update

        logger.info(f"⏱️ METRIC CARD {metric_index}: Starting processing")

        # Get base dataframe and apply current filters
        base_df = get_cached_dataframe()
        df = apply_data_filters(base_df, event_state, f"metric-{metric_index}")

        # Find component configuration
        component_config = None
        for comp in DASHBOARD_COMPONENTS:
            if comp["type"] == "metric" and comp["index"] == metric_index:
                component_config = comp
                break

        if not component_config:
            logger.error(f"❌ METRIC CARD {metric_index}: Component configuration not found")
            logger.error(
                f"Available metric indices: {[c['index'] for c in DASHBOARD_COMPONENTS if c['type'] == 'metric']}"
            )
            return html.Div(f"Configuration Error: Metric {metric_index} not found")

        # Get metric data from DataFrame
        metric_key = component_config["metric_key"]
        metric_config = DATA_CONFIG["metrics"][metric_key]

        # Calculate aggregated value using polars (e.g., sum, mean, latest)
        if metric_config["format"] == "int":
            aggregated_value = df[metric_key].sum()
        else:
            aggregated_value = df[metric_key].mean()

        # Icon mapping based on metric type
        icon_mapping = {
            "users": "mdi:account-group",
            "revenue": "mdi:currency-usd",
            "conversion_rate": "mdi:chart-line",
            "sessions": "mdi:monitor-eye",
        }

        # Color mapping based on metric type
        color_mapping = {
            "users": "blue",
            "revenue": "green",
            "conversion_rate": "orange",
            "sessions": "purple",
        }

        # Generate growth percentage
        growth = random.uniform(1.0, 25.0)

        metric_data = {
            "title": component_config["title"],
            "value": format_metric_value(aggregated_value, metric_config["format"]),
            "icon": icon_mapping.get(metric_key, "mdi:chart-box"),
            "color": color_mapping.get(metric_key, "gray"),
            "change": f"+{growth:.1f}%",
        }

        card = create_metric_card(metric_data)

        logger.info(
            f"✅ METRIC CARD {metric_index}: Rendered '{component_config['title']}' ({metric_data['value']})"
        )
        return card

    # Individual MATCH callback for each chart component
    @app.callback(
        Output({"type": "chart-component", "index": MATCH}, "children"),
        [
            Input({"type": "chart-component", "index": MATCH}, "id"),
            Input("dashboard-event-store", "data"),  # Listen to event changes
        ],
        State("local-store", "data"),
        prevent_initial_call="initial_duplicate",
        background=True,  # Background execution for each individual chart
    )
    def render_single_chart_component(component_id, event_state, local_store):
        """
        Render a single chart component - each chart has its own callback.
        This is called individually for EACH chart component.
        """

        # Safely extract chart index with error handling
        if not component_id or "index" not in component_id:
            logger.error(f"❌ CHART COMPONENT: Invalid component_id: {component_id}")
            return html.Div("Component Error")

        chart_index = component_id["index"]
        logger.info(f"🔄 CHART COMPONENT {chart_index}: Individual rendering (background)")

        # Check if this component should update based on event changes
        from dash import callback_context

        ctx = callback_context
        trigger_id = ctx.triggered[0]["prop_id"] if ctx.triggered else None

        logger.info(f"🔍 CHART COMPONENT {chart_index}: Trigger ID = {trigger_id}")
        logger.info(f"🔍 CHART COMPONENT {chart_index}: Event state = {event_state}")

        # For debugging: always update when event store changes until we fix the changed flag issue
        if trigger_id == "dashboard-event-store.data":
            logger.info(f"🔄 CHART COMPONENT {chart_index}: Updating due to event store change")
        else:
            # Use centralized logic to determine if update is needed for other triggers
            if not should_component_update("chart", event_state, trigger_id):
                logger.info(
                    f"⏭️ CHART COMPONENT {chart_index}: Skipping update - no relevant changes"
                )
                from dash import no_update

                # Keep current state when skipping update
                return no_update

        logger.info(f"⏱️ CHART COMPONENT {chart_index}: Starting processing")

        # Get base dataframe and apply current filters
        base_df = get_cached_dataframe()
        df = apply_data_filters(base_df, event_state, f"chart-{chart_index}")

        # Find component configuration
        component_config = None
        for comp in DASHBOARD_COMPONENTS:
            if comp["type"] == "chart" and comp["index"] == chart_index:
                component_config = comp
                break

        if not component_config:
            logger.error(f"❌ CHART COMPONENT {chart_index}: Component configuration not found")
            logger.error(
                f"Available chart indices: {[c['index'] for c in DASHBOARD_COMPONENTS if c['type'] == 'chart']}"
            )
            return html.Div(f"Configuration Error: Chart {chart_index} not found")

        # Apply intelligent sampling for optimal performance
        try:
            optimized_df = get_optimized_chart_data(df, component_config)

            # Get current chart height from events
            chart_height = (
                event_state.get("chart_height", {}).get("value", 400) if event_state else 400
            )
            chart_theme = (
                event_state.get("chart_theme", {}).get("value", "plotly")
                if event_state
                else "plotly"
            )

            # Update component config with current event values
            enhanced_config = component_config.copy()
            enhanced_config["chart_height"] = chart_height
            enhanced_config["chart_theme"] = chart_theme

            # Generate figure directly - Flask-Cache will handle caching transparently
            fig = create_chart_figure(optimized_df, enhanced_config)

            # Create chart component with Plotly graph
            chart = dmc.Paper(
                shadow="sm",
                radius="md",
                p="lg",
                withBorder=True,
                children=[
                    dmc.Group(
                        justify="space-between",
                        align="center",
                        mb="md",
                        children=[
                            dmc.Title(component_config["title"], order=4),
                            dmc.Badge(
                                component_config["chart_type"].title(),
                                color="blue",
                                variant="light",
                                leftSection=DashIconify(icon="mdi:chart-line", width=12),
                            ),
                        ],
                    ),
                    dcc.Graph(
                        figure=fig,
                        config={
                            "displayModeBar": True,
                            "displaylogo": False,
                            "modeBarButtonsToRemove": ["pan2d", "lasso2d"],
                        },
                    ),
                    dmc.Text(
                        f"📊 {len(optimized_df):,} data points • Generated at {time.strftime('%H:%M:%S')}",
                        size="xs",
                        c="gray",
                        ta="center",
                        mt="sm",
                    ),
                ],
            )

            logger.info(
                f"✅ CHART COMPONENT {chart_index}: Rendered {component_config['chart_type']} chart '{component_config['title']}'"
            )
            return chart

        except Exception as e:
            logger.error(f"❌ CHART COMPONENT {chart_index}: Error creating chart: {e}")
            return dmc.Paper(
                shadow="sm",
                radius="md",
                p="lg",
                withBorder=True,
                children=[
                    dmc.Title(f"Chart Error {chart_index}", order=4, c="red"),
                    dmc.Text(f"Failed to generate chart: {str(e)}", c="red"),
                ],
            )

    # Individual MATCH callback for each interactive component
    @app.callback(
        Output({"type": "interactive-component", "index": MATCH}, "children"),
        [
            Input({"type": "interactive-component", "index": MATCH}, "id"),
        ],
        State("local-store", "data"),
        prevent_initial_call="initial_duplicate",
        background=True,  # Background execution for each interactive component
    )
    def render_single_interactive_component(component_id, local_store):
        """
        Render a single interactive component - each component has its own callback.
        This is called individually for EACH interactive component.
        """

        interactive_index = component_id["index"]
        logger.info(
            f"🔄 INTERACTIVE COMPONENT {interactive_index}: Individual rendering (background)"
        )

        # Interactive components should load immediately for optimal performance

        # Find component configuration
        component_config = None
        for comp in DASHBOARD_COMPONENTS:
            if comp["type"] == "interactive" and comp["index"] == interactive_index:
                component_config = comp
                break

        if not component_config:
            logger.error(
                f"❌ INTERACTIVE COMPONENT {interactive_index}: Component configuration not found"
            )
            return html.Div("Configuration Error")

        # Create data filtering controls panel
        try:
            interactive_panel = dmc.Paper(
                shadow="sm",
                radius="md",
                p="lg",
                withBorder=True,
                mb="xl",
                children=[
                    dmc.Group(
                        justify="space-between",
                        align="center",
                        mb="md",
                        children=[
                            dmc.Title("Data Filters", order=4),
                            dmc.Badge(
                                "Interactive Data Controls",
                                color="violet",
                                variant="light",
                                leftSection=DashIconify(icon="mdi:filter-variant", width=12),
                            ),
                        ],
                    ),
                    dmc.Grid(
                        [
                            # First row: Revenue and Users range sliders
                            dmc.GridCol(
                                [
                                    dmc.Text("Revenue Range", size="sm", fw="bold", mb="xs"),
                                    dcc.RangeSlider(
                                        id={"type": "data-filter-range", "index": "revenue_range"},
                                        min=DATA_CONFIG["metrics"]["revenue"]["min"],
                                        max=DATA_CONFIG["metrics"]["revenue"]["max"],
                                        step=5000,
                                        value=[
                                            DATA_CONFIG["metrics"]["revenue"]["min"],
                                            DATA_CONFIG["metrics"]["revenue"]["max"],
                                        ],
                                        marks={
                                            DATA_CONFIG["metrics"]["revenue"][
                                                "min"
                                            ]: f"${DATA_CONFIG['metrics']['revenue']['min']:,}",
                                            DATA_CONFIG["metrics"]["revenue"][
                                                "max"
                                            ]: f"${DATA_CONFIG['metrics']['revenue']['max']:,}",
                                        },
                                        tooltip={"placement": "bottom", "always_visible": True},
                                    ),
                                ],
                                span=6,
                            ),
                            dmc.GridCol(
                                [
                                    dmc.Text("Users Range", size="sm", fw="bold", mb="xs"),
                                    dcc.RangeSlider(
                                        id={"type": "data-filter-range", "index": "users_range"},
                                        min=DATA_CONFIG["metrics"]["users"]["min"],
                                        max=DATA_CONFIG["metrics"]["users"]["max"],
                                        step=500,
                                        value=[
                                            DATA_CONFIG["metrics"]["users"]["min"],
                                            DATA_CONFIG["metrics"]["users"]["max"],
                                        ],
                                        marks={
                                            DATA_CONFIG["metrics"]["users"][
                                                "min"
                                            ]: f"{DATA_CONFIG['metrics']['users']['min']:,}",
                                            DATA_CONFIG["metrics"]["users"][
                                                "max"
                                            ]: f"{DATA_CONFIG['metrics']['users']['max']:,}",
                                        },
                                        tooltip={"placement": "bottom", "always_visible": True},
                                    ),
                                ],
                                span=6,
                            ),
                            # Second row: Category and Date filters
                            dmc.GridCol(
                                [
                                    dmc.Text("Category Filter", size="sm", fw="bold", mb="xs"),
                                    dcc.Dropdown(
                                        id={
                                            "type": "data-filter-dropdown",
                                            "index": "category_filter",
                                        },
                                        options=[
                                            {"label": "All Categories", "value": "all"},
                                        ]
                                        + [
                                            {"label": cat, "value": cat}
                                            for cat in DATA_CONFIG["categories"]
                                        ],
                                        value=["all"],
                                        multi=True,
                                        placeholder="Select categories to include...",
                                    ),
                                ],
                                span=6,
                            ),
                            dmc.GridCol(
                                [
                                    dmc.Text("Date Range Filter", size="sm", fw="bold", mb="xs"),
                                    dcc.Dropdown(
                                        id={"type": "data-filter-dropdown", "index": "date_range"},
                                        options=[
                                            {"label": "All Time", "value": "all"},
                                            {"label": "Last 7 Days", "value": "last_7_days"},
                                            {"label": "Last 30 Days", "value": "last_30_days"},
                                            {"label": "Last 90 Days", "value": "last_90_days"},
                                        ],
                                        value="all",
                                        clearable=False,
                                    ),
                                ],
                                span=6,
                            ),
                        ],
                        gutter="lg",
                    ),
                    dmc.Text(
                        "🔍 Data filters loaded • Adjust ranges and categories to filter dashboard data",
                        size="xs",
                        c="gray",
                        ta="center",
                        mt="md",
                    ),
                ],
            )

            logger.info(
                f"✅ INTERACTIVE COMPONENT {interactive_index}: Rendered controls panel '{component_config['title']}'"
            )
            return interactive_panel

        except Exception as e:
            logger.error(
                f"❌ INTERACTIVE COMPONENT {interactive_index}: Error creating controls: {e}"
            )
            return dmc.Paper(
                shadow="sm",
                radius="md",
                p="lg",
                withBorder=True,
                children=[
                    dmc.Title(f"Controls Error {interactive_index}", order=4, c="red"),
                    dmc.Text(f"Failed to generate controls: {str(e)}", c="red"),
                ],
            )

    # ============================================================================
    # CENTRALIZED EVENT LISTENER CALLBACKS
    # ============================================================================

    # Event listener for range slider changes (data filtering)
    @app.callback(
        Output("dashboard-event-store", "data", allow_duplicate=True),
        [
            Input({"type": "data-filter-range", "index": "revenue_range"}, "value"),
            Input({"type": "data-filter-range", "index": "users_range"}, "value"),
        ],
        State("dashboard-event-store", "data"),
        prevent_initial_call=True,
    )
    def update_event_store_from_range_sliders(revenue_range, users_range, current_event_state):
        """
        Central event listener for data filtering range slider changes.
        Updates the event store with new range values and marks them as changed.
        """
        from dash import callback_context

        ctx = callback_context
        if not ctx.triggered:
            return current_event_state

        # Determine which range slider triggered the callback
        trigger_id = ctx.triggered[0]["prop_id"]
        trigger_value = ctx.triggered[0]["value"]

        logger.info(f"🎛️ RANGE FILTER EVENT: {trigger_id} = {trigger_value}")

        # Update event state based on which range slider changed
        if "revenue_range" in trigger_id and revenue_range is not None:
            new_state = update_event_state(current_event_state, "revenue_range", revenue_range)
            logger.info(
                f"💰 EVENT STATE: Revenue range updated to ${revenue_range[0]:,} - ${revenue_range[1]:,}"
            )
            return new_state
        elif "users_range" in trigger_id and users_range is not None:
            new_state = update_event_state(current_event_state, "users_range", users_range)
            logger.info(
                f"👥 EVENT STATE: Users range updated to {users_range[0]:,} - {users_range[1]:,}"
            )
            return new_state

        return current_event_state

    # Event listener for dropdown changes (data filtering)
    @app.callback(
        Output("dashboard-event-store", "data", allow_duplicate=True),
        [
            Input({"type": "data-filter-dropdown", "index": "category_filter"}, "value"),
            Input({"type": "data-filter-dropdown", "index": "date_range"}, "value"),
        ],
        State("dashboard-event-store", "data"),
        prevent_initial_call=True,
    )
    def update_event_store_from_filter_dropdowns(category_filter, date_range, current_event_state):
        """
        Central event listener for data filtering dropdown changes.
        Updates the event store with new filter values and marks them as changed.
        """
        from dash import callback_context

        ctx = callback_context
        if not ctx.triggered:
            return current_event_state

        # Determine which dropdown triggered the callback
        trigger_id = ctx.triggered[0]["prop_id"]
        trigger_value = ctx.triggered[0]["value"]

        logger.info(f"🎛️ FILTER DROPDOWN EVENT: {trigger_id} = {trigger_value}")

        # Update event state based on which dropdown changed
        if "category_filter" in trigger_id and category_filter is not None:
            new_state = update_event_state(current_event_state, "category_filter", category_filter)
            logger.info(f"🔍 EVENT STATE: Category filter updated to {category_filter}")
            return new_state
        elif "date_range" in trigger_id and date_range is not None:
            new_state = update_event_state(current_event_state, "date_range", date_range)
            logger.info(f"📅 EVENT STATE: Date range filter updated to {date_range}")
            return new_state

        return current_event_state

    # Reactive component updates based on event changes
    @app.callback(
        Output("dummy-event-output", "children", allow_duplicate=True),
        Input("dashboard-event-store", "data"),
        prevent_initial_call=True,
    )
    def trigger_component_updates_from_events(event_state):
        """
        Central dispatcher that triggers component updates when events change.
        This callback listens to the event store and forces re-rendering of affected components.
        """
        if not event_state:
            return ""

        logger.info("🔄 EVENT DISPATCH: Processing event state changes")

        # Check what changed and log dependencies
        changed_events = []
        for control_id, state in event_state.items():
            if state.get("changed", False):
                changed_events.append(control_id)

        if not changed_events:
            logger.info("⏭️ EVENT DISPATCH: No changed events detected")
            return ""

        logger.info(f"📢 EVENT DISPATCH: Changed events: {changed_events}")

        # Log which components will be affected
        affected_components = set()
        for component_type, dependencies in COMPONENT_DEPENDENCIES.items():
            for changed_event in changed_events:
                if changed_event in dependencies:
                    affected_components.add(component_type)

        logger.info(f"🎯 EVENT DISPATCH: Components to update: {list(affected_components)}")

        # This dummy output triggers the component updates through the pattern matching system
        # The actual component updates happen in their individual MATCH callbacks
        return f"Event dispatch: {', '.join(changed_events)} at {time.strftime('%H:%M:%S')}"

    # Component completion tracker - updates when any component children change
    @app.callback(
        Output("loading-completion-tracker", "data"),
        [
            Input({"type": "metric-card", "index": ALL}, "children"),
            Input({"type": "chart-component", "index": ALL}, "children"),
            Input({"type": "interactive-component", "index": ALL}, "children"),
        ],
        prevent_initial_call=True,
    )
    def track_component_completion(metric_cards, chart_components, interactive_components):
        """Track when all components have finished loading/updating."""
        import time

        # Count total components that have content (non-empty children)
        total_components = 0
        loaded_components = 0

        # Check metric cards
        for card in metric_cards:
            total_components += 1
            if card and card != "Loading...":
                loaded_components += 1

        # Check chart components
        for chart in chart_components:
            total_components += 1
            if chart and chart != "Loading...":
                loaded_components += 1

        # Check interactive components
        for interactive in interactive_components:
            total_components += 1
            if interactive and interactive != "Loading...":
                loaded_components += 1

        logger.info(
            f"🔄 COMPLETION TRACKER: {loaded_components}/{total_components} components loaded"
        )

        return {
            "components_loaded": loaded_components,
            "total_components": total_components,
            "timestamp": time.time(),
            "all_loaded": loaded_components == total_components and total_components > 0,
        }

    # Hybrid dashboard loading indicator - show immediately on events, hide when components complete
    app.clientside_callback(
        """
        function(pathname, event_store, completion_data) {
            console.log('🔧 DASHBOARD LOADING INDICATOR: triggered', {pathname, event_store, completion_data});

            // Only show on dashboard pages
            if (!pathname || !pathname.startsWith('/dashboard/')) {
                return {"display": "none"};
            }

            // Get the context to see what triggered this callback
            var ctx = window.dash_clientside.callback_context;
            var triggered_id = ctx.triggered.length > 0 ? ctx.triggered[0].prop_id : '';
            console.log('🔧 TRIGGERED BY:', triggered_id);

            // If completion tracker indicates all components are loaded, hide indicator
            if (completion_data && completion_data.all_loaded && triggered_id === 'loading-completion-tracker.data') {
                console.log('✅ LOADING INDICATOR: All components loaded - hiding indicator');

                // Clear any existing timeout
                if (window.loadingIndicatorTimeout) {
                    clearTimeout(window.loadingIndicatorTimeout);
                }

                return {"display": "none"};
            }

            // If dashboard-event-store changed, show indicator immediately
            if (triggered_id === 'dashboard-event-store.data') {
                console.log('📊 LOADING INDICATOR: SHOWING IMMEDIATELY - event detected');

                // Clear any existing timeout
                if (window.loadingIndicatorTimeout) {
                    clearTimeout(window.loadingIndicatorTimeout);
                }

                // Show indicator
                var showStyle = {
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "8px"
                };

                // Fallback timeout (in case component tracking fails)
                window.loadingIndicatorTimeout = setTimeout(function() {
                    console.log('⏰ LOADING INDICATOR: Fallback timeout - hiding indicator');
                    var indicator = document.getElementById('dashboard-loading-indicator');
                    if (indicator) {
                        indicator.style.display = 'none';
                    }
                }, 5000);

                return showStyle;
            }

            // For initial page load, show briefly
            if (triggered_id === 'url.pathname' || triggered_id === '') {
                console.log('📊 LOADING INDICATOR: Showing for initial load');

                return {
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "8px"
                };
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output("dashboard-loading-indicator", "style"),
        [
            Input("url", "pathname"),
            Input("dashboard-event-store", "data"),
            Input("loading-completion-tracker", "data"),
        ],
        prevent_initial_call=False,
    )

    logger.info("✅ DASHBOARD CONTENT: All callbacks registered successfully")


def create_metric_card(metric):
    """Create a single metric card using dmc.Paper."""

    return dmc.Paper(
        shadow="sm",
        radius="md",
        p="lg",
        withBorder=True,
        style={
            "height": "150px",
            "display": "flex",
            "flexDirection": "column",
            "justifyContent": "space-between",
        },
        children=[
            # Header with icon and title
            dmc.Group(
                justify="space-between",
                align="center",
                children=[
                    dmc.Text(
                        metric["title"],
                        size="sm",
                        c="gray",
                        fw="bold",
                    ),
                    DashIconify(
                        icon=metric["icon"],
                        width=24,
                        height=24,
                        color=f"var(--mantine-color-{metric['color']}-6)",
                    ),
                ],
            ),
            # Main metric value
            dmc.Text(
                str(metric["value"]),
                size="xl",
                fw="bold",
                c=metric["color"],
                style={"fontSize": "2rem"},
            ),
            # Change indicator
            dmc.Group(
                justify="flex-start",
                align="center",
                gap="xs",
                children=[
                    DashIconify(
                        icon="mdi:trending-up",
                        width=16,
                        height=16,
                        color="var(--mantine-color-green-6)",
                    ),
                    dmc.Text(
                        metric["change"],
                        size="sm",
                        c="green",
                        fw="bold",
                    ),
                    dmc.Text(
                        "vs last month",
                        size="xs",
                        c="gray",
                    ),
                ],
            ),
        ],
    )


def create_login_prompt():
    """Create login prompt for unauthenticated users."""

    return dmc.Container(
        size="sm",
        style={"textAlign": "center", "paddingTop": "4rem"},
        children=[
            DashIconify(
                icon="mdi:lock",
                width=64,
                height=64,
                color="var(--mantine-color-gray-4)",
                style={"marginBottom": "1rem"},
            ),
            dmc.Title(
                "Authentication Required",
                order=3,
                mb="md",
                c="gray",
            ),
            dmc.Text(
                "Please log in to view dashboard content.",
                size="sm",
                c="gray",
                mb="lg",
            ),
            dmc.Button(
                "Go to Login",
                leftSection=DashIconify(icon="mdi:login", width=16),
                color="blue",
                size="md",
            ),
        ],
    )


logger.info("✅ DASHBOARD CONTENT: Module loaded successfully")
