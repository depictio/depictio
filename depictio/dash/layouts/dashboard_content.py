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
from depictio.dash.layouts.dashboard_export import create_standalone_html

# ============================================================================
# DASHBOARD METADATA CONFIGURATION
# ============================================================================
# Central metadata location - the only input required to render components

# RNA-seq data generation configuration
DATA_CONFIG = {
    "rows": 1000,  # 1K genes for fast development
    "categories": ["Control", "Treatment", "Timepoint_0h", "Timepoint_6h", "Timepoint_24h"],
    "metrics": {
        "deg_count": {"min": 500, "max": 2500, "format": "int"},
        "upregulated": {"min": 200, "max": 1200, "format": "int"},
        "downregulated": {"min": 200, "max": 1200, "format": "int"},
        "total_samples": {"min": 12, "max": 48, "format": "int"},
        "log2_fold_change": {"min": -5.0, "max": 5.0, "format": "float"},
        "p_value": {"min": 0.001, "max": 0.1, "format": "scientific"},
        "base_mean": {"min": 0, "max": 10000, "format": "int"},
    },
}

# RNA-seq interactive control configurations
INTERACTIVE_CONTROLS = [
    {
        "id": 0,
        "control_type": "range_slider",
        "field": "log2_fold_change",
        "label": "Log2 Fold Change",
        "min": -5.0,
        "max": 5.0,
        "step": 0.1,
        "format": "float",
        "marks": {-2: "-2", 0: "0", 2: "2"},
    },
    {
        "id": 1,
        "control_type": "range_slider",
        "field": "p_value",
        "label": "P-Value Threshold",
        "min": 0.001,
        "max": 0.1,
        "step": 0.001,
        "format": "scientific",
        "marks": {0.001: "0.001", 0.01: "0.01", 0.05: "0.05", 0.1: "0.1"},
    },
    {
        "id": 2,
        "control_type": "multi_select",
        "field": "sample_type",
        "label": "Sample Types",
        "options": ["Control", "Treatment", "Timepoint_0h", "Timepoint_6h", "Timepoint_24h"],
        "default": ["all"],
    },
    {
        "id": 3,
        "control_type": "dropdown",
        "field": "gene_biotype",
        "label": "Gene Biotype",
        "options": [
            {"label": "All Biotypes", "value": "all"},
            {"label": "Protein Coding", "value": "protein_coding"},
            {"label": "lncRNA", "value": "lncrna"},
            {"label": "miRNA", "value": "mirna"},
            {"label": "Pseudogene", "value": "pseudogene"},
        ],
        "default": "all",
    },
    {
        "id": 4,
        "control_type": "range_slider",
        "field": "base_mean",
        "label": "Base Mean Expression",
        "min": 0,
        "max": 10000,
        "step": 100,
        "format": "int",
        "marks": {0: "0", 1000: "1K", 5000: "5K", 10000: "10K"},
    },
    {
        "id": 5,
        "control_type": "dropdown",
        "field": "pathway",
        "label": "Pathway Enrichment",
        "options": [
            {"label": "All Pathways", "value": "all"},
            {"label": "Cell Cycle", "value": "cell_cycle"},
            {"label": "Metabolism", "value": "metabolism"},
            {"label": "Immune Response", "value": "immune_response"},
            {"label": "Signal Transduction", "value": "signal_transduction"},
        ],
        "default": "all",
    },
]

# Component dependency mapping - now uses field names dynamically
COMPONENT_DEPENDENCIES = {
    "metric": ["all"],  # Metrics affected by all filters
    "chart": ["all"],  # Charts affected by all filters
    "interactive": [],  # Interactive components don't depend on other controls
}

DASHBOARD_COMPONENTS = [
    # Interactive controls for filters
    {"type": "interactive", "index": 0, "title": "RNA-seq Analysis Filters", "position": "top"},
    # RNA-seq metrics cards
    {
        "type": "metric",
        "index": 0,
        "title": "Differentially Expressed Genes",
        "metric_key": "deg_count",
    },
    {"type": "metric", "index": 1, "title": "Upregulated Genes", "metric_key": "upregulated"},
    {"type": "metric", "index": 2, "title": "Downregulated Genes", "metric_key": "downregulated"},
    {"type": "metric", "index": 3, "title": "Total Samples", "metric_key": "total_samples"},
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
        "title": "Gene Expression Scatter",
        "chart_type": "scatter",
        "x_col": "log2_fold_change",
        "y_col": "base_mean",
    },
    {
        "type": "chart",
        "index": 1,
        "title": "DEG Count by Sample Type",
        "chart_type": "bar",
        "x_col": "category",
        "y_col": "deg_count",
    },
    {
        "type": "chart",
        "index": 2,
        "title": "P-Value Distribution",
        "chart_type": "box",
        "x_col": "category",
        "y_col": "p_value",
    },
    {
        "type": "chart",
        "index": 3,
        "title": "Fold Change Timeline",
        "chart_type": "line",
        "x_col": "date",
        "y_col": "log2_fold_change",
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
    """Create the initial state for the dashboard event store with dynamic filtering controls."""
    event_state = {}

    for control in INTERACTIVE_CONTROLS:
        control_id = f"control-{control['id']}"

        if control["control_type"] == "range_slider":
            # Initialize range sliders with min/max values
            event_state[control_id] = {
                "value": [control["min"], control["max"]],
                "timestamp": time.time(),
                "changed": False,
                "field": control["field"],
                "control_type": control["control_type"],
            }
        elif control["control_type"] == "multi_select":
            # Initialize multi-select with default
            event_state[control_id] = {
                "value": control.get("default", ["all"]),
                "timestamp": time.time(),
                "changed": False,
                "field": control["field"],
                "control_type": control["control_type"],
            }
        elif control["control_type"] == "dropdown":
            # Initialize dropdown with default
            event_state[control_id] = {
                "value": control.get("default", "all"),
                "timestamp": time.time(),
                "changed": False,
                "field": control["field"],
                "control_type": control["control_type"],
            }

    # Mark first control as changed to trigger initial render
    if event_state:
        first_key = list(event_state.keys())[0]
        event_state[first_key]["changed"] = True

    return event_state


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

    # Check if any control has changed (for "all" dependencies)
    if "all" in dependencies:
        # Check all dynamic controls
        for control_key, control_state in event_state.items():
            if control_key.startswith("control-") and control_state.get("changed", False):
                logger.info(
                    f"🔄 COMPONENT UPDATE: {component_type} updating due to {control_key} change"
                )
                return True
    else:
        # Check specific dependencies (if we ever add specific field dependencies)
        for dep in dependencies:
            for control_key, control_state in event_state.items():
                if control_state.get("field") == dep and control_state.get("changed", False):
                    logger.info(
                        f"🔄 COMPONENT UPDATE: {component_type} updating due to {control_key} change"
                    )
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
    Now supports dynamic control IDs with metadata preservation.

    Args:
        current_state: Current event state
        control_id: ID of the control that changed (format: "control-N")
        new_value: New value of the control

    Returns:
        dict: Updated event state
    """
    if not current_state:
        current_state = create_initial_event_state()

    # Reset all changed flags while preserving metadata
    updated_state = {}
    for key, state in current_state.items():
        updated_state[key] = {
            "value": state["value"],
            "timestamp": state["timestamp"],
            "changed": False,
            # Preserve metadata fields
            "field": state.get("field", "unknown"),
            "control_type": state.get("control_type", "unknown"),
        }

    # Update the changed control
    if control_id in updated_state:
        old_value = updated_state[control_id]["value"]
        if old_value != new_value:
            updated_state[control_id].update(
                {
                    "value": new_value,
                    "timestamp": time.time(),
                    "changed": True,
                }
            )
            field = updated_state[control_id].get("field", "unknown")
            logger.info(
                f"🎛️ EVENT UPDATE: {control_id} ({field}) changed from {old_value} → {new_value}"
            )
    else:
        # If control doesn't exist, create it (dynamic addition)
        logger.warning(
            f"⚠️ EVENT UPDATE: Control {control_id} not found in state, creating new entry"
        )
        updated_state[control_id] = {
            "value": new_value,
            "timestamp": time.time(),
            "changed": True,
            "field": "dynamic",
            "control_type": "unknown",
        }

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
    Now works with dynamic control configurations.

    Args:
        df: polars DataFrame to filter
        event_state: Current dashboard event state
        component_id: ID of component requesting filtering (for debugging)

    Returns:
        pl.DataFrame: Filtered DataFrame
    """
    if not event_state:
        return df

    logger.info(f"🔍 FILTER DEBUG [{component_id}]: Processing {len(event_state)} controls")

    filtered_df = df

    # Apply filters dynamically based on control configurations
    for control_key, control_state in event_state.items():
        if not control_key.startswith("control-"):
            continue

        field = control_state.get("field")
        control_type = control_state.get("control_type")
        value = control_state.get("value")

        logger.info(
            f"🔍 FILTER DEBUG [{component_id}]: {control_key} - field={field}, type={control_type}, value={value}"
        )

        # Debug the condition check
        is_range_slider = control_type == "range_slider"
        has_value = bool(value)
        is_list_of_two = isinstance(value, list) and len(value) == 2
        logger.info(
            f"🔍 CONDITION DEBUG [{component_id}]: {control_key} - is_range_slider={is_range_slider}, has_value={has_value}, is_list_of_two={is_list_of_two}"
        )

        if control_type == "range_slider" and value and isinstance(value, list) and len(value) == 2:
            # Apply range filter
            min_val, max_val = value
            column_name = field  # Map field to column name
            logger.info(
                f"🔍 FILTER DEBUG [{component_id}]: Range slider condition met - min={min_val}, max={max_val}"
            )

            if column_name in filtered_df.columns:
                filtered_df = filtered_df.filter(
                    (pl.col(column_name) >= min_val) & (pl.col(column_name) <= max_val)
                )
                logger.info(
                    f"🔍 DATA FILTER [{component_id}]: {field} range [{min_val:,} - {max_val:,}] → {len(filtered_df):,} rows"
                )
            else:
                logger.info(
                    f"🔍 FILTER DEBUG [{component_id}]: Column {column_name} not found in DataFrame"
                )

        elif control_type == "multi_select" and value:
            # Apply category filter
            if "all" not in value:
                column_name = field  # Map field to column name
                if column_name in filtered_df.columns:
                    before_filter = len(filtered_df)
                    filtered_df = filtered_df.filter(pl.col(column_name).is_in(value))
                    logger.info(
                        f"🔍 DATA FILTER [{component_id}]: {field} {value} → {before_filter:,} → {len(filtered_df):,} rows"
                    )

        elif control_type == "dropdown" and value and value != "all":
            # Apply date range or other dropdown filters
            if field == "date_range":
                if value == "last_7_days":
                    cutoff_date = datetime.now() - timedelta(days=7)
                    filtered_df = filtered_df.filter(pl.col("date") >= cutoff_date)
                    logger.info(
                        f"🔍 DATA FILTER [{component_id}]: Last 7 days → {len(filtered_df):,} rows"
                    )
                elif value == "last_30_days":
                    cutoff_date = datetime.now() - timedelta(days=30)
                    filtered_df = filtered_df.filter(pl.col("date") >= cutoff_date)
                    logger.info(
                        f"🔍 DATA FILTER [{component_id}]: Last 30 days → {len(filtered_df):,} rows"
                    )
                elif value == "last_90_days":
                    cutoff_date = datetime.now() - timedelta(days=90)
                    filtered_df = filtered_df.filter(pl.col("date") >= cutoff_date)
                    logger.info(
                        f"🔍 DATA FILTER [{component_id}]: Last 90 days → {len(filtered_df):,} rows"
                    )
        else:
            logger.info(
                f"🔍 FILTER DEBUG [{component_id}]: Control {control_key} not processed - type={control_type}, value={value}, value_len={len(value) if value else 'None'}"
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
    height = chart_config.get("chart_height", 450)  # Increased default height for full-width charts
    theme = chart_config.get("chart_theme", "plotly")

    logger.info(
        f"🔧 CHART GENERATION: Creating {chart_type} chart '{title}' (height={height}, theme={theme}) - using native Polars"
    )

    # Enhanced RNA-seq color palette
    rna_colors_primary = ["#2E7CD6", "#48BB78", "#ED8936", "#9F7AEA", "#F56565", "#38B2AC"]

    if chart_type == "scatter":
        # Enhanced scatter plot with size variation
        fig = px.scatter(
            df,
            x=x_col,
            y=y_col,
            title=title,
            height=height,
            template="plotly_white",  # Clean white background
            color_discrete_sequence=rna_colors_primary,
            opacity=0.8,
        )

        # Update scatter markers with better styling
        fig.update_traces(
            marker=dict(size=10, line=dict(width=1, color="white"), symbol="circle"),
            selector=dict(mode="markers"),
        )

        # Add statistical significance thresholds for RNA-seq with better styling
        if "log2_fold_change" in x_col or "base_mean" in y_col:
            # Add volcano plot thresholds if applicable
            if "log2_fold_change" in x_col:
                fig.add_vline(
                    x=1,
                    line_dash="dot",
                    line_color="#48BB78",
                    line_width=2,
                    annotation_text="FC > 2",
                    annotation_position="top left",
                    annotation=dict(font_size=11, font_color="#48BB78"),
                )
                fig.add_vline(
                    x=-1,
                    line_dash="dot",
                    line_color="#F56565",
                    line_width=2,
                    annotation_text="FC < -2",
                    annotation_position="top right",
                    annotation=dict(font_size=11, font_color="#F56565"),
                )
            if "p_value" in y_col:
                fig.add_hline(
                    y=0.05,
                    line_dash="dot",
                    line_color="#9F7AEA",
                    line_width=2,
                    annotation_text="p = 0.05",
                    annotation_position="bottom right",
                    annotation=dict(font_size=11, font_color="#9F7AEA"),
                )

    elif chart_type == "bar":
        # Aggregate data for bar chart using polars directly
        agg_df = df.group_by(x_col).agg(pl.col(y_col).mean())
        fig = px.bar(
            agg_df,
            x=x_col,
            y=y_col,
            title=title,
            height=height,
            template="plotly_white",
            color_discrete_sequence=rna_colors_primary,
            text_auto=".2f",  # Show values on bars
        )

        # Update bar styling with rounded corners effect
        fig.update_traces(
            marker=dict(line=dict(width=0), opacity=0.9),
            textfont_size=11,
            textangle=0,
            textposition="outside",
            cliponaxis=False,
        )

    elif chart_type == "box":
        # Enhanced box plot with violin overlay option
        fig = px.box(
            df,
            x=x_col,
            y=y_col,
            title=title,
            height=height,
            template="plotly_white",
            color_discrete_sequence=rna_colors_primary,
            notched=True,  # Show confidence interval
            points="outliers",  # Show outlier points
        )

        # Update box plot styling
        fig.update_traces(
            marker=dict(size=6, opacity=0.7, line=dict(width=1, color="white")),
            line=dict(width=2),
            fillcolor="rgba(0,0,0,0)",
            opacity=0.9,
        )

    elif chart_type == "line":
        # Enhanced line chart with smooth curves and markers
        fig = px.line(
            df,
            x=x_col,
            y=y_col,
            title=title,
            height=height,
            template="plotly_white",
            color_discrete_sequence=rna_colors_primary,
            line_shape="spline",  # Smooth curves
            render_mode="svg",  # Better rendering quality
        )

        # Update line styling with markers
        fig.update_traces(
            mode="lines+markers",
            line=dict(width=3),
            marker=dict(size=8, symbol="circle", line=dict(width=2, color="white")),
        )

    else:
        # Default enhanced scatter
        fig = px.scatter(
            df,
            x=x_col,
            y=y_col,
            title=title,
            height=height,
            template="plotly_white",
            color_discrete_sequence=rna_colors_primary,
            opacity=0.85,
        )

        fig.update_traces(
            marker=dict(size=12, line=dict(width=1.5, color="white"), symbol="diamond")
        )

    # Enhanced modern layout with better typography and spacing
    layout_updates = {
        "font": dict(
            size=13,
            family="Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
            color="#2D3748",
        ),
        "margin": dict(l=80, r=80, t=100, b=80),  # Symmetric margins for centered full-width charts
        "title": dict(
            text=f"<b>{title}</b>",  # Bold title
            font=dict(
                size=22,  # Larger title for full-width charts
                color="#1A365D",
                family="Inter, -apple-system, BlinkMacSystemFont, sans-serif",
            ),
            x=0.5,
            xanchor="center",
            y=0.98,
            yanchor="top",
        ),
        "xaxis": dict(
            title_font=dict(size=14, color="#4A5568"),
            tickfont=dict(size=11, color="#718096"),
            gridcolor="rgba(203, 213, 224, 0.4)",
            gridwidth=1,
            zeroline=True,
            zerolinecolor="rgba(203, 213, 224, 0.8)",
            zerolinewidth=2,
            showline=True,
            linewidth=1,
            linecolor="rgba(203, 213, 224, 0.8)",
            mirror=False,
            ticks="outside",
            ticklen=4,
            tickcolor="rgba(203, 213, 224, 0.5)",
        ),
        "yaxis": dict(
            title_font=dict(size=14, color="#4A5568"),
            tickfont=dict(size=11, color="#718096"),
            gridcolor="rgba(203, 213, 224, 0.4)",
            gridwidth=1,
            zeroline=True,
            zerolinecolor="rgba(203, 213, 224, 0.8)",
            zerolinewidth=2,
            showline=True,
            linewidth=1,
            linecolor="rgba(203, 213, 224, 0.8)",
            mirror=False,
            ticks="outside",
            ticklen=4,
            tickcolor="rgba(203, 213, 224, 0.5)",
        ),
        "hoverlabel": dict(
            bgcolor="rgba(255, 255, 255, 0.95)",
            bordercolor="rgba(0, 0, 0, 0.1)",
            font=dict(size=12, family="Inter, -apple-system, sans-serif", color="#2D3748"),
            align="left",
        ),
        "plot_bgcolor": "#FAFAFA",  # Very light gray background
        "paper_bgcolor": "rgba(255, 255, 255, 0)",
        "showlegend": True,
        "legend": dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(255, 255, 255, 0.8)",
            bordercolor="rgba(203, 213, 224, 0.5)",
            borderwidth=1,
            font=dict(size=11),
        ),
        "hovermode": "closest",
        "dragmode": "pan",  # Enable panning by default
    }

    # Add subtle animation
    layout_updates["transition"] = {"duration": 500, "easing": "cubic-in-out"}

    fig.update_layout(**layout_updates)

    # Custom modebar buttons configuration (unused for now)

    # Add range slider for time series data
    if chart_type == "line" and "date" in x_col.lower():
        fig.update_xaxes(
            rangeslider_visible=True,
            rangeslider_thickness=0.1,
            rangeslider_bgcolor="rgba(203, 213, 224, 0.2)",
            rangeslider_bordercolor="rgba(203, 213, 224, 0.4)",
            rangeslider_borderwidth=1,
        )

    # Enable spike lines for better data reading
    fig.update_xaxes(
        showspikes=True,
        spikecolor="rgba(0,0,0,0.2)",
        spikesnap="cursor",
        spikemode="across",
        spikethickness=1,
    )
    fig.update_yaxes(
        showspikes=True,
        spikecolor="rgba(0,0,0,0.2)",
        spikethickness=1,
        spikedash="dot",
        spikemode="across",
    )

    logger.info(
        f"✅ CHART GENERATION: Created enhanced {chart_type} chart with {len(df)} data points"
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
        logger.info("📊 MEMOIZING CACHE: Loading dataframe (will be cached for 15 minutes)")
        return get_cached_dataframe()

    # Cache figure generation for 5 minutes
    @flask_cache.memoize(timeout=300)
    def create_cached_chart_figure(df_shape, config_str):
        """Cached wrapper for chart figure generation."""
        logger.info("📊 MEMOIZING CACHE: Generating figure (will be cached for 5 minutes)")
        # Reconstruct the dataframe and config
        # In production, you'd want to pass serializable parameters
        df = get_cached_dataframe()
        import json

        config = json.loads(config_str)
        return create_chart_figure(df, config)

    # Make memoized functions accessible to callbacks
    app.get_cached_dataframe_with_memoize = get_cached_dataframe_with_memoize
    app.create_cached_chart_figure = create_cached_chart_figure

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

        # Create filter controls for left panel (1/4)
        filter_controls = []
        for comp in components:
            if comp["type"] == "interactive" and comp.get("position") == "top":
                logger.info(f"🚨 DEBUG: Creating interactive container for index {comp['index']}")
                filter_controls.append(
                    html.Div(
                        html.Div(
                            "Loading interactive filters...",
                            style={"height": "120px", "textAlign": "center", "paddingTop": "50px"},
                        ),
                        id={"type": "interactive-component", "index": comp["index"]},
                        style={"marginBottom": "16px"},
                    )
                )
                logger.info(
                    f"✅ DEBUG: Interactive container created with ID: {{'type': 'interactive-component', 'index': {comp['index']}}}"
                )

        # Create containers for metric cards and charts
        metric_containers = []
        chart_containers = []

        for comp in components:
            if comp["type"] == "metric":
                # Create standard container for metric cards
                metric_containers.append(
                    html.Div(
                        id=f"metric-{comp['index']}",
                        style={
                            "width": "100%",
                            "height": "100%",
                            "position": "relative",
                        },
                        children=[
                            # Content container that gets replaced by callback
                            html.Div(
                                "Loading RNA-seq metrics...",
                                id={"type": "metric-card", "index": comp["index"]},
                                style={
                                    "width": "100%",
                                    "height": "100%",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "backgroundColor": "var(--app-surface-color, #ffffff)",
                                    "borderRadius": "8px",
                                    "boxShadow": "0 1px 3px rgba(0,0,0,0.1)",
                                    "boxSizing": "border-box",
                                },
                            ),
                        ],
                    )
                )
            elif comp["type"] == "chart":
                # Create standard container for chart components
                chart_containers.append(
                    html.Div(
                        id=f"chart-{comp['index']}",
                        style={
                            "width": "100%",
                            "height": "100%",
                            "position": "relative",
                        },
                        children=[
                            # Content container that gets replaced by callback
                            html.Div(
                                "Loading RNA-seq visualization...",
                                id={"type": "chart-component", "index": comp["index"]},
                                style={
                                    "width": "100%",
                                    "height": "100%",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "backgroundColor": "var(--app-surface-color, #ffffff)",
                                    "borderRadius": "8px",
                                    "boxShadow": "0 1px 3px rgba(0,0,0,0.1)",
                                    "boxSizing": "border-box",
                                },
                            ),
                        ],
                    )
                )

        # Use flexbox layout for better sticky positioning support
        containers.append(
            dmc.Container(
                fluid=True,
                p="md",
                style={
                    "display": "flex",
                    "gap": "1rem",
                    "alignItems": "flex-start",
                    "flexWrap": "wrap",
                },
                children=[
                    # Filters panel - sticky sidebar
                    html.Div(
                        children=[
                            dmc.Paper(
                                children=[
                                    dmc.Group(
                                        children=[
                                            DashIconify(icon="mdi:filter-variant", width=20),
                                            dmc.Title("Filters", order=4),
                                        ],
                                        gap="xs",
                                        mb="md",
                                    ),
                                    dmc.Stack(children=filter_controls, gap="sm"),
                                ],
                                p="md",
                                shadow="sm",
                                radius="md",
                                withBorder=True,
                                style={
                                    "backgroundColor": "var(--app-surface-color, #ffffff)",
                                    "maxHeight": "calc(100vh - 4rem)",
                                    "overflowY": "auto",
                                    "overflowX": "hidden",
                                },
                            )
                        ],
                        className="filters-sidebar",
                        style={
                            "position": "sticky",
                            "top": "0px",
                            "width": "300px",
                            "minWidth": "280px",
                            "flexShrink": 0,
                            "height": "100vh",
                            "overflowY": "auto",
                            "zIndex": 10,
                        },
                    ),
                    # Main content area - flexible
                    html.Div(
                        style={
                            "flex": "1",
                            "minWidth": "0",  # Allow shrinking
                        },
                        children=[
                            # Metrics section with container
                            dmc.Paper(
                                children=[
                                    dmc.Group(
                                        children=[
                                            DashIconify(
                                                icon="material-symbols:analytics", width=20
                                            ),
                                            dmc.Title("Metrics Overview", order=4),
                                        ],
                                        gap="xs",
                                        mb="md",
                                    ),
                                    dmc.Grid(
                                        children=[
                                            dmc.GridCol(
                                                span=3,
                                                children=metric_containers[i]
                                                if i < len(metric_containers)
                                                else [],
                                            )
                                            for i in range(4)  # 4 metric cards in a row
                                        ],
                                    ),
                                ],
                                p="md",
                                shadow="sm",
                                radius="md",
                                withBorder=True,
                                mb="md",
                                style={
                                    "backgroundColor": "var(--app-surface-color, #ffffff)",
                                },
                                id="metrics-section",
                            ),
                            # Charts section with container
                            dmc.Paper(
                                children=[
                                    dmc.Group(
                                        children=[
                                            DashIconify(
                                                icon="material-symbols:bar-chart", width=20
                                            ),
                                            dmc.Title("Visualizations", order=4),
                                        ],
                                        gap="xs",
                                        mb="md",
                                    ),
                                    dmc.Stack(
                                        id="dashboard-charts-stack",
                                        children=chart_containers
                                        if chart_containers
                                        else [
                                            dmc.Text(
                                                "No charts available",
                                                style={"textAlign": "center", "padding": "2rem"},
                                                c="gray",
                                            )
                                        ],
                                        gap="md",
                                        style={"minHeight": "400px", "width": "100%"},
                                    ),
                                ],
                                p="md",
                                shadow="sm",
                                radius="md",
                                withBorder=True,
                                style={
                                    "backgroundColor": "var(--app-surface-color, #ffffff)",
                                },
                                id="charts-section",
                            ),
                        ],
                    ),
                ],
            )
        )

        logger.info(f"✅ DASHBOARD CONTENT: Created {len(components)} component containers")

        # Add event store for centralized state management and export functionality
        containers.extend(
            [
                dcc.Store(id="dashboard-event-store", data=create_initial_event_state()),
                dcc.Store(
                    id="pending-changes-store",
                    data={"has_pending_changes": False, "pending_controls": {}},
                ),
                html.Div(id="dummy-event-output"),  # Dummy output for event callbacks
                html.Div(id="dummy-anchor-output"),  # Dummy output for anchor navigation
                dcc.Download(
                    id={"type": "dashboard-export-download", "dashboard_id": dashboard_id}
                ),
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

        # TEMPORARY FIX: Always render components until we debug the conditional logic
        logger.info(f"🔄 METRIC CARD {metric_index}: Rendering (debugging mode - always render)")
        logger.info(f"🔍 DEBUG: trigger_id = {trigger_id}")
        logger.info(f"🔍 DEBUG: event_state = {event_state}")

        # Check what should_component_update would return
        should_update = should_component_update("metric", event_state, trigger_id)
        logger.info(f"🔍 DEBUG: should_component_update returned {should_update}")

        logger.info(f"⏱️ METRIC CARD {metric_index}: Starting processing")

        # Get base dataframe and apply current filters
        base_df = app.get_cached_dataframe_with_memoize()
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

        # Icon mapping based on RNA-seq metric type
        icon_mapping = {
            "deg_count": "mdi:dna",
            "upregulated": "mdi:trending-up",
            "downregulated": "mdi:trending-down",
            "total_samples": "mdi:test-tube",
            "log2_fold_change": "mdi:delta",
            "p_value": "mdi:sigma",
            "base_mean": "mdi:chart-scatter-plot",
            # Legacy business metrics (fallback)
            "users": "mdi:account-group",
            "revenue": "mdi:currency-usd",
            "conversion_rate": "mdi:chart-line",
            "sessions": "mdi:monitor-eye",
        }

        # Color mapping based on RNA-seq metric type
        color_mapping = {
            "deg_count": "blue",
            "upregulated": "red",
            "downregulated": "green",
            "total_samples": "orange",
            "log2_fold_change": "purple",
            "p_value": "yellow",
            "base_mean": "gray",
            # Legacy business metrics (fallback)
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

        # TEMPORARY FIX: Always render components until we debug the conditional logic
        logger.info(f"🔄 CHART COMPONENT {chart_index}: Rendering (debugging mode - always render)")
        logger.info(f"🔍 DEBUG: trigger_id = {trigger_id}")
        logger.info(f"🔍 DEBUG: event_state = {event_state}")

        # Check what should_component_update would return
        should_update = should_component_update("chart", event_state, trigger_id)
        logger.info(f"🔍 DEBUG: should_component_update returned {should_update}")

        logger.info(f"⏱️ CHART COMPONENT {chart_index}: Starting processing")

        # Get base dataframe and apply current filters
        base_df = app.get_cached_dataframe_with_memoize()
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
                event_state.get("chart_height", {}).get("value", 450) if event_state else 450
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

            # Create chart component with Plotly graph and fullscreen button
            chart = html.Div(
                style={
                    "width": "100%",
                    "height": "100%",
                    "position": "relative",
                },
                children=[
                    dmc.Paper(
                        shadow="sm",
                        radius="md",
                        p="lg",
                        withBorder=True,
                        style={
                            "width": "100%",
                            "height": "100%",
                            "boxSizing": "border-box",
                            "overflow": "hidden",
                        },
                        children=[
                            # Fullscreen button (hidden by default, visible on hover)
                            html.Button(
                                DashIconify(icon="mdi:fullscreen", width=18),
                                id={"type": "chart-fullscreen-btn", "index": chart_index},
                                n_clicks=0,
                                style={
                                    "position": "absolute",
                                    "top": "8px",
                                    "right": "8px",
                                    "background": "rgba(0,0,0,0.7)",
                                    "color": "white",
                                    "border": "none",
                                    "borderRadius": "4px",
                                    "width": "32px",
                                    "height": "32px",
                                    "cursor": "pointer",
                                    "zIndex": 1000,
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "opacity": "0",
                                    "transition": "opacity 0.2s ease",
                                },
                                className="chart-fullscreen-btn",
                            ),
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
        prevent_initial_call=False,  # Allow initial render to fix Loading... issue
        # background=True,  # Temporarily disabled to debug loading issue
    )
    def render_single_interactive_component(component_id, local_store):
        """
        Render a single interactive component - each component has its own callback.
        This is called individually for EACH interactive component.
        """
        logger.info(f"🚨 DEBUG: Interactive callback triggered with component_id={component_id}")

        if not component_id or "index" not in component_id:
            logger.error(f"❌ INTERACTIVE: Invalid component_id: {component_id}")
            return html.Div("Invalid Component ID")

        interactive_index = component_id["index"]
        logger.info(
            f"🔄 INTERACTIVE COMPONENT {interactive_index}: Individual rendering (non-background)"
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

        # Create data filtering controls panel dynamically
        try:
            # Build controls dynamically from configuration
            control_elements = []

            for control_config in INTERACTIVE_CONTROLS:
                control_id = control_config["id"]
                control_type = control_config["control_type"]

                if control_type == "range_slider":
                    # Create range slider control
                    control_elements.append(
                        dmc.GridCol(
                            span=12,  # Full width - 1 component per row
                            children=[
                                dmc.Text(control_config["label"], size="sm", fw="bold", mb="xs"),
                                dmc.RangeSlider(
                                    id={
                                        "type": "interactive-control",
                                        "index": control_id,
                                        "field": control_config["field"],
                                    },
                                    min=control_config["min"],
                                    max=control_config["max"],
                                    step=control_config.get("step", 100),
                                    value=(control_config["min"], control_config["max"]),
                                    marks=[
                                        {
                                            "value": control_config["min"],
                                            "label": (
                                                f"${control_config['min']:,}"
                                                if control_config.get("format") == "currency"
                                                else f"{control_config['min']:,}"
                                            ),
                                        },
                                        {
                                            "value": control_config["max"],
                                            "label": (
                                                f"${control_config['max']:,}"
                                                if control_config.get("format") == "currency"
                                                else f"{control_config['max']:,}"
                                            ),
                                        },
                                    ],
                                    thumbSize=16,
                                    styles={
                                        "track": {
                                            "backgroundColor": "var(--app-border-color, #ddd)"
                                        },
                                        "bar": {"backgroundColor": "var(--mantine-color-blue-6)"},
                                        "thumb": {"borderColor": "var(--mantine-color-blue-6)"},
                                    },
                                ),
                            ],
                        )
                    )

                elif control_type == "multi_select":
                    # Create multi-select dropdown
                    options = [{"label": "All", "value": "all"}] + [
                        {"label": opt, "value": opt} for opt in control_config["options"]
                    ]
                    control_elements.append(
                        dmc.GridCol(
                            span=12,  # Full width - 1 component per row
                            children=[
                                dmc.Text(control_config["label"], size="sm", fw="bold", mb="xs"),
                                dmc.MultiSelect(
                                    id={
                                        "type": "interactive-control",
                                        "index": control_id,
                                        "field": control_config["field"],
                                    },
                                    data=[
                                        {"value": opt["value"], "label": opt["label"]}
                                        for opt in options
                                    ],
                                    value=control_config.get("default", ["all"]),
                                    placeholder=f"Select {control_config['label'].lower()}...",
                                    searchable=True,
                                    clearable=True,
                                    styles={
                                        "input": {"borderColor": "var(--app-border-color, #ddd)"},
                                        "dropdown": {
                                            "borderColor": "var(--app-border-color, #ddd)"
                                        },
                                        "label": {"color": "var(--app-text-color, #000)"},
                                    },
                                ),
                            ],
                        )
                    )

                elif control_type == "dropdown":
                    # Create single-select dropdown
                    control_elements.append(
                        dmc.GridCol(
                            span=12,  # Full width - 1 component per row
                            children=[
                                dmc.Text(control_config["label"], size="sm", fw="bold", mb="xs"),
                                dmc.Select(
                                    id={
                                        "type": "interactive-control",
                                        "index": control_id,
                                        "field": control_config["field"],
                                    },
                                    data=[
                                        {"value": opt["value"], "label": opt["label"]}
                                        for opt in control_config["options"]
                                    ],
                                    value=control_config.get("default", "all"),
                                    clearable=False,
                                    searchable=True,
                                    styles={
                                        "input": {"borderColor": "var(--app-border-color, #ddd)"},
                                        "dropdown": {
                                            "borderColor": "var(--app-border-color, #ddd)"
                                        },
                                        "label": {"color": "var(--app-text-color, #000)"},
                                    },
                                ),
                            ],
                        )
                    )

            interactive_panel = dmc.Grid(
                control_elements,
                gutter="lg",
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

    # Unified event listener for ALL interactive controls using MATCH pattern
    @app.callback(
        Output("pending-changes-store", "data", allow_duplicate=True),
        Input({"type": "interactive-control", "index": ALL, "field": ALL}, "value"),
        State("pending-changes-store", "data"),
        prevent_initial_call=True,
    )
    def track_pending_control_changes(control_values, pending_state):
        """
        Track pending changes from ALL interactive controls using pattern matching.
        This unified callback handles any number of dynamic controls.
        """
        import json

        from dash import callback_context

        ctx = callback_context
        if not ctx.triggered:
            return pending_state

        # Parse the triggered control's ID
        trigger_id_str = ctx.triggered[0]["prop_id"]
        trigger_value = ctx.triggered[0]["value"]

        # Extract the control info from the trigger ID
        try:
            # Parse the pattern-matched ID
            trigger_id_json = trigger_id_str.split(".value")[0]
            trigger_id = json.loads(trigger_id_json)
            control_index = trigger_id["index"]
            control_field = trigger_id["field"]

            logger.info(
                f"📋 PENDING CHANGE: Control {control_index} ({control_field}) = {trigger_value}"
            )
        except Exception as e:
            logger.error(f"Failed to parse trigger ID: {e}")
            return pending_state

        # Get initial state to check if this is a real change
        initial_defaults = create_initial_event_state()
        control_key = f"control-{control_index}"

        # Check if value matches initial default
        if control_key in initial_defaults:
            initial_value = initial_defaults[control_key]["value"]
            if trigger_value == initial_value:
                logger.info(
                    f"⏭️ PENDING SKIP: Control {control_index} matches initial default, ignoring"
                )
                return pending_state

        # Update pending changes
        updated_pending = (
            pending_state.copy()
            if pending_state
            else {"has_pending_changes": False, "pending_controls": {}}
        )
        updated_pending["has_pending_changes"] = True

        # Store the change with control metadata
        updated_pending["pending_controls"][control_key] = {
            "value": trigger_value,
            "field": control_field,
            "index": control_index,
        }

        logger.info(f"✅ PENDING: Control {control_index} ({control_field}) staged for update")

        return updated_pending

    # Callback to enable/disable Apply button based on pending changes
    @app.callback(
        [
            Output("apply-updates-button", "disabled"),
            Output("apply-updates-button", "children"),
        ],
        Input("pending-changes-store", "data"),
        prevent_initial_call=False,
    )
    def update_apply_button_state(pending_state):
        """
        Enable/disable the Apply button based on whether there are pending changes.
        Also update button text to indicate pending changes count.
        """
        if not pending_state or not pending_state.get("has_pending_changes"):
            return True, "Apply Updates"  # Disabled with default text

        pending_count = len(pending_state.get("pending_controls", {}))
        button_text = f"Apply Updates ({pending_count} changes)"

        logger.info(f"🔘 APPLY BUTTON: Enabled with {pending_count} pending changes")
        return False, button_text  # Enabled with change count

    # Apply button callback - applies pending changes to event store
    @app.callback(
        [
            Output("dashboard-event-store", "data", allow_duplicate=True),
            Output("pending-changes-store", "data", allow_duplicate=True),
        ],
        Input("apply-updates-button", "n_clicks"),
        [
            State("pending-changes-store", "data"),
            State("dashboard-event-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def apply_pending_changes(n_clicks, pending_state, current_event_state):
        """
        Apply all pending changes to the event store when Apply button is clicked.
        This triggers component updates and resets pending changes.
        """
        if not n_clicks or not pending_state or not pending_state.get("has_pending_changes"):
            from dash import no_update

            return no_update, no_update

        logger.info(
            f"🚀 APPLY CHANGES: Applying {len(pending_state.get('pending_controls', {}))} pending changes"
        )

        # Apply all pending changes to the event store
        updated_event_state = (
            current_event_state.copy() if current_event_state else create_initial_event_state()
        )
        pending_controls = pending_state.get("pending_controls", {})

        logger.info(f"🔍 DEBUG APPLY: Current event state keys: {list(updated_event_state.keys())}")
        logger.info(f"🔍 DEBUG APPLY: Pending controls keys: {list(pending_controls.keys())}")

        for control_key, control_data in pending_controls.items():
            # Handle both old format (direct value) and new format (with metadata)
            if isinstance(control_data, dict) and "value" in control_data:
                control_value = control_data["value"]
                field = control_data.get("field", "unknown")
            else:
                control_value = control_data  # Backward compatibility
                field = "legacy"

            old_state = updated_event_state.get(control_key, {}).get("value", "N/A")
            updated_event_state = update_event_state(
                updated_event_state, control_key, control_value
            )

            # FORCE the changed flag to true for all applied controls - this ensures components update
            if control_key in updated_event_state:
                updated_event_state[control_key]["changed"] = True
                updated_event_state[control_key]["timestamp"] = time.time()
                logger.info(
                    f"🔧 FORCED UPDATE: {control_key} marked as changed for component refresh"
                )

            logger.info(f"✅ APPLIED: {control_key} ({field}) = {old_state} → {control_value}")

        # Log final state for debugging
        changed_controls = [k for k, v in updated_event_state.items() if v.get("changed", False)]
        logger.info(f"🔍 DEBUG APPLY: Controls marked as changed: {changed_controls}")

        # Reset pending changes
        reset_pending_state = {"has_pending_changes": False, "pending_controls": {}}

        logger.info("🎯 APPLY COMPLETE: All pending changes applied to event store")
        return updated_event_state, reset_pending_state

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
            if control_id.startswith("control-") and state.get("changed", False):
                field = state.get("field", "unknown")
                changed_events.append(f"{control_id} ({field})")

        if not changed_events:
            logger.info("⏭️ EVENT DISPATCH: No changed events detected")
            return ""

        logger.info(f"📢 EVENT DISPATCH: Changed controls: {changed_events}")

        # Log which components will be affected - all components react to dynamic controls
        affected_components = []
        for component_type, dependencies in COMPONENT_DEPENDENCIES.items():
            if "all" in dependencies or dependencies:  # Either explicit "all" or any dependencies
                affected_components.append(component_type)

        logger.info(f"🎯 EVENT DISPATCH: Components to update: {affected_components}")

        # This dummy output triggers the component updates through the pattern matching system
        # The actual component updates happen in their individual MATCH callbacks
        return f"Dynamic controls updated: {len(changed_events)} controls at {time.strftime('%H:%M:%S')}"

    # Simple fullscreen toggle callback
    app.clientside_callback(
        """
        function(n_clicks, button_id) {
            if (!n_clicks) {
                return window.dash_clientside.no_update;
            }

            console.log('Fullscreen button clicked:', button_id);

            // Find the button using the event target (much simpler)
            const button = document.activeElement;
            console.log('Active button:', button);

            if (!button || button.tagName !== 'BUTTON') {
                console.error('Could not find button element');
                return window.dash_clientside.no_update;
            }

            // The button is inside the Paper container - find it by going up the parent chain
            let paper = button.parentElement;
            console.log('Button parent:', paper);

            // The Paper container should have the style position: relative that we set
            while (paper && !paper.style.position) {
                paper = paper.parentElement;
                console.log('Checking parent:', paper);
            }

            console.log('Found paper container:', paper);

            if (!paper) {
                console.error('Could not find chart container - using button parent as fallback');
                paper = button.parentElement;
            }

            // Toggle fullscreen
            if (paper.classList.contains('chart-fullscreen')) {
                // Exit fullscreen
                console.log('Exiting fullscreen');
                paper.classList.remove('chart-fullscreen');

                // Reset all styles to original state
                paper.style.cssText = paper.getAttribute('data-original-style') || 'position: relative;';

                // Reset button position
                button.style.position = 'absolute';
                button.style.top = '8px';
                button.style.right = '8px';

                // Reset body overflow
                document.body.style.overflow = '';

                // Force graph resize with explicit dimension restoration
                setTimeout(() => {
                    const graphs = paper.querySelectorAll('.js-plotly-plot');
                    graphs.forEach((graph, index) => {
                        // Get stored original dimensions
                        const originalWidth = paper.getAttribute(`data-graph-${index}-width`);
                        const originalHeight = paper.getAttribute(`data-graph-${index}-height`);

                        console.log(`Restoring graph ${index} to original size:`, originalWidth, 'x', originalHeight);

                        // Clear all inline dimensions first
                        graph.style.cssText = graph.style.cssText.replace(/width\\s*:[^;]*(;|$)/g, '').replace(/height\\s*:[^;]*(;|$)/g, '');

                        // Clear parent dimensions
                        let parent = graph.parentElement;
                        while (parent && parent !== paper) {
                            parent.style.cssText = parent.style.cssText.replace(/width\\s*:[^;]*(;|$)/g, '').replace(/height\\s*:[^;]*(;|$)/g, '');
                            parent = parent.parentElement;
                        }

                        // Set explicit dimensions if we have stored values
                        if (originalWidth && originalHeight) {
                            graph.style.width = originalWidth + 'px';
                            graph.style.height = originalHeight + 'px';
                            console.log(`Set explicit dimensions: ${originalWidth}px x ${originalHeight}px`);
                        }

                        // Force relayout with explicit dimensions
                        if (window.Plotly) {
                            const update = {
                                'xaxis.autorange': true,
                                'yaxis.autorange': true,
                                autosize: false  // Disable autosize to respect explicit dimensions
                            };

                            if (originalWidth && originalHeight) {
                                update.width = parseInt(originalWidth);
                                update.height = parseInt(originalHeight);
                            }

                            window.Plotly.relayout(graph, update).then(() => {
                                window.Plotly.Plots.resize(graph);
                            });
                        }
                    });
                }, 50);

                // Additional resize after longer delay
                setTimeout(() => {
                    const graphs = paper.querySelectorAll('.js-plotly-plot');
                    graphs.forEach((graph, index) => {
                        if (window.Plotly) {
                            console.log(`Final resize attempt for graph ${index}, current size:`, graph.offsetWidth, 'x', graph.offsetHeight);
                            window.Plotly.Plots.resize(graph);
                        }
                    });
                }, 500);

            } else {
                // Enter fullscreen
                console.log('Entering fullscreen');

                // Store original styles AND graph dimensions before modifying
                paper.setAttribute('data-original-style', paper.style.cssText);

                // Store original graph dimensions (always capture current state)
                const graphs = paper.querySelectorAll('.js-plotly-plot');
                graphs.forEach((graph, index) => {
                    const rect = graph.getBoundingClientRect();
                    paper.setAttribute(`data-graph-${index}-width`, rect.width);
                    paper.setAttribute(`data-graph-${index}-height`, rect.height);
                    console.log(`Storing graph ${index} current size before fullscreen:`, rect.width, 'x', rect.height);
                    console.log(`Graph ${index} current style:`, graph.style.cssText);
                });

                paper.classList.add('chart-fullscreen');
                paper.style.position = 'fixed';
                paper.style.top = '0';
                paper.style.left = '0';
                paper.style.width = '100vw';
                paper.style.height = '100vh';
                paper.style.zIndex = '9999';
                paper.style.background = 'var(--mantine-color-body, white)';
                paper.style.margin = '0';
                paper.style.boxSizing = 'border-box';

                document.body.style.overflow = 'hidden';

                // Force graph resize for fullscreen - more aggressive approach
                setTimeout(() => {
                    graphs.forEach(graph => {
                        console.log('Resizing graph for fullscreen, current dimensions:', graph.offsetWidth, 'x', graph.offsetHeight);

                        // Set graph to take full container size in fullscreen
                        graph.style.width = '100%';
                        graph.style.height = 'calc(100vh - 100px)';  // Account for padding and title

                        if (window.Plotly) {
                            // Re-enable autosize for fullscreen mode
                            window.Plotly.relayout(graph, {
                                autosize: true,
                                'xaxis.autorange': true,
                                'yaxis.autorange': true,
                                width: null,
                                height: null
                            }).then(() => {
                                console.log('Plotly relayout complete, now calling resize');
                                window.Plotly.Plots.resize(graph);
                                console.log('After resize, graph dimensions:', graph.offsetWidth, 'x', graph.offsetHeight);
                            });
                        }
                    });
                }, 100);

                // Additional resize attempt
                setTimeout(() => {
                    graphs.forEach(graph => {
                        if (window.Plotly) {
                            console.log('Second resize attempt for fullscreen');
                            window.Plotly.Plots.resize(graph);
                        }
                    });
                }, 300);
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output({"type": "chart-fullscreen-btn", "index": MATCH}, "n_clicks"),
        Input({"type": "chart-fullscreen-btn", "index": MATCH}, "n_clicks"),
        State({"type": "chart-fullscreen-btn", "index": MATCH}, "id"),
        prevent_initial_call=True,
    )

    # Dashboard export callback
    @app.callback(
        Output({"type": "dashboard-export-download", "dashboard_id": MATCH}, "data"),
        Input({"type": "export-dashboard-button", "dashboard_id": MATCH}, "n_clicks"),
        [
            State("dashboard-event-store", "data"),
            State({"type": "export-dashboard-button", "dashboard_id": MATCH}, "id"),
        ],
        prevent_initial_call=True,
        background=True,  # Background processing for export
    )
    def export_dashboard_html(n_clicks, event_state, button_id):
        """
        Export the current dashboard state as a standalone HTML file.
        This generates a complete HTML page with embedded charts and data.
        """
        if not n_clicks:
            from dash import no_update

            return no_update

        dashboard_id = button_id["dashboard_id"]
        logger.info(f"🔄 DASHBOARD EXPORT: Starting export for dashboard {dashboard_id}")

        try:
            # Get current dashboard data
            base_df = app.get_cached_dataframe_with_memoize()
            filtered_df = apply_data_filters(base_df, event_state, f"export-{dashboard_id}")

            # Generate all current charts
            charts = []
            chart_components = [c for c in DASHBOARD_COMPONENTS if c["type"] == "chart"]

            for comp in chart_components:
                try:
                    # Apply chart-specific optimization
                    optimized_df = get_optimized_chart_data(filtered_df, comp)

                    # Create chart figure
                    fig = create_chart_figure(optimized_df, comp)
                    charts.append(fig)

                    logger.info(f"📊 EXPORT: Added chart '{comp['title']}' to export")
                except Exception as e:
                    logger.error(
                        f"❌ EXPORT: Failed to create chart '{comp.get('title', 'Unknown')}': {e}"
                    )
                    # Continue with other charts even if one fails

            # Prepare dashboard data for export
            dashboard_data = {
                "dashboard_id": dashboard_id,
                "export_timestamp": datetime.now().isoformat(),
                "total_data_points": len(filtered_df),
                "applied_filters": event_state,
                "chart_count": len(charts),
            }

            # Create standalone HTML
            title = f"Dashboard {dashboard_id} Export"
            html_content = create_standalone_html(dashboard_data, charts, title)

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"dashboard_{dashboard_id}_export_{timestamp}.html"

            logger.info(f"✅ DASHBOARD EXPORT: Successfully exported {len(charts)} charts")

            # Return download data
            return {"content": html_content, "filename": filename, "type": "text/html"}

        except Exception as e:
            logger.error(f"❌ DASHBOARD EXPORT: Failed to export dashboard {dashboard_id}: {e}")

            # Return error HTML as fallback
            error_html = f"""
            <!DOCTYPE html>
            <html>
            <head><title>Export Error</title></head>
            <body>
                <h1>Dashboard Export Error</h1>
                <p>Failed to export dashboard {dashboard_id}: {str(e)}</p>
                <p>Please try again or contact support.</p>
            </body>
            </html>
            """

            return {
                "content": error_html,
                "filename": f"dashboard_{dashboard_id}_export_error.html",
                "type": "text/html",
            }

    # Enhanced anchor navigation with better debugging and immediate execution
    app.clientside_callback(
        """
        function(pathname) {
            console.log('🎯 Anchor callback triggered with pathname:', pathname);

            // Define global anchor navigation function
            window.scrollToAnchor = function(targetId, maxRetries = 5) {
                console.log('🎯 scrollToAnchor called for:', targetId);
                let attempts = 0;
                const delays = [100, 300, 600, 1200, 2000];

                function tryScroll() {
                    const element = document.getElementById(targetId);
                    console.log('🎯 Looking for element:', targetId, 'Found:', !!element);

                    if (element) {
                        console.log('🎯 Scrolling to element:', targetId);

                        // Get actual header height dynamically
                        const appShell = document.querySelector('.mantine-AppShell-header');
                        const headerHeight = appShell ? appShell.offsetHeight + 10 : 40; // 10px padding

                        console.log('🎯 Header height detected:', headerHeight);

                        const elementPosition = element.getBoundingClientRect().top + window.pageYOffset;
                        const offsetPosition = elementPosition - headerHeight;

                        window.scrollTo({
                            top: offsetPosition,
                            behavior: 'smooth'
                        });

                        // Add visual indicator
                        element.style.boxShadow = '0 0 10px rgba(0, 123, 255, 0.5)';
                        setTimeout(() => {
                            element.style.boxShadow = '';
                        }, 2000);

                        return true;
                    }

                    if (attempts < maxRetries) {
                        attempts++;
                        console.log(`🎯 Retry ${attempts}/${maxRetries} for:`, targetId);
                        setTimeout(tryScroll, delays[attempts - 1] || 2000);
                    } else {
                        console.warn('🎯 Failed to find element after retries:', targetId);
                        // List all elements with IDs for debugging
                        const allElements = document.querySelectorAll('[id]');
                        console.log('🎯 Available elements with IDs:', Array.from(allElements).map(el => el.id));
                    }
                }

                tryScroll();
            };

            // Handle URL-based navigation
            if (pathname && pathname.includes('#')) {
                const targetId = pathname.split('#')[1];
                console.log('🎯 Extracted anchor ID:', targetId);
                if (targetId) {
                    // Try immediate scroll first
                    setTimeout(() => window.scrollToAnchor(targetId), 50);
                }
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output("dummy-anchor-output", "children", allow_duplicate=True),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )

    logger.info("✅ DASHBOARD CONTENT: All callbacks registered successfully")


def create_metric_card(metric):
    """Create a single metric card using dmc.Paper."""

    return html.Div(
        style={
            "width": "100%",
            "height": "100%",
            "position": "relative",
        },
        children=[
            dmc.Paper(
                shadow="sm",
                radius="md",
                p="lg",
                withBorder=True,
                style={
                    "width": "100%",
                    "height": "100%",
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "space-between",
                    "boxSizing": "border-box",
                    "overflow": "hidden",
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
                                "vs baseline",
                                size="xs",
                                c="gray",
                            ),
                        ],
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
