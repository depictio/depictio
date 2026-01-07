# Phase 2C: Clientside Callback Conversions - Summary

## Date: 2025-10-28

## Objective
Convert UI callbacks to clientside JavaScript to eliminate HTTP round-trips and reduce load time from ~3.4-3.5s (post-Phase 2A) to <1.5s target.

## Changes Made

### 1. Theme Callbacks → Clientside (4 conversions)

All AG Grid theme callbacks converted from server-side to clientside JavaScript:

#### 1.1 Table Component Theme (table_component/frontend.py:125-136)

**Before (Server-side)**:
```python
@app.callback(
    Output({"type": "table-aggrid", "index": MATCH}, "className"),
    Input("theme-store", "data"),
    prevent_initial_call=False,
)
def update_table_ag_grid_theme(theme_data):
    """Update AG Grid theme class based on current theme."""
    theme = theme_data or "light"
    if theme == "dark":
        return "ag-theme-alpine-dark"
    else:
        return "ag-theme-alpine"
```

**After (Clientside)**:
```python
# PHASE 2C: Converted to clientside callback for better performance
app.clientside_callback(
    """
    function(themeData) {
        const theme = themeData || 'light';
        return theme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine';
    }
    """,
    Output({"type": "table-aggrid", "index": MATCH}, "className"),
    Input("theme-store", "data"),
    prevent_initial_call=False,
)
```

#### 1.2 Stepper AG Grid Theme (stepper.py:1662-1673)

**Changes**:
- Added `clientside_callback` to imports (line 7)
- Converted module-level callback to clientside
- Uses same JavaScript logic as table component

#### 1.3 User Management AG Grid Theme (projectwise_user_management.py:1243-1254)

**Changes**:
- Converted app-level callback to clientside
- Same JavaScript logic for theme switching

#### 1.4 Projects AG Grid Theme (projects.py:1900-1911)

**Changes**:
- Converted app-level callback to clientside
- Same JavaScript logic for theme switching

**Impact per theme callback**:
- Eliminates 1 HTTP round-trip per theme change
- Instant visual feedback (no network latency)
- Reduces server load

---

### 2. Toggle Callbacks → Clientside (1 conversion)

#### 2.1 Edit Mode Badge Toggle (header.py:567-582)

**Before (Server-side)**:
```python
@app.callback(
    Output("unified-edit-mode-button", "checked", allow_duplicate=True),
    Input("edit-status-badge-clickable-2", "n_clicks"),
    State("unified-edit-mode-button", "checked"),
    prevent_initial_call=True,
)
def toggle_edit_mode_from_badge(n_clicks, current_state):
    """Toggle edit mode when clicking on edit status badge."""
    if n_clicks:
        return not current_state
    return dash.no_update
```

**After (Clientside)**:
```python
# PHASE 2C: Converted to clientside callback for better performance
app.clientside_callback(
    """
    function(n_clicks, current_state) {
        if (n_clicks) {
            return !current_state;
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("unified-edit-mode-button", "checked", allow_duplicate=True),
    Input("edit-status-badge-clickable-2", "n_clicks"),
    State("unified-edit-mode-button", "checked"),
    prevent_initial_call=True,
)
```

**Impact**:
- Eliminates HTTP round-trip for edit mode toggle
- Instant UI response
- Reduces server load

---

## Summary of Conversions

| Category | Conversions | Files Modified |
|----------|-------------|----------------|
| Theme callbacks | 4 | table_component/frontend.py, stepper.py, projectwise_user_management.py, projects.py |
| Toggle callbacks | 1 | header.py |
| **Total** | **5** | **5 files** |

---

## Expected Impact

### Performance Improvements (Estimated):

- **Per theme change**: 4 → 0 HTTP requests (4 × ~50ms = ~200ms saved)
- **Per edit mode toggle**: 1 → 0 HTTP requests (~50ms saved)
- **Overall**: 5 fewer HTTP requests per user interaction

### Load Time Impact:

Assuming each callback saves ~50ms on average:
- 5 callbacks × 50ms = ~250ms total savings
- Combined with Phase 2A: 3.9s → ~3.1-3.2s (estimated)

**Note**: Further conversions needed to reach <1.5s target

---

## Files Modified

1. `depictio/dash/modules/table_component/frontend.py` - Lines 125-136
2. `depictio/dash/layouts/stepper.py` - Lines 7 (import), 1662-1673 (callback)
3. `depictio/dash/layouts/projectwise_user_management.py` - Lines 1243-1254
4. `depictio/dash/layouts/projects.py` - Lines 1900-1911
5. `depictio/dash/layouts/header.py` - Lines 567-582

---

## Testing & Validation

### Pre-commit Status: ✅ All Passed

```bash
pre-commit run --files \
  depictio/dash/modules/table_component/frontend.py \
  depictio/dash/layouts/stepper.py \
  depictio/dash/layouts/projectwise_user_management.py \
  depictio/dash/layouts/projects.py \
  depictio/dash/layouts/header.py
```

All checks passed:
- ✅ Ruff format
- ✅ Ruff lint
- ✅ Ty check (type checking)

### Functional Testing Required:

1. **Theme Switching**:
   - [ ] Test light → dark theme switch
   - [ ] Test dark → light theme switch
   - [ ] Verify AG Grid tables update correctly in all contexts
   - [ ] Verify no console errors

2. **Edit Mode Toggle**:
   - [ ] Test clicking edit status badge
   - [ ] Verify edit mode toggles on/off correctly
   - [ ] Verify no console errors

3. **Browser Compatibility**:
   - [ ] Test in Chrome/Edge
   - [ ] Test in Firefox
   - [ ] Test in Safari

---

## Next Steps

### Additional Conversions Needed:

To reach the ~18 callback target and <1.5s load time, consider converting:

1. **Modal/Panel Toggles** (~5-8 more):
   - Share modal toggle (header.py)
   - Notes panel toggle
   - Parameters offcanvas toggle
   - Component edit panels

2. **Visibility/Disabled State Updates** (~5-8 more):
   - Button disable/enable based on state
   - Component visibility toggles
   - Conditional rendering helpers

3. **Simple State Synchronization** (~3-5 more):
   - Badge updates
   - Status indicators
   - UI feedback elements

### Conversion Criteria:

Good candidates for clientside conversion:
- ✅ No server-side computation needed
- ✅ No API calls or database access
- ✅ Simple conditional logic
- ✅ Pure UI state updates
- ✅ Synchronous operations

Poor candidates (keep server-side):
- ❌ Requires API calls
- ❌ Requires database access
- ❌ Complex business logic
- ❌ Data transformations
- ❌ Async operations

---

## Implementation Notes

### Clientside Callback Patterns:

**Pattern 1: Module-level (stepper.py)**
```python
from dash import clientside_callback, Input, Output

clientside_callback(
    "function(input) { return output; }",
    Output(...),
    Input(...),
)
```

**Pattern 2: App-level (table_component/frontend.py)**
```python
def register_callbacks(app):
    app.clientside_callback(
        "function(input) { return output; }",
        Output(...),
        Input(...),
    )
```

### Common JavaScript Patterns:

**Boolean toggle**:
```javascript
function(n_clicks, current_state) {
    if (n_clicks) {
        return !current_state;
    }
    return window.dash_clientside.no_update;
}
```

**Conditional string**:
```javascript
function(condition) {
    return condition ? 'value-if-true' : 'value-if-false';
}
```

**Theme switching**:
```javascript
function(themeData) {
    const theme = themeData || 'light';
    return theme === 'dark' ? 'dark-class' : 'light-class';
}
```

---

## Performance Monitoring

To measure impact:

```bash
# Start docker environment
docker compose -f docker-compose.dev.yaml up

# Run performance monitor
cd dev/performance_analysis
python performance_monitor.py

# After dashboard loads, press ENTER to capture metrics

# Analyze results
python callback_flow_analyzer.py performance_report_*.json --verbose
```

**Metrics to compare**:
- Total callback count (should decrease by 5+)
- Total load time (should decrease by ~250ms+)
- Server CPU usage (should decrease)
- Network request count (should decrease by 5+)

---

## Rollback Plan

If issues arise, revert changes:

```bash
# Revert specific file
git checkout HEAD -- depictio/dash/modules/table_component/frontend.py

# Or revert all changes
git checkout HEAD -- \
  depictio/dash/modules/table_component/frontend.py \
  depictio/dash/layouts/stepper.py \
  depictio/dash/layouts/projectwise_user_management.py \
  depictio/dash/layouts/projects.py \
  depictio/dash/layouts/header.py
```

---

## Conclusion

Phase 2C (partial) successfully converted 5 callbacks to clientside, eliminating HTTP round-trips for theme switching and edit mode toggling.

**Status**: ✅ Partial completion (5/18 target conversions)
**Next**: Additional conversions + functional testing + performance validation
