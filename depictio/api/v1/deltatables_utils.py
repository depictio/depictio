import concurrent.futures
import itertools
import sys

import httpx
import polars as pl
from bson import ObjectId

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.s3 import polars_s3_config


# Function to add filter criteria to a list
def add_filter(
    filter_list,
    interactive_component_type,
    column_name,
    value,
    min_value=None,
    max_value=None,
):
    # logger.debug(f"filter_list: {filter_list}")
    # logger.info(f"interactive_component_type: {interactive_component_type}")
    # logger.info(f"column_name: {column_name}")
    # logger.info(f"value: {value}")
    # logger.info(f"min_value: {min_value}")
    # logger.info(f"max_value: {max_value}")

    if interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        if value:
            # Ensure value is a list for is_in() function
            if not isinstance(value, list):
                value = [value]
            logger.debug(
                f"Creating filter: column='{column_name}', values={value}, type={interactive_component_type}"
            )

            # Cast both the column and values to string to ensure type compatibility
            try:
                # Convert values to strings to match string casting
                string_values = [str(v) for v in value]
                filter_list.append(pl.col(column_name).cast(pl.String).is_in(string_values))
                logger.debug(f"Applied string casting for filter on column '{column_name}'")
            except Exception as e:
                logger.warning(
                    f"Failed to apply filter with string casting on column '{column_name}': {e}"
                )
                # Fallback to original filter without casting
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

                logger.debug(f"Applied date range filter on column '{column_name}'")
            except Exception as e:
                logger.warning(f"Failed to apply date range filter on column '{column_name}': {e}")


# Function to process metadata and build filter list
def process_metadata_and_filter(metadata):
    filter_list = []

    for i, component in enumerate(metadata):
        if "metadata" in component:
            # logger.info(f"Component {i} does not have metadata key : {component}")
            # continue
            # logger.info(f"i: {i}")
            # logger.info(f"component: {component}")
            interactive_component_type = component["metadata"]["interactive_component_type"]
            column_name = component["metadata"]["column_name"]
        else:
            interactive_component_type = component["interactive_component_type"]
            column_name = component["column_name"]
        # logger.info(f"interactive_component_type: {interactive_component_type}")
        # logger.info(f"column_name: {column_name}")
        value = component["value"]

        add_filter(
            filter_list,
            interactive_component_type=interactive_component_type,
            column_name=column_name,
            value=value,
        )

    # Apply the filters to the DataFrame
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


def _load_joined_deltatable(
    workflow_id: ObjectId,
    joined_data_collection_id: str,
    metadata: list[dict] | None = None,
    TOKEN: str | None = None,
    limit_rows: int | None = None,
    load_for_options: bool = False,
    load_for_preview: bool = False,
    select_columns: list[str] | None = None,
) -> pl.DataFrame:
    """
    Load and join data collections based on a joined data collection ID.

    Args:
        workflow_id (ObjectId): The ID of the workflow.
        joined_data_collection_id (str): Joined ID in format "dc1--dc2".
        metadata (Optional[list[dict]]): List of metadata dicts for filtering.
        TOKEN (Optional[str]): Authorization token.
        limit_rows (Optional[int]): Maximum number of rows to return.
        load_for_options (bool): Whether loading for component options.
        select_columns (Optional[list[str]]): Columns to select (applied after join).

    Returns:
        pl.DataFrame: The joined DataFrame.
    """
    logger.info(f"Loading joined data collection: {joined_data_collection_id}")

    # Parse the joined DC ID to get individual DC IDs
    dc_ids = joined_data_collection_id.split("--")
    if len(dc_ids) != 2:
        raise ValueError(f"Invalid joined data collection ID format: {joined_data_collection_id}")

    dc1_id, dc2_id = dc_ids

    # Get join configuration from the API
    try:
        joins_response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/get_dc_joined/{workflow_id}",
            headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {},
        )
        joins_response.raise_for_status()
        joins_data = joins_response.json()

        workflow_joins = joins_data.get(str(workflow_id), {})
        join_config = workflow_joins.get(joined_data_collection_id)

        if not join_config:
            raise ValueError(f"No join configuration found for {joined_data_collection_id}")

    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch join configuration: {e}")
        raise Exception("Error fetching join configuration") from e

    # CRITICAL FIX: Group metadata by dc_id to apply filters only to relevant dataframes
    # This prevents filters on columns that don't exist in both DCs from causing silent failures
    dc1_metadata = []
    dc2_metadata = []

    if metadata and not load_for_options:
        logger.debug(f"🔍 Grouping {len(metadata)} metadata items by dc_id for joined load")
        for meta_item in metadata:
            # Handle both nested and flat metadata structures
            if "metadata" in meta_item:
                item_dc_id = meta_item["metadata"].get("dc_id")
            else:
                item_dc_id = meta_item.get("dc_id")

            # Normalize dc_id to string for comparison
            item_dc_id_str = str(item_dc_id) if item_dc_id else None

            # Assign metadata to the correct DC
            if item_dc_id_str == dc1_id:
                dc1_metadata.append(meta_item)
                logger.debug(f"📌 Metadata for DC1 ({dc1_id}): {meta_item.get('value', 'N/A')}")
            elif item_dc_id_str == dc2_id:
                dc2_metadata.append(meta_item)
                logger.debug(f"📌 Metadata for DC2 ({dc2_id}): {meta_item.get('value', 'N/A')}")
            else:
                # Metadata doesn't match either DC - log warning
                logger.warning(
                    f"⚠️ Metadata with dc_id={item_dc_id_str} doesn't match DC1 ({dc1_id}) or DC2 ({dc2_id}) - skipping"
                )

        logger.info(
            f"✅ Metadata grouped: DC1={len(dc1_metadata)} filters, DC2={len(dc2_metadata)} filters"
        )
    else:
        logger.debug(
            f"⏭️  Skipping metadata grouping (load_for_options={load_for_options}, metadata={'present' if metadata else 'None'})"
        )

    # Load individual DataFrames with dc-specific metadata
    logger.debug(f"Loading DataFrame for DC1: {dc1_id} with {len(dc1_metadata)} filters")
    df1 = load_deltatable_lite(
        workflow_id=workflow_id,
        data_collection_id=ObjectId(dc1_id),
        metadata=dc1_metadata if dc1_metadata else None,
        TOKEN=TOKEN,
        limit_rows=None,  # Don't limit individual DFs before join
        load_for_options=load_for_options,
        load_for_preview=load_for_preview,
    )

    logger.debug(f"Loading DataFrame for DC2: {dc2_id} with {len(dc2_metadata)} filters")
    df2 = load_deltatable_lite(
        workflow_id=workflow_id,
        data_collection_id=ObjectId(dc2_id),
        metadata=dc2_metadata if dc2_metadata else None,
        TOKEN=TOKEN,
        limit_rows=None,  # Don't limit individual DFs before join
        load_for_options=load_for_options,
        load_for_preview=load_for_preview,
    )

    # Perform the join
    join_how = join_config.get("how", "inner")
    join_columns = join_config.get("on_columns", []).copy()

    if not join_columns:
        raise ValueError(f"No join columns specified for {joined_data_collection_id}")

    # Fetch metatypes for both data collections to determine join strategy
    # Only add depictio_run_id to join if BOTH collections are Aggregate type
    # For Metadata collections, drop depictio_run_id to avoid mismatches
    if "depictio_run_id" in df1.columns and "depictio_run_id" in df2.columns:
        try:
            from depictio.api.v1.db import data_collections_collection

            # Fetch data collections to get metatypes
            dc1_doc = data_collections_collection.find_one({"_id": ObjectId(dc1_id)})
            dc2_doc = data_collections_collection.find_one({"_id": ObjectId(dc2_id)})

            dc1_metatype = (
                dc1_doc.get("config", {}).get("metatype")
                if dc1_doc and "config" in dc1_doc
                else None
            )
            dc2_metatype = (
                dc2_doc.get("config", {}).get("metatype")
                if dc2_doc and "config" in dc2_doc
                else None
            )

            logger.debug(f"DC1 ({dc1_id}) metatype: {dc1_metatype}")
            logger.debug(f"DC2 ({dc2_id}) metatype: {dc2_metatype}")

            # Only add depictio_run_id to join keys if BOTH are explicitly Aggregate tables
            # SAFE DEFAULT: If metatype is None/missing, DON'T add depictio_run_id (prevents metadata join failures)
            both_aggregate = (
                dc1_metatype is not None
                and dc2_metatype is not None
                and dc1_metatype.lower() == "aggregate"
                and dc2_metatype.lower() == "aggregate"
            )

            if both_aggregate and "depictio_run_id" not in join_columns:
                join_columns.append("depictio_run_id")
                logger.debug(
                    f"✅ LoadJoinedDeltatable: Added depictio_run_id to join columns (both {dc1_id} and {dc2_id} are Aggregate tables)"
                )
            else:
                # Drop depictio_run_id from Metadata tables OR when metatype is unknown
                # This prevents join failures when collections have different depictio_run_id values
                if dc1_metatype is None or (dc1_metatype and dc1_metatype.lower() == "metadata"):
                    if "depictio_run_id" in df1.columns:
                        logger.debug(
                            f"🗑️ LoadJoinedDeltatable: Dropping depictio_run_id from DC1 {dc1_id} (metatype={dc1_metatype})"
                        )
                        df1 = df1.drop("depictio_run_id")

                if dc2_metatype is None or (dc2_metatype and dc2_metatype.lower() == "metadata"):
                    if "depictio_run_id" in df2.columns:
                        logger.debug(
                            f"🗑️ LoadJoinedDeltatable: Dropping depictio_run_id from DC2 {dc2_id} (metatype={dc2_metatype})"
                        )
                        df2 = df2.drop("depictio_run_id")

                logger.debug(
                    f"⏭️ LoadJoinedDeltatable: Skipped depictio_run_id join key (DC1 metatype={dc1_metatype}, DC2 metatype={dc2_metatype})"
                )

        except Exception as e:
            logger.warning(
                f"Failed to fetch metatypes for join decision: {e}. Using safe default (drop depictio_run_id)."
            )
            # Safe default: Drop depictio_run_id if we can't determine metatypes
            # This prevents join failures at the cost of potentially mixing runs (less common issue)
            if "depictio_run_id" in df1.columns:
                logger.debug(
                    "🗑️ LoadJoinedDeltatable: Dropping depictio_run_id from DC1 (fallback - metatype fetch failed)"
                )
                df1 = df1.drop("depictio_run_id")

            if "depictio_run_id" in df2.columns:
                logger.debug(
                    "🗑️ LoadJoinedDeltatable: Dropping depictio_run_id from DC2 (fallback - metatype fetch failed)"
                )
                df2 = df2.drop("depictio_run_id")

    logger.info(f"Joining DataFrames on columns {join_columns} using {join_how} join")
    logger.debug(f"DF1 shape: {df1.shape}, columns: {df1.columns}")
    logger.debug(f"DF2 shape: {df2.shape}, columns: {df2.columns}")

    try:
        # Normalize join column types to ensure compatibility
        df1, df2 = normalize_join_column_types(df1, df2, join_columns)

        # Perform the join using Polars
        joined_df = df1.join(df2, on=join_columns, how=join_how)
        logger.info(f"Successfully joined DataFrames. Result shape: {joined_df.shape}")

        # Apply column projection AFTER join (if specified)
        if select_columns:
            # Ensure join columns are included if not already specified
            columns_to_select = list(select_columns)
            for join_col in join_columns:
                if join_col not in columns_to_select:
                    columns_to_select.append(join_col)

            # Filter to only columns that exist in the joined DataFrame
            available_columns = [col for col in columns_to_select if col in joined_df.columns]
            if available_columns:
                joined_df = joined_df.select(available_columns)
                logger.debug(
                    f"Applied column projection after join: {len(available_columns)} columns"
                )

        # Apply row limit if specified
        if limit_rows:
            joined_df = joined_df.limit(limit_rows)
            logger.debug(f"Applied row limit: {limit_rows}")

        return joined_df

    except Exception as e:
        logger.error(f"Error during join operation: {e}")
        logger.error(f"DF1 columns: {df1.columns}")
        logger.error(f"DF2 columns: {df2.columns}")
        logger.error(f"Join columns: {join_columns}")
        raise Exception(f"Join operation failed: {str(e)}") from e


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


def load_deltatable_lite(
    workflow_id: ObjectId,
    data_collection_id: ObjectId | str,  # Allow string for joined DC IDs like "dc1--dc2"
    metadata: list[dict] | None = None,
    TOKEN: str | None = None,
    limit_rows: int | None = None,
    load_for_options: bool = False,  # New parameter to load unfiltered data for component options
    load_for_preview: bool = False,  # New parameter to separate preview cache from full data cache
    select_columns: list[str] | None = None,  # Column projection for efficient data loading
) -> pl.DataFrame:
    """
    Load a Delta table with adaptive memory management based on DataFrame size.

    ADAPTIVE MEMORY STRATEGY:
    - Small DataFrames (<1GB): Cached in memory for fast filtering
    - Large DataFrames (>=1GB): Always use lazy loading to prevent OOM

    COLUMN PROJECTION:
    - Specify select_columns to load only needed columns (10-50x I/O reduction for wide tables)
    - Projection happens at scan level (Polars predicate pushdown)
    - For joined DCs, projection applied after join to preserve join columns

    Supports both regular data collection IDs and joined data collection IDs (format: "dc1--dc2").

    Args:
        workflow_id (ObjectId): The ID of the workflow.
        data_collection_id (ObjectId | str): The ID of the data collection or joined ID like "dc1--dc2".
        metadata (Optional[list[dict]], optional): List of metadata dicts for filtering the DataFrame. Defaults to None.
        TOKEN (Optional[str], optional): Authorization token. Defaults to None.
        limit_rows (Optional[int], optional): Maximum number of rows to return. Defaults to None.
        load_for_options (bool): Whether loading unfiltered data for component options.
        load_for_preview (bool): Whether loading for preview (separate cache).
        select_columns (Optional[list[str]]): Columns to select for projection (None = all columns).

    Returns:
        pl.DataFrame: The loaded and optionally filtered DataFrame.

    Raises:
        Exception: If the HTTP request to load the Delta table fails.
    """
    # Check if this is a joined data collection ID
    data_collection_id_str = str(data_collection_id)
    if isinstance(data_collection_id, str) and "--" in data_collection_id:
        # Handle joined data collection - pass column selection through
        logger.info(f"Loading joined data collection: {data_collection_id}")
        return _load_joined_deltatable(
            workflow_id,
            data_collection_id,
            metadata,
            TOKEN,
            limit_rows,
            load_for_options,
            load_for_preview,
            select_columns,
        )

    # Convert ObjectId to string for regular data collections
    workflow_id_str = str(workflow_id)
    data_collection_id_str = str(data_collection_id)

    # CACHE STATUS: Check both Redis and memory cache
    try:
        from depictio.api.cache import get_cache_stats

        cache_stats = get_cache_stats()
        total_cached = cache_stats.get("redis_keys", 0) + cache_stats.get("memory_keys", 0)
        total_memory = cache_stats.get("redis_memory_used_mb", 0) + cache_stats.get(
            "memory_size_mb", 0
        )
        logger.info(
            f"📊 CACHE STATUS: {total_cached} DataFrames cached ({cache_stats.get('redis_keys', 0)} Redis + {cache_stats.get('memory_keys', 0)} Memory), {total_memory:.1f}MB"
        )
    except Exception:
        # Fallback to old method if Redis cache not available
        logger.info(
            f"📊 CACHE STATUS: {len(_dataframe_memory_cache)} DataFrames cached, {sum(sys.getsizeof(df) for df in _dataframe_memory_cache.values()) / 1024 / 1024:.1f}MB"
        )

    # PERFORMANCE OPTIMIZATION: Early cache check to skip expensive operations
    # Separate cache keys for preview vs full data to prevent conflicts
    # Include column selection in cache key to avoid conflicts between different projections
    cache_suffix = "preview" if load_for_preview else "base"
    if select_columns:
        # Create deterministic string from sorted column list
        columns_key = "_".join(sorted(select_columns))
        base_cache_key = (
            f"{workflow_id_str}_{data_collection_id_str}_{cache_suffix}_cols_{columns_key}"
        )
    else:
        base_cache_key = f"{workflow_id_str}_{data_collection_id_str}_{cache_suffix}"
    logger.debug(
        f"🔑 Generated cache key: {base_cache_key} (load_for_preview={load_for_preview}, columns={len(select_columns) if select_columns else 'all'})"
    )

    # REDIS INTEGRATION: Check Redis cache first, then fallback to memory
    try:
        from depictio.api.cache import get_cached_dataframe

        redis_cached_df = get_cached_dataframe(base_cache_key)
        if redis_cached_df is not None:
            logger.info(f"🚀 REDIS CACHE HIT: Skipping DB/HTTP calls for key: {base_cache_key}")
            logger.info(
                f"📊 CACHED DATAFRAME SIZE: {redis_cached_df.height:,} rows × {redis_cached_df.width} columns"
            )

            # Apply column projection first (if specified and not already applied in cache)
            if select_columns and not any(
                col for col in select_columns if col not in redis_cached_df.columns
            ):
                # All requested columns exist - apply projection
                df = redis_cached_df.select(select_columns)
                logger.debug(f"Applied column projection from cache: {len(select_columns)} columns")
            else:
                df = redis_cached_df

            # DEBUG: Check filter application conditions
            logger.debug(
                f"🔍 PRE-FILTER CHECK: metadata={metadata is not None}, "
                f"load_for_options={load_for_options}, "
                f"metadata_len={len(metadata) if metadata else 0}"
            )

            # Apply metadata filters in memory (very fast)
            if metadata and not load_for_options:
                logger.info(f"🎯 APPLYING FILTERS: {len(metadata)} filter(s) to cached DataFrame")
                df = apply_runtime_filters(df, metadata)
                logger.info(f"📊 AFTER FILTERS: {df.height:,} rows × {df.width} columns")
            else:
                logger.debug("⏭️  SKIPPING FILTERS: metadata empty or load_for_options=True")

            # Apply row limit AFTER filters
            if limit_rows:
                df = df.limit(limit_rows)
                logger.debug(f"Applied row limit: {limit_rows}")

            # Drop the 'depictio_aggregation_time' column if it exists
            if "depictio_aggregation_time" in df.columns:
                df = df.drop("depictio_aggregation_time")
                logger.debug("Dropped 'depictio_aggregation_time' column.")

            logger.debug(f"Final DataFrame shape: {df.height} rows x {df.width} columns")
            return df
    except Exception as e:
        logger.debug(f"Redis cache check failed, falling back to memory: {e}")

    # Fallback to existing memory cache
    if base_cache_key in _dataframe_memory_cache:
        logger.info(f"💾 MEMORY CACHE HIT: Skipping DB/HTTP calls for key: {base_cache_key}")
        update_cache_timestamp(base_cache_key)

        # Get cached DataFrame and apply column projection if needed
        cached_df = _dataframe_memory_cache[base_cache_key]
        logger.info(
            f"📊 MEMORY CACHED DATAFRAME SIZE: {cached_df.height:,} rows × {cached_df.width} columns"
        )

        # Apply column projection first (if specified and not already applied in cache)
        if select_columns and not any(
            col for col in select_columns if col not in cached_df.columns
        ):
            df = cached_df.select(select_columns)
            logger.debug(
                f"Applied column projection from memory cache: {len(select_columns)} columns"
            )
        else:
            df = cached_df

        # Apply metadata filters in memory (very fast)
        if metadata and not load_for_options:
            df = apply_runtime_filters(df, metadata)
            logger.debug(f"📊 AFTER FILTERS: {df.height:,} rows × {df.width} columns")

        # Apply row limit AFTER filters to avoid limiting joined data prematurely
        if limit_rows:
            df = df.limit(limit_rows)
            logger.debug(f"Applied row limit: {limit_rows}")

        return df

    # ADAPTIVE MEMORY MANAGEMENT - Check DataFrame size first (only for cache misses)
    data_collection_id_obj = (
        ObjectId(data_collection_id) if isinstance(data_collection_id, str) else data_collection_id
    )
    size_bytes = get_deltatable_size_from_db(data_collection_id_obj)

    if size_bytes > 0:
        logger.debug(
            f"Loading deltatable {data_collection_id_str}: size={size_bytes} bytes ({size_bytes / (1024 * 1024):.2f} MB)"
        )
    else:
        logger.debug(
            f"Loading deltatable {data_collection_id_str}: size unknown, will estimate dynamically"
        )

    # Prepare the request URL and headers
    url = f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{data_collection_id_str}"
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

    # Make the HTTP GET request to fetch the Delta table location
    try:
        response = httpx.get(url, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(
            f"HTTP error loading deltatable for workflow {workflow_id_str} "
            f"and data collection {data_collection_id_str}: {e}"
        )
        raise Exception("Error loading deltatable") from e

    # Extract the file ID from the response
    file_id = response.json().get("delta_table_location")
    if not file_id:
        logger.error(
            f"No 'delta_table_location' found in response for workflow {workflow_id_str} "
            f"and data collection {data_collection_id_str}: {response.json()}"
        )
        raise Exception("Invalid response: missing 'delta_table_location'")

    # Initialize the Delta table scan
    delta_scan = pl.scan_delta(file_id, storage_options=polars_s3_config)

    # COLUMN PROJECTION: Apply column selection at scan level for efficient I/O
    # This is predicate pushdown - only read specified columns from storage
    if select_columns:
        # Filter to only columns that exist (defensive programming)
        # Note: We can't validate columns at scan time, so we'll let Polars handle errors
        delta_scan = delta_scan.select(select_columns)
        logger.debug(f"Applied column projection at scan level: {len(select_columns)} columns")

    # ADAPTIVE LOADING STRATEGY
    if size_bytes == -1:
        # UNKNOWN SIZE: Use dynamic estimation approach
        logger.debug(
            "Unknown DataFrame size - will estimate dynamically and decide caching strategy"
        )

        # CACHE MISS: Load DataFrame and estimate size dynamically
        logger.info(f"❌ CACHE MISS: Loading DataFrame from storage for key: {base_cache_key}")
        logger.debug("Loading DataFrame for dynamic size estimation")

        # Apply row limit to scan if specified
        if limit_rows:
            delta_scan = delta_scan.limit(limit_rows)
            logger.debug(f"Applied row limit: {limit_rows}")

        # Collect the FULL DataFrame first (no filters) to get accurate size and cache the full data
        try:
            df = delta_scan.collect()
            # LOG RAW DATAFRAME SHAPE IMMEDIATELY AFTER LOADING
            logger.info(
                f"📊 RAW DATAFRAME LOADED: {df.height:,} rows × {df.width} columns (DC: {data_collection_id_str})"
            )
            logger.debug(f"RAW DataFrame columns: {df.columns}")
            # Use Polars' estimated_size method if available, fallback to rough estimation
            if hasattr(df, "estimated_size"):
                actual_size = df.estimated_size("b")
            else:
                # Fallback: rough estimate based on shape and data types
                actual_size = df.height * df.width * 8  # 8 bytes per cell average

            logger.debug(
                f"Estimated DataFrame size: {actual_size} bytes ({actual_size / (1024 * 1024):.2f} MB)"
            )

            # Cache the FULL DataFrame if small enough
            if actual_size <= MEMORY_THRESHOLD_BYTES:
                import time

                logger.debug(
                    f"DataFrame is small ({actual_size / (1024 * 1024):.2f} MB), caching full dataset for future use"
                )

                # Try to cache in Redis first (persistent across page refreshes)
                try:
                    from depictio.api.cache import cache_dataframe

                    if cache_dataframe(base_cache_key, df):
                        logger.debug(
                            f"✅ Redis cached: {base_cache_key} ({actual_size / (1024 * 1024):.2f} MB)"
                        )
                except Exception as e:
                    logger.debug(f"Redis caching failed: {e}")

                # Also cache in memory (faster access during session)
                _dataframe_memory_cache[base_cache_key] = df
                _cache_metadata[base_cache_key] = {
                    "size_bytes": actual_size,
                    "timestamp": time.time(),
                }
                global _total_memory_usage
                _total_memory_usage += actual_size
            else:
                logger.debug(
                    f"DataFrame is large ({actual_size / (1024 * 1024):.2f} MB), not caching"
                )

        except Exception as e:
            logger.error(f"Error collecting Delta table data: {e}")
            raise Exception("Error collecting Delta table data") from e

        # Apply metadata filters IN MEMORY after loading (preserves full dataset in cache)
        if metadata and not load_for_options:
            logger.debug("Applying metadata filters in memory after loading full dataset")
            df = apply_runtime_filters(df, metadata)

    elif size_bytes <= MEMORY_THRESHOLD_BYTES:
        # SMALL DATAFRAME: Use memory caching for fast filtering
        logger.debug(
            f"Small DataFrame ({size_bytes / (1024 * 1024):.2f} MB) - using memory caching"
        )

        # CACHE MISS: Load and cache the small DataFrame
        logger.info(
            f"❌ [SMALL DF] CACHE MISS: Loading DataFrame from storage for key: {base_cache_key}"
        )
        logger.debug(f"Loading and caching DataFrame: {base_cache_key}")

        # Apply row limit to scan if specified
        if limit_rows:
            delta_scan = delta_scan.limit(limit_rows)
            logger.debug(f"Applied row limit: {limit_rows}")

        # Load and cache the base DataFrame (no filters)
        df = load_and_cache_dataframe(base_cache_key, size_bytes, delta_scan)

        # Apply metadata filters in memory after caching
        if metadata and not load_for_options:
            df = apply_runtime_filters(df, metadata)

    else:
        # LARGE DATAFRAME: Always use lazy loading to prevent memory issues
        logger.debug(f"Large DataFrame ({size_bytes / (1024 * 1024):.2f} MB) - using lazy loading")

        # Apply filtering if metadata is provided and not loading for options
        if metadata and not load_for_options:
            filter_expressions = process_metadata_and_filter(metadata)
            logger.debug(f"Filter expressions: {filter_expressions}")

            if filter_expressions:
                combined_filter = filter_expressions[0]
                for filt in filter_expressions[1:]:
                    combined_filter &= filt
                delta_scan = delta_scan.filter(combined_filter)
                logger.debug("Applied filters to lazy scan.")
        elif load_for_options:
            logger.debug("Skipping filters - loading unfiltered data for component options")

        if limit_rows:
            delta_scan = delta_scan.limit(limit_rows)
            logger.debug(f"Applied row limit: {limit_rows}")

        # Collect the DataFrame (materialization happens here)
        try:
            df = delta_scan.collect()
            # LOG RAW DATAFRAME SHAPE IMMEDIATELY AFTER LOADING (LARGE DF PATH)
            logger.info(
                f"📊 RAW DATAFRAME LOADED (LARGE): {df.height:,} rows × {df.width} columns (DC: {data_collection_id_str})"
            )
            logger.debug(f"RAW DataFrame columns: {df.columns}")
        except Exception as e:
            logger.error(f"Error collecting Delta table data: {e}")
            raise Exception("Error collecting Delta table data") from e

    # Drop the 'depictio_aggregation_time' column if it exists
    if "depictio_aggregation_time" in df.columns:
        df = df.drop("depictio_aggregation_time")
        logger.debug("Dropped 'depictio_aggregation_time' column.")

    logger.debug(f"Final DataFrame shape: {df.height} rows x {df.width} columns")
    return df


def merge_multiple_dataframes(
    dataframes: dict[str, pl.DataFrame],
    join_instructions: list[dict],
    essential_cols: set[str] = set(),
    dc_metatypes: dict[str, str] | None = None,
) -> pl.DataFrame:
    """
    Merge multiple Polars DataFrames based on join instructions, handling type alignment and overlapping columns.

    Parameters:
    - dataframes: Dict[str, pl.DataFrame]
        A dictionary mapping unique DataFrame identifiers to Polars DataFrames.
    - join_instructions: List[Dict]
        A list where each element is a dictionary specifying a join step with the following keys:
            - 'left': str - Identifier of the left DataFrame.
            - 'right': str - Identifier of the right DataFrame.
            - 'how': str - Type of join ('inner', 'left', 'right', 'outer', etc.).
            - 'on': List[str] - Columns to join on.
    - essential_cols: Set[str] (optional)
        A set of column names that should not be renamed during the join process to preserve their integrity.
    - dc_metatypes: Dict[str, str] (optional)
        A dictionary mapping DC IDs to their metatype ('Metadata' or 'Aggregate').
        Used to determine whether to include depictio_run_id in join keys.
        If not provided, depictio_run_id will be included by default when present in both DataFrames.
    - logger: logging.Logger (optional)
        A logger instance for logging information and warnings. If not provided, a default logger is created.

    Returns:
    - pl.DataFrame
        The final merged DataFrame after performing all join operations.
    """

    # Define metadata columns that should never be join keys
    # These are timestamp/tracking columns that may differ between tables
    METADATA_COLS_EXCLUDE = {
        "aggregation_time",
        "depictio_aggregation_time",
        "timestamp",
        "created_at",
        "updated_at",
    }

    logger.info("Starting the merge process.")

    # Step 1: Determine Common Column Types
    logger.debug("Aligning column types across all DataFrames.")
    column_types = {}

    for df_id, df in dataframes.items():
        for col, dtype in df.schema.items():
            if col not in column_types:
                column_types[col] = dtype
            else:
                # Determine the most general type
                current_type = column_types[col]
                if current_type != dtype:
                    # Define rules for type promotion
                    if pl.Utf8 in {current_type, dtype}:
                        column_types[col] = pl.Utf8
                    elif pl.Float64 in {current_type, dtype}:
                        column_types[col] = pl.Float64
                    elif pl.Int64 in {current_type, dtype}:
                        column_types[col] = pl.Int64
                    elif pl.Boolean in {current_type, dtype}:
                        column_types[col] = pl.Boolean
                    else:
                        # Default to Utf8 for complex type mismatches
                        column_types[col] = pl.Utf8
                    logger.debug(f"Column '{col}' type promoted to {column_types[col]}.")

    logger.debug(f"Common column types determined: {column_types}")

    # Step 2: Cast Columns to Common Types
    for df_id, df in dataframes.items():
        cast_columns = []
        for col, desired_dtype in column_types.items():
            if col in df.columns and df[col].dtype != desired_dtype:
                cast_columns.append(pl.col(col).cast(desired_dtype))
                logger.debug(
                    f"Casting column '{col}' in DataFrame '{df_id}' from {df[col].dtype} to {desired_dtype}."
                )
        if cast_columns:
            dataframes[df_id] = df.with_columns(cast_columns)
            logger.debug(f"DataFrame '{df_id}' columns casted to common types.")

    # Step 3: Perform Joins
    merged_df = None
    dc_ids_processed = set()
    if not join_instructions:
        logger.debug("No join instructions provided. Returning the first DataFrame.")
        return next(iter(dataframes.values()))
    for idx, join_step in enumerate(join_instructions, start=1):
        left_id = join_step["left"]
        right_id = join_step["right"]
        how = join_step["how"]
        on = join_step["on"].copy()  # Make a copy to modify

        # Handle depictio_run_id based on table types (Metadata vs Aggregate)
        # Only include depictio_run_id in join when BOTH tables are Aggregate type
        # For Metadata tables, drop depictio_run_id to avoid mismatches (auto-generated values)
        if merged_df is None:
            left_df = dataframes[left_id]
        else:
            left_df = merged_df
        right_df = dataframes[right_id]

        # Check if depictio_run_id exists in both DataFrames
        if "depictio_run_id" in left_df.columns and "depictio_run_id" in right_df.columns:
            # Get metatypes for both DCs (default to None if not provided)
            left_metatype = dc_metatypes.get(left_id) if dc_metatypes else None
            right_metatype = dc_metatypes.get(right_id) if dc_metatypes else None

            # Only add depictio_run_id to join keys if BOTH are Aggregate tables
            both_aggregate = (
                left_metatype
                and right_metatype
                and left_metatype.lower() == "aggregate"
                and right_metatype.lower() == "aggregate"
            )

            if both_aggregate and "depictio_run_id" not in on:
                on.append("depictio_run_id")
                logger.debug(
                    f"✅ Added depictio_run_id to join keys (both {left_id} and {right_id} are Aggregate tables)"
                )
            elif not both_aggregate and dc_metatypes:
                # Drop depictio_run_id from Metadata tables to avoid mismatches
                # Keep it in Aggregate tables
                if left_metatype and left_metatype.lower() == "metadata":
                    logger.debug(
                        f"🗑️ Dropping depictio_run_id from left table {left_id} (Metadata table)"
                    )
                    left_df = left_df.drop("depictio_run_id")
                    if merged_df is None:
                        dataframes[left_id] = left_df
                    else:
                        merged_df = left_df

                if right_metatype and right_metatype.lower() == "metadata":
                    logger.debug(
                        f"🗑️ Dropping depictio_run_id from right table {right_id} (Metadata table)"
                    )
                    right_df = right_df.drop("depictio_run_id")
                    dataframes[right_id] = right_df

                logger.debug(
                    f"⏭️ Skipped depictio_run_id join key ({left_id}={left_metatype}, {right_id}={right_metatype})"
                )
            elif "depictio_run_id" not in on and not dc_metatypes:
                # Fallback: If metatypes not provided, include depictio_run_id (backward compatibility)
                on.append("depictio_run_id")
                logger.debug(
                    "⚠️ Added depictio_run_id to join keys (metatypes not provided - backward compatibility)"
                )

        logger.debug(
            f"Join Step {idx}: '{left_id}' {how} joined with '{right_id}' on columns {on}."
        )

        if right_id in dc_ids_processed:
            logger.debug(f"Skipping join with '{right_id}' as it has already been processed.")
            continue

        # Identify overlapping columns excluding join keys
        overlapping_cols = set(left_df.columns).intersection(set(right_df.columns)) - set(on)

        logger.debug(f"Overlapping columns detected: {overlapping_cols}")

        # Determine overlapping essential columns
        overlapping_essential_cols = overlapping_cols.intersection(essential_cols)

        logger.debug(f"Overlapping essential columns detected: {overlapping_essential_cols}")

        # FIX: Exclude metadata columns from being added as join keys
        # Only add essential columns that aren't metadata timestamps
        if overlapping_essential_cols:
            cols_to_add = overlapping_essential_cols - METADATA_COLS_EXCLUDE
            if cols_to_add:
                logger.debug(f"Adding essential overlapping columns to join keys: {cols_to_add}")
                on += list(cols_to_add)

        # Handle metadata overlapping columns by dropping them from right_df
        # These columns may have different values (timestamps) and shouldn't be join keys
        metadata_overlap = overlapping_cols & METADATA_COLS_EXCLUDE
        if metadata_overlap:
            logger.debug(f"Dropping metadata columns from right DataFrame: {metadata_overlap}")
            right_df = right_df.drop(list(metadata_overlap))
            # Update the dataframes dict
            dataframes[right_id] = right_df
        #     # # Drop these columns from the right DataFrame to prevent duplication
        #     # right_df = right_df.drop(list(overlapping_essential_cols))
        #     # logger.info(f"Dropped overlapping essential columns {overlapping_essential_cols} from right DataFrame '{right_id}'.")

        # logger.info(f"Columns to join on after adding overlapping essential columns: {on}")

        # # Re-identify overlapping columns after adding essential columns to 'on'
        # overlapping_cols = set(left_df.columns).intersection(set(right_df.columns)) - set(on)
        # logger.info(f"Remaining overlapping columns after adjusting join keys: {overlapping_cols}")

        # # Handle overlapping non-essential columns by dropping them from the right DataFrame
        # if overlapping_cols:
        #     logger.info(f"Overlapping non-essential columns detected: {overlapping_cols}. Dropping from right DataFrame '{right_id}'.")
        #     right_df = right_df.drop(list(overlapping_cols))
        #     dataframes[right_id] = right_df  # Update the DataFrame in the dictionary

        #     logger.info(f"Dropped overlapping non-essential columns from '{right_id}'. Remaining columns: {right_df.columns}")

        # Perform the join using Polars' join method
        try:
            logger.debug(
                f"Performing '{how}' join between left DataFrame and '{right_id}' on columns: {on}."
            )
            logger.debug(f"Left DataFrame shape: {left_df.shape} and columns: {left_df.columns}")
            logger.debug(
                f"Right DataFrame '{right_id}' shape: {right_df.shape} and columns: {right_df.columns}"
            )

            # Diagnostic logging to debug join failures
            logger.debug(f"🔍 JOIN DIAGNOSTIC - Join columns: {on}")
            if "sample" in on and "sample" in left_df.columns and "sample" in right_df.columns:
                left_samples = left_df.select("sample").unique().to_series().to_list()
                right_samples = right_df.select("sample").unique().to_series().to_list()
                logger.debug(f"🔍 Left sample values ({len(left_samples)}): {left_samples[:10]}")
                logger.debug(f"🔍 Right sample values ({len(right_samples)}): {right_samples[:10]}")
            if (
                "depictio_run_id" in on
                and "depictio_run_id" in left_df.columns
                and "depictio_run_id" in right_df.columns
            ):
                left_run_ids = left_df.select("depictio_run_id").unique().to_series().to_list()
                right_run_ids = right_df.select("depictio_run_id").unique().to_series().to_list()
                logger.debug(f"🔍 Left depictio_run_id values: {left_run_ids}")
                logger.debug(f"🔍 Right depictio_run_id values: {right_run_ids}")

            if merged_df is None:
                # Initial merge
                merged_df = left_df.join(right_df, on=on, how=how)
                logger.debug(
                    f"Joined '{left_id}' and '{right_id}'. Merged DataFrame shape: {merged_df.shape}"
                )

                # Warn if join returned 0 rows
                if merged_df.height == 0:
                    logger.warning("⚠️ JOIN RETURNED 0 ROWS - No matching values found!")
                    logger.warning(f"⚠️ Check if {on} column values match between tables")
            else:
                # Subsequent merges
                merged_df = left_df.join(right_df, on=on, how=how)
                logger.debug(f"Joined with '{right_id}'. Merged DataFrame shape: {merged_df.shape}")
            dc_ids_processed.add(left_id)
            dc_ids_processed.add(right_id)
        except Exception as e:
            logger.error(f"Error during join between '{left_id}' and '{right_id}': {e}")
            raise

    logger.info("All join operations completed.")

    # Step 4: Verify Essential Columns
    missing_essentials = essential_cols - set(merged_df.columns)  # type: ignore[possibly-unbound-attribute]
    if missing_essentials:
        logger.warning(f"Essential columns missing from the final DataFrame: {missing_essentials}")

    logger.debug(f"Final merged DataFrame shape: {merged_df.shape}")  # type: ignore[possibly-unbound-attribute]
    logger.debug(f"Final merged DataFrame columns: {merged_df.columns}")  # type: ignore[possibly-unbound-attribute]

    return merged_df  # type: ignore[invalid-return-type]


def transform_joins_dict_to_instructions(
    joins_dict: dict[tuple, list[dict]],
) -> list[dict]:
    """
    Transform joins_dict into a list of join instructions compatible with merge_multiple_dataframes.

    Parameters:
    - joins_dict: Dict[tuple, List[Dict]]
        The original joins_dict structure.

    Returns:
    - List[Dict]
        A list of join instructions.
    """
    join_instructions = []
    for join_key_tuple, join_list in joins_dict.items():
        for join in join_list:
            for join_id, join_details in join.items():
                dc_id1, dc_id2 = join_id.split("--")
                instruction = {
                    "left": dc_id1,
                    "right": dc_id2,
                    "how": join_details["how"],
                    "on": join_details["on_columns"],
                }
                join_instructions.append(instruction)
    return join_instructions


def compute_essential_columns(dataframes: dict[str, pl.DataFrame]) -> set[str]:
    """
    Compute essential columns as those appearing in more than one DataFrame.

    Parameters:
    - dataframes: Dict[str, pl.DataFrame]
        A dictionary mapping DataFrame identifiers to Polars DataFrames.

    Returns:
    - Set[str]
        A set of column names that are present in multiple DataFrames.
    """
    from collections import defaultdict

    column_counts = defaultdict(int)
    for df in dataframes.values():
        for col in df.columns:
            column_counts[col] += 1

    # Essential columns are those appearing in two or more DataFrames
    essential_cols = {col for col, count in column_counts.items() if count > 1}
    return essential_cols


# def iterative_join(workflow_id: ObjectId, joins_dict: dict, metadata_dict: dict, TOKEN: str = None):
#     logger.info(f"workflow_id: {workflow_id}")
#     logger.info(f"joins_dict: {joins_dict}")
#     logger.info(f"metadata_dict: {metadata_dict}")

#     # Extract interactive components
#     interactive_components_list = [metadata for metadata in metadata_dict.values() if metadata.get("component_type") == "interactive"]
#     logger.info(f"Interactive components: {interactive_components_list}")

#     # If no joins are specified, load a single DataFrame
#     if not joins_dict:
#         first_dc_id = next(iter(metadata_dict.keys()))["metadata"]["dc_id"]
#         return load_deltatable_lite(workflow_id, first_dc_id, interactive_components_list, TOKEN=TOKEN)

#     # Initialize dictionary to store loaded DataFrames
#     loaded_dfs = {}
#     used_dcs = set()

#     # Load all necessary DataFrames based on joins_dict
#     for join_key_tuple in joins_dict.keys():
#         for dc_id in join_key_tuple:
#             if dc_id not in loaded_dfs:
#                 logger.info(f"Loading DataFrame for dc_id: {dc_id}")
#                 # Filter metadata for the current dc_id
#                 relevant_metadata = [md for md in metadata_dict.values() if md["metadata"]["dc_id"] == dc_id]
#                 logger.info(f"Relevant metadata for dc_id {dc_id}: {relevant_metadata}")
#                 # Load the DataFrame
#                 loaded_dfs[dc_id] = load_deltatable_lite(workflow_id, dc_id, relevant_metadata, TOKEN=TOKEN)
#                 logger.info(f"Loaded DataFrame for dc_id {dc_id} with shape: {loaded_dfs[dc_id].shape}")
#                 logger.info(f"Loaded DataFrame columns: {loaded_dfs[dc_id].columns}")

#     # Transform joins_dict to join_instructions
#     join_instructions = transform_joins_dict_to_instructions(joins_dict)
#     logger.info(f"Join instructions: {join_instructions}")

#     # Compute essential_cols dynamically
#     essential_cols = compute_essential_columns(loaded_dfs)
#     logger.info(f"Essential columns determined: {essential_cols}")

#     # Perform the merge using the updated generic function
#     merged_df = merge_multiple_dataframes(
#         dataframes=loaded_dfs,
#         join_instructions=join_instructions,
#         essential_cols=essential_cols,
#     )
#     return merged_df


# Cache for loaded DataFrames to avoid redundant loading
_iterative_join_cache = {}

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

    # Calculate actual size
    actual_size = df.estimated_size("b") if hasattr(df, "estimated_size") else size_bytes

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
    if filter_expressions:
        try:
            # Apply filters using Polars expressions on materialized DataFrame
            combined_filter = filter_expressions[0]
            for filt in filter_expressions[1:]:
                combined_filter &= filt
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


def iterative_join(
    workflow_id: ObjectId,
    joins_dict: dict,
    metadata_dict: dict,
    TOKEN: str | None = None,
    dc_type_mapping: dict[str, str] | None = None,
):
    # Create cache key for this specific join operation
    cache_key = f"{workflow_id}_{hash(str(joins_dict))}_{hash(str(metadata_dict))}"

    if cache_key in _iterative_join_cache:
        # logger.debug(f"IterativeJoin: Using cached result for workflow {workflow_id}")
        return _iterative_join_cache[cache_key]

    # logger.debug(
    #     f"IterativeJoin: Processing workflow {workflow_id} with {len(joins_dict)} join groups"
    # )
    logger.debug(f"Joins dict: {joins_dict}")
    logger.debug(f"Metadata dict: {metadata_dict}")
    logger.debug(f"DC type mapping: {dc_type_mapping}")

    # Optimize: Pre-filter interactive components once
    interactive_components_list = [
        metadata
        for metadata in metadata_dict.values()
        if metadata.get("component_type") == "interactive"
    ]

    if not joins_dict:
        dc_id = next(iter(metadata_dict.values()))["metadata"]["dc_id"]

        # Check if this is a non-table type (multiqc, jbrowse) that doesn't use deltatables
        if dc_type_mapping:
            normalized_mapping = {str(k): v for k, v in dc_type_mapping.items()}
            dc_type = normalized_mapping.get(str(dc_id), "table")
            if dc_type in ["multiqc", "jbrowse"]:
                logger.info(
                    f"IterativeJoin: Skipping deltatable load for {dc_type} dc_id {dc_id} (no joins required)"
                )
                # Return empty dataframe for non-table types
                import polars as pl

                result = pl.DataFrame()
                _iterative_join_cache[cache_key] = result
                return result

        result = load_deltatable_lite(
            workflow_id,
            dc_id,
            interactive_components_list,
            TOKEN=TOKEN,
        )
        _iterative_join_cache[cache_key] = result
        return result

    # Optimize: Collect all unique data collection IDs upfront
    all_dc_ids = set()
    for join_key_tuple in joins_dict.keys():
        all_dc_ids.update(join_key_tuple)

    # Filter out non-table dc_ids (jbrowse, multiqc) that don't have deltatable storage
    if dc_type_mapping:
        # Normalize mapping keys to strings for consistent lookup
        normalized_mapping = {str(k): v for k, v in dc_type_mapping.items()}
        logger.debug(f"IterativeJoin: Normalized dc_type_mapping: {normalized_mapping}")

        table_dc_ids = {
            dc_id for dc_id in all_dc_ids if normalized_mapping.get(str(dc_id), "table") == "table"
        }
        excluded_dc_ids = all_dc_ids - table_dc_ids
        if excluded_dc_ids:
            logger.info(
                f"IterativeJoin: Excluding non-table dc_ids from deltatable loading: {excluded_dc_ids}"
            )
        all_dc_ids = table_dc_ids

        # Also filter joins_dict to remove any joins involving non-table dc_ids
        filtered_joins_dict = {}
        for join_key_tuple, join_list in joins_dict.items():
            # Only keep this join group if ALL dc_ids in the tuple are table types
            if all(dc_id in table_dc_ids for dc_id in join_key_tuple):
                filtered_joins_dict[join_key_tuple] = join_list
            else:
                logger.debug(
                    f"IterativeJoin: Filtering out join group {join_key_tuple} (contains non-table dc_ids)"
                )
        joins_dict = filtered_joins_dict
        logger.info(f"IterativeJoin: After filtering, {len(joins_dict)} join groups remain")
    else:
        logger.warning(
            "IterativeJoin: No dc_type_mapping provided, attempting to load all dc_ids as tables"
        )

    # Check if we have any joins left after filtering
    if not joins_dict:
        logger.warning("IterativeJoin: No valid joins remaining after filtering non-table dc_ids")
        # Return the first available loaded dataframe or empty result
        if all_dc_ids:
            # Double-check that first_dc_id is actually a table type
            first_dc_id = next(iter(all_dc_ids))
            if dc_type_mapping:
                normalized_mapping = {str(k): v for k, v in dc_type_mapping.items()}
                dc_type = normalized_mapping.get(str(first_dc_id), "table")
                if dc_type != "table":
                    logger.warning(
                        f"IterativeJoin: Filtered dc_id {first_dc_id} is type {dc_type}, returning empty dataframe"
                    )
                    import polars as pl

                    result = pl.DataFrame()
                    _iterative_join_cache[cache_key] = result
                    return result

            result = load_deltatable_lite(
                workflow_id,
                first_dc_id,
                interactive_components_list,
                TOKEN=TOKEN,
            )
            _iterative_join_cache[cache_key] = result
            return result
        else:
            logger.info(
                "IterativeJoin: No table-type data collections available, returning empty dataframe"
            )
            import polars as pl

            result = pl.DataFrame()
            _iterative_join_cache[cache_key] = result
            return result

    # logger.debug(f"IterativeJoin: Loading {len(all_dc_ids)} unique data collections")

    # Initialize containers
    loaded_dfs = {}
    used_dcs = set()

    # Optimize: Pre-group metadata by dc_id for efficient lookup
    metadata_by_dc_id = {}
    component_values = {}  # Track individual component values for debugging

    for component_id, metadata in metadata_dict.items():
        dc_id = metadata["metadata"]["dc_id"]
        if dc_id not in metadata_by_dc_id:
            metadata_by_dc_id[dc_id] = []
        metadata_by_dc_id[dc_id].append(metadata)
        component_values[component_id] = {
            "dc_id": dc_id,
            "value": metadata["value"],
            "component_type": metadata.get("component_type", "unknown"),
        }

    # logger.debug(f"IterativeJoin: Component values breakdown: {component_values}")
    # logger.debug(f"IterativeJoin: Metadata by dc_id: {list(metadata_by_dc_id.keys())}")

    # Load all necessary dataframes concurrently (optimized)

    # Prepare loading tasks
    loading_tasks = []
    dc_ids_to_load = []

    for dc_id in all_dc_ids:
        if dc_id not in loaded_dfs:
            relevant_metadata = metadata_by_dc_id.get(dc_id, [])
            loading_tasks.append((dc_id, relevant_metadata))
            # logger.debug(
            #     f"IterativeJoin: Preparing to load DataFrame for dc_id {dc_id} with metadata: {relevant_metadata}"
            # )
            dc_ids_to_load.append(dc_id)

    logger.debug(f"IterativeJoin: Loading {len(loading_tasks)} DataFrames concurrently")

    import os
    import threading

    # Load DataFrames concurrently using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(loading_tasks), 4)) as executor:
        future_to_dc_id = {
            executor.submit(load_deltatable_lite, workflow_id, dc_id, metadata, TOKEN): dc_id
            for dc_id, metadata in loading_tasks
        }

        for future in concurrent.futures.as_completed(future_to_dc_id):
            dc_id = future_to_dc_id[future]
            try:
                df = future.result()
                loaded_dfs[dc_id] = df
                # Add thread/process ID to log message
                thread_id = threading.get_ident()
                process_id = os.getpid()
                logger.debug(
                    f"IterativeJoin: [PID:{process_id}|TID:{thread_id}] Loaded {dc_id} with shape: {df.shape}"
                )
            except Exception as e:
                thread_id = threading.get_ident()
                process_id = os.getpid()
                logger.error(
                    f"IterativeJoin: [PID:{process_id}|TID:{thread_id}] Failed to load {dc_id}: {e}"
                )
                raise

    # Optimize join execution with improved strategy
    thread_id = threading.get_ident()
    process_id = os.getpid()
    # logger.debug(
    #     f"IterativeJoin: [PID:{process_id}|TID:{thread_id}] Executing {sum(len(join_list) for join_list in joins_dict.values())} total joins"
    # )

    # Initialize merged_df with the first loaded dataframe (skip non-loaded dc_ids)
    initial_dc_id = None
    for join_key_tuple in joins_dict.keys():
        for dc_id in join_key_tuple:
            if dc_id in loaded_dfs:
                initial_dc_id = dc_id
                break
        if initial_dc_id:
            break

    if not initial_dc_id:
        logger.error("IterativeJoin: No loaded dataframes found to initialize merged_df")
        import polars as pl

        return pl.DataFrame()

    merged_df = loaded_dfs[initial_dc_id]
    used_dcs.add(initial_dc_id)
    logger.debug(f"IterativeJoin: Starting with {initial_dc_id} (shape: {merged_df.shape})")

    join_count = 0
    # Iteratively join dataframes based on joins_dict
    for join_key_tuple, join_list in joins_dict.items():
        # logger.debug(
        #     f"IterativeJoin: Processing {len(join_list)} joins for group: {join_key_tuple}"
        # )

        for join in join_list:
            join_id, join_details = list(join.items())[0]
            dc_id1, dc_id2 = join_id.split("--")
            join_count += 1

            # Skip joins where one or both dc_ids weren't loaded (filtered out as non-table types)
            if dc_id1 not in loaded_dfs or dc_id2 not in loaded_dfs:
                logger.debug(
                    f"IterativeJoin: Skipping join {join_id} - one or both dc_ids not in loaded_dfs (dc_id1={dc_id1 in loaded_dfs}, dc_id2={dc_id2 in loaded_dfs})"
                )
                continue

            # Optimize: Skip already processed joins
            if dc_id1 in used_dcs and dc_id2 in used_dcs:
                # logger.debug(
                #     f"IterativeJoin: Skipping join {join_count}/{join_id} (both collections already used)"
                # )
                continue

            # Determine which dataframe to join
            if dc_id1 in used_dcs:
                right_df = loaded_dfs[dc_id2]
                used_dcs.add(dc_id2)
            elif dc_id2 in used_dcs:
                right_df = loaded_dfs[dc_id1]
                used_dcs.add(dc_id1)
            else:
                # Initial join case
                right_df = loaded_dfs[dc_id2]
                used_dcs.add(dc_id2)
                merged_df = loaded_dfs[dc_id1]
                used_dcs.add(dc_id1)

            # Optimize: Build join columns efficiently
            base_columns = join_details["on_columns"]
            join_columns = base_columns.copy()

            # Determine which DC IDs are involved in this specific join
            # This helps us check metatypes for depictio_run_id join strategy
            if dc_id1 in used_dcs:
                joining_dc_id = dc_id2  # right_df is from dc_id2
                other_dc_ids = list(used_dcs)  # merged_df contains these DCs
            elif dc_id2 in used_dcs:
                joining_dc_id = dc_id1  # right_df is from dc_id1
                other_dc_ids = list(used_dcs)  # merged_df contains these DCs
            else:
                # Initial join case
                joining_dc_id = dc_id2
                other_dc_ids = [dc_id1]

            # Apply metatype-aware depictio_run_id handling (same logic as _load_joined_deltatable)
            # Only add depictio_run_id to join if ALL involved DCs are explicitly Aggregate type
            if "depictio_run_id" in merged_df.columns and "depictio_run_id" in right_df.columns:
                try:
                    from depictio.api.v1.db import data_collections_collection

                    # Fetch metatype for the DC being joined (right_df)
                    joining_dc_doc = data_collections_collection.find_one(
                        {"_id": ObjectId(joining_dc_id)}
                    )
                    joining_dc_metatype = (
                        joining_dc_doc.get("config", {}).get("metatype")
                        if joining_dc_doc and "config" in joining_dc_doc
                        else None
                    )

                    # For merged_df, check if ALL constituent DCs are aggregate
                    # If any DC in the merge is metadata/None, don't use depictio_run_id
                    all_aggregate = (
                        joining_dc_metatype is not None
                        and joining_dc_metatype.lower() == "aggregate"
                    )

                    # Check all DCs that contributed to merged_df
                    for other_dc_id in other_dc_ids:
                        other_dc_doc = data_collections_collection.find_one(
                            {"_id": ObjectId(other_dc_id)}
                        )
                        other_dc_metatype = (
                            other_dc_doc.get("config", {}).get("metatype")
                            if other_dc_doc and "config" in other_dc_doc
                            else None
                        )
                        if other_dc_metatype is None or (
                            other_dc_metatype and other_dc_metatype.lower() != "aggregate"
                        ):
                            all_aggregate = False
                            break

                    logger.debug(
                        f"IterativeJoin: Metatype check for {joining_dc_id} -> {joining_dc_metatype}, all_aggregate={all_aggregate}"
                    )

                    if all_aggregate and "depictio_run_id" not in join_columns:
                        join_columns.append("depictio_run_id")
                        logger.debug(
                            "✅ IterativeJoin: Added depictio_run_id to join columns (all DCs are Aggregate)"
                        )
                    else:
                        # Drop depictio_run_id from dataframes if NOT all aggregate
                        # This prevents join failures when collections have different depictio_run_id values
                        if joining_dc_metatype is None or (
                            joining_dc_metatype and joining_dc_metatype.lower() == "metadata"
                        ):
                            if "depictio_run_id" in right_df.columns:
                                logger.debug(
                                    f"🗑️ IterativeJoin: Dropping depictio_run_id from right_df ({joining_dc_id}, metatype={joining_dc_metatype})"
                                )
                                right_df = right_df.drop("depictio_run_id")

                        # Also drop from merged_df if it contains metadata/None DCs
                        if not all_aggregate and "depictio_run_id" in merged_df.columns:
                            logger.debug(
                                "🗑️ IterativeJoin: Dropping depictio_run_id from merged_df (contains non-aggregate DCs)"
                            )
                            merged_df = merged_df.drop("depictio_run_id")

                        logger.debug(
                            "⏭️ IterativeJoin: Skipped depictio_run_id join key (not all DCs are aggregate)"
                        )

                except Exception as e:
                    logger.warning(
                        f"IterativeJoin: Failed to fetch metatypes for join decision: {e}. Using safe default (drop depictio_run_id)."
                    )
                    # Safe default: drop depictio_run_id to prevent join failures
                    if "depictio_run_id" in merged_df.columns:
                        merged_df = merged_df.drop("depictio_run_id")
                    if "depictio_run_id" in right_df.columns:
                        right_df = right_df.drop("depictio_run_id")

            logger.debug(f"IterativeJoin: Final join columns: {join_columns}")

            # logger.debug(
            #     f"IterativeJoin: Join {join_count} - {join_dc_id} ({right_df.shape}) -> merged ({merged_df.shape})"
            # )

            # Perform the join
            merged_df = merged_df.join(right_df, on=join_columns, how=join_details["how"])

            # logger.debug(f"IterativeJoin: Result shape: {merged_df.shape}")

    logger.debug(f"IterativeJoin: Completed {join_count} joins, final shape: {merged_df.shape}")

    # Apply post-join filtering based on interactive components
    if interactive_components_list:
        # Filter to only components that have actual filtering criteria
        # Exclude components with empty/falsy values that don't provide filtering
        filterable_components = [
            comp
            for comp in interactive_components_list
            if comp.get("metadata", {}).get("interactive_component_type") is not None
            and comp.get("metadata", {}).get("column_name") is not None
            and comp.get("value") not in [None, [], "", False]
        ]

        logger.debug(
            f"IterativeJoin: Found {len(filterable_components)} filterable components out of {len(interactive_components_list)} total"
        )

        if filterable_components:
            logger.debug(
                f"IterativeJoin: Applying post-join filtering with {len(filterable_components)} components"
            )
            try:
                filter_list = process_metadata_and_filter(filterable_components)
                if filter_list:
                    # Apply all filters to the merged dataframe
                    for filter_condition in filter_list:
                        merged_df = merged_df.filter(filter_condition)
                    logger.debug(f"IterativeJoin: After filtering, final shape: {merged_df.shape}")
            except Exception as e:
                logger.warning(f"IterativeJoin: Failed to apply post-join filtering: {e}")
                # Continue without filtering if there's an error

    # Cache the result
    _iterative_join_cache[cache_key] = merged_df
    return merged_df


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, item):
        if item not in self.parent:
            self.parent[item] = item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, item1, item2):
        root1 = self.find(item1)
        root2 = self.find(item2)
        if root1 != root2:
            self.parent[root2] = root1


# Cache for join tables to avoid redundant API calls
_join_tables_cache = {}


def get_join_tables(wf, TOKEN):
    """
    Get join tables with caching to improve performance.
    """
    cache_key = f"{wf}_{hash(TOKEN) % 10000 if TOKEN else 'none'}"

    if cache_key in _join_tables_cache:
        logger.debug(f"Using cached join tables for workflow {wf}")
        return _join_tables_cache[cache_key]

    logger.debug(f"Fetching join tables for workflow {wf}")

    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/get_dc_joined/{wf}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    if response.status_code == 200:
        result = response.json()
        _join_tables_cache[cache_key] = result
        logger.debug(f"Cached join tables for workflow {wf}")
        return result
    return {}


def return_joins_dict(wf, stored_metadata, TOKEN, extra_dc=None, dc_type_mapping=None):
    # logger.info(f"wf - {wf}")
    # logger.info(f"return_joins_dict - stored_metadata - {stored_metadata}")
    # Extract all the data collection IDs from the stored metadata
    dc_ids_all_components = list(
        set(
            [
                v["dc_id"]
                for v in stored_metadata
                if v["component_type"] not in ["jbrowse", "multiqc"]
            ]
        )
    )
    logger.debug(f"Initial DCs from components: {dc_ids_all_components}")
    if extra_dc:
        dc_ids_all_components += [extra_dc]
    # logger.info(f"dc_ids_all_components - {dc_ids_all_components}")

    # Generate initial join combinations - this will be updated after we identify additional DCs
    # with interactive components (the actual logic for this is below after we filter joins)
    initial_dc_ids_all_joins = list(itertools.combinations(dc_ids_all_components, 2))
    dc_ids_all_joins = [f"{dc_id1}--{dc_id2}" for dc_id1, dc_id2 in initial_dc_ids_all_joins] + [
        f"{dc_id2}--{dc_id1}" for dc_id1, dc_id2 in initial_dc_ids_all_joins
    ]

    # logger.info(f"dc_ids_all_joins - {dc_ids_all_joins}")

    stored_metadata_interactive_components_wf = [e for e in stored_metadata if e["wf_id"] == wf]
    # stored_metadata_interactive_components_wf = [e for e in stored_metadata if e["component_type"] in ["interactive"] and e["wf_id"] == wf]
    # logger.info(
    #     f"stored_metadata_interactive_components_wf - {stored_metadata_interactive_components_wf}"
    # )
    # stored_metadata_interactive_components_wf = [v for k, v in interactive_components_dict.items() if v["metadata"]["wf_id"] == wf]
    join_tables_for_wf = get_join_tables(wf, TOKEN)
    # logger.info(f"join_tables_for_wf - {join_tables_for_wf}")

    # ENHANCED LOGIC: Include all joins that contain DCs with interactive components
    # This ensures that joined DCs stay synchronized with their constituent DCs

    # First, identify DCs that have interactive components
    dc_ids_with_interactive = list(
        set(
            [
                v["dc_id"]
                for v in stored_metadata
                if v["component_type"] == "interactive" and v["wf_id"] == wf
            ]
        )
    )
    logger.debug(f"DCs with interactive components: {dc_ids_with_interactive}")

    # Extract the intersection between dc_ids_all_joins and join_tables_for_wf[wf].keys()
    # PLUS include any joins that contain DCs with interactive components
    filtered_joins = {}

    # Defensive check: ensure workflow exists in join_tables_for_wf
    if wf not in join_tables_for_wf:
        logger.warning(
            f"Workflow {wf} not found in join_tables_for_wf. Available workflows: {list(join_tables_for_wf.keys())}"
        )
        logger.debug(f"dc_ids_all_joins: {dc_ids_all_joins}")
        logger.debug(f"dc_ids_all_components: {dc_ids_all_components}")
        return {"joins": filtered_joins, "dc_ids": dc_ids_all_components}

    logger.debug(f"Available join keys: {list(join_tables_for_wf[wf].keys())}")
    logger.debug(f"dc_ids_all_joins: {dc_ids_all_joins}")
    logger.debug(f"dc_ids_all_components: {dc_ids_all_components}")
    logger.debug(f"join_tables_for_wf: {join_tables_for_wf}")

    for join_key, join_config in join_tables_for_wf[wf].items():
        # Include join if it's between current dashboard components (original logic)
        if join_key in dc_ids_all_joins:
            filtered_joins[join_key] = join_config
            logger.debug(f"Including join (dashboard components): {join_key}")
        # OR include join if it contains any DC with interactive components (new logic)
        elif any(dc_id in join_key for dc_id in dc_ids_with_interactive):
            filtered_joins[join_key] = join_config
            logger.debug(f"Including join (interactive DC dependency): {join_key}")

            # Also add the constituent DCs to the components list if not already present
            # Filter out non-table types (multiqc, jbrowse) using dc_type_mapping
            dc_id1, dc_id2 = join_key.split("--")

            # Check if dc_id1 is a table type
            if dc_id1 not in dc_ids_all_components:
                if dc_type_mapping:
                    dc1_type = dc_type_mapping.get(dc_id1, "table")
                    if dc1_type == "table":
                        dc_ids_all_components.append(dc_id1)
                        logger.debug(f"Added DC to components list: {dc_id1} (type: {dc1_type})")
                    else:
                        logger.debug(f"Skipping DC {dc_id1} (non-table type: {dc1_type})")
                else:
                    # No mapping available, add anyway (legacy behavior)
                    dc_ids_all_components.append(dc_id1)
                    logger.debug(f"Added DC to components list: {dc_id1} (no type mapping)")

            # Check if dc_id2 is a table type
            if dc_id2 not in dc_ids_all_components:
                if dc_type_mapping:
                    dc2_type = dc_type_mapping.get(dc_id2, "table")
                    if dc2_type == "table":
                        dc_ids_all_components.append(dc_id2)
                        logger.debug(f"Added DC to components list: {dc_id2} (type: {dc2_type})")
                    else:
                        logger.debug(f"Skipping DC {dc_id2} (non-table type: {dc2_type})")
                else:
                    # No mapping available, add anyway (legacy behavior)
                    dc_ids_all_components.append(dc_id2)
                    logger.debug(f"Added DC to components list: {dc_id2} (no type mapping)")
        else:
            logger.debug(
                f"Skipping join {join_key} - no match for dashboard components or interactive DCs"
            )

    join_tables_for_wf[wf] = filtered_joins
    logger.debug(f"Total joins after filtering: {len(filtered_joins)}")

    # Regenerate join combinations with the updated component list (including newly added DCs)
    updated_dc_ids_all_joins = list(itertools.combinations(dc_ids_all_components, 2))
    dc_ids_all_joins = [f"{dc_id1}--{dc_id2}" for dc_id1, dc_id2 in updated_dc_ids_all_joins] + [
        f"{dc_id2}--{dc_id1}" for dc_id1, dc_id2 in updated_dc_ids_all_joins
    ]
    logger.debug(f"Updated join combinations: {len(dc_ids_all_joins)} total combinations")
    # logger.info(f"join_tables_for_wf - {join_tables_for_wf}")

    # Initialize Union-Find structure
    uf = UnionFind()

    joins = []

    # logger.info(
    #     f"stored_metadata_interactive_components_wf - {stored_metadata_interactive_components_wf}"
    # )
    for interactive_component in stored_metadata_interactive_components_wf:
        wf_dc_key = (interactive_component["wf_id"], interactive_component["dc_id"])
        # logger.info(f"wf_dc - {wf_dc_key}")

        # Gather joins for the current workflow data collection
        for j in join_tables_for_wf[wf_dc_key[0]].keys():
            if (wf_dc_key[1] in j) and (wf_dc_key[1] in dc_ids_all_components):
                # logger.info(f"j - {j}")
                # logger.info(f"dc_ids_all_components - {dc_ids_all_components}")
                # logger.info(f"wf_dc[1] - {wf_dc_key[1]}")
                joins.append({j: join_tables_for_wf[wf_dc_key[0]][j]})

        # Union the related data collection IDs
        for join in joins:
            for join_id in join.keys():
                dc_id1, dc_id2 = join_id.split("--")
                uf.union(dc_id1, dc_id2)

    # Create groups of related data collection IDs
    groups = {}
    for dc_id in dc_ids_all_components:
        root = uf.find(dc_id)
        if root not in groups:
            groups[root] = set()
        groups[root].add(dc_id)

    # Create the joins dictionary based on these groups
    joins_dict = {}
    for root, group in groups.items():
        join_key_tuple = tuple(sorted(group))
        joins_dict[join_key_tuple] = []

    # Populate the joins dictionary
    added_joins = set()
    for join in joins:
        for join_id in join.keys():
            dc_id1, dc_id2 = join_id.split("--")
            root = uf.find(dc_id1)
            join_key_tuple = tuple(sorted(groups[root]))
            if join_id not in added_joins and f"{dc_id2}--{dc_id1}" not in added_joins:
                joins_dict[join_key_tuple].append(join)
                added_joins.add(join_id)

    # logger.info(f"joins_dict - {joins_dict}")

    # Identify and add missing joins
    for join_key_tuple, join_list in joins_dict.items():
        # for join_key_tuple, joins in joins_dict.items():
        # logger.info(f"Processing joins for: {join_key_tuple}")

        dc_ids = list(join_key_tuple)
        all_possible_joins = list(itertools.combinations(dc_ids, 2))
        for dc_id1, dc_id2 in all_possible_joins:
            join_id = f"{dc_id1}--{dc_id2}"
            reverse_join_id = f"{dc_id2}--{dc_id1}"
            if join_id not in added_joins and reverse_join_id not in added_joins:
                # Create a placeholder join based on available join details
                if dc_id1 in join_tables_for_wf[wf] and dc_id2 in join_tables_for_wf[wf]:
                    example_join = next(iter(join_tables_for_wf[wf].values()))
                    new_join = {
                        join_id: {
                            "how": example_join["how"],
                            "on_columns": example_join["on_columns"],
                            "dc_tags": example_join["dc_tags"],
                        }
                    }
                    joins_dict[join_key_tuple].append(new_join)
                    added_joins.add(join_id)
    return joins_dict


def join_deltatables_dev(
    wf_id: str, joins: list, metadata: dict = dict(), TOKEN: str | None = None
):
    # Initialize a dictionary to store loaded dataframes
    loaded_dfs = {}
    logger.info(f"Loading dataframes for workflow {wf_id}")
    logger.info(f"Joins: {joins}")
    logger.info(f"Metadata: {metadata}")

    # Load all necessary dataframes based on join_dict
    for join_dict in joins:
        for join_id in join_dict:
            dc_id1, dc_id2 = join_id.split("--")

            if dc_id1 not in loaded_dfs:
                logger.info(f"Loading dataframe for dc_id1: {dc_id1}")
                logger.info(
                    f"Metadata: {[e for e in metadata if e['metadata']['dc_id'] == dc_id1]}"
                )
                loaded_dfs[dc_id1] = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id1),
                    [e for e in metadata if e["metadata"]["dc_id"] == dc_id1],
                    TOKEN=TOKEN,
                )
                logger.info(f"dc1 columns: {loaded_dfs[dc_id1].columns}")
                logger.info(f"dc1 shape: {loaded_dfs[dc_id1].shape}")
            if dc_id2 not in loaded_dfs:
                logger.info(f"Loading dataframe for dc_id2: {dc_id2}")
                logger.info(
                    f"Metadata: {[e for e in metadata if e['metadata']['dc_id'] == dc_id2]}"
                )

                loaded_dfs[dc_id2] = load_deltatable_lite(
                    ObjectId(wf_id),
                    ObjectId(dc_id2),
                    [e for e in metadata if e["metadata"]["dc_id"] == dc_id2],
                    TOKEN=TOKEN,
                )
                logger.info(f"dc2 columns: {loaded_dfs[dc_id2].columns}")
                logger.info(f"dc2 shape: {loaded_dfs[dc_id2].shape}")

    logger.info(
        f"AFTER 1st FOR LOOP - Loaded dataframes columns: {[df.columns for df in loaded_dfs.values()]}"
    )
    logger.info(
        f"AFTER 1st FOR LOOP - Loaded dataframes shapes: {[df.shape for df in loaded_dfs.values()]}"
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

    # logger.info(f"Initial merged_df shape: {merged_df.shape}")
    # logger.info(f"Columns in merged_df: {merged_df.columns}")
    # logger.info(f"dc1 columns: {loaded_dfs[dc_id1].columns}")
    # logger.info(f"dc2 columns: {loaded_dfs[dc_id2].columns}")
    # logger.info(f"Common columns: {common_columns}")

    # Track which dataframes have been merged
    used_dfs = {dc_id1, dc_id2}

    # Perform remaining joins iteratively
    for join_dict in joins[1:]:
        for join_id, join_details in join_dict.items():
            dc_id1, dc_id2 = join_id.split("--")

            if dc_id2 not in used_dfs and dc_id2 in loaded_dfs:
                new_df = loaded_dfs[dc_id2]
                # logger.info(f"new_df shape: {new_df.shape}")
                # logger.info(f"new_df columns: {new_df.columns}")
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

    logger.info(f"AFTER 2nd FOR LOOP - merged_df shape: {merged_df.shape}")
    logger.info(f"Columns in merged_df: {merged_df.columns}")
    logger.info(f"Common columns: {common_columns}")
    logger.info(f"Used dataframes: {used_dfs}")
    logger.info(f"Loaded dataframes: {loaded_dfs.keys()}")
    logger.info(f"Merged df shape: {merged_df.shape}")

    return merged_df
