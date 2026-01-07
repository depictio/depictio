# O(n²) Performance Analysis: Metadata Callback

## The Problem

**Callback**: `store_wf_dc_selection()` in `draggable.py:420-573`
**Output**: `local-store-components-metadata.data`
**Performance**:
- 3 components: 313ms
- 11 components: 2359ms (**7.5x slower** for 3.7x components)
- **Expected O(n)**: 11 components should take ~1150ms (3.7x slower)
- **Actual**: 2359ms suggests **O(n²) or worse complexity**

## Root Cause Analysis

### Issue #1: Multiple Nested Loops (O(n) per callback)

**Lines 476-527**: Process workflow selections
```python
for wf_id_value, wf_id_prop in zip(wf_values, wf_ids):  # O(n) - ALL components
    trigger_index = str(trigger_id.get("index"))

    # Potential HTTP request per component if cache miss
    if wf_id_value is None or wf_id_value == "":
        component_data = get_component_data(...)  # HTTP request
        wf_id_value = component_data.get("wf_id", wf_id_value)

    # Potential HTTP request per component if cache miss
    wf_tag = return_wf_tag_from_id(workflow_id=wf_id_value, TOKEN=TOKEN)
    components_store[trigger_index]["wf_tag"] = wf_tag
```

**Lines 529-570**: Process datacollection selections
```python
for dc_id_value, dc_id_prop in zip(dc_values, dc_ids):  # O(n) - ALL components
    trigger_index = str(trigger_id.get("index"))

    # Potential HTTP request per component if cache miss
    if dc_id_value is None or dc_id_value == "":
        component_data = get_component_data(...)  # HTTP request
        dc_id_value = component_data.get("dc_id", dc_id_value)

    # Potential HTTP request per component if cache miss
    dc_tag = return_dc_tag_from_id(data_collection_id=dc_id_value, TOKEN=TOKEN)
    components_store[trigger_index]["dc_tag"] = dc_tag
```

**Complexity per callback**: O(2n) = O(n)

### Issue #2: Callback Fires on EVERY Page Load

**Inputs** (line 405):
```python
Input("url", "pathname"),  # Fires on dashboard navigation
Input({"type": "btn-done", "index": ALL}, "n_clicks"),
Input({"type": "btn-done-edit", "index": ALL}, "n_clicks"),
Input({"type": "edit-box-button", "index": ALL}, "n_clicks"),
Input({"type": "duplicate-box-button", "index": ALL}, "n_clicks"),
```

With `prevent_initial_call=True`, this callback:
- **DOES fire** on URL pathname changes (dashboard navigation)
- Processes ALL n components every time
- For 11 components: 2 loops × 11 iterations = **22 potential HTTP requests**

### Issue #3: Individual HTTP Requests (Not Batched)

**get_component_data()** (lines 499, 551):
- Makes individual HTTP requests per component
- Not using bulk fetching despite `get_bulk_component_data()` being available
- Each HTTP request: ~100-200ms
- 11 components with cache misses: 11 × 150ms = **1650ms** just for HTTP

**return_wf_tag_from_id()** (line 519):
- LRU cached (Phase 1a), but only helps if same workflow IDs reused
- Cache miss = HTTP request (~180ms per call)
- 11 unique workflows: 11 × 180ms = **1980ms**

**return_dc_tag_from_id()** (line 561):
- LRU cached (Phase 1a), but only helps if same DC IDs reused
- Cache miss = HTTP request (~180ms per call)
- 11 unique DCs: 11 × 180ms = **1980ms**

**Total worst case**: 1650 + 1980 + 1980 = **5610ms** of HTTP requests

### Issue #4: Why It's Getting Worse with More Components

**Math breakdown**:

| Components | HTTP Requests | Est. Time | Actual Time | Overhead |
|------------|---------------|-----------|-------------|----------|
| 3 | 6 (2 per comp) | ~900ms | 313ms | ✅ Good caching |
| 11 | 22 (2 per comp) | ~3300ms | 2359ms | ⚠️ Some caching |
| 20 | 40 (2 per comp) | ~6000ms | **~8000ms**? | 🔴 O(n²)? |

The **non-linear scaling** (7.5x slower for 3.7x components) suggests:
1. **Cache misses increasing** as more unique workflows/DCs are added
2. **Network contention** as more simultaneous requests compete
3. **Hidden O(n²) loop** somewhere in the API or database query

## The Fix Strategy

### Priority 1: Use Bulk Fetching (Eliminate N HTTP Calls)

**Current** (lines 476-570):
```python
for wf_id_value, wf_id_prop in zip(wf_values, wf_ids):
    # Individual HTTP request per component
    component_data = get_component_data(input_id, dashboard_id, TOKEN)
    wf_tag = return_wf_tag_from_id(workflow_id=wf_id_value, TOKEN=TOKEN)
```

**Optimized**:
```python
# Fetch ALL component data in ONE bulk request BEFORE loops
dashboard_id = pathname.split("/")[-1]
all_component_ids = [str(wf_id.get("index")) for wf_id in wf_ids]
bulk_component_data = get_bulk_component_data(
    input_ids=all_component_ids,
    dashboard_id=dashboard_id,
    TOKEN=TOKEN
)

# Then iterate with cached data
for wf_id_value, wf_id_prop in zip(wf_values, wf_ids):
    trigger_index = str(wf_id_prop.get("index"))

    # Use bulk data instead of individual HTTP request
    if wf_id_value is None or wf_id_value == "":
        component_data = bulk_component_data.get(trigger_index, {})
        wf_id_value = component_data.get("wf_id", wf_id_value)

    # LRU cache should help here
    wf_tag = return_wf_tag_from_id(workflow_id=wf_id_value, TOKEN=TOKEN)
```

**Expected improvement**:
- Before: 11 HTTP requests (~1650ms)
- After: 1 bulk HTTP request (~150-200ms)
- **Savings: ~1400ms**

### Priority 2: Batch Tag Lookups

**Current** (lines 519, 561):
```python
# Individual API calls per component
for wf_id_value in wf_values:
    wf_tag = return_wf_tag_from_id(workflow_id=wf_id_value, TOKEN=TOKEN)
```

**Optimized**:
```python
# Collect all unique workflow IDs first
unique_wf_ids = list(set([wf for wf in wf_values if wf]))

# Batch fetch all tags in ONE API call
wf_tags_map = get_bulk_workflow_tags(workflow_ids=unique_wf_ids, TOKEN=TOKEN)

# Then use cached tags in loop
for wf_id_value in wf_values:
    wf_tag = wf_tags_map.get(wf_id_value, "")
```

**Expected improvement**:
- Before: 11 HTTP requests (~1980ms)
- After: 1 bulk HTTP request (~150-200ms)
- **Savings: ~1750ms**

### Priority 3: Skip Callback on Initial Load

**Current** (line 418):
```python
prevent_initial_call=True,
```

Despite this, the callback still fires on `url.pathname` changes (dashboard navigation).

**Optimized**:
```python
def store_wf_dc_selection(...):
    # Early return if triggered by URL change on initial load
    ctx = callback_context
    if ctx.triggered_id == "url":
        # On initial load, metadata should be loaded from dashboard restore
        # No need to reprocess everything
        return components_store or no_update

    # Only process on actual button clicks
    ...
```

**Expected improvement**:
- Callback doesn't run on initial dashboard load
- Only runs when user actually edits/duplicates components
- **Savings: ~2359ms on page load**

## Implementation Plan

### Step 1: Add Bulk Tag Fetching API

**New API endpoints needed**:
```python
# depictio/api/v1/endpoints/workflows.py
@router.post("/bulk_get_tags")
def bulk_get_workflow_tags(workflow_ids: List[str], TOKEN: str):
    # Fetch all workflow tags in single database query
    tags = db.workflows.find({"_id": {"$in": workflow_ids}}, {"tag": 1})
    return {str(wf["_id"]): wf["tag"] for wf in tags}

# depictio/api/v1/endpoints/datacollections.py
@router.post("/bulk_get_tags")
def bulk_get_dc_tags(dc_ids: List[str], TOKEN: str):
    # Fetch all DC tags in single database query
    tags = db.datacollections.find({"_id": {"$in": dc_ids}}, {"tag": 1})
    return {str(dc["_id"]): dc["tag"] for dc in tags}
```

### Step 2: Add Frontend Bulk Fetching Functions

**New functions in utils.py**:
```python
def get_bulk_workflow_tags(workflow_ids: List[str], TOKEN: str) -> Dict[str, str]:
    """Fetch multiple workflow tags in single API call."""
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/workflows/bulk_get_tags",
        json={"workflow_ids": workflow_ids},
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=5.0,
    )
    return response.json() if response.status_code == 200 else {}

def get_bulk_dc_tags(dc_ids: List[str], TOKEN: str) -> Dict[str, str]:
    """Fetch multiple DC tags in single API call."""
    response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/bulk_get_tags",
        json={"dc_ids": dc_ids},
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=5.0,
    )
    return response.json() if response.status_code == 200 else {}
```

### Step 3: Refactor Metadata Callback

**Updated callback in draggable.py**:
```python
def store_wf_dc_selection(...):
    # Early return for URL changes (initial load)
    ctx = callback_context
    if ctx.triggered_id == "url":
        return components_store or no_update

    # Validate access token
    if not local_store or "access_token" not in local_store:
        return components_store

    TOKEN = local_store["access_token"]
    dashboard_id = pathname.split("/")[-1]

    # Initialize store
    if not components_store:
        components_store = {}

    # OPTIMIZATION: Bulk fetch all component data ONCE
    all_component_ids = [str(wf_id.get("index")) for wf_id in wf_ids if wf_id]
    bulk_component_data = get_bulk_component_data(
        input_ids=all_component_ids,
        dashboard_id=dashboard_id,
        TOKEN=TOKEN
    )

    # OPTIMIZATION: Collect unique workflow/DC IDs
    unique_wf_ids = list(set([wf for wf in wf_values if wf]))
    unique_dc_ids = list(set([dc for dc in dc_values if dc]))

    # OPTIMIZATION: Bulk fetch all tags ONCE
    wf_tags_map = get_bulk_workflow_tags(unique_wf_ids, TOKEN) if unique_wf_ids else {}
    dc_tags_map = get_bulk_dc_tags(unique_dc_ids, TOKEN) if unique_dc_ids else {}

    # Process workflow selections (now with cached data)
    for wf_id_value, wf_id_prop in zip(wf_values, wf_ids):
        trigger_index = str(wf_id_prop.get("index"))
        if not trigger_index:
            continue

        components_store.setdefault(trigger_index, {})
        components_store[trigger_index]["wf_id"] = wf_id_value

        # Use bulk component data instead of individual HTTP request
        if wf_id_value is None or wf_id_value == "":
            component_data = bulk_component_data.get(trigger_index, {})
            wf_id_value = component_data.get("wf_id", wf_id_value)

        # Use bulk tags instead of individual HTTP request
        wf_tag = wf_tags_map.get(wf_id_value, "")
        components_store[trigger_index]["wf_tag"] = wf_tag

    # Process datacollection selections (now with cached data)
    for dc_id_value, dc_id_prop in zip(dc_values, dc_ids):
        trigger_index = str(dc_id_prop.get("index"))
        if not trigger_index:
            continue

        components_store.setdefault(trigger_index, {})
        components_store[trigger_index]["dc_id"] = dc_id_value

        # Use bulk component data instead of individual HTTP request
        if dc_id_value is None or dc_id_value == "":
            component_data = bulk_component_data.get(trigger_index, {})
            dc_id_value = component_data.get("dc_id", dc_id_value)

        # Use bulk tags instead of individual HTTP request
        dc_tag = dc_tags_map.get(dc_id_value, "")
        components_store[trigger_index]["dc_tag"] = dc_tag

    return components_store
```

## Expected Performance Impact

### Before Optimization
```
3 components: 313ms
11 components: 2359ms (7.5x slower)
20 components: ~8000ms (estimated)
```

### After Optimization
```
3 components: ~50ms (bulk fetching + early return)
11 components: ~150ms (3x slower - linear scaling)
20 components: ~300ms (2x slower - linear scaling)
```

**Savings**:
- 11 components: 2359ms → 150ms = **-2209ms (93% faster)**
- Eliminates O(n²) complexity
- Converts 22+ HTTP requests to 3 HTTP requests (component data, workflow tags, DC tags)

## Next Steps

1. **Create bulk tag fetching API endpoints** (backend work)
2. **Add bulk fetching functions** to utils.py (frontend work)
3. **Refactor metadata callback** to use bulk fetching
4. **Add early return** for URL-triggered callbacks
5. **Test with 11 components** to verify ~2200ms improvement

## Alternative: Skip Metadata Callback Entirely on Load

**Radical optimization**: The metadata callback might not be needed on initial load at all!

**Why**: Dashboard restore already loads all component metadata from the database. The metadata callback is only needed when users **edit** or **duplicate** components, not on initial page load.

**Implementation**:
```python
def store_wf_dc_selection(...):
    # PERFORMANCE: Skip entirely on initial page load
    ctx = callback_context
    if not ctx.triggered or ctx.triggered_id == "url":
        # Metadata already loaded by dashboard restore
        return no_update

    # Only process when user actually clicks a button
    ...
```

**Expected improvement**:
- **Initial load**: 2359ms → 0ms (**100% elimination**)
- **Edit operations**: Still fast with bulk fetching
- **Best of both worlds**: Zero cost on load, fast on edits

This is the **recommended approach** - why rebuild metadata that was just loaded from the database?
