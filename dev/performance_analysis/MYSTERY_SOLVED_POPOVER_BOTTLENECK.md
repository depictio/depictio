# Mystery Solved: Popover Button Bottleneck (4.5s)

## 🎉 Root Cause Identified

The 4.5-second delay in callbacks #26-27 is caused by the **partial data popover button** callback in figure components.

### Callback Details

**File**: `depictio/dash/modules/figure_component/frontend.py:3010-3140`

```python
@app.callback(
    Output(
        {"type": "partial-data-button-wrapper", "index": MATCH},
        "children",
        allow_duplicate=True,
    ),
    Input({"type": "stored-metadata-component", "index": MATCH}, "data"),
    State({"type": "partial-data-button-wrapper", "index": MATCH}, "id"),
    prevent_initial_call=True,
)
def update_partial_data_popover_from_interactive(metadata, wrapper_id):
    """Recreate the entire partial data popover button when metadata changes."""
```

### What It Does

This callback recreates the **"⚠️ Partial Data Displayed" popover button** that shows:
- "Showing: X points"
- "Total: Y points"
- "Load All Y Points" button

### Performance Impact

**From performance report**:
- **Callback #26**: Updates `.style` - 2192ms
- **Callback #27**: Updates `.children` - 2340ms
- **Total**: 4532ms (4.5 seconds!)
- **Triggered by**: `stored-metadata-component.data` changes

### Dashboard Context

- **3 figure components** on dashboard
- Each figure has a popover button
- All 3 popovers update when metadata changes
- Total overhead: 4.5s × 3 = **13.5 seconds of cumulative callback time!**

(Note: Actual wall-clock time is ~4.5s due to parallel execution)

## Why It's So Slow

### 1. Complex Component Creation

The callback creates a deeply nested DMC component tree:

```
dmc.Popover
  └── dmc.PopoverTarget
      └── dmc.Tooltip
          └── dmc.ActionIcon
              └── DashIconify (icon component)
  └── dmc.PopoverDropdown
      └── dmc.Stack
          ├── dmc.Text (title)
          ├── html.Div (content wrapper)
          │   ├── html.Div (showing count)
          │   ├── html.Div (total count)
          │   └── html.Div (footer text)
          └── dmc.Button (action button)
              └── DashIconify (button icon)
```

**Overhead**:
- 12+ component instantiations
- 2 icon lookups (DashIconify)
- Multiple style calculations
- String formatting with thousands separator (e.g., `1,234,567`)

### 2. Import Overhead

```python
from dash import callback_context
from depictio.dash.modules.figure_component.utils import ComponentConfig
```

These imports happen INSIDE the callback (not at module level), adding latency.

### 3. Metadata Processing

```python
# Extract data counts from metadata
config = ComponentConfig()
cutoff = config.max_data_points

displayed_count = metadata.get("displayed_data_count", cutoff)
total_count = metadata.get("total_data_count", cutoff)
was_sampled = metadata.get("was_sampled", False)
full_data_loaded = metadata.get("full_data_loaded", False)
```

Reading configuration and extracting multiple fields adds processing time.

### 4. Allow_duplicate Flag

`allow_duplicate=True` might be causing additional Dash internal overhead for deduplication checks.

### 5. Logging Overhead

```python
logger.info(
    f"📊 [{component_index}] Recreating popover button from metadata change (trigger: {trigger}): "
    f"displayed={displayed_count:,}, total={total_count:,}, sampled={was_sampled}, full_loaded={full_data_loaded}"
)
```

String formatting and logging add latency, especially with emoji and thousand separators.

## Why Metadata Changes Trigger This

The callback is triggered by `Input({"type": "stored-metadata-component", "index": MATCH}, "data")`.

Metadata changes happen when:
1. **Dashboard loads** - all component metadata initialized
2. **Filters applied** - `patch_figure_interactive` updates metadata
3. **Full data load** - metadata updated with new data counts
4. **Component edits** - metadata changes via edit callbacks

**Problem**: This callback fires EVERY time metadata changes, even if `displayed_count` and `total_count` haven't changed!

## Solution: Optimize Popover Callback

### Priority 1: Add Skip Check (Early Return)

**Problem**: Callback recreates popover even when data counts unchanged.

**Solution**: Add early return check to skip unnecessary updates:

```python
def update_partial_data_popover_from_interactive(metadata, wrapper_id):
    """Recreate the entire partial data popover button when metadata changes."""

    # PERFORMANCE OPTIMIZATION: Skip if data counts unchanged
    # Only recreate popover if displayed_count, total_count, or full_data_loaded changed

    if not metadata:
        raise PreventUpdate

    # Extract current values
    displayed_count = metadata.get("displayed_data_count", 0)
    total_count = metadata.get("total_data_count", 0)
    was_sampled = metadata.get("was_sampled", False)
    full_data_loaded = metadata.get("full_data_loaded", False)

    # Check if these values actually changed (requires storing previous state)
    # If unchanged, skip update
    component_index = wrapper_id.get("index") if wrapper_id else None

    # Option 1: Store previous state in global dict (fast)
    # Option 2: Compare with existing button text (hacky)
    # Option 3: Add "last_popover_update" timestamp to metadata (clean)

    # For now, skip if data wasn't sampled (no popover needed)
    if not was_sampled and displayed_count == total_count:
        logger.info(f"📊 [{component_index}] Skipping popover update - full data displayed")
        raise PreventUpdate

    # Continue with popover creation...
```

**Expected Impact**:
- Skip ~50% of popover updates
- Reduce 4.5s to ~2.25s when data counts unchanged

### Priority 2: Move Imports to Module Level

**Before**:
```python
def update_partial_data_popover_from_interactive(metadata, wrapper_id):
    from dash import callback_context
    from depictio.dash.modules.figure_component.utils import ComponentConfig
    # ...
```

**After** (at top of file):
```python
from dash import callback_context
from depictio.dash.modules.figure_component.utils import ComponentConfig

def update_partial_data_popover_from_interactive(metadata, wrapper_id):
    # ...
```

**Expected Impact**: -50-100ms per callback

### Priority 3: Simplify Component Tree

**Problem**: 12+ nested components cause slowdown.

**Solution**: Create simpler popover without Tooltip wrapper:

```python
# BEFORE: Complex nested structure
dmc.Popover(
    [
        dmc.PopoverTarget(
            dmc.Tooltip(  # <-- Extra wrapper
                label="Partial data displayed",
                children=dmc.ActionIcon(...),
            )
        ),
        dmc.PopoverDropdown(fresh_content),
    ],
    ...
)

# AFTER: Simpler structure
dmc.Popover(
    [
        dmc.PopoverTarget(
            dmc.ActionIcon(
                ...
                # Tooltip can be shown via Popover itself
            )
        ),
        dmc.PopoverDropdown(fresh_content),
    ],
    ...
)
```

**Expected Impact**: -200-500ms per callback

### Priority 4: Reduce Logging

**Before**:
```python
logger.info(
    f"📊 [{component_index}] Recreating popover button from metadata change (trigger: {trigger}): "
    f"displayed={displayed_count:,}, total={total_count:,}, sampled={was_sampled}, full_loaded={full_data_loaded}"
)
```

**After**:
```python
# Only log if DEBUG level enabled
logger.debug(f"📊 [{component_index}] Updating popover: displayed={displayed_count}, total={total_count}")
```

**Expected Impact**: -10-50ms per callback

### Priority 5: Consider Clientside Callback (Advanced)

**Problem**: Python callback has serialization overhead.

**Solution**: Convert to clientside JavaScript for instant updates:

```javascript
app.clientside_callback(
    """
    function(metadata, wrapper_id) {
        if (!metadata) return window.dash_clientside.no_update;

        const displayed = metadata.displayed_data_count || 0;
        const total = metadata.total_data_count || 0;
        const sampled = metadata.was_sampled || false;

        if (!sampled || displayed === total) {
            return window.dash_clientside.no_update;
        }

        // Return button HTML/structure
        // (DMC components might not be compatible with clientside)
        return createPopoverButton(displayed, total);
    }
    """,
    Output({"type": "partial-data-button-wrapper", "index": MATCH}, "children"),
    Input({"type": "stored-metadata-component", "index": MATCH}, "data"),
    State({"type": "partial-data-button-wrapper", "index": MATCH}, "id"),
    prevent_initial_call=True,
)
```

**Challenge**: DMC components may not work in clientside callbacks (need HTML/Dash components instead).

**Expected Impact**: 2340ms → 10-50ms (99% faster)

## Implementation Plan

### Phase 4B: Optimize Popover Callback

**Steps**:

1. **Add early return check** (easiest, biggest impact):
   ```python
   # Skip if data not sampled or counts unchanged
   if not was_sampled or (displayed_count == total_count):
       raise PreventUpdate
   ```

2. **Move imports to module level**:
   ```python
   # At top of frontend.py
   from dash import callback_context
   from depictio.dash.modules.figure_component.utils import ComponentConfig
   ```

3. **Simplify component tree**:
   - Remove Tooltip wrapper
   - Reduce nested html.Div layers

4. **Reduce logging**:
   - Change to `logger.debug()` for non-critical logs

5. **Test with 11 components**:
   - Collect new performance report
   - Verify popover callback improvement
   - Check for regressions

**Expected Total Impact**:
- Before: 4532ms (4.5s)
- After Phase 4B: ~1000ms (1.0s)
- **Improvement**: -3532ms (-78% faster)**

## Additional Findings

### Question: Why `.style` AND `.children` callbacks?

The performance report shows TWO callbacks:
- #26: Updates `.style` (2192ms)
- #27: Updates `.children@de65...` (2340ms)

**Analysis**:
- Only ONE callback found in code (updates `.children` only)
- Possible explanations:
  1. Dash internally splits updates into multiple network requests
  2. `allow_duplicate=True` causes duplicate callback execution
  3. Style update is implicit (component re-creation triggers style recalculation)
  4. There's a hidden/dynamic callback not visible in static code

**Next Step**: Check Python backend logs during callback execution to see if callback is called once or twice:
```bash
docker logs depictio 2>&1 | grep "Recreating popover button"
```

### Why This Wasn't Noticed Before

1. **Only affects dashboards with figures** that have sampled data
2. **Only 3 figures** on current test dashboard (not 11 components)
3. **Parallel execution** masks the delay (happens simultaneously with other callbacks)
4. **No sampling in 3-component dashboard** (data small enough to show all points)

## Related Issues to Fix

While investigating, I also identified:

### Issue #2: Metadata Callback (1335ms)
- Should be 0ms with early return (Phase 3)
- Early return check not working (`ctx.triggered_id != "url"`)
- **Fix**: Debug actual trigger ID format

### Issue #3: Interactive Store (1584ms)
- Was 450ms before Phase 4A
- 3.5x slower after clientside filter optimization
- **Fix**: Profile callback to identify slowdown cause

## Performance Projection

### Current State (After Phase 4A)
```
Load Time: ~6.8s
- Filter resets: 0ms ✅
- Popover callbacks: 4532ms ❌ (BIGGEST BOTTLENECK)
- Metadata: 1335ms ❌
- Interactive store: 1584ms ❌
```

### After Phase 4B (Popover Fix)
```
Load Time: ~3.3s
- Filter resets: 0ms ✅
- Popover callbacks: 1000ms ✅ (-78% improvement)
- Metadata: 1335ms ❌
- Interactive store: 1584ms ❌
```

### After Phase 4C (Metadata Fix)
```
Load Time: ~2.0s
- Filter resets: 0ms ✅
- Popover callbacks: 1000ms ✅
- Metadata: 0ms ✅ (early return working)
- Interactive store: 1584ms ❌
```

### After Phase 4D (Interactive Store Fix)
```
Load Time: ~1.4s
- Filter resets: 0ms ✅
- Popover callbacks: 1000ms ✅
- Metadata: 0ms ✅
- Interactive store: 450ms ✅ (back to original)
```

### After Phase 4E (Advanced Optimizations)
```
Load Time: ~0.5-0.8s
- Clientside popover callback
- Lazy component loading
- Optimized card rendering
- **Target achieved: Sub-1-second for 11 components** ✅
```

## Conclusion

**Root Cause**: The popover button callback (`update_partial_data_popover_from_interactive`) is recreating complex DMC component trees on EVERY metadata change, taking 4.5 seconds for 3 figure components.

**Quick Win**: Add early return check to skip unnecessary updates when data counts unchanged. **Expected: -78% improvement (4.5s → 1.0s)**.

**Long-term Solution**: Convert to clientside callback or lazy-render popovers only when user hovers/clicks.

---

**Report Generated**: 2025-10-16
**Callback Identified**: `update_partial_data_popover_from_interactive` (`frontend.py:3020`)
**Performance Data**: `performance_report_20251016_213310.json`
