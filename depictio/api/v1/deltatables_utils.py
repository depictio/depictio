import hashlib
import json
import os
import sys
import warnings

import httpx
import polars as pl
from bson import ObjectId

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.s3 import polars_s3_config

# FEATURE FLAGS
ENABLE_CACHING = True  # Global toggle for caching system

# PERFORMANCE TESTING: Toggle for local filesystem caching
USE_LOCAL_FILES = os.getenv("DEPICTIO_USE_LOCAL_FILES", "false").lower() == "true"
DELTA_CACHE_DIR = "/app/cache/delta_cache"
logger.info(f"Data loading mode: {'LOCAL CACHE' if USE_LOCAL_FILES else 'S3/MinIO'}")


def get_local_cache_path(s3_path: str) -> str:
    """
    Get local cache path for a Delta table.

    Example:
        s3://depictio-bucket/646b0f3c1e4a2d7f8e5b8c9c
        → /app/cache/delta_cache/646b0f3c1e4a2d7f8e5b8c9c
    """
    if s3_path.startswith("s3://"):
        # Extract data collection ID from S3 path
        dc_id = s3_path.split("/")[-1]
        return os.path.join(DELTA_CACHE_DIR, dc_id)
    return s3_path


def cache_delta_table_from_s3(s3_path: str, polars_s3_config: dict) -> str:
    """
    Cache Delta table from S3 to local filesystem for faster subsequent reads.

    Args:
        s3_path: S3 path to Delta table (e.g., s3://depictio-bucket/646b0f3c1e4a2d7f8e5b8c9c)
        polars_s3_config: S3 configuration for Polars

    Returns:
        Local cache path where Delta table is stored
    """
    import shutil

    cache_path = get_local_cache_path(s3_path)

    # Check if already cached
    if os.path.exists(cache_path) and os.path.exists(os.path.join(cache_path, "_delta_log")):
        logger.debug(f"📦 Cache hit: {cache_path}")
        return cache_path

    # Create cache directory
    os.makedirs(DELTA_CACHE_DIR, exist_ok=True)

    # Remove stale cache if exists
    if os.path.exists(cache_path):
        shutil.rmtree(cache_path)

    logger.info(f"📥 Caching from S3 to local: {s3_path} → {cache_path}")

    # Read from S3 and write to local cache
    df = pl.scan_delta(s3_path, storage_options=polars_s3_config).collect()
    df.write_delta(cache_path, mode="overwrite")

    logger.info(f"✅ Cache created: {cache_path} ({len(df)} rows)")
    return cache_path


# PERFORMANCE OPTIMIZATION: Filter hash generation for caching filtered DataFrames
def _generate_filter_hash(metadata: list[dict] | None) -> str:
    """
    Generate a stable hash from metadata filters for cache key generation.

    Args:
        metadata: List of metadata dicts containing filter information

    Returns:
        Short hash string (8 chars) representing the filter state
    """
    if not metadata:
        return "nofilters"

    # Create a stable representation of filters
    # Sort by column name to ensure consistent ordering
    filter_repr = []
    for component in metadata:
        # Extract metadata from nested structure if needed
        if "metadata" in component:
            meta = component["metadata"]
            column_name = meta.get("column_name", "")
            component_type = meta.get("interactive_component_type", "")
            value = component.get("value")
        else:
            column_name = component.get("column_name", "")
            component_type = component.get("interactive_component_type", "")
            value = component.get("value")

        # Create stable representation
        filter_dict = {"col": column_name, "type": component_type, "val": value}
        filter_repr.append(filter_dict)

    # Sort for stability
    filter_repr.sort(key=lambda x: (x["col"], x["type"]))

    # Convert to JSON and hash
    filter_json = json.dumps(filter_repr, sort_keys=True)
    filter_hash = hashlib.md5(filter_json.encode()).hexdigest()[:8]

    return filter_hash


def add_filter(
    filter_list: list,
    interactive_component_type: str,
    column_name: str,
    value,
    min_value=None,
    max_value=None,
) -> None:
    """Add filter criteria to a filter list based on component type."""
    if interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        if value:
            # Ensure value is a list for is_in() function
            if not isinstance(value, list):
                value = [value]
            logger.debug(
                f"Creating filter: column='{column_name}', values={value}, type={interactive_component_type}"
            )

            # Use native type filtering - Polars handles type coercion automatically
            # Join type mismatches are handled separately by normalize_join_column_types()
            filter_list.append(pl.col(column_name).is_in(value))

    elif interactive_component_type == "TextInput":
        if value:
            filter_list.append(pl.col(column_name).str.contains(value))

    elif interactive_component_type == "Slider":
        if value:
            filter_list.append(pl.col(column_name) == value)

    elif interactive_component_type == "RangeSlider":
        if value:
            filter_list.append(
                (pl.col(column_name) >= value[0]) & (pl.col(column_name) <= value[1])
            )

    elif interactive_component_type == "DateRangePicker":
        if value and isinstance(value, list) and len(value) == 2:
            try:
                # Convert date strings to datetime if needed
                start_date = value[0]
                end_date = value[1]

                # Handle string dates - convert to datetime
                if isinstance(start_date, str):
                    start_date = pl.lit(start_date).str.strptime(pl.Datetime, "%Y-%m-%d")
                if isinstance(end_date, str):
                    end_date = pl.lit(end_date).str.strptime(pl.Datetime, "%Y-%m-%d")

                logger.debug(
                    f"Creating date range filter: column='{column_name}', range=[{start_date}, {end_date}]"
                )

                # Apply date range filter
                # Cast column to datetime if it's not already
                date_col = pl.col(column_name).cast(pl.Datetime)
                filter_list.append((date_col >= start_date) & (date_col <= end_date))

            except Exception as e:
                logger.warning(f"Failed to apply date range filter on column '{column_name}': {e}")


def process_metadata_and_filter(metadata: list) -> list:
    """Process metadata and build a list of Polars filter expressions."""
    filter_list = []

    for component in metadata:
        if "metadata" in component:
            interactive_component_type = component["metadata"]["interactive_component_type"]
            column_name = component["metadata"]["column_name"]
        else:
            interactive_component_type = component["interactive_component_type"]
            column_name = component["column_name"]

        add_filter(
            filter_list,
            interactive_component_type=interactive_component_type,
            column_name=column_name,
            value=component["value"],
        )

    return filter_list


def convert_filter_model_to_metadata(filter_model):
    """
    Convert dash_ag_grid filterModel to a metadata list compatible with Polars filtering.
    """
    metadata = []
    for column, filter_details in filter_model.items():
        filter_type = filter_details.get("filterType", "text")
        operator = filter_details.get("type", "contains")
        value = filter_details.get("filter")
        filter_to = filter_details.get("filterTo")

        if operator == "inRange":
            # Range filter corresponds to RangeSlider
            interactive_component_type = "RangeSlider"
            if value is not None and filter_to is not None:
                metadata.append(
                    {
                        "metadata": {
                            "interactive_component_type": interactive_component_type,
                            "column_name": column,
                            "min_value": value,
                            "max_value": filter_to,
                        },
                        "value": [value, filter_to],
                    }
                )
        elif operator in [
            "equals",
            "notEqual",
            "greaterThan",
            "greaterThanOrEqual",
            "lessThan",
            "lessThanOrEqual",
        ]:
            # Numerical or exact match filters
            if filter_type == "number":
                interactive_component_type = "Slider"
                metadata.append(
                    {
                        "metadata": {
                            "interactive_component_type": interactive_component_type,
                            "column_name": column,
                        },
                        "value": value,
                    }
                )
            else:
                # Non-number filters treated as TextInput
                interactive_component_type = "TextInput"
                metadata.append(
                    {
                        "metadata": {
                            "interactive_component_type": interactive_component_type,
                            "column_name": column,
                        },
                        "value": value,
                    }
                )
        elif operator in [
            "contains",
            "notContains",
            "startsWith",
            "notStartsWith",
            "endsWith",
            "notEndsWith",
        ]:
            # String filters
            interactive_component_type = "TextInput"
            metadata.append(
                {
                    "metadata": {
                        "interactive_component_type": interactive_component_type,
                        "column_name": column,
                    },
                    "value": value,
                }
            )
        elif operator in ["blank", "notBlank"]:
            # Special filters for null values
            interactive_component_type = (
                "Select"  # Assuming a select component to choose between blank/notBlank
            )
            metadata.append(
                {
                    "metadata": {
                        "interactive_component_type": interactive_component_type,
                        "column_name": column,
                    },
                    "value": None,  # Value not needed for blank/notBlank
                }
            )
        # Extend with more operators as needed

    return metadata


def normalize_join_column_types(df1, df2, join_columns):
    """
    Normalize the data types of join columns between two DataFrames to ensure compatibility.

    Args:
        df1: First DataFrame
        df2: Second DataFrame
        join_columns: List of column names to normalize

    Returns:
        tuple: (normalized_df1, normalized_df2)
    """
    for col in join_columns:
        if col in df1.columns and col in df2.columns:
            dtype1 = df1[col].dtype
            dtype2 = df2[col].dtype

            # If types are different, cast both to string for compatibility
            if dtype1 != dtype2:
                logger.debug(
                    f"Type mismatch in join column '{col}': {dtype1} vs {dtype2}. Converting both to String."
                )

                # Cast both columns to string to ensure compatibility
                df1 = df1.with_columns(pl.col(col).cast(pl.String))
                df2 = df2.with_columns(pl.col(col).cast(pl.String))

                logger.debug(f"Normalized column '{col}' to String type for both DataFrames")

    return df1, df2


# =============================================================================
# HELPER FUNCTIONS FOR load_deltatable_lite()
# =============================================================================


def _generate_cache_keys(
    workflow_id_str: str,
    data_collection_id_str: str,
    load_for_preview: bool,
    select_columns: list[str] | None,
    metadata: list[dict] | None,
    load_for_options: bool,
) -> tuple[str, str | None, str | None]:
    """
    Generate cache keys for DataFrame caching.

    Returns:
        Tuple of (base_cache_key, filtered_cache_key, filter_hash).
        filtered_cache_key and filter_hash are None if no filters apply.
    """
    cache_suffix = "preview" if load_for_preview else "base"

    if select_columns:
        columns_key = "_".join(sorted(select_columns))
        base_cache_key = (
            f"{workflow_id_str}_{data_collection_id_str}_{cache_suffix}_cols_{columns_key}"
        )
    else:
        base_cache_key = f"{workflow_id_str}_{data_collection_id_str}_{cache_suffix}"

    filter_hash = None
    filtered_cache_key = None

    if metadata and not load_for_options:
        filter_hash = _generate_filter_hash(metadata)
        filtered_cache_key = f"{base_cache_key}_filters_{filter_hash}"
        logger.debug(
            f"Generated FILTERED cache key: {filtered_cache_key} (filters={len(metadata)})"
        )
    else:
        logger.debug(
            f"Generated BASE cache key: {base_cache_key} "
            f"(preview={load_for_preview}, columns={len(select_columns) if select_columns else 'all'})"
        )

    return base_cache_key, filtered_cache_key, filter_hash


def _get_delta_location(
    data_collection_id_str: str,
    workflow_id_str: str,
    init_data: dict[str, dict] | None,
    token: str | None,
) -> str:
    """
    Get Delta table location from init_data or via API call (legacy).

    Args:
        data_collection_id_str: String ID of the data collection.
        workflow_id_str: String ID of the workflow.
        init_data: Optional pre-loaded initialization data.
        token: Optional auth token for legacy API path.

    Returns:
        Delta table location (S3 path).

    Raises:
        Exception: If API call fails or response is invalid.
    """
    if init_data and data_collection_id_str in init_data:
        file_id = init_data[data_collection_id_str]["delta_location"]
        logger.info(f"Using init_data for DC {data_collection_id_str}")
        return file_id

    # Legacy API path with deprecation warning
    warnings.warn(
        f"Loading DC {data_collection_id_str} without init_data - making API call (deprecated). "
        "Pass init_data parameter to avoid API calls on every load.",
        DeprecationWarning,
        stacklevel=3,
    )

    url = f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{data_collection_id_str}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        response = httpx.get(url, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(
            f"HTTP error loading deltatable for workflow {workflow_id_str} "
            f"and data collection {data_collection_id_str}: {e}"
        )
        raise Exception("Error loading deltatable") from e

    file_id = response.json().get("delta_table_location")
    if not file_id:
        logger.error(
            f"No 'delta_table_location' found in response for workflow {workflow_id_str} "
            f"and data collection {data_collection_id_str}"
        )
        raise Exception("Invalid response: missing 'delta_table_location'")

    return file_id


def _create_delta_scan(file_id: str) -> pl.LazyFrame:
    """
    Create a Polars LazyFrame scan from Delta table location.

    Args:
        file_id: S3 path or local path to Delta table.

    Returns:
        Polars LazyFrame for the Delta table.
    """
    if USE_LOCAL_FILES:
        cache_path = cache_delta_table_from_s3(file_id, polars_s3_config)
        logger.debug(f"Reading from local cache: {cache_path}")
        return pl.scan_delta(cache_path)

    logger.debug(f"Reading from S3: {file_id}")
    return pl.scan_delta(file_id, storage_options=polars_s3_config)


def _apply_scan_options(
    delta_scan: pl.LazyFrame,
    select_columns: list[str] | None,
    limit_rows: int | None,
) -> pl.LazyFrame:
    """
    Apply column projection and row limit to a LazyFrame scan.

    Args:
        delta_scan: Polars LazyFrame to modify.
        select_columns: Optional list of columns to select.
        limit_rows: Optional row limit.

    Returns:
        Modified LazyFrame with projections/limits applied.
    """
    if select_columns:
        delta_scan = delta_scan.select(select_columns)
        logger.debug(f"Applied column projection: {len(select_columns)} columns")

    if limit_rows:
        delta_scan = delta_scan.limit(limit_rows)
        logger.debug(f"Applied row limit: {limit_rows}")

    return delta_scan


def _finalize_dataframe(
    df: pl.DataFrame,
    metadata: list[dict] | None,
    load_for_options: bool,
    limit_rows: int | None,
) -> pl.DataFrame:
    """
    Apply final processing to a DataFrame: filters, row limit, and column cleanup.

    Args:
        df: DataFrame to process.
        metadata: Optional filter metadata.
        load_for_options: If True, skip filtering.
        limit_rows: Optional row limit.

    Returns:
        Processed DataFrame.
    """
    # Apply filters if needed
    if metadata and not load_for_options:
        logger.debug(f"Applying {len(metadata)} filter(s)")
        df = apply_runtime_filters(df, metadata)
        logger.debug(f"After filters: {df.height:,} rows x {df.width} columns")

    # Apply row limit
    if limit_rows:
        df = df.limit(limit_rows)
        logger.debug(f"Applied row limit: {limit_rows}")

    # Drop aggregation time column if exists
    if "depictio_aggregation_time" in df.columns:
        df = df.drop("depictio_aggregation_time")
        logger.debug("Dropped 'depictio_aggregation_time' column")

    return df


def _check_redis_cache(
    base_cache_key: str,
    filtered_cache_key: str | None,
    filter_hash: str | None,
    metadata: list[dict] | None,
    load_for_options: bool,
    select_columns: list[str] | None,
    limit_rows: int | None,
) -> pl.DataFrame | None:
    """
    Check Redis cache for cached DataFrame.

    Returns:
        Cached DataFrame if found, None otherwise.
    """
    try:
        from depictio.api.cache import cache_dataframe, get_cached_dataframe

        # Check filtered cache first if filters exist
        if filter_hash and filtered_cache_key:
            cached_df = get_cached_dataframe(filtered_cache_key)
            if cached_df is not None:
                logger.info(f"FILTERED CACHE HIT (Redis): {filtered_cache_key}")
                logger.debug(
                    f"Cached DataFrame: {cached_df.height:,} rows x {cached_df.width} cols"
                )
                return _finalize_dataframe(cached_df, None, True, limit_rows)

        # Check base cache
        cached_df = get_cached_dataframe(base_cache_key)
        if cached_df is not None:
            logger.info(f"BASE CACHE HIT (Redis): {base_cache_key}")
            logger.debug(f"Cached DataFrame: {cached_df.height:,} rows x {cached_df.width} columns")

            # Apply column projection if needed
            if select_columns and all(col in cached_df.columns for col in select_columns):
                cached_df = cached_df.select(select_columns)
                logger.debug(f"Applied column projection: {len(select_columns)} columns")

            # Apply filters and cache the filtered result
            if metadata and not load_for_options:
                logger.debug(f"Applying {len(metadata)} filter(s) to cached DataFrame")
                cached_df = apply_runtime_filters(cached_df, metadata)
                logger.debug(
                    f"After filters: {cached_df.height:,} rows x {cached_df.width} columns"
                )

                # Cache filtered result
                if filter_hash and filtered_cache_key:
                    cache_dataframe(filtered_cache_key, cached_df)
                    logger.debug(f"Cached filtered result: {filtered_cache_key}")

            return _finalize_dataframe(cached_df, None, True, limit_rows)

    except Exception as e:
        logger.debug(f"Redis cache check failed: {e}")

    return None


def _check_memory_cache(
    base_cache_key: str,
    filtered_cache_key: str | None,
    filter_hash: str | None,
    metadata: list[dict] | None,
    load_for_options: bool,
    select_columns: list[str] | None,
    limit_rows: int | None,
) -> pl.DataFrame | None:
    """
    Check memory cache for cached DataFrame.

    Returns:
        Cached DataFrame if found, None otherwise.
    """
    import time

    # Check filtered cache first if filters exist
    if filter_hash and filtered_cache_key and filtered_cache_key in _dataframe_memory_cache:
        logger.info(f"FILTERED CACHE HIT (memory): {filtered_cache_key}")
        update_cache_timestamp(filtered_cache_key)
        cached_df = _dataframe_memory_cache[filtered_cache_key]
        logger.debug(f"Cached DataFrame: {cached_df.height:,} rows x {cached_df.width} columns")
        return _finalize_dataframe(cached_df, None, True, limit_rows)

    # Check base cache
    if base_cache_key in _dataframe_memory_cache:
        logger.info(f"BASE CACHE HIT (memory): {base_cache_key}")
        update_cache_timestamp(base_cache_key)
        cached_df = _dataframe_memory_cache[base_cache_key]
        logger.debug(f"Cached DataFrame: {cached_df.height:,} rows x {cached_df.width} columns")

        # Apply column projection if needed
        if select_columns and all(col in cached_df.columns for col in select_columns):
            cached_df = cached_df.select(select_columns)
            logger.debug(f"Applied column projection: {len(select_columns)} columns")

        # Apply filters and cache the filtered result
        if metadata and not load_for_options:
            cached_df = apply_runtime_filters(cached_df, metadata)
            logger.debug(f"After filters: {cached_df.height:,} rows x {cached_df.width} columns")

            # Cache filtered result in memory
            if filter_hash and filtered_cache_key:
                _dataframe_memory_cache[filtered_cache_key] = cached_df
                _cache_metadata[filtered_cache_key] = {
                    "size_bytes": sys.getsizeof(cached_df),
                    "timestamp": time.time(),
                }
                logger.debug(f"Cached filtered result (memory): {filtered_cache_key}")

        return _finalize_dataframe(cached_df, None, True, limit_rows)

    return None


def _cache_dataframe_to_stores(
    cache_key: str,
    df: pl.DataFrame,
    size_bytes: int,
) -> None:
    """
    Cache a DataFrame to both Redis and memory stores.

    Args:
        cache_key: Cache key for the DataFrame.
        df: DataFrame to cache.
        size_bytes: Estimated size in bytes.
    """
    import time

    global _total_memory_usage

    if size_bytes > MEMORY_THRESHOLD_BYTES:
        logger.debug(f"DataFrame too large to cache ({size_bytes / (1024 * 1024):.2f} MB)")
        return

    # Try Redis first
    try:
        from depictio.api.cache import cache_dataframe

        if cache_dataframe(cache_key, df):
            logger.debug(f"Cached to Redis: {cache_key} ({size_bytes / (1024 * 1024):.2f} MB)")
    except Exception as e:
        logger.debug(f"Redis caching failed: {e}")

    # Also cache in memory
    _dataframe_memory_cache[cache_key] = df
    _cache_metadata[cache_key] = {
        "size_bytes": size_bytes,
        "timestamp": time.time(),
    }
    _total_memory_usage += size_bytes
    logger.debug(f"Cached to memory: {cache_key} ({size_bytes / (1024 * 1024):.2f} MB)")


def _log_cache_status() -> None:
    """Log current cache status (Redis and memory)."""
    try:
        from depictio.api.cache import get_cache_stats

        stats = get_cache_stats()
        total_keys = stats.get("redis_keys", 0) + stats.get("memory_keys", 0)
        total_mb = stats.get("redis_memory_used_mb", 0) + stats.get("memory_size_mb", 0)
        logger.info(
            f"CACHE STATUS: {total_keys} DataFrames "
            f"({stats.get('redis_keys', 0)} Redis + {stats.get('memory_keys', 0)} memory), "
            f"{total_mb:.1f}MB"
        )
    except Exception:
        total_mb = sum(sys.getsizeof(df) for df in _dataframe_memory_cache.values()) / 1024 / 1024
        logger.info(
            f"CACHE STATUS: {len(_dataframe_memory_cache)} DataFrames (memory only), {total_mb:.1f}MB"
        )


def _load_and_cache_fresh_data(
    delta_scan: pl.LazyFrame,
    base_cache_key: str,
    filtered_cache_key: str | None,
    filter_hash: str | None,
    data_collection_id_str: str,
    metadata: list[dict] | None,
    load_for_options: bool,
    size_bytes: int,
) -> pl.DataFrame:
    """
    Load DataFrame from storage and cache it.

    Args:
        delta_scan: Polars LazyFrame to collect.
        base_cache_key: Cache key for unfiltered data.
        filtered_cache_key: Optional cache key for filtered data.
        filter_hash: Optional filter hash.
        data_collection_id_str: Data collection ID for logging.
        metadata: Optional filter metadata.
        load_for_options: If True, skip filtering.
        size_bytes: Expected size for caching decisions (-1 for unknown).

    Returns:
        Loaded DataFrame.
    """
    import time

    global _total_memory_usage

    logger.info(f"CACHE MISS: Loading from storage for key: {base_cache_key}")

    try:
        df = delta_scan.collect()
    except Exception as e:
        logger.error(f"Error collecting Delta table data: {e}")
        raise Exception("Error collecting Delta table data") from e

    logger.info(
        f"Loaded DataFrame: {df.height:,} rows x {df.width} columns (DC: {data_collection_id_str})"
    )
    logger.debug(f"DataFrame columns: {df.columns}")

    # Estimate size if unknown
    if size_bytes == -1:
        size_bytes = df.height * df.width * 8  # 8 bytes per cell average
        logger.debug(f"Estimated DataFrame size: {size_bytes / (1024 * 1024):.2f} MB")

    # Cache the base DataFrame
    _cache_dataframe_to_stores(base_cache_key, df, size_bytes)

    # Apply filters if needed
    if metadata and not load_for_options:
        logger.debug(f"Applying {len(metadata)} filter(s) after loading")
        df = apply_runtime_filters(df, metadata)
        logger.debug(f"After filters: {df.height:,} rows x {df.width} columns")

        # Cache filtered result
        if filter_hash and filtered_cache_key:
            filtered_size = df.height * df.width * 8
            try:
                from depictio.api.cache import cache_dataframe

                if cache_dataframe(filtered_cache_key, df):
                    logger.debug(f"Cached filtered result: {filtered_cache_key}")
                else:
                    _dataframe_memory_cache[filtered_cache_key] = df
                    _cache_metadata[filtered_cache_key] = {
                        "size_bytes": filtered_size,
                        "timestamp": time.time(),
                    }
                    logger.debug(f"Cached filtered result (memory): {filtered_cache_key}")
            except Exception:
                _dataframe_memory_cache[filtered_cache_key] = df
                _cache_metadata[filtered_cache_key] = {
                    "size_bytes": filtered_size,
                    "timestamp": time.time(),
                }

    return df


def _load_large_dataframe(
    delta_scan: pl.LazyFrame,
    data_collection_id_str: str,
    metadata: list[dict] | None,
    load_for_options: bool,
    limit_rows: int | None,
    size_bytes: int,
) -> pl.DataFrame:
    """
    Load a large DataFrame using lazy evaluation with filters applied at scan time.

    Args:
        delta_scan: Polars LazyFrame to process.
        data_collection_id_str: Data collection ID for logging.
        metadata: Optional filter metadata.
        load_for_options: If True, skip filtering.
        limit_rows: Optional row limit.
        size_bytes: Size for logging.

    Returns:
        Loaded DataFrame.
    """
    logger.debug(f"Large DataFrame ({size_bytes / (1024 * 1024):.2f} MB) - using lazy loading")

    # Apply filters at scan level for large DataFrames
    if metadata and not load_for_options:
        filter_expressions = process_metadata_and_filter(metadata)
        logger.debug(f"Filter expressions: {filter_expressions}")

        if filter_expressions:
            combined_filter = filter_expressions[0]
            for filt in filter_expressions[1:]:
                combined_filter &= filt
            delta_scan = delta_scan.filter(combined_filter)
            logger.debug("Applied filters to lazy scan")
    elif load_for_options:
        logger.debug("Skipping filters - loading for component options")

    if limit_rows:
        delta_scan = delta_scan.limit(limit_rows)
        logger.debug(f"Applied row limit: {limit_rows}")

    try:
        df = delta_scan.collect()
    except Exception as e:
        logger.error(f"Error collecting Delta table data: {e}")
        raise Exception("Error collecting Delta table data") from e

    logger.info(
        f"Loaded large DataFrame: {df.height:,} rows x {df.width} columns "
        f"(DC: {data_collection_id_str})"
    )
    logger.debug(f"DataFrame columns: {df.columns}")

    return df


# =============================================================================
# MAIN FUNCTION
# =============================================================================


def load_deltatable_lite(
    workflow_id: ObjectId,
    data_collection_id: ObjectId | str,
    metadata: list[dict] | None = None,
    TOKEN: str | None = None,  # DEPRECATED: kept for backward compat, use init_data instead
    limit_rows: int | None = None,
    load_for_options: bool = False,
    load_for_preview: bool = False,
    select_columns: list[str] | None = None,
    init_data: dict[str, dict] | None = None,
) -> pl.DataFrame:
    """
    Load a Delta table with adaptive memory management based on DataFrame size.

    ADAPTIVE MEMORY STRATEGY:
    - Small DataFrames (<1GB): Cached in memory for fast filtering (when ENABLE_CACHING=True)
    - Large DataFrames (>=1GB): Always use lazy loading to prevent OOM

    COLUMN PROJECTION:
    - Specify select_columns to load only needed columns (10-50x I/O reduction for wide tables)
    - Projection happens at scan level (Polars predicate pushdown)

    DASHBOARD INITIALIZATION:
    - Pass init_data to avoid API/DB calls on every data load
    - init_data should contain delta_location and size_bytes for each DC
    - When init_data is None, falls back to legacy API/DB call path (with deprecation warning)

    Args:
        workflow_id: The ID of the workflow.
        data_collection_id: The ID of the data collection.
        metadata: List of metadata dicts for filtering the DataFrame.
        TOKEN: DEPRECATED - Use init_data instead to avoid API calls.
        limit_rows: Maximum number of rows to return.
        load_for_options: Whether loading unfiltered data for component options.
        load_for_preview: Whether loading for preview (separate cache).
        select_columns: Columns to select for projection (None = all columns).
        init_data: Dashboard initialization data to avoid API/DB calls.
            Structure: {"dc_id": {"delta_location": str, "size_bytes": int}}

    Returns:
        The loaded and optionally filtered DataFrame.

    Raises:
        Exception: If the HTTP request to load the Delta table fails (legacy path).
        NotImplementedError: If attempting to load a joined DC format (deprecated).
    """
    data_collection_id_str = str(data_collection_id)
    workflow_id_str = str(workflow_id)

    # Reject deprecated joined DC format
    if isinstance(data_collection_id, str) and "--" in data_collection_id:
        raise NotImplementedError(
            f"Joined DC '{data_collection_id}' format is deprecated. "
            "Use the pre-computed result data collection ID instead. "
            "See get_result_dc_for_workflow() in depictio/dash/utils.py."
        )

    # CACHING DISABLED PATH - load directly from storage
    if not ENABLE_CACHING:
        logger.debug("Caching disabled (ENABLE_CACHING=False), loading directly")
        file_id = _get_delta_location(data_collection_id_str, workflow_id_str, init_data, TOKEN)
        delta_scan = _create_delta_scan(file_id)
        delta_scan = _apply_scan_options(delta_scan, select_columns, limit_rows)
        df = delta_scan.collect()
        logger.info(f"Loaded DataFrame: {df.height:,} rows x {df.width} columns")
        return _finalize_dataframe(df, metadata, load_for_options, None)

    # CACHING ENABLED PATH
    _log_cache_status()

    # Generate cache keys
    base_cache_key, filtered_cache_key, filter_hash = _generate_cache_keys(
        workflow_id_str,
        data_collection_id_str,
        load_for_preview,
        select_columns,
        metadata,
        load_for_options,
    )

    # Check Redis cache
    cached_df = _check_redis_cache(
        base_cache_key,
        filtered_cache_key,
        filter_hash,
        metadata,
        load_for_options,
        select_columns,
        limit_rows,
    )
    if cached_df is not None:
        return cached_df

    # Check memory cache
    cached_df = _check_memory_cache(
        base_cache_key,
        filtered_cache_key,
        filter_hash,
        metadata,
        load_for_options,
        select_columns,
        limit_rows,
    )
    if cached_df is not None:
        return cached_df

    # CACHE MISS - need to load from storage
    # Get DataFrame size for adaptive loading strategy
    if init_data and data_collection_id_str in init_data:
        size_bytes = init_data[data_collection_id_str].get("size_bytes", -1)
        logger.debug(f"Using size from init_data: {size_bytes} bytes")
    else:
        data_collection_id_obj = (
            ObjectId(data_collection_id)
            if isinstance(data_collection_id, str)
            else data_collection_id
        )
        size_bytes = get_deltatable_size_from_db(data_collection_id_obj)

    if size_bytes > 0:
        logger.debug(f"DataFrame size: {size_bytes / (1024 * 1024):.2f} MB")
    else:
        logger.debug("DataFrame size unknown, will estimate dynamically")

    # Get delta location and create scan
    file_id = _get_delta_location(data_collection_id_str, workflow_id_str, init_data, TOKEN)
    delta_scan = _create_delta_scan(file_id)

    # Apply column projection at scan level
    if select_columns:
        delta_scan = delta_scan.select(select_columns)
        logger.debug(f"Applied column projection at scan level: {len(select_columns)} columns")

    # ADAPTIVE LOADING STRATEGY
    if size_bytes == -1 or size_bytes <= MEMORY_THRESHOLD_BYTES:
        # Unknown or small DataFrame - load, cache, then filter in memory
        if limit_rows:
            delta_scan = delta_scan.limit(limit_rows)
            logger.debug(f"Applied row limit: {limit_rows}")

        df = _load_and_cache_fresh_data(
            delta_scan,
            base_cache_key,
            filtered_cache_key,
            filter_hash,
            data_collection_id_str,
            metadata,
            load_for_options,
            size_bytes,
        )
    else:
        # Large DataFrame - use lazy loading with filters at scan level
        df = _load_large_dataframe(
            delta_scan,
            data_collection_id_str,
            metadata,
            load_for_options,
            limit_rows,
            size_bytes,
        )

    # Final cleanup (drop aggregation column)
    if "depictio_aggregation_time" in df.columns:
        df = df.drop("depictio_aggregation_time")
        logger.debug("Dropped 'depictio_aggregation_time' column")

    logger.debug(f"Final DataFrame: {df.height} rows x {df.width} columns")
    return df


# Memory management for DataFrames - new adaptive caching system
_dataframe_memory_cache = {}
_cache_metadata = {}  # Track size and timestamp for each cached DataFrame
_total_memory_usage = 0
MEMORY_THRESHOLD_BYTES = 1024 * 1024 * 1024  # 1GB threshold


def get_deltatable_size_from_db(data_collection_id: ObjectId) -> int:
    """
    Get pre-calculated DataFrame size from MongoDB deltatable metadata.

    Args:
        data_collection_id: ObjectId of the data collection

    Returns:
        Size in bytes, or estimated small size if not found
    """
    from depictio.api.v1.db import deltatables_collection

    try:
        dt_doc = deltatables_collection.find_one({"data_collection_id": data_collection_id})
        if dt_doc and "flexible_metadata" in dt_doc:
            size_bytes = dt_doc["flexible_metadata"].get("deltatable_size_bytes")
            if size_bytes and isinstance(size_bytes, (int, float)) and size_bytes > 0:
                logger.debug(
                    f"Found deltatable size for {data_collection_id}: {size_bytes} bytes ({size_bytes / (1024 * 1024):.2f} MB)"
                )
                return int(size_bytes)

        # If no size metadata found, try to estimate from the DataFrame directly
        logger.debug(
            f"No size metadata found for {data_collection_id}, will estimate size dynamically"
        )
        return -1  # Special value to indicate dynamic estimation needed

    except Exception as e:
        logger.warning(f"Error retrieving deltatable size for {data_collection_id}: {e}")
        return -1  # Special value to indicate dynamic estimation needed


def evict_oldest_cached_dataframe():
    """
    Evict the oldest cached DataFrame to free memory.
    Uses LRU (Least Recently Used) strategy.
    """
    global _total_memory_usage

    if not _cache_metadata:
        return

    # Find oldest cached DataFrame by timestamp
    oldest_key = min(_cache_metadata.keys(), key=lambda k: _cache_metadata[k]["timestamp"])

    # Remove from cache and update memory usage
    if oldest_key in _dataframe_memory_cache:
        size_bytes = _cache_metadata[oldest_key]["size_bytes"]
        del _dataframe_memory_cache[oldest_key]
        del _cache_metadata[oldest_key]
        _total_memory_usage -= size_bytes

        logger.debug(
            f"Evicted cached DataFrame {oldest_key}, freed {size_bytes} bytes ({size_bytes / (1024 * 1024):.2f} MB)"
        )
        logger.debug(
            f"Total memory usage now: {_total_memory_usage} bytes ({_total_memory_usage / (1024 * 1024):.2f} MB)"
        )


def load_and_cache_dataframe(cache_key: str, size_bytes: int, delta_scan) -> pl.DataFrame:
    """
    Load DataFrame and cache it in Redis and memory if space allows.

    Args:
        cache_key: Unique identifier for this DataFrame
        size_bytes: Expected size of the DataFrame in bytes
        delta_scan: Polars LazyFrame to materialize

    Returns:
        Materialized DataFrame
    """
    global _total_memory_usage
    import time

    # Evict oldest entries if adding this would exceed threshold
    while _total_memory_usage + size_bytes > MEMORY_THRESHOLD_BYTES and _cache_metadata:
        evict_oldest_cached_dataframe()

    # Materialize the DataFrame
    logger.debug(f"Materializing DataFrame for cache key: {cache_key}")
    df = delta_scan.collect()

    # PERFORMANCE: Use fast row count instead of expensive estimated_size() for small datasets
    # For datasets < 100KB, pickling overhead exceeds recalculation cost - skip Redis entirely
    row_count = df.height
    REDIS_SKIP_THRESHOLD_ROWS = 1000  # Skip Redis for datasets < 1000 rows (~100KB)

    if row_count < REDIS_SKIP_THRESHOLD_ROWS:
        # TINY DATASET: Skip Redis pickling overhead, use memory-only cache
        logger.debug(
            f"⚡ TINY DATASET ({row_count} rows < {REDIS_SKIP_THRESHOLD_ROWS} threshold) - Skipping Redis, memory-only cache"
        )
        actual_size = size_bytes  # Use estimate, avoid expensive df.estimated_size() scan

        # Memory cache only (much faster than Redis for tiny datasets)
        if _total_memory_usage + actual_size <= MEMORY_THRESHOLD_BYTES:
            _dataframe_memory_cache[cache_key] = df
            _cache_metadata[cache_key] = {
                "size_bytes": actual_size,
                "timestamp": time.time(),
            }
            _total_memory_usage += actual_size
            logger.debug(f"💾 Memory cached (Redis skipped): {cache_key} ({row_count} rows)")

        return df

    # LARGER DATASET: Use Redis + memory caching
    # Use fast estimate (df.estimated_size() scan disabled for performance)
    actual_size = df.height * df.width * 8  # 8 bytes per cell average

    # Try to cache in Redis first (persistent across page refreshes)
    try:
        from depictio.api.cache import cache_dataframe

        if cache_dataframe(cache_key, df):
            logger.debug(f"✅ Redis cached: {cache_key} ({actual_size / (1024 * 1024):.2f} MB)")
    except Exception as e:
        logger.debug(f"Redis caching failed: {e}")

    # Also cache in memory if under threshold (faster access during session)
    if _total_memory_usage + actual_size <= MEMORY_THRESHOLD_BYTES:
        _dataframe_memory_cache[cache_key] = df
        _cache_metadata[cache_key] = {
            "size_bytes": actual_size,
            "timestamp": time.time(),
        }
        _total_memory_usage += actual_size

        logger.debug(f"💾 Memory cached: {cache_key} ({actual_size / (1024 * 1024):.2f} MB)")
        logger.debug(
            f"Total memory usage: {_total_memory_usage} bytes ({_total_memory_usage / (1024 * 1024):.2f} MB)"
        )
    else:
        logger.debug(f"DataFrame {cache_key} too large for memory cache ({actual_size} bytes)")

    return df


def apply_runtime_filters(df: pl.DataFrame, metadata: list[dict] | None) -> pl.DataFrame:
    """
    Apply filters to a cached DataFrame in memory - very fast operation.

    Args:
        df: Materialized DataFrame
        metadata: List of metadata dicts for filtering

    Returns:
        Filtered DataFrame
    """
    if not metadata:
        return df

    original_row_count = df.height
    logger.debug(
        f"🔍 Applying runtime filters to DataFrame ({original_row_count} rows) with {len(metadata)} filter criteria"
    )

    # Get DataFrame columns for validation
    df_columns = set(df.columns)

    # Validate that all filter columns exist in the DataFrame
    skipped_filters = []
    for component in metadata:
        if "metadata" in component:
            column_name = component["metadata"].get("column_name")
            component_type = component["metadata"].get("interactive_component_type", "unknown")
        else:
            column_name = component.get("column_name")
            component_type = component.get("interactive_component_type", "unknown")

        if column_name and column_name not in df_columns:
            skipped_filters.append(
                {
                    "column": column_name,
                    "type": component_type,
                    "value": component.get("value", "N/A"),
                }
            )

    # If any filters were skipped, log prominently and return unfiltered data
    if skipped_filters:
        logger.warning(
            f"⚠️ FILTER MISMATCH: Skipping {len(skipped_filters)} filter(s) - columns not present in DataFrame"
        )
        for skip in skipped_filters:
            logger.warning(
                f"  ❌ Column '{skip['column']}' (type={skip['type']}, value={skip['value']}) not in DataFrame"
            )
        logger.warning(f"  📋 Available columns in DataFrame: {sorted(df_columns)}")
        logger.warning(
            f"  ⏭️  Returning UNFILTERED DataFrame with {original_row_count} rows (filtering skipped)"
        )
        # Return unfiltered DataFrame if any column is missing
        # This prevents ColumnNotFoundError
        return df

    filter_expressions = process_metadata_and_filter(metadata)

    # Debug logging for filter expressions
    if filter_expressions:
        logger.debug(f"🔍 Generated {len(filter_expressions)} filter expression(s):")
        for i, expr in enumerate(filter_expressions, 1):
            logger.debug(f"   Filter {i}: {expr}")

    if filter_expressions:
        try:
            # Apply filters using Polars expressions on materialized DataFrame
            combined_filter = filter_expressions[0]
            for filt in filter_expressions[1:]:
                combined_filter &= filt

            logger.debug(f"🔍 Combined filter expression: {combined_filter}")

            df = df.filter(combined_filter)
            filtered_row_count = df.height
            logger.info(
                f"✅ Filtering applied successfully: {original_row_count} → {filtered_row_count} rows "
                f"({len(metadata)} filter(s), {original_row_count - filtered_row_count} rows removed)"
            )
        except pl.exceptions.ColumnNotFoundError as e:
            logger.error(f"❌ Column not found when applying filters: {e}")
            logger.error(f"Available columns: {sorted(df_columns)}")
            logger.error(f"⏭️  Returning UNFILTERED DataFrame with {original_row_count} rows")
            # Return unfiltered DataFrame instead of crashing
            return df

    return df


def update_cache_timestamp(cache_key: str):
    """Update timestamp for LRU cache management."""
    import time

    if cache_key in _cache_metadata:
        _cache_metadata[cache_key]["timestamp"] = time.time()


def get_memory_cache_stats() -> dict:
    """
    Get current memory cache statistics for monitoring and debugging.

    Returns:
        dict: Cache statistics including total usage, cached DataFrames, etc.
    """
    return {
        "total_memory_usage_bytes": _total_memory_usage,
        "total_memory_usage_mb": _total_memory_usage / (1024 * 1024),
        "memory_threshold_bytes": MEMORY_THRESHOLD_BYTES,
        "memory_threshold_mb": MEMORY_THRESHOLD_BYTES / (1024 * 1024),
        "cached_dataframes_count": len(_dataframe_memory_cache),
        "memory_utilization_percent": (_total_memory_usage / MEMORY_THRESHOLD_BYTES) * 100,
        "cached_dataframes": [
            {
                "cache_key": key,
                "size_bytes": _cache_metadata[key]["size_bytes"],
                "size_mb": _cache_metadata[key]["size_bytes"] / (1024 * 1024),
                "timestamp": _cache_metadata[key]["timestamp"],
            }
            for key in _dataframe_memory_cache.keys()
            if key in _cache_metadata
        ],
    }


def clear_memory_cache():
    """Clear all cached DataFrames to free memory."""
    global _total_memory_usage

    _dataframe_memory_cache.clear()
    _cache_metadata.clear()
    _total_memory_usage = 0

    logger.info("Cleared all cached DataFrames from memory")


def join_deltatables_dev(
    wf_id: str, joins: list, metadata: dict | None = None, TOKEN: str | None = None
) -> pl.DataFrame:
    """Development function for joining deltatables."""
    if metadata is None:
        metadata = {}

    loaded_dfs = {}
    logger.debug(f"Loading dataframes for workflow {wf_id}")

    for join_dict in joins:
        for join_id in join_dict:
            dc_id1, dc_id2 = join_id.split("--")

            if dc_id1 not in loaded_dfs:
                loaded_dfs[dc_id1] = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id1),
                    [e for e in metadata if e["metadata"]["dc_id"] == dc_id1],
                    TOKEN=TOKEN,
                )
            if dc_id2 not in loaded_dfs:
                loaded_dfs[dc_id2] = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id2),
                    [e for e in metadata if e["metadata"]["dc_id"] == dc_id2],
                    TOKEN=TOKEN,
                )

    # Initialize merged_df with the first join
    join_dict = joins[0]
    join_id, join_details = list(join_dict.items())[0]
    dc_id1, dc_id2 = join_id.split("--")

    # Merge based on common columns
    common_columns = list(
        set(loaded_dfs[dc_id1].columns).intersection(set(loaded_dfs[dc_id2].columns))
    )

    # Normalize join column types to ensure compatibility
    df1_normalized, df2_normalized = normalize_join_column_types(
        loaded_dfs[dc_id1], loaded_dfs[dc_id2], common_columns
    )

    merged_df = df1_normalized.join(df2_normalized, on=common_columns, how=join_details["how"])

    used_dfs = {dc_id1, dc_id2}

    # Perform remaining joins iteratively
    for join_dict in joins[1:]:
        for join_id, join_details in join_dict.items():
            dc_id1, dc_id2 = join_id.split("--")

            if dc_id2 not in used_dfs and dc_id2 in loaded_dfs:
                new_df = loaded_dfs[dc_id2]
                used_dfs.add(dc_id2)
            elif dc_id1 not in used_dfs and dc_id1 in loaded_dfs:
                new_df = loaded_dfs[dc_id1]
                used_dfs.add(dc_id1)
            else:
                continue

            common_columns = list(set(merged_df.columns).intersection(set(new_df.columns)))

            # Normalize join column types to ensure compatibility
            merged_df_normalized, new_df_normalized = normalize_join_column_types(
                merged_df, new_df, common_columns
            )

            merged_df = merged_df_normalized.join(
                new_df_normalized, on=common_columns, how=join_details["how"]
            )

    logger.debug(f"Join complete: merged_df shape: {merged_df.shape}")
    return merged_df
