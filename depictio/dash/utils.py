import collections
import functools
import sys
import time
import uuid
from typing import Any, Dict, Optional

import httpx
import numpy as np
from bson import ObjectId

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger

SELECTED_STYLE = {
    "display": "inline-block",
    "width": "250px",
    "height": "80px",
    "border": "3px solid",
    "opacity": 1,
    "fontFamily": "Virgil",
}

UNSELECTED_STYLE = {
    "display": "inline-block",
    "width": "250px",
    "height": "80px",
    "border": "3px solid",
    "opacity": 1,
    "fontFamily": "Virgil",
}


# Helper Functions
def generate_unique_index():
    """
    Generate a unique index using UUID4.
    Used to create unique identifiers for components.
    """
    return str(uuid.uuid4())


def get_size(obj, seen=None):
    """Recursively finds size of objects"""
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    # Important mark as seen *before* entering recursion to gracefully handle
    # self-referential objects
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum([get_size(v, seen) for v in obj.values()])
        size += sum([get_size(k, seen) for k in obj.keys()])
    elif hasattr(obj, "__dict__"):
        size += get_size(obj.__dict__, seen)
    elif hasattr(obj, "__iter__") and not isinstance(obj, str | bytes | bytearray):
        size += sum([get_size(i, seen) for i in obj])
    return size


# PERFORMANCE OPTIMIZATION: Enhanced component data caching

_component_data_cache: Dict[
    str, Dict[str, Any]
] = {}  # cache_key -> {data, timestamp, access_count}
_cache_stats = {"hits": 0, "misses": 0, "evictions": 0, "total_requests": 0}

# Cache configuration
COMPONENT_CACHE_TTL_SECONDS = 600  # 10 minutes (longer than figure cache)
COMPONENT_CACHE_MAX_SIZE = 200  # More components than figures
COMPONENT_CACHE_ACCESS_THRESHOLD = 5  # Keep frequently accessed items longer

# PERFORMANCE OPTIMIZATION: Batch component data fetching
_batch_fetch_queue: dict = dict()  # dashboard_id -> {component_ids: set, callbacks: list}
_batch_fetch_timer: dict = dict()  # dashboard_id -> timer_id


def _get_cache_key(dashboard_id: str, input_id: str, TOKEN: str) -> str:
    """Generate consistent cache key for component data."""
    return f"{dashboard_id}_{input_id}_{hash(TOKEN) % 10000 if TOKEN else 'none'}"


def _get_cached_component_data(cache_key: str) -> Optional[Any]:
    """Get component data from cache with TTL and access tracking."""
    if cache_key not in _component_data_cache:
        _cache_stats["misses"] += 1
        return None

    cached_item = _component_data_cache[cache_key]
    current_time = time.time()

    # Check TTL expiration
    if current_time - cached_item["timestamp"] > COMPONENT_CACHE_TTL_SECONDS:
        del _component_data_cache[cache_key]
        _cache_stats["misses"] += 1
        logger.debug(f"⏰ Cache expired for component: {cache_key}")
        return None

    # Update access tracking
    cached_item["access_count"] += 1
    cached_item["last_access"] = current_time

    _cache_stats["hits"] += 1
    logger.debug(f"🚀 CACHE HIT: component {cache_key} (accessed {cached_item['access_count']}x)")
    return cached_item["data"]


def _cache_component_data(cache_key: str, data: Any):
    """Cache component data with intelligent eviction policy."""
    current_time = time.time()

    # Eviction policy: Remove oldest, least accessed items first
    while len(_component_data_cache) >= COMPONENT_CACHE_MAX_SIZE:
        # Find item to evict (oldest with low access count)
        evict_key = min(
            _component_data_cache.keys(),
            key=lambda k: (
                _component_data_cache[k]["access_count"] < COMPONENT_CACHE_ACCESS_THRESHOLD,
                _component_data_cache[k]["timestamp"],
            ),
        )

        del _component_data_cache[evict_key]
        _cache_stats["evictions"] += 1
        logger.debug(f"🗑️  Evicted cached component: {evict_key}")

    # Cache the data
    _component_data_cache[cache_key] = {
        "data": data,
        "timestamp": current_time,
        "last_access": current_time,
        "access_count": 1,
    }
    logger.debug(f"💾 CACHED: component {cache_key}")


def get_component_cache_stats() -> dict:
    """Get cache performance statistics for monitoring."""
    total = _cache_stats["hits"] + _cache_stats["misses"]
    hit_rate = (_cache_stats["hits"] / total * 100) if total > 0 else 0

    return {
        **_cache_stats,
        "hit_rate_percent": hit_rate,
        "cache_size": len(_component_data_cache),
        "max_cache_size": COMPONENT_CACHE_MAX_SIZE,
        "ttl_seconds": COMPONENT_CACHE_TTL_SECONDS,
    }


def clear_component_cache():
    """Clear all cached component data."""
    _component_data_cache.clear()
    _cache_stats.update({"hits": 0, "misses": 0, "evictions": 0, "total_requests": 0})
    logger.info("🧹 Cleared component data cache")


def bulk_get_component_data(component_ids: list, dashboard_id: str, TOKEN: str) -> dict:
    """
    PERFORMANCE OPTIMIZATION: Fetch multiple component data in a single API call.

    Args:
        component_ids: List of component IDs to fetch
        dashboard_id: Dashboard ID
        TOKEN: Authorization token

    Returns:
        Dict mapping component_id -> component_data
    """
    logger.info(f"🚀 BATCH FETCH: Getting {len(component_ids)} components in one request")

    # Check enhanced cache for each component first
    results = {}
    uncached_ids = []

    _cache_stats["total_requests"] += len(component_ids)

    for input_id in component_ids:
        cache_key = _get_cache_key(dashboard_id, input_id, TOKEN)
        cached_data = _get_cached_component_data(cache_key)

        if cached_data is not None:
            results[input_id] = cached_data
        else:
            uncached_ids.append(input_id)

    # Fetch uncached components in bulk
    if uncached_ids:
        logger.info(f"📡 BULK API: Fetching {len(uncached_ids)} uncached components")

        # Make bulk API request
        bulk_url = f"{API_BASE_URL}/depictio/api/v1/dashboards/bulk_component_data/{dashboard_id}"
        payload = {"component_ids": uncached_ids}

        try:
            response = httpx.post(
                bulk_url, json=payload, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10.0
            )

            if response.status_code == 200:
                bulk_data = response.json()

                # Cache and add to results using enhanced caching
                for input_id, component_data in bulk_data.items():
                    cache_key = _get_cache_key(dashboard_id, input_id, TOKEN)
                    _cache_component_data(cache_key, component_data)
                    results[input_id] = component_data

                logger.info(f"✅ BULK SUCCESS: Cached {len(bulk_data)} components")
            else:
                logger.warning(
                    f"❌ BULK FAILED: {response.status_code}, falling back to individual requests"
                )
                # Fallback to individual requests
                for input_id in uncached_ids:
                    results[input_id] = get_component_data_individual(input_id, dashboard_id, TOKEN)

        except Exception as e:
            logger.error(f"❌ BULK ERROR: {e}, falling back to individual requests")
            # Fallback to individual requests
            for input_id in uncached_ids:
                results[input_id] = get_component_data_individual(input_id, dashboard_id, TOKEN)

    return results


def get_component_data_individual(input_id, dashboard_id, TOKEN):
    """Original individual component data fetching (used as fallback)."""
    logger.debug(f"📡 INDIVIDUAL: Fetching component data for {input_id}")

    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/get_component_data/{dashboard_id}/{input_id}",
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=5.0,
    )

    if response.status_code == 200:
        component_data = response.json()
        # Cache using enhanced caching system
        cache_key = _get_cache_key(dashboard_id, input_id, TOKEN)
        _cache_component_data(cache_key, component_data)
        return component_data
    else:
        logger.warning(f"❌ FAILED: component {input_id} - {response.status_code}")
        return None


def get_component_data(input_id, dashboard_id, TOKEN, _bulk_data=None):
    """
    Get component data with caching and performance optimization.

    Args:
        input_id: Component ID to fetch
        dashboard_id: Dashboard ID
        TOKEN: Authorization token
        _bulk_data: Pre-fetched bulk data (optimization)

    For backward compatibility, this still works as individual calls,
    but with improved caching and error handling.
    """
    _cache_stats["total_requests"] += 1

    # PERFORMANCE OPTIMIZATION: Use pre-fetched bulk data if available
    if _bulk_data is not None:
        logger.info(f"🚀 BULK HIT: Using pre-fetched data for component {input_id}")
        return _bulk_data

    # Check enhanced cache first
    cache_key = _get_cache_key(dashboard_id, input_id, TOKEN)
    cached_data = _get_cached_component_data(cache_key)

    if cached_data is not None:
        logger.debug(f"📦 CACHED: Component data cache hit for {input_id}")
        return cached_data

    # Use the individual fetching function
    logger.info(
        f"📡 INDIVIDUAL FETCH: Fetching component data for {input_id} (no bulk/cache available)"
    )
    return get_component_data_individual(input_id, dashboard_id, TOKEN)


def load_depictio_data_mongo(dashboard_id: str, TOKEN: str):
    url = f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}"
    try:
        response = httpx.get(url, headers={"Authorization": f"Bearer {TOKEN}"})
        if response.status_code == 200:
            response = response.json()
            return response
        else:
            print(f"Failed to load dashboard data. Status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"An error occurred while trying to fetch dashboard data: {e}")
        return None


def return_user_from_token(token: str) -> dict | None:
    # call API to get user from token without using PUBLIC KEY
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code == 200:
        return response.json()
    else:
        print("Error fetching user from token")
        return None


# Cache for workflows to avoid redundant API calls
_workflows_cache: dict = dict()


def list_workflows(token: str | None = None):
    """
    List workflows with caching to improve performance.
    """
    if not token:
        print("A valid token must be provided for authentication.")
        return None

    # Create cache key
    cache_key = f"workflows_{hash(token) % 10000}"

    # Check cache first
    if cache_key in _workflows_cache:
        logger.debug("Using cached workflows list")
        return _workflows_cache[cache_key]

    logger.debug("Fetching workflows from API")
    headers = {"Authorization": f"Bearer {token}"}

    workflows = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows", headers=headers
    )
    workflows_json = workflows.json()

    # Cache the result
    _workflows_cache[cache_key] = workflows_json
    logger.debug("Cached workflows list")

    return workflows_json


# def list_workflows_for_dropdown():
#     workflows_model_list = list_workflows(TOKEN)
#     # print(workflows_model_list)
#     workflows = [wf["workflow_tag"] for wf in workflows_model_list]
#     workflows_dict_for_dropdown = [{"label": wf, "value": wf} for wf in workflows]
#     return workflows_dict_for_dropdown


# def list_data_collections_for_dropdown(workflow_tag: str = None):
#     if workflow_tag is None:
#         return []
#     else:
#         data_collections = [dc["data_collection_tag"] for wf in list_workflows(TOKEN) for dc in wf["data_collections"] if wf["workflow_tag"] == workflow_tag]
#         data_collections_dict_for_dropdown = [{"label": dc, "value": dc} for dc in data_collections]
#         return data_collections_dict_for_dropdown


def return_wf_tag_from_id(workflow_id: ObjectId, TOKEN: str | None = None):
    """
    PERFORMANCE OPTIMIZED: Get workflow tag from ID with LRU caching.

    Caches workflow tags to avoid redundant API calls. This is critical for performance
    when loading dashboards with multiple components that reference the same workflow.

    Args:
        workflow_id: Workflow ObjectId
        TOKEN: Authorization token

    Returns:
        Workflow tag string or None if not found
    """
    # Use token hash for cache key to avoid caching issues with different users
    token_hash = hash(TOKEN) % 10000 if TOKEN else 0
    return _fetch_wf_tag_with_lru_cache(str(workflow_id), TOKEN, token_hash)


@functools.lru_cache(maxsize=256)
def _fetch_wf_tag_with_lru_cache(workflow_id_str: str, TOKEN: str, token_hash: int):
    """Internal LRU-cached function for fetching workflow tags."""
    logger.debug(f"🔍 LRU CACHE MISS: Fetching workflow tag for {workflow_id_str}")

    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/workflows/get_tag_from_id/{workflow_id_str}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    if response.status_code == 200:
        result = response.json()
        logger.debug(f"✅ LRU CACHED: Workflow tag for {workflow_id_str} = {result}")
        return result
    else:
        logger.error(f"No workflow found for ID {workflow_id_str}")
        return None


def return_dc_tag_from_id(
    # workflow_id: ObjectId,
    data_collection_id: ObjectId,
    # workflows: list = None,
    TOKEN: str | None = None,
):
    """
    PERFORMANCE OPTIMIZED: Get data collection tag from ID with LRU caching.

    Caches data collection tags to avoid redundant API calls. This is critical for performance
    when loading dashboards with multiple components that reference the same data collection.

    Args:
        data_collection_id: Data collection ObjectId
        TOKEN: Authorization token

    Returns:
        Data collection tag string or None if not found
    """
    # Use token hash for cache key to avoid caching issues with different users
    token_hash = hash(TOKEN) % 10000 if TOKEN else 0
    return _fetch_dc_tag_with_lru_cache(str(data_collection_id), TOKEN, token_hash)


@functools.lru_cache(maxsize=256)
def _fetch_dc_tag_with_lru_cache(data_collection_id_str: str, TOKEN: str, token_hash: int):
    """Internal LRU-cached function for fetching data collection tags."""
    logger.debug(f"🔍 LRU CACHE MISS: Fetching DC tag for {data_collection_id_str}")

    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/get_tag_from_id/{data_collection_id_str}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    if response.status_code == 200:
        result = response.json()
        logger.debug(f"✅ LRU CACHED: DC tag for {data_collection_id_str} = {result}")
        return result
    else:
        logger.error(f"No data collection found for ID {data_collection_id_str}")
        return None


def return_mongoid(
    workflow_tag: str | None = None,
    workflow_id: ObjectId | None = None,
    data_collection_tag: str | None = None,
    data_collection_id: ObjectId | None = None,
    workflows: list | None = None,
    TOKEN: str | None = None,
):
    if not workflows:
        workflows = list_workflows(TOKEN)
    # else:
    #     workflows = [convert_objectid_to_str(workflow.mongo()) for workflow in workflows]

    if workflow_tag is not None and data_collection_tag is not None:
        # print("workflow_tag and data_collection_tag")
        workflow_id = [e for e in workflows if e["workflow_tag"] == workflow_tag][0]["_id"]
        # print("workflow_id", workflow_id)
        data_collection_id = [
            f
            for e in workflows
            if e["_id"] == workflow_id
            for f in e["data_collections"]
            if f["data_collection_tag"] == data_collection_tag
        ][0]["_id"]
        # print("data_collection_id", data_collection_id)
    elif workflow_id is not None and data_collection_tag is not None:
        # print("workflow_id and data_collection_tag")
        data_collection_id = [
            f
            for e in workflows
            if str(e["_id"]) == str(workflow_id)
            for f in e["data_collections"]
            if f["data_collection_tag"] == data_collection_tag
        ][0]["_id"]
    else:
        # print("Invalid input")
        return None, None

    return workflow_id, data_collection_id


# PERFORMANCE OPTIMIZATION: LRU cache for column metadata fetching


def get_columns_from_data_collection(
    workflow_id: str,
    data_collection_id: str,
    TOKEN: str,
):
    """
    PERFORMANCE OPTIMIZED: Get columns from data collection with LRU caching.

    This function now uses functools.lru_cache for automatic cache management with:
    - LRU eviction policy (maxsize=128)
    - Efficient token hashing
    - Automatic size management

    Saves ~0.5-1 second per call by avoiding redundant API calls and DataFrame schema generation.
    """
    # Determine cache version for joined vs regular data collections
    cache_version = (
        "v2" if isinstance(data_collection_id, str) and "--" in data_collection_id else "v1"
    )
    token_hash = hash(TOKEN) % 10000 if TOKEN else 0

    # Use LRU-cached function for automatic cache management
    # Cache key: (workflow_id, data_collection_id, TOKEN, cache_version, token_hash)
    # The token_hash ensures cache uniqueness while TOKEN provides API access
    return _fetch_columns_with_lru_cache(
        workflow_id=workflow_id,
        data_collection_id=data_collection_id,
        TOKEN=TOKEN,
        cache_version=cache_version,
        token_hash=token_hash,
    )


@functools.lru_cache(maxsize=128)
def _fetch_columns_with_lru_cache(
    workflow_id: str,
    data_collection_id: str,
    TOKEN: str,
    cache_version: str,
    token_hash: int,
):
    """
    Internal LRU-cached function for fetching column specs.

    Args:
        workflow_id: Workflow ID
        data_collection_id: Data collection ID (may be joined with '--' separator)
        TOKEN: Authorization token
        cache_version: Cache version ('v1' or 'v2')
        token_hash: Hash of token for cache key (unused but needed for LRU key uniqueness)

    Returns:
        defaultdict with column specifications
    """
    logger.info(
        f"🔍 LRU CACHE MISS: Fetching specs for DC {data_collection_id} from WF {workflow_id}"
    )

    if workflow_id is None or data_collection_id is None:
        logger.error("workflow_id or data_collection_id is None")
        return collections.defaultdict(dict)

    # Check if this is a joined data collection ID
    if isinstance(data_collection_id, str) and "--" in data_collection_id:
        logger.info(f"Handling joined data collection specs for: {data_collection_id}")
        # For joined data collections, we need to get the combined column specs
        # by loading the actual joined DataFrame and extracting its schema
        try:
            from bson import ObjectId

            from depictio.api.v1.deltatables_utils import load_deltatable_lite

            # Load the joined DataFrame to get its schema
            df = load_deltatable_lite(
                workflow_id=ObjectId(workflow_id),
                data_collection_id=data_collection_id,
                TOKEN=TOKEN,
                limit_rows=1,  # Only need one row to get schema
                load_for_options=True,
            )

            # Build column specs from the DataFrame schema
            reformat_cols: collections.defaultdict = collections.defaultdict(dict)
            for col_name in df.columns:
                dtype = str(df[col_name].dtype)
                # Map Polars dtypes to pandas-compatible types for component compatibility
                if "Int" in dtype or "UInt" in dtype:
                    col_type = "int64"
                elif "Float" in dtype:
                    col_type = "float64"
                elif "Utf8" in dtype or "String" in dtype:
                    col_type = "object"
                elif "Boolean" in dtype:
                    col_type = "bool"
                elif "Date" in dtype or "Datetime" in dtype:
                    col_type = "datetime"
                else:
                    col_type = dtype.lower()

                reformat_cols[col_name]["type"] = col_type
                reformat_cols[col_name]["description"] = "Column from joined data collection"
                reformat_cols[col_name]["specs"] = {
                    "nunique": df[col_name].n_unique(),
                    "dtype": dtype,
                }

            logger.info(
                f"✅ LRU CACHED: Generated specs for joined DC {data_collection_id} ({len(reformat_cols)} columns)"
            )
            return reformat_cols

        except Exception as e:
            logger.error(f"Error generating specs for joined DC {data_collection_id}: {str(e)}")
            return collections.defaultdict(dict)

    # Regular data collection - use existing API
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/deltatables/specs/{data_collection_id}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
        },
    )

    if response.status_code == 200:
        json_cols = response.json()
        reformat_cols: collections.defaultdict = collections.defaultdict(dict)
        for c in json_cols:
            reformat_cols[c["name"]]["type"] = c["type"]
            reformat_cols[c["name"]]["description"] = c["description"]
            reformat_cols[c["name"]]["specs"] = c["specs"]

        logger.info(
            f"✅ LRU CACHED: Fetched specs for regular DC {data_collection_id} ({len(reformat_cols)} columns)"
        )
        return reformat_cols
    else:
        logger.error(f"Error getting columns for {data_collection_id}: {response.text}")
        return collections.defaultdict(dict)


def serialize_dash_component(obj):
    # If the object is a NumPy array, convert it to a list
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: serialize_dash_component(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_dash_component(v) for v in obj]
    elif hasattr(obj, "to_dict"):
        # If the object is a Dash component with a to_dict method
        return obj.to_dict()
    elif hasattr(obj, "__dict__"):
        # Attempt to serialize objects by converting their __dict__ attribute
        return serialize_dash_component(obj.__dict__)
    else:
        # Return the object as is if none of the above conditions are met
        return obj


def analyze_structure(struct, depth=0):
    """
    Recursively analyze a nested plotly dash structure.

    Args:
    - struct: The nested structure.
    - depth: Current depth in the structure. Default is 0 (top level).
    """

    if isinstance(struct, list):
        logger.info("  " * depth + f"Depth {depth} Type: List with {len(struct)} elements")
        for idx, child in enumerate(struct):
            logger.info(
                "  " * depth + f"Element {idx} ID: {child.get('props', {}).get('id', None)}"
            )
            analyze_structure(child, depth=depth + 1)
        return

    # Base case: if the struct is not a dictionary, we stop the recursion
    if not isinstance(struct, dict):
        return

    # Extracting id if available

    id_value = struct.get("props", {}).get("id", None)
    children = struct.get("props", {}).get("children", None)

    # Printing the id value
    logger.info("  " * depth + f"Depth {depth} ID: {id_value}")

    if isinstance(children, dict):
        logger.info("  " * depth + f"Depth {depth} Type: Dict")
        # Recursive call
        analyze_structure(children, depth=depth + 1)

    elif isinstance(children, list):
        logger.info("  " * depth + f"Depth {depth} Type: List with {len(children)} elements")
        for idx, child in enumerate(children):
            logger.info(
                "  " * depth + f"Element {idx} ID: {child.get('props', {}).get('id', None)}"
            )
            # Recursive call
            analyze_structure(child, depth=depth + 1)


def analyze_structure_and_get_deepest_type(
    struct, depth=0, max_depth=0, deepest_type=None, print=False
):
    """
    Recursively analyze a nested plotly dash structure and return the type of the deepest element (excluding 'stored-metadata-component').

    Args:
    - struct: The nested structure.
    - depth: Current depth in the structure.
    - max_depth: Maximum depth encountered so far.
    - deepest_type: Type of the deepest element encountered so far.

    Returns:
    - tuple: (Maximum depth of the structure, Type of the deepest element)
    """

    if print:
        logger.info(f"Analyzing level: {depth}")  # Debug print

    # Update the maximum depth and deepest type if the current depth is greater
    current_type = None
    if isinstance(struct, dict):
        id_value = struct.get("props", {}).get("id", None)
        if isinstance(id_value, dict) and id_value.get("type") != "stored-metadata-component":
            current_type = id_value.get("type")
            if print:
                logger.info(
                    f"Found component of type: {current_type} at depth: {depth}"
                )  # Debug print

    if depth > max_depth:
        max_depth = depth
        deepest_type = current_type
        if print:
            logger.info(
                f"Updated max_depth to {max_depth} with deepest_type: {deepest_type}"
            )  # Debug print
    elif depth == max_depth and current_type is not None:
        deepest_type = current_type
        if print:
            logger.info(
                f"Updated deepest_type to {deepest_type} at same max_depth: {max_depth}"
            )  # Debug print

    if isinstance(struct, list):
        for child in struct:
            if print:
                logger.info(f"Descending into list at depth: {depth}")  # Debug print
            max_depth, deepest_type = analyze_structure_and_get_deepest_type(
                child, depth=depth + 1, max_depth=max_depth, deepest_type=deepest_type
            )
    elif isinstance(struct, dict):
        children = struct.get("props", {}).get("children", None)
        if isinstance(children, list | dict):
            if print:
                logger.info(f"Descending into dict at depth: {depth}")  # Debug print
            max_depth, deepest_type = analyze_structure_and_get_deepest_type(
                children,
                depth=depth + 1,
                max_depth=max_depth,
                deepest_type=deepest_type,
            )

    return max_depth, deepest_type
