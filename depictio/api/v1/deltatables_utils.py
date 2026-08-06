import hashlib
import json
import os
import sys
import threading
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
DELTA_CACHE_DIR = os.getenv("DEPICTIO_DELTA_CACHE_DIR", "/app/cache/delta_cache")

# Delta schema cache (#12). ``collect_schema()`` reads the Delta log; on the hot
# render path (a card grid re-computing on every filter change, or a projected
# figure load) that's a repeated round-trip for a schema that only changes when
# ingest bumps the aggregation version. Cache the full schema per
# (data_collection_id, aggregation_version) so a new ingest naturally
# invalidates the entry — the same discriminator the dataframe cache keys use.
#
# The dtypes are cached alongside the names because they are what lets
# ``add_filter`` build a *typed* categorical predicate instead of wrapping the
# column in a ``cast(Utf8)`` — see the comment there. Both come from the same
# ``collect_schema()`` call, so keeping dtypes costs no extra round-trip.
_DELTA_SCHEMA_CACHE: dict[tuple[str, str], dict[str, pl.DataType]] = {}
_DELTA_SCHEMA_CACHE_MAX = 512  # bounded; the version salt churns keys over time


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
        return cache_path

    # Create cache directory
    os.makedirs(DELTA_CACHE_DIR, exist_ok=True)

    # Remove stale cache if exists
    if os.path.exists(cache_path):
        shutil.rmtree(cache_path)

    # Read from S3 and write to local cache
    df = pl.scan_delta(s3_path, storage_options=polars_s3_config).collect()
    df.write_delta(cache_path, mode="overwrite")

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
        # Extract metadata from nested structure if needed. ``dict.get(k, "")``
        # returns the actual value when the key is present even if it's None,
        # so coerce None → "" explicitly to keep the sort key well-ordered.
        if "metadata" in component:
            meta = component["metadata"]
            column_name = meta.get("column_name") or ""
            component_type = meta.get("interactive_component_type") or ""
            value = component.get("value")
        else:
            column_name = component.get("column_name") or ""
            component_type = component.get("interactive_component_type") or ""
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


# Synthetic ``interactive_component_type`` for "a cross-DC link resolved to no
# target values". Not a user-facing component: it exists so an empty resolution
# can be carried through the ordinary filter payload and still mean "no rows",
# which an empty value list cannot express (see ``add_filter``).
LINK_NO_MATCH = "__link_no_match__"


def _categorical_predicate(column_name: str, values: list, dtype: pl.DataType | None) -> pl.Expr:
    """Build the ``is_in`` predicate for Select/MultiSelect/SegmentedControl.

    The values arrive stringified: ``unique_values`` stringifies for the React
    MultiSelect, and scatter/table selections round-trip through the same path.
    So an ``int64`` column compared against ``["1", "2"]`` must still match.

    The obvious way to get that — ``pl.col(c).cast(pl.Utf8).is_in([...])`` — is
    a performance trap. Wrapping the *column* in a cast makes the predicate
    opaque to Polars' parquet reader: row-group min/max statistics can no
    longer be used to skip, and dictionary pushdown is lost, so every filtered
    read fully decodes the filter column across the whole table. Measured on
    the 1 GB benchmark tier that turned a 100-row filtered table page into an
    18-second load.

    So we cast the *values* to the column's dtype instead, which leaves
    ``pl.col(c)`` bare and keeps the predicate pushable. ``dtype`` comes from
    the cached Delta schema; when it is unknown (no schema available) or of a
    kind we don't convert confidently, we fall back to the original
    column-cast form — correctness first, speed only when it is free.

    How a value is converted depends on the dtype, and getting this wrong is
    how a filter silently empties a component:

    - numerics and ``Date`` — ``cast`` parses their string form directly.
    - ``Datetime`` and ``Time`` — ``cast`` from string is a *numeric* parse and
      returns null without raising, so casting is not merely slow, it drops
      every row. They need the real parsers (``str.to_datetime`` /
      ``str.to_time``), which also accept every rendering a client sends:
      ``str()`` (``"2024-01-01 12:30:45"``), ``isoformat()`` (with ``T``), and
      Polars' own ``cast(Utf8)`` (with microseconds). Note the column-cast form
      matched *none* of those — it renders microseconds while clients send
      seconds — so temporal categorical filters never matched anything before;
      routing them through a parser fixes that as well as making them pushable.
    - ``Duration`` — no parser, and its string form isn't castable at all, so
      it keeps the fallback (which raises on contact; pre-existing).
    - everything else (Boolean, Categorical, nested) keeps the fallback: the
      conversion rules aren't obvious enough to risk a silent behaviour change.

    A value that cannot be converted is dropped rather than matched: an int
    column genuinely has no row equal to ``"abc"``, which is what the
    column-cast form returned too. But if *nothing* converts we fall back
    instead of returning "matches nothing" — an all-null conversion is far more
    likely to mean "this dtype doesn't parse from text" than "the user picked
    values this column cannot hold", and guessing wrong empties the component.
    """
    str_values = [str(v) for v in values]
    fallback = pl.col(column_name).cast(pl.Utf8, strict=False).is_in(str_values)

    if dtype is None:
        return fallback

    # Already text: no conversion needed on either side, and the bare column
    # is directly pushable. The common case for categorical filters.
    if dtype == pl.String:  # pl.Utf8 is the same dtype under an older name
        return pl.col(column_name).is_in(str_values)

    raw = pl.Series(str_values, dtype=pl.Utf8)
    base = dtype.base_type()
    try:
        if dtype.is_numeric() or dtype == pl.Date:
            converted = raw.cast(dtype, strict=False)
        elif base == pl.Datetime:
            # Parse naive, then cast to the column's own unit/zone. Verified to
            # round-trip for naive, UTC and offset zones.
            converted = raw.str.to_datetime(strict=False).cast(dtype, strict=False)
        elif base == pl.Time:
            converted = raw.str.to_time(strict=False)
        else:
            return fallback
    except Exception as e:
        logger.debug(
            f"_categorical_predicate: cannot convert values to {dtype} for column "
            f"{column_name!r} ({e}); using the string-cast predicate"
        )
        return fallback

    typed_values = converted.drop_nulls().to_list()
    if not typed_values:
        logger.debug(
            f"_categorical_predicate: no value converted to {dtype} for column "
            f"{column_name!r}; using the string-cast predicate"
        )
        return fallback
    return pl.col(column_name).is_in(typed_values)


def add_filter(
    filter_list: list,
    interactive_component_type: str,
    column_name: str,
    value,
    min_value=None,
    max_value=None,
    dtype: pl.DataType | None = None,
) -> None:
    """Add filter criteria to a filter list based on component type.

    ``dtype`` is the column's Delta dtype when the caller knows it (from the
    cached schema); it only affects categorical filters, where it enables a
    pushable predicate. Omitting it preserves the previous behaviour exactly.
    """
    if interactive_component_type == LINK_NO_MATCH:
        # A cross-DC link resolved to zero target values: the user's filter is
        # satisfiable on the source but matches nothing on this DC, so the
        # correct result is no rows.
        #
        # This cannot be expressed as an empty ``is_in`` list, because every
        # branch below is guarded by ``if value:`` — an empty list falls through
        # as "no filter at all" and the component renders EVERY row, which reads
        # as "the filter did nothing" rather than "nothing matched". Hence an
        # explicit component type carrying an always-false predicate.
        filter_list.append(pl.lit(False))

    elif interactive_component_type in ["Select", "MultiSelect", "SegmentedControl"]:
        if value:
            # Ensure value is a list for is_in() function
            if not isinstance(value, list):
                value = [value]

            filter_list.append(_categorical_predicate(column_name, value, dtype))

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

    elif interactive_component_type in ("DateRangePicker", "Timeline"):
        logger.info(
            f"[DEBUG] {interactive_component_type} filter: column={column_name}, value={value}, type={type(value)}"
        )

        if value and isinstance(value, list) and len(value) == 2:
            logger.info(f"[DEBUG] {interactive_component_type} validation passed, applying filter")
            try:
                from datetime import date as _date
                from datetime import datetime as _dt

                # Parse the React-supplied ISO strings (or pass through if
                # already a date/datetime) into Python ``datetime`` objects.
                # Timeline accepts richer ISO formats (yyyy-mm-ddTHH:MM:SS) so
                # try a list of formats; DateRangePicker historically used
                # day-precision strings.
                def _parse_iso(raw: object) -> object:
                    if isinstance(raw, (_dt, _date)):
                        return raw
                    if not isinstance(raw, str):
                        return raw
                    for fmt in (
                        "%Y-%m-%dT%H:%M:%S.%f",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d",
                    ):
                        try:
                            return _dt.strptime(raw, fmt)
                        except ValueError:
                            continue
                    # Fall back to ISO 8601 parser (handles trailing 'Z' etc).
                    return _dt.fromisoformat(raw.rstrip("Z"))

                start_dt = _parse_iso(value[0])
                end_dt = _parse_iso(value[1])

                # Robust column expression: works for Date, Datetime, AND
                # Utf8 columns. ``cast(pl.Datetime)`` alone fails at
                # evaluation when the column is stored as a string (which
                # ampliseq's ``sampling_date`` is). Casting to Utf8 first
                # then coalesce-parsing across formats covers all three
                # dtypes plus full ISO timestamps (``2026-05-05T16:10:27Z``,
                # which the React Timeline emits and earlier code rejected
                # because it only tried the date-only ``%Y-%m-%d`` format).
                col_str = pl.col(column_name).cast(pl.Utf8, strict=False)
                # Strip any inferred timezone so the `pl.lit(start_dt)`
                # comparison literals (naive Python `datetime`s) match.
                # Polars treats `datetime[μs, UTC]` and `datetime[μs]` as
                # incompatible for `>=` even when the wall-clock values are
                # identical — strings like `2026-05-05T16:10:27Z` parse with
                # tz, plain `2026-05-05` parses without. Coalescing requires
                # both branches to share a dtype, so we normalize.
                parsed_iso = col_str.str.to_datetime(strict=False).dt.replace_time_zone(None)
                parsed_date = col_str.str.strptime(pl.Datetime, "%Y-%m-%d", strict=False)
                date_col = pl.coalesce([parsed_iso, parsed_date])
                # Strip tz from the literals too in case some caller hands
                # us tz-aware datetimes (DateRangePicker historically sent
                # date-only strings, but Timeline now emits ISO with `Z`).
                start_naive = (
                    start_dt.replace(tzinfo=None)
                    if isinstance(start_dt, _dt) and start_dt.tzinfo
                    else start_dt
                )
                end_naive = (
                    end_dt.replace(tzinfo=None)
                    if isinstance(end_dt, _dt) and end_dt.tzinfo
                    else end_dt
                )
                filter_list.append(
                    (date_col >= pl.lit(start_naive)) & (date_col <= pl.lit(end_naive))
                )

            except Exception as e:
                logger.warning(
                    f"Failed to apply {interactive_component_type} filter on column '{column_name}': {e}"
                )
        else:
            logger.warning(
                f"[DEBUG] {interactive_component_type} validation FAILED: value={value}, "
                f"is_list={isinstance(value, list)}, "
                f"len={len(value) if isinstance(value, list) else 'N/A'}"
            )


def process_metadata_and_filter(
    metadata: list, schema: dict[str, pl.DataType] | None = None
) -> list:
    """Process metadata and build a list of Polars filter expressions.

    If a component carries ``filter_expr`` (either at the top level or under
    ``metadata.filter_expr``), the compiled expression is appended alongside
    the value-based filter so downstream consumers see the source's row
    scoping in addition to the user's selection.

    ``schema`` is the DC's ``{column: dtype}`` map when the caller has it (the
    lazy scan path does, via the cached Delta schema). It is passed down so
    categorical filters can be built as pushable typed predicates; without it
    they keep their previous dtype-agnostic form.
    """
    filter_list = []

    for component in metadata:
        if "metadata" in component:
            meta = component["metadata"]
            interactive_component_type = meta.get("interactive_component_type")
            column_name = meta.get("column_name")
            filter_expr = meta.get("filter_expr") or component.get("filter_expr")
        else:
            interactive_component_type = component.get("interactive_component_type")
            column_name = component.get("column_name")
            filter_expr = component.get("filter_expr")

        # Expression-only filters (e.g. AI-injected `source: 'ai_prompt'`
        # entries) carry a filter_expr but no widget type/column/value —
        # only widget-backed entries go through add_filter.
        if interactive_component_type and column_name:
            add_filter(
                filter_list,
                interactive_component_type=interactive_component_type,
                column_name=column_name,
                value=component.get("value"),
                dtype=schema.get(column_name) if schema else None,
            )

        if filter_expr:
            try:
                from depictio.models.components.filter_expr import build_filter_expr

                filter_list.append(build_filter_expr(filter_expr))
            except Exception as e:
                logger.warning(
                    f"Skipping invalid filter_expr {filter_expr!r} on component "
                    f"column={column_name}: {e}"
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
                # Cast both columns to string to ensure compatibility
                df1 = df1.with_columns(pl.col(col).cast(pl.String))
                df2 = df2.with_columns(pl.col(col).cast(pl.String))

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
    version_salt: str | int | None = None,
) -> tuple[str, str | None, str | None]:
    """
    Generate cache keys for DataFrame caching.

    Returns:
        Tuple of (base_cache_key, filtered_cache_key, filter_hash).
        filtered_cache_key and filter_hash are None if no filters apply.

    ``version_salt`` is an optional discriminator embedded in the key — typically
    the deltatable's latest ``aggregation_version``. Including it means that
    when realtime ingest bumps the version, every worker's next lookup uses a
    new key and naturally bypasses any stale per-process memory cache. Without
    this salt, multi-worker deployments serve stale data after a WS update
    because cache invalidation only reaches one worker process.
    """
    cache_suffix = "preview" if load_for_preview else "base"
    salt = f"_v{version_salt}" if version_salt is not None else ""

    if select_columns:
        columns_key = "_".join(sorted(select_columns))
        base_cache_key = (
            f"{workflow_id_str}_{data_collection_id_str}_{cache_suffix}_cols_{columns_key}{salt}"
        )
    else:
        base_cache_key = f"{workflow_id_str}_{data_collection_id_str}_{cache_suffix}{salt}"

    filter_hash = None
    filtered_cache_key = None

    if metadata and not load_for_options:
        filter_hash = _generate_filter_hash(metadata)
        filtered_cache_key = f"{base_cache_key}_filters_{filter_hash}"

    return base_cache_key, filtered_cache_key, filter_hash


def _get_aggregation_version(data_collection_id_str: str) -> str | None:
    """Fetch latest aggregation_version for a DC from MongoDB.

    Used as a cache-key salt so multi-worker API deployments don't serve
    stale data after a realtime ingest: invalidating one worker's in-process
    dataframe cache leaves the other workers still pointing at the old key,
    so we discriminate the keys by version instead.

    Returns ``None`` on lookup failure so callers can fall back to unsalted
    keys (preserves prior behavior on errors).
    """
    try:
        from depictio.api.v1.db import deltatables_collection as _dt_coll

        dt = _dt_coll.find_one(
            {"data_collection_id": ObjectId(data_collection_id_str)},
            {"aggregation": 1},
        )
        agg_list = (dt or {}).get("aggregation") or []
        if not agg_list:
            return None
        return str(agg_list[-1].get("aggregation_version") or "")
    except Exception as e:
        logger.debug(f"_get_aggregation_version({data_collection_id_str}) failed: {e}")
        return None


def _get_aggregation_hash(data_collection_id_str: str) -> str | None:
    """Fetch the latest ``aggregation_hash`` for a DC from MongoDB.

    Preferred over ``_get_aggregation_version`` as a cache-key salt: the version
    is a counter the upsert increments, whereas the hash is derived from the
    Delta log itself (table version + active files, see ``_delta_identity_hash``)
    and therefore describes the *state of the data* rather than how many times
    it has been written.

    Note it is additionally salted with the write timestamp, so it is not a
    content-identity hash: two upserts of byte-identical data produce different
    hashes. For invalidation that bias is the safe one — it can cause a
    redundant recompute, never a stale answer.

    Returns ``None`` on lookup failure so callers can fall back.
    """
    try:
        from depictio.api.v1.db import deltatables_collection as _dt_coll

        dt = _dt_coll.find_one(
            {"data_collection_id": ObjectId(data_collection_id_str)},
            {"aggregation": 1},
        )
        agg_list = (dt or {}).get("aggregation") or []
        if not agg_list:
            return None
        return str(agg_list[-1].get("aggregation_hash") or "")
    except Exception as e:
        logger.debug(f"_get_aggregation_hash({data_collection_id_str}) failed: {e}")
        return None


def _get_dc_type_from_db(data_collection_id: ObjectId) -> str | None:
    """
    Fetch data collection type from MongoDB.

    Args:
        data_collection_id: ObjectId of the data collection.

    Returns:
        Data collection type (e.g., "MultiQC", "Table") or None if not found.
    """
    try:
        # Data collections are embedded in projects/workflows, not in separate collection
        from depictio.api.v1.db import projects_collection

        project = projects_collection.find_one(
            {"workflows.data_collections._id": data_collection_id},
            {"workflows.data_collections.$": 1},
        )
        if project:
            for wf in project.get("workflows", []):
                for dc in wf.get("data_collections", []):
                    if dc["_id"] == data_collection_id:
                        config = dc.get("config", {})
                        if isinstance(config, dict):
                            return config.get("type")
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch dc_type for {data_collection_id}: {e}")
        return None


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


def _create_delta_scan(file_id: str, dc_type: str | None = None) -> pl.LazyFrame:
    """
    Create a Polars LazyFrame scan from Delta table location or parquet files.

    Args:
        file_id: S3 path or local path to Delta table or parquet files.
        dc_type: Data collection type (e.g., "MultiQC", "Table"). If "MultiQC", uses parquet scan.

    Returns:
        Polars LazyFrame for the Delta table or parquet files.
    """
    # MultiQC data is stored as parquet, not delta tables
    # Case-insensitive check for MultiQC type
    if dc_type and dc_type.lower() == "multiqc":
        # Handle both directory and file paths
        # If file_id ends with .parquet, it's a direct file path
        if file_id.endswith(".parquet"):
            parquet_pattern = file_id
        else:
            # It's a directory, scan all parquet files
            parquet_pattern = f"{file_id}/**/*.parquet"

        if USE_LOCAL_FILES:
            cache_path = cache_delta_table_from_s3(file_id, polars_s3_config)
            if file_id.endswith(".parquet"):
                return pl.scan_parquet(cache_path)
            return pl.scan_parquet(f"{cache_path}/**/*.parquet")
        return pl.scan_parquet(parquet_pattern, storage_options=polars_s3_config)

    # Standard delta table scan
    if USE_LOCAL_FILES:
        cache_path = cache_delta_table_from_s3(file_id, polars_s3_config)
        return pl.scan_delta(cache_path)

    return pl.scan_delta(file_id, storage_options=polars_s3_config)


def _get_cached_dtypes(
    delta_scan: pl.LazyFrame,
    data_collection_id_str: str,
    version_salt: str | int | None,
) -> dict[str, pl.DataType] | None:
    """Return a DC's Delta schema as ``{column: dtype}``, cached (#12).

    On cache miss, reads the lazy schema once (a Delta-log round-trip, no data)
    and memoizes it. Returns ``None`` if the schema can't be read, so callers
    fall back to their pre-cache behaviour (no projection / no filter pruning /
    untyped filter predicates).

    ``version_salt`` is what makes a cached entry safe to reuse: an upsert
    increments the aggregation version, so a re-ingest that changes a column's
    dtype lands under a new key. When the version is *unknown* (``None`` — the
    Mongo lookup failed, or the DC has no aggregation yet) that guarantee is
    gone, and a stale dtype is worse than a stale name set: the predicate is
    built for the wrong type and the scan raises instead of merely mispruning.
    So an unknown version reads the schema fresh and does not memoize it.
    """
    if version_salt is None:
        try:
            schema = dict(delta_scan.collect_schema())
        except Exception as e:
            logger.debug(
                f"_get_cached_dtypes: schema read failed for {data_collection_id_str}: {e}"
            )
            return None
        return schema or None

    cache_key = (data_collection_id_str, str(version_salt))
    cached = _DELTA_SCHEMA_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        schema = dict(delta_scan.collect_schema())
    except Exception as e:
        logger.debug(f"_get_cached_dtypes: schema read failed for {data_collection_id_str}: {e}")
        return None
    if not schema:
        # A columnless schema is not a real DC, and treating it as authoritative
        # is actively dangerous: callers use the name set to decide which
        # filters apply, so an empty answer silently drops *every* filter and
        # renders unfiltered data. Report it as unreadable instead, which makes
        # callers fall back to their unguarded behaviour.
        logger.debug(f"_get_cached_dtypes: empty schema for {data_collection_id_str}; ignoring")
        return None
    # Simple bound: a schema is cheap to re-read, so clearing on overflow is
    # fine and avoids tracking per-entry recency.
    if len(_DELTA_SCHEMA_CACHE) >= _DELTA_SCHEMA_CACHE_MAX:
        _DELTA_SCHEMA_CACHE.clear()
    _DELTA_SCHEMA_CACHE[cache_key] = schema
    return schema


def _get_cached_schema(
    delta_scan: pl.LazyFrame,
    data_collection_id_str: str,
    version_salt: str | int | None,
) -> frozenset[str] | None:
    """Return a DC's Delta column names, cached per (collection, version) (#12).

    Thin view over :func:`_get_cached_dtypes` — callers that only need to know
    *which* columns exist (projection guards, filter pruning) keep taking a
    name set, and share the one cached schema read with the dtype consumers.
    """
    schema = _get_cached_dtypes(delta_scan, data_collection_id_str, version_salt)
    return None if schema is None else frozenset(schema)


def _filter_columns(metadata: list[dict] | None) -> set[str]:
    """Column names referenced by a filter metadata list.

    Mirrors the column extraction used by ``apply_runtime_filters`` and the
    large-path filter pruning: a filter component carries its column either at
    the top level or under a nested ``metadata`` dict.
    """
    cols: set[str] = set()
    for component in metadata or []:
        if not isinstance(component, dict):
            continue
        nested = component.get("metadata") if isinstance(component.get("metadata"), dict) else None
        col = component.get("column_name") or (nested.get("column_name") if nested else None)
        if col:
            cols.add(col)
    return cols


def _effective_projection(
    select_columns: list[str] | None,
    metadata: list[dict] | None,
    load_for_options: bool,
) -> list[str] | None:
    """Resolve the column set a projected load must actually scan (#7).

    Returns ``None`` (full load) when no projection was requested, preserving
    today's behaviour for every caller that doesn't opt in.

    When a projection *is* requested, the columns the pending filters reference
    are folded in: projection happens at scan level *before* filtering, and
    ``apply_runtime_filters`` silently skips a filter whose column is missing —
    so dropping a filter column would quietly change results, not just error.
    Folding filter columns into the returned set also means the cache key
    (derived from this list) reflects the exact columns of the cached frame, so
    two requests sharing a projection but filtering on different columns can't
    collide on the same base entry.
    """
    if not select_columns:
        return None
    cols = set(select_columns)
    if metadata and not load_for_options:
        cols |= _filter_columns(metadata)
    return sorted(cols)


def _project_scan(
    delta_scan: pl.LazyFrame,
    effective_cols: list[str] | None,
    data_collection_id_str: str,
    version_salt: str | int | None,
) -> pl.LazyFrame:
    """Apply scan-level column projection, intersected with the real schema.

    ``effective_cols`` already unions the requested columns with the columns
    the pending filters reference (see ``_effective_projection``). Columns not
    on this DC's schema are dropped here rather than passed to ``.select`` —
    which would raise ``ColumnNotFoundError`` at ``collect`` — mirroring the
    cross-DC filter pruning the large path already does. Projection therefore
    never changes which rows or columns a load would otherwise return; it only
    avoids reading columns nothing needs.

    If the schema can't be read (``_get_cached_schema`` returns ``None``), we
    skip projection entirely and load the full frame — passing an unverified
    ``effective_cols`` to ``.select`` could include a column absent from this DC
    (e.g. a cross-DC filter column) and turn a transient schema-read failure
    into a hard ``ColumnNotFoundError`` at ``collect``.
    """
    if not effective_cols:
        return delta_scan
    schema_names = _get_cached_schema(delta_scan, data_collection_id_str, version_salt)
    projection = (
        [c for c in effective_cols if c in schema_names] if schema_names is not None else None
    )
    if projection:
        delta_scan = delta_scan.select(projection)
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
        df = apply_runtime_filters(df, metadata)

    # Apply row limit
    if limit_rows:
        df = df.limit(limit_rows)

    # Drop aggregation time column if exists
    if "depictio_aggregation_time" in df.columns:
        df = df.drop("depictio_aggregation_time")

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
                return _finalize_dataframe(cached_df, None, True, limit_rows)

        # Check base cache
        cached_df = get_cached_dataframe(base_cache_key)
        if cached_df is not None:
            # Apply column projection if needed
            if select_columns and all(col in cached_df.columns for col in select_columns):
                cached_df = cached_df.select(select_columns)

            # Apply filters and cache the filtered result
            if metadata and not load_for_options:
                cached_df = apply_runtime_filters(cached_df, metadata)

                # Cache filtered result
                if filter_hash and filtered_cache_key:
                    cache_dataframe(filtered_cache_key, cached_df)

            return _finalize_dataframe(cached_df, None, True, limit_rows)

    except Exception:
        pass

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
        update_cache_timestamp(filtered_cache_key)
        cached_df = _dataframe_memory_cache[filtered_cache_key]
        return _finalize_dataframe(cached_df, None, True, limit_rows)

    # Check base cache
    if base_cache_key in _dataframe_memory_cache:
        update_cache_timestamp(base_cache_key)
        cached_df = _dataframe_memory_cache[base_cache_key]

        # Apply column projection if needed
        if select_columns and all(col in cached_df.columns for col in select_columns):
            cached_df = cached_df.select(select_columns)

        # Apply filters and cache the filtered result
        if metadata and not load_for_options:
            cached_df = apply_runtime_filters(cached_df, metadata)

            # Cache filtered result in memory
            if filter_hash and filtered_cache_key:
                _dataframe_memory_cache[filtered_cache_key] = cached_df
                _cache_metadata[filtered_cache_key] = {
                    "size_bytes": sys.getsizeof(cached_df),
                    "timestamp": time.time(),
                }

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
        return

    # Try Redis first
    try:
        from depictio.api.cache import cache_dataframe

        cache_dataframe(cache_key, df)
    except Exception:
        pass

    # Also cache in memory
    _dataframe_memory_cache[cache_key] = df
    _cache_metadata[cache_key] = {
        "size_bytes": size_bytes,
        "timestamp": time.time(),
    }
    _total_memory_usage += size_bytes


def _log_cache_status() -> None:
    """Log current cache status (Redis and memory)."""
    # Cache status logging disabled for cleaner output
    pass


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

    try:
        df = delta_scan.collect()
    except Exception as e:
        logger.error(f"Error collecting Delta table data: {e}")
        raise Exception("Error collecting Delta table data") from e

    # Estimate size if unknown
    if size_bytes == -1:
        size_bytes = df.height * df.width * 8  # 8 bytes per cell average

    # Cache the base DataFrame
    _cache_dataframe_to_stores(base_cache_key, df, size_bytes)

    # Apply filters if needed
    if metadata and not load_for_options:
        df = apply_runtime_filters(df, metadata)

        # Cache filtered result
        if filter_hash and filtered_cache_key:
            filtered_size = df.height * df.width * 8
            try:
                from depictio.api.cache import cache_dataframe

                if not cache_dataframe(filtered_cache_key, df):
                    # Fallback to memory cache if Redis fails
                    _dataframe_memory_cache[filtered_cache_key] = df
                    _cache_metadata[filtered_cache_key] = {
                        "size_bytes": filtered_size,
                        "timestamp": time.time(),
                    }
            except Exception:
                _dataframe_memory_cache[filtered_cache_key] = df
                _cache_metadata[filtered_cache_key] = {
                    "size_bytes": filtered_size,
                    "timestamp": time.time(),
                }

    return df


def _apply_scan_filters(
    delta_scan: pl.LazyFrame,
    metadata: list[dict] | None,
    data_collection_id_str: str,
    version_salt: str | int | None = None,
) -> pl.LazyFrame:
    """Push ``metadata`` filters onto a lazy Delta scan (schema-guarded).

    Skips filters whose column isn't present on this DC — happens when a
    cross-DC filter (e.g. metadata.habitat) is also being applied to a
    canonical advanced-viz DC keyed on sample_id. The link resolver appends
    the translated sample_id filter, so we can safely drop the untranslated
    habitat filter here instead of failing the whole load with a polars
    ColumnNotFoundError. Returns the scan unchanged when there are no filters.
    """
    if not metadata:
        return delta_scan

    schema = _get_cached_dtypes(delta_scan, data_collection_id_str, version_salt)

    usable_metadata = metadata
    if schema is not None:
        usable_metadata = []
        for component in metadata:
            meta = component.get("metadata") or {}
            col = component.get("column_name") or meta.get("column_name")
            if col and col not in schema:
                logger.info(
                    "Skipping filter on column %r — not present in DC (available: %s)",
                    col,
                    sorted(schema),
                )
                continue
            usable_metadata.append(component)

    filter_expressions = process_metadata_and_filter(usable_metadata, schema)

    if filter_expressions:
        combined_filter = filter_expressions[0]
        for filt in filter_expressions[1:]:
            combined_filter &= filt
        delta_scan = delta_scan.filter(combined_filter)

    return delta_scan


def _estimate_frame_size_bytes(delta_scan: pl.LazyFrame) -> int:
    """Cheaply estimate a lazy frame's materialised footprint (bytes).

    Reads the row count via Polars aggregation pushdown (Delta parquet stats —
    no data scan) and the projected width via the lazy schema (a Delta-log read),
    then applies the same ``rows × cols × 8`` heuristic the fresh-load path uses
    for unknown sizes. Used to classify a DC whose ``size_bytes`` was never
    recorded so the adaptive loader doesn't mistake a multi-GB table for a small
    one. Returns ``-1`` if the estimate can't be computed (caller then keeps its
    prior unknown-size behaviour).
    """
    try:
        n_cols = len(delta_scan.collect_schema())
        n_rows = int(delta_scan.select(pl.len()).collect().item())
        return n_rows * max(n_cols, 1) * 8
    except Exception as e:
        logger.debug(f"_estimate_frame_size_bytes: estimate failed: {e}")
        return -1


def _open_sortable_scan(
    workflow_id_str: str,
    data_collection_id_str: str,
    init_data: dict[str, dict] | None,
    metadata: list[dict] | None,
    effective_cols: list[str] | None,
    version_salt: str | int | None,
    TOKEN: str | None = None,
) -> pl.LazyFrame | None:
    """Build a filtered + projected lazy Delta scan (no collect).

    Used by the sorted-page path so a large frame can be sorted + sliced lazily
    (bounded memory) instead of going through the full-frame cache. Filters are
    applied before projection; ``effective_cols`` already folds in the filter
    columns (see ``_effective_projection``) so nothing a filter references is
    projected away. Returns ``None`` if the scan can't be built, so the caller
    falls back to the memoised full-sort path.
    """
    try:
        if init_data and data_collection_id_str in init_data:
            dc_type = init_data[data_collection_id_str].get("dc_type")
        else:
            dc_type = _get_dc_type_from_db(ObjectId(data_collection_id_str))
        file_id = _get_delta_location(data_collection_id_str, workflow_id_str, init_data, TOKEN)
        delta_scan = _create_delta_scan(file_id, dc_type)
        delta_scan = _apply_scan_filters(delta_scan, metadata, data_collection_id_str, version_salt)
        delta_scan = _project_scan(delta_scan, effective_cols, data_collection_id_str, version_salt)
        return delta_scan
    except Exception as e:
        logger.debug(f"_open_sortable_scan: failed to build scan for {data_collection_id_str}: {e}")
        return None


def open_deltatable_scan(
    workflow_id: ObjectId | str,
    data_collection_id: ObjectId | str,
    metadata: list[dict] | None = None,
    init_data: dict[str, dict] | None = None,
    select_columns: list[str] | None = None,
    TOKEN: str | None = None,
) -> pl.LazyFrame | None:
    """Public entry point for a filtered + projected **lazy** Delta scan.

    The counterpart to ``load_deltatable_lite`` for callers that want to express
    their work as a Polars aggregation rather than receive rows: figure
    aggregation (box/histogram/density), card metrics, and any other reduction
    that parquet statistics + projection pushdown can answer without
    materialising the frame. A ``mean`` over a 28 M-row table costs a column
    scan here versus a full in-memory collect through the row-returning loader.

    Resolves the aggregation ``version_salt`` and the effective projection (which
    folds in the filter columns, so nothing a filter references is projected
    away) exactly like the row loader, keeping filter semantics identical between
    the two paths. Returns ``None`` when the scan can't be built — every caller
    is expected to fall back to ``load_deltatable_lite``.

    Note this deliberately bypasses the frame cache: the result of a scan is a
    plan, not data, and the aggregates built on it are far smaller than the
    frames the cache is sized for (they belong in the result cache instead).
    """
    data_collection_id_str = str(data_collection_id)
    version_salt = _get_aggregation_version(data_collection_id_str)
    effective_cols = _effective_projection(select_columns, metadata, False)
    return _open_sortable_scan(
        str(workflow_id),
        data_collection_id_str,
        init_data,
        metadata,
        effective_cols,
        version_salt,
        TOKEN,
    )


def _load_large_dataframe(
    delta_scan: pl.LazyFrame,
    data_collection_id_str: str,
    metadata: list[dict] | None,
    load_for_options: bool,
    limit_rows: int | None,
    size_bytes: int,
    version_salt: str | int | None = None,
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
        version_salt: Aggregation version for the schema cache key (#12).

    Returns:
        Loaded DataFrame.
    """

    # Apply filters at scan level for large DataFrames
    if metadata and not load_for_options:
        delta_scan = _apply_scan_filters(delta_scan, metadata, data_collection_id_str, version_salt)

    if limit_rows:
        delta_scan = delta_scan.limit(limit_rows)

    try:
        df = delta_scan.collect()
    except Exception as e:
        logger.error(f"Error collecting Delta table data: {e}")
        raise Exception("Error collecting Delta table data") from e

    return df


# =============================================================================
# GEOJSON LOADING
# =============================================================================


def load_geojson_from_s3(dc_id: str, TOKEN: str | None = None) -> dict | None:
    """Load a GeoJSON file from S3 for a given data collection ID.

    Fetches the delta_location (S3 path) from the API, then reads and parses
    the GeoJSON file from S3.

    Args:
        dc_id: Data collection ID for the GeoJSON DC.
        TOKEN: Access token for API authentication.

    Returns:
        Parsed GeoJSON dict, or None if loading fails.
    """
    try:
        # Get the S3 location via the deltatable API
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{dc_id}",
            headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {},
            timeout=30.0,
        )
        if response.status_code != 200:
            logger.error(f"Failed to get GeoJSON location for DC {dc_id}: {response.text}")
            return None

        data = response.json()
        s3_path = data.get("delta_table_location") or data.get("delta_location")
        if not s3_path:
            logger.error(f"No S3 location found for GeoJSON DC {dc_id}")
            return None

        logger.info(f"Loading GeoJSON from S3: {s3_path}")

        # Read the GeoJSON from S3
        import s3fs

        fs = s3fs.S3FileSystem(**polars_s3_config)
        with fs.open(s3_path, "r") as f:
            geojson_data = json.load(f)

        feature_count = len(geojson_data.get("features", []))
        logger.info(f"Loaded GeoJSON with {feature_count} features from {s3_path}")
        return geojson_data

    except Exception as e:
        logger.error(f"Failed to load GeoJSON for DC {dc_id}: {e}", exc_info=True)
        return None


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

    # Resolve the effective projection once, up front (no I/O): the requested
    # columns plus any columns the pending filters reference. Used for the
    # cache key, the cache lookups, and the scan so they all agree on the exact
    # column set of the (cached) frame. ``None`` when no projection was asked
    # for, which keeps every non-opted-in caller on today's full-load path.
    effective_cols = _effective_projection(select_columns, metadata, load_for_options)

    # CACHING DISABLED PATH - load directly from storage
    if not ENABLE_CACHING:
        file_id = _get_delta_location(data_collection_id_str, workflow_id_str, init_data, TOKEN)
        # Extract dc_type for special handling (e.g., MultiQC uses parquet)
        if init_data and data_collection_id_str in init_data:
            dc_type = init_data[data_collection_id_str].get("dc_type")
        else:
            # Fallback: query database for dc_type when init_data not available
            data_collection_id_obj = (
                ObjectId(data_collection_id)
                if isinstance(data_collection_id, str)
                else data_collection_id
            )
            dc_type = _get_dc_type_from_db(data_collection_id_obj)
        delta_scan = _create_delta_scan(file_id, dc_type)
        delta_scan = _project_scan(delta_scan, effective_cols, data_collection_id_str, None)
        if limit_rows:
            delta_scan = delta_scan.limit(limit_rows)
        df = delta_scan.collect()
        return _finalize_dataframe(df, metadata, load_for_options, None)

    # CACHING ENABLED PATH
    _log_cache_status()

    # Salt the cache keys with the latest aggregation_version so realtime
    # ingest naturally invalidates this worker's per-process memory cache —
    # `invalidate_data_collection_cache` from the WS handler only reaches the
    # one worker that received the event, so without a per-version key the
    # other 3 default workers keep serving the stale dataframe. The version
    # bumps on every CLI rewrite, so the new fetch lands on a new key.
    version_salt = _get_aggregation_version(data_collection_id_str)

    # Generate cache keys
    base_cache_key, filtered_cache_key, filter_hash = _generate_cache_keys(
        workflow_id_str,
        data_collection_id_str,
        load_for_preview,
        effective_cols,
        metadata,
        load_for_options,
        version_salt=version_salt,
    )

    # Check Redis cache
    cached_df = _check_redis_cache(
        base_cache_key,
        filtered_cache_key,
        filter_hash,
        metadata,
        load_for_options,
        effective_cols,
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
        effective_cols,
        limit_rows,
    )
    if cached_df is not None:
        return cached_df

    # CACHE MISS - need to load from storage
    # Get DataFrame size for adaptive loading strategy
    if init_data and data_collection_id_str in init_data:
        size_bytes = init_data[data_collection_id_str].get("size_bytes", -1)
        dc_type = init_data[data_collection_id_str].get("dc_type")
    else:
        data_collection_id_obj = (
            ObjectId(data_collection_id)
            if isinstance(data_collection_id, str)
            else data_collection_id
        )
        size_bytes = get_deltatable_size_from_db(data_collection_id_obj)
        # Fallback: query database for dc_type when init_data not available
        dc_type = _get_dc_type_from_db(data_collection_id_obj)

    # Get delta location and create scan
    file_id = _get_delta_location(data_collection_id_str, workflow_id_str, init_data, TOKEN)
    delta_scan = _create_delta_scan(file_id, dc_type)

    # Apply column projection at scan level (schema-guarded; see _project_scan)
    delta_scan = _project_scan(delta_scan, effective_cols, data_collection_id_str, version_salt)

    # A DC whose in-memory footprint was never recorded (size_bytes None/0/-1)
    # must NOT be assumed small: a multi-GB table would then take the
    # cache-the-whole-frame branch below and fully collect every row on each
    # paginated page fetch (and, being over the per-item cap, never even cache).
    # Estimate the footprint cheaply from a pushdown row count × projected width
    # so the adaptive branch routes big tables to the lazy limit-pushdown path.
    if size_bytes is None or size_bytes <= 0:
        size_bytes = _estimate_frame_size_bytes(delta_scan)

    # ADAPTIVE LOADING STRATEGY
    if size_bytes == -1 or size_bytes <= MEMORY_THRESHOLD_BYTES:
        # Unknown or small DataFrame - load, cache, then filter in memory.
        # NOTE: cache the *full* frame and apply ``limit_rows`` only to the
        # returned view (below). The cache key intentionally ignores
        # ``limit_rows`` (see _generate_cache_keys), so caching a pre-limited
        # frame here would poison the key for any later load of the same DC +
        # filters with a different (or no) limit — e.g. paging a table (limit
        # 10, then 20, …) or a 1-row schema peek followed by a real page.
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
        if limit_rows:
            df = df.limit(limit_rows)
    else:
        # Large DataFrame - use lazy loading with filters at scan level
        df = _load_large_dataframe(
            delta_scan,
            data_collection_id_str,
            metadata,
            load_for_options,
            limit_rows,
            size_bytes,
            version_salt,
        )

    # Final cleanup (drop aggregation column)
    if "depictio_aggregation_time" in df.columns:
        df = df.drop("depictio_aggregation_time")

    return df


def load_sorted_deltatable_lite(
    workflow_id: ObjectId,
    data_collection_id: ObjectId | str,
    sort_by: str,
    descending: bool = True,
    metadata: list[dict] | None = None,
    init_data: dict[str, dict] | None = None,
    nulls_last: bool = True,
    select_columns: list[str] | None = None,
    page: tuple[int, int] | None = None,
) -> pl.DataFrame:
    """Return a sorted (optionally filtered / projected) frame, or one page of it.

    ``load_deltatable_lite`` already caches the *unsorted* frame, so the table
    render endpoint's ``load`` is a cache hit on pages 2..N. The cost that kept
    repeating was the ``df.sort(...)`` itself: AG Grid's infinite row model
    fetches one block per scroll, and each block re-sorted the whole cached
    frame. We memoise the *sorted* frame under a key derived from the same
    base/filter key plus ``(cols, sort_by, sort_dir, nulls_last)`` so every block
    after the first slices an already-sorted frame — no re-sort.

    ``select_columns`` restricts the load to the columns the grid will actually
    render (plus the sort column), cutting I/O + memory on wide tables; the memo
    key reflects the projection so different projections don't collide.

    ``page`` = ``(start, limit)`` returns only that window. Small frames are
    fully sorted once and memoised, so later pages are free slices. A frame whose
    estimated footprint exceeds the per-item memo cap is instead sorted **lazily**
    and sliced at scan level — never fully materialised in memory — trading the
    memo (deep pages re-sort) for bounded memory and a far cheaper first page.
    ``page=None`` returns the whole sorted frame (memoised full-sort path).

    The key embeds the dc_id and the aggregation ``version_salt`` (via
    ``_generate_cache_keys``), so a realtime ingest that bumps the version — or
    an explicit ``invalidate_data_collection_cache`` (dc_id substring match) —
    busts this entry for free, exactly like the base frame.
    """
    import time

    global _total_memory_usage

    data_collection_id_str = str(data_collection_id)
    workflow_id_str = str(workflow_id)

    version_salt = _get_aggregation_version(data_collection_id_str)
    effective_cols = _effective_projection(select_columns, metadata, False)
    base_key, filtered_key, _ = _generate_cache_keys(
        workflow_id_str,
        data_collection_id_str,
        load_for_preview=False,
        select_columns=effective_cols,
        metadata=metadata,
        load_for_options=False,
        version_salt=version_salt,
    )
    key_root = filtered_key or base_key
    sort_key = (
        f"{key_root}_sort_{sort_by}_{'desc' if descending else 'asc'}"
        f"_{'nl' if nulls_last else 'nf'}"
    )

    def _page(frame: pl.DataFrame) -> pl.DataFrame:
        return frame.slice(page[0], page[1]) if page is not None else frame

    cached = _dataframe_memory_cache.get(sort_key)
    if cached is not None:
        update_cache_timestamp(sort_key)
        return _page(cached)

    # Per-key lock: this endpoint is a sync ``def`` (threadpool), and AG Grid's
    # infinite row model fires the first few blocks for the same (dc, sort) key
    # near-simultaneously. Without serialising the miss, each of those threads
    # would run the full load + full-frame sort in parallel (thundering herd on
    # exactly the first-paint moment we want to be fast) and each would add its
    # own ``size_bytes`` to the shared budget while overwriting the single
    # metadata entry — leaking the accounting. One thread computes; the rest wait
    # and hit the cache via the double-check below.
    with _sorted_cache_locks_guard:
        key_lock = _sorted_cache_locks.setdefault(sort_key, threading.Lock())

    with key_lock:
        cached = _dataframe_memory_cache.get(sort_key)
        if cached is not None:
            update_cache_timestamp(sort_key)
            return _page(cached)

        # Lazy sorted-page path for large frames: estimate the footprint from the
        # projected scan and, above the per-item memo cap, sort + slice lazily so
        # we never materialise the whole sorted frame. Only when a page is
        # requested — a full-frame caller needs every row anyway.
        if page is not None:
            scan = _open_sortable_scan(
                workflow_id_str,
                data_collection_id_str,
                init_data,
                metadata,
                effective_cols,
                version_salt,
            )
            if scan is not None:
                est = _estimate_frame_size_bytes(scan)
                if est == -1 or est > MEMORY_PER_ITEM_MAX_BYTES:
                    start, limit = page
                    # ``maintain_order`` keeps tie-breaking deterministic and
                    # identical to the eager memo path below, so a table that
                    # sits near the memo cap can't reorder equal-key rows between
                    # requests (page boundaries stay stable). ~10% sort cost.
                    page_df = (
                        scan.sort(
                            sort_by,
                            descending=descending,
                            nulls_last=nulls_last,
                            maintain_order=True,
                        )
                        .slice(start, limit)
                        .collect()
                    )
                    if "depictio_aggregation_time" in page_df.columns:
                        page_df = page_df.drop("depictio_aggregation_time")
                    return page_df

        # Small frame (or full-frame request): full sort once + memoise so later
        # pages are free slices of the cached frame.
        df = load_deltatable_lite(
            workflow_id=workflow_id,
            data_collection_id=data_collection_id,
            metadata=metadata,
            init_data=init_data,
            select_columns=select_columns,
        )
        sorted_df = df.sort(
            sort_by, descending=descending, nulls_last=nulls_last, maintain_order=True
        )

        # Reuse the base cache's LRU budget + per-item cap so the sorted copy
        # can't pin more RAM than a normal frame. ``estimated_size`` is cheap on
        # an already materialised frame (buffer-size sum, no scan).
        size_bytes = sorted_df.estimated_size()
        if size_bytes <= MEMORY_PER_ITEM_MAX_BYTES:
            while _total_memory_usage + size_bytes > MEMORY_THRESHOLD_BYTES and _cache_metadata:
                evict_oldest_cached_dataframe()
            _dataframe_memory_cache[sort_key] = sorted_df
            _cache_metadata[sort_key] = {"size_bytes": size_bytes, "timestamp": time.time()}
            _total_memory_usage += size_bytes

        return _page(sorted_df)


def count_deltatable_lite(
    workflow_id: ObjectId,
    data_collection_id: ObjectId | str,
    metadata: list[dict] | None = None,
    init_data: dict[str, dict] | None = None,
    TOKEN: str | None = None,
) -> int:
    """Count rows of a (optionally filtered) Delta table without materialising it.

    Runs ``scan.filter(...).select(pl.len())`` so the row count comes back via
    Polars predicate/aggregation pushdown — no full-width, all-rows load. Used
    by the figure/table render endpoints to report ``total_data_count`` cheaply
    when the row payload itself is capped or paginated with pushdown.

    Filters are applied with the same schema-guard as ``load_deltatable_lite``
    (see ``_apply_scan_filters``). Returns 0 on any scan/collect error rather
    than raising — a missing count only degrades the UI's "N of M" hint.
    """
    data_collection_id_str = str(data_collection_id)
    workflow_id_str = str(workflow_id)

    if isinstance(data_collection_id, str) and "--" in data_collection_id:
        raise NotImplementedError(
            f"Joined DC '{data_collection_id}' format is deprecated. "
            "Use the pre-computed result data collection ID instead."
        )

    try:
        if init_data and data_collection_id_str in init_data:
            dc_type = init_data[data_collection_id_str].get("dc_type")
        else:
            dc_type = _get_dc_type_from_db(
                ObjectId(data_collection_id)
                if isinstance(data_collection_id, str)
                else data_collection_id
            )
        version_salt = _get_aggregation_version(data_collection_id_str)
        file_id = _get_delta_location(data_collection_id_str, workflow_id_str, init_data, TOKEN)
        delta_scan = _create_delta_scan(file_id, dc_type)
        delta_scan = _apply_scan_filters(delta_scan, metadata, data_collection_id_str, version_salt)
        result = delta_scan.select(pl.len()).collect()
        return int(result.item()) if result.height else 0
    except Exception as e:
        logger.warning(f"count_deltatable_lite failed for DC {data_collection_id_str}: {e}")
        return 0


def schema_deltatable_lite(
    workflow_id: ObjectId,
    data_collection_id: ObjectId | str,
    init_data: dict[str, dict] | None = None,
    TOKEN: str | None = None,
) -> dict:
    """Return the Delta table's column schema (name → dtype) without loading rows.

    Reads only the Delta log via ``scan.collect_schema()`` — no data scan and no
    cache interaction, so it can safely precede a cached ``load_deltatable_lite``
    call. (A ``limit_rows=1`` peek would instead share the cache key and could
    poison it.) Used by the table render endpoint to resolve the default sort
    column and build AG Grid column defs before choosing a load strategy.
    Returns ``{}`` on error; the caller degrades gracefully.
    """
    data_collection_id_str = str(data_collection_id)
    workflow_id_str = str(workflow_id)
    try:
        if init_data and data_collection_id_str in init_data:
            dc_type = init_data[data_collection_id_str].get("dc_type")
        else:
            dc_type = _get_dc_type_from_db(
                ObjectId(data_collection_id)
                if isinstance(data_collection_id, str)
                else data_collection_id
            )
        file_id = _get_delta_location(data_collection_id_str, workflow_id_str, init_data, TOKEN)
        schema = _create_delta_scan(file_id, dc_type).collect_schema()
        return dict(schema)
    except Exception as e:
        logger.warning(f"schema_deltatable_lite failed for DC {data_collection_id_str}: {e}")
        return {}


# Memory management for DataFrames - new adaptive caching system
_dataframe_memory_cache = {}
_cache_metadata = {}  # Track size and timestamp for each cached DataFrame
_total_memory_usage = 0
# Per-sort-key locks so concurrent AG Grid block fetches for the same
# (dc, filters, sort) compute the sorted frame once instead of stampeding.
# ``_sorted_cache_locks_guard`` only protects the tiny setdefault of the
# per-key lock, never the load/sort itself. See ``load_sorted_deltatable_lite``.
_sorted_cache_locks: dict[str, threading.Lock] = {}
_sorted_cache_locks_guard = threading.Lock()
MEMORY_THRESHOLD_BYTES = 1024 * 1024 * 1024  # 1GB threshold (total in-process cache)
# Per-item cap: a single large DataFrame must not be able to consume most of the
# in-process cache and evict every smaller, frequently-reused frame. Above this
# it still lives in Redis (subject to its own cap) but is re-materialised on a
# process-local miss instead of pinning RAM here. Also bounds per-worker RSS,
# which matters now that the worker runs multiple prefork processes.
MEMORY_PER_ITEM_MAX_BYTES = 256 * 1024 * 1024  # 256 MB


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
        if dt_doc and "flexible_metadata" in dt_doc and dt_doc["flexible_metadata"] is not None:
            size_bytes = dt_doc["flexible_metadata"].get("deltatable_size_bytes")
            if size_bytes and isinstance(size_bytes, (int, float)) and size_bytes > 0:
                return int(size_bytes)

        # If no size metadata found, try to estimate from the DataFrame directly
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
    df = delta_scan.collect()

    # PERFORMANCE: Use fast row count instead of expensive estimated_size() for small datasets
    # For datasets < 100KB, pickling overhead exceeds recalculation cost - skip Redis entirely
    row_count = df.height
    REDIS_SKIP_THRESHOLD_ROWS = 1000  # Skip Redis for datasets < 1000 rows (~100KB)

    if row_count < REDIS_SKIP_THRESHOLD_ROWS:
        # TINY DATASET: Skip Redis pickling overhead, use memory-only cache
        actual_size = size_bytes  # Use estimate, avoid expensive df.estimated_size() scan

        # Memory cache only (much faster than Redis for tiny datasets)
        if _total_memory_usage + actual_size <= MEMORY_THRESHOLD_BYTES:
            _dataframe_memory_cache[cache_key] = df
            _cache_metadata[cache_key] = {
                "size_bytes": actual_size,
                "timestamp": time.time(),
            }
            _total_memory_usage += actual_size

        return df

    # LARGER DATASET: Use Redis + memory caching
    # Use fast estimate (df.estimated_size() scan disabled for performance)
    actual_size = df.height * df.width * 8  # 8 bytes per cell average

    # Try to cache in Redis first (persistent across page refreshes)
    try:
        from depictio.api.cache import cache_dataframe

        cache_dataframe(cache_key, df)
    except Exception:
        pass

    # Also cache in memory if it fits the per-item cap AND the total threshold
    # (faster access during session). Oversized frames stay in Redis only.
    if (
        actual_size <= MEMORY_PER_ITEM_MAX_BYTES
        and _total_memory_usage + actual_size <= MEMORY_THRESHOLD_BYTES
    ):
        _dataframe_memory_cache[cache_key] = df
        _cache_metadata[cache_key] = {
            "size_bytes": actual_size,
            "timestamp": time.time(),
        }
        _total_memory_usage += actual_size

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

    # Get DataFrame columns for validation
    df_columns = set(df.columns)

    # Validate filter columns and keep only those matching DataFrame columns.
    # Non-matching filters are skipped individually (not bail-out-all) so that
    # valid row-level filters still apply even when heatmap column-level or
    # cross-DC pseudo-column filters are present.
    valid_metadata = []
    skipped_filters = []
    for component in metadata:
        filter_value = component.get("value")
        if filter_value in [None, [], "", False]:
            valid_metadata.append(component)
            continue

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
                    "value": filter_value,
                }
            )
        else:
            valid_metadata.append(component)

    if skipped_filters:
        logger.warning(
            f"⚠️ FILTER MISMATCH: Skipping {len(skipped_filters)} filter(s) - columns not present in DataFrame"
        )
        for skip in skipped_filters:
            logger.warning(
                f"  ❌ Column '{skip['column']}' (type={skip['type']}, value={skip['value']}) not in DataFrame"
            )
        logger.warning(f"  📋 Available columns in DataFrame: {sorted(df_columns)}")
        if valid_metadata:
            logger.info(f"  ✅ Continuing with {len(valid_metadata)} valid filter(s)")

    # The frame is materialised, so its schema is free — and passing it keeps
    # this path's categorical semantics identical to the lazy scan path, which
    # also builds typed predicates.
    filter_expressions = process_metadata_and_filter(valid_metadata, dict(df.schema))

    if filter_expressions:
        try:
            # Apply filters using Polars expressions on materialized DataFrame
            combined_filter = filter_expressions[0]
            for filt in filter_expressions[1:]:
                combined_filter &= filt

            df = df.filter(combined_filter)
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


def invalidate_data_collection_cache(data_collection_id: str) -> int:
    """Drop every cached DataFrame whose key references the given DC.

    Cache keys are formed as ``{wf_id}_{dc_id}_{...}`` (see _generate_cache_keys),
    so a substring match on the DC id captures the base entry and every filter
    variant. Clears BOTH the in-process memory cache AND the Redis-backed
    cache in ``depictio.api.cache`` — without the Redis pass, ``render_*``
    endpoints continue to read the stale DataFrame after the CLI rewrites the
    delta. Called from the realtime event path so that a re-fetch after a
    ``data_collection_updated`` event sees the newly written delta rows.
    """
    global _total_memory_usage

    affected = [k for k in list(_dataframe_memory_cache.keys()) if data_collection_id in k]
    for key in affected:
        meta = _cache_metadata.pop(key, None)
        if meta is not None:
            _total_memory_usage = max(0, _total_memory_usage - int(meta.get("size_bytes", 0)))
        _dataframe_memory_cache.pop(key, None)

    redis_dropped = 0
    try:
        from depictio.api.cache import invalidate_dataframe_cache_pattern

        redis_dropped = invalidate_dataframe_cache_pattern(data_collection_id)
    except Exception as e:
        logger.warning(f"Redis cache invalidation failed for dc_id={data_collection_id}: {e}")

    return len(affected) + redis_dropped


def join_deltatables_dev(
    wf_id: str, joins: list, metadata: dict | None = None, TOKEN: str | None = None
) -> pl.DataFrame:
    """Development function for joining deltatables."""
    if metadata is None:
        metadata = {}

    loaded_dfs = {}

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

    return merged_df
