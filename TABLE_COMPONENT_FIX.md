# Table Component Fix - Empty cols_json Issue

**Date**: 2026-01-20
**Status**: ✅ **FIXED** - Awaiting Testing

## Problem

Table components were showing only an "ID" column with no data, even though:
- ✅ Download button returned correct data
- ✅ Deltatable existed with 150 rows × 7 columns
- ✅ Component `dc_id` matched deltatable
- ✅ API endpoints were working

## Root Cause

When a saved dashboard is loaded from MongoDB, table components have **empty `cols_json: {}`**.

The `build_table()` function in `depictio/dash/modules/table_component/utils.py` (line 168) only creates data columns if `cols_json` is populated:

```python
if cols:  # False when cols_json is {}
    data_columns = []
    for c, e in cols.items():
        # Build column definitions
```

Since `cols_json` was empty, only the ID column was added to `columnDefs`, resulting in a table with no visible data columns.

## Why cols_json is Empty

- `cols_json` is **not stored in YAML** (intentionally - it's metadata derived from deltatable)
- When YAML is imported, `cols_json` is set to `{}` in MongoDB
- **Design mode**: Fetches `cols_json` dynamically via `get_columns_from_data_collection()`
- **View mode**: Was passing empty `cols_json` directly to `build_table()` ❌

## The Fix

**File**: `depictio/dash/layouts/draggable_scenarios/restore_dashboard.py`

**Location**: Before line 237 (before building components)

**Implementation**: Fetch `cols_json` dynamically for table components when loading a dashboard:

```python
# CRITICAL FIX: Fetch cols_json for table components if empty
if component_type == "table" and (not child_metadata.get("cols_json") or child_metadata.get("cols_json") == {}):
    logger.info(f"📊 Table component has empty cols_json, fetching from data collection...")
    wf_id = child_metadata.get("wf_id")
    dc_id = child_metadata.get("dc_id")
    if wf_id and dc_id:
        try:
            from depictio.dash.utils import get_columns_from_data_collection
            cols_json = get_columns_from_data_collection(wf_id, dc_id, TOKEN)
            child_metadata["cols_json"] = cols_json
            logger.info(f"✅ Fetched {len(cols_json)} columns for table component")
        except Exception as e:
            logger.error(f"❌ Failed to fetch cols_json for table: {e}")
            child_metadata["cols_json"] = {}
```

This mirrors what design mode does but applies it to view mode.

## How It Works

1. Dashboard loads from MongoDB with `cols_json: {}`
2. `restore_dashboard.py` iterates through components
3. For each table component:
   - Check if `cols_json` is empty
   - If yes, call `get_columns_from_data_collection(wf_id, dc_id, TOKEN)`
   - Populate `child_metadata["cols_json"]` with fetched column definitions
4. Pass populated metadata to `build_table()`
5. `build_table()` creates all data columns (not just ID)

## Expected Result

After refreshing the dashboard:
- ✅ Table should show 7 columns: sepal.length, sepal.width, petal.length, petal.width, variety, depictio_run_id, aggregation_time
- ✅ Table should display 150 rows of data (with infinite scroll pagination)
- ✅ Column headers should have proper names and tooltips
- ✅ Filters and sorting should work

## Testing

1. **Refresh the dashboard** in the browser (may need hard refresh: Cmd+Shift+R / Ctrl+Shift+F5)
2. **Check frontend logs**:
   ```bash
   docker logs depictio-frontend --tail 100 | grep -E "(cols_json|Fetched.*columns|Table component)"
   ```
   Expected: `✅ Fetched 7 columns for table component`

3. **Verify table rendering**:
   - Columns: Should see 7 data columns + ID column
   - Data: Should see rows of iris data
   - Pagination: Should be able to scroll/paginate through 150 rows

4. **Test functionality**:
   - Column filters (click filter icon in headers)
   - Column sorting (click headers)
   - Download button (should still work as before)
   - Interactive filters (should filter table data)

## Files Modified

1. **`depictio/dash/layouts/draggable_scenarios/restore_dashboard.py`** (lines 232-247)
   - Added dynamic `cols_json` fetching for table components
   - Mirrors design mode behavior

## Why This Approach

**Alternative considered**: Store `cols_json` in MongoDB

**Rejected because**:
- `cols_json` can become stale if deltatable schema changes
- Would increase MongoDB storage unnecessarily
- Design mode already fetches dynamically - view mode should too

**Chosen approach**: Fetch `cols_json` on-demand when loading dashboard
- ✅ Always up-to-date with deltatable schema
- ✅ Minimal storage in MongoDB
- ✅ Consistent with design mode behavior
- ✅ Works across YAML export/import cycles

## Edge Cases Handled

1. **Missing wf_id or dc_id**: Skips fetch, table shows empty
2. **API call fails**: Logs error, table shows with ID column only
3. **Non-empty cols_json**: Skips fetch (respects existing data)
4. **Non-table components**: Skips fetch (only runs for tables)

## Rollback

If issues arise:
```bash
git checkout HEAD -- depictio/dash/layouts/draggable_scenarios/restore_dashboard.py
docker restart depictio-frontend
```

## Related Issues

- MVP YAML system stores empty `cols_json: {}` (intentional)
- Tables work in design mode but not view mode (now fixed)
- Download button works but table doesn't display (cols_json vs data loading)
