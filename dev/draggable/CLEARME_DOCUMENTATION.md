# CLEARME Section - Removed Functionality Documentation

## Overview
This document captures functionality from the removed CLEARME section (lines 438-2643, ~2,200 lines)
that needs future restoration.

**Removal Date**: 2025-10-27
**Original File**: `depictio/dash/layouts/draggable.py`
**Section Removed**: Monolithic `populate_draggable()` callback

---

## Already Replaced (No Action Needed)

These functionalities have been successfully modularized and are working in production:

- ✅ **Add component** → `add_component_simple.py`
- ✅ **Edit component** → `edit_component_simple.py`, `edit_page.py`
- ✅ **Remove component** → `remove_component_simple.py`
- ✅ **Layout changes** → Active callback in draggable.py (update_grid_edit_mode)
- ✅ **Interactive filters** → Pattern-matching architecture with `interactive-values-store`
- ✅ **Edit mode toggle** → Active callback (update_grid_edit_mode)
- ✅ **Reset filters** → Store pattern (update_interactive_values_store)
- ✅ **Theme handling** → Theme store pattern
- ✅ **Modal close without save** → Handled by edit_page.py

---

## 🔴 TODO: Future Restoration Required

### 1. Graph Interactions (clickData/selectedData)

**Status**: Functions exist in `draggable_scenarios/graphs_interactivity.py` but not connected

**Original Location**: Lines 1527-1644 in CLEARME section

#### What It Did:
User interactions on scatter plots (click/select) filter other dashboard components.
Only works for `visu_type == "scatter"`.

#### Trigger Types:

##### A. clickData - Single Point Click

**User Action**: User clicks on a single point in a scatter plot

**Original Behavior**:
1. Extract clicked point's data values (e.g., `sample_id`, `group`)
2. Update `interactive-values-store` with single-value filter
3. Pattern-matching callbacks in other components reload with filter applied
4. Example: Click on "Sample_A" → all tables/figures show only Sample_A data

**Implementation Reference**:
```python
# Function: refresh_children_based_on_click_data()
# Location: draggable_scenarios/graphs_interactivity.py:1530-1576
#
# Signature:
def refresh_children_based_on_click_data(
    graph_click_data,
    graph_ids,
    ctx_triggered_prop_id_index,
    stored_metadata,
    interactive_components_dict,
    draggable_children,
    edit_components_mode_button,
    TOKEN,
    dashboard_id
):
    # Extract click data
    # Update interactive_components_dict
    # Rebuild affected components
    # Return updated children + interactive components
```

##### B. selectedData - Lasso/Box Selection

**User Action**: User draws lasso or box selection around multiple points

**Original Behavior**:
1. Extract all selected points' data values
2. Apply multi-value filter to `interactive-values-store`
3. Pattern-matching callbacks reload with multi-filter
4. Example: Select 5 samples → all components show only those 5 samples

**Implementation Reference**:
```python
# Function: refresh_children_based_on_selected_data()
# Location: draggable_scenarios/graphs_interactivity.py:1585-1618
#
# Signature:
def refresh_children_based_on_selected_data(
    graph_selected_data,
    graph_ids,
    ctx_triggered_prop_id_index,
    stored_metadata,
    interactive_components_dict,
    draggable_children,
    edit_components_mode_button,
    TOKEN,
    dashboard_id
):
    # Extract selected points
    # Build multi-value filter
    # Update interactive_components_dict
    # Rebuild affected components
    # Return updated children + interactive components
```

##### C. relayoutData - Zoom/Pan (NOT IMPLEMENTED)

**Original TODO Comment**: "Implement this"

**Potential Use Cases**:
- Viewport-based progressive data loading
- Zoom-level dependent detail rendering
- Pan-triggered data prefetching

**No implementation existed in CLEARME section** - this was a placeholder for future enhancement.

#### Original Callback Signature:

```python
@app.callback(
    Output("draggable", "items"),
    Output("draggable", "currentLayout"),
    Output("stored-draggable-layouts", "data"),
    Output("current-edit-parent-index", "data"),
    # ... other Outputs
    State({"type": "graph", "index": ALL}, "selectedData"),
    State({"type": "graph", "index": ALL}, "clickData"),
    State({"type": "graph", "index": ALL}, "relayoutData"),
    State({"type": "graph", "index": ALL}, "id"),
    State({"type": "stored-metadata-component", "index": ALL}, "data"),
    State("draggable", "items"),
    State("interactive-components-dict", "data"),
    State("unified-edit-mode-button", "checked"),
    State("url", "pathname"),
    State("local-store", "data"),
    # ... other States
    prevent_initial_call=True
)
def populate_draggable(...):
    # ... massive function that handled EVERYTHING

    if "graph" in triggered_input:
        graph_metadata = [e for e in stored_metadata if e["index"] == ctx_triggered_prop_id_index]

        # Restrict to scatter plots only
        if graph_metadata.get("visu_type", "").lower() == "scatter":
            if "clickData" in ctx_triggered_prop_id:
                result = refresh_children_based_on_click_data(...)
                updated_children, _ = result
                return (updated_children, dash.no_update, dash.no_update, dash.no_update)

            elif "selectedData" in ctx_triggered_prop_id:
                result = refresh_children_based_on_selected_data(...)
                updated_children, _ = result
                return (updated_children, dash.no_update, dash.no_update, dash.no_update)
```

#### Reimplementation Strategy:

**Modern Pattern-Matching Approach** (Recommended):

1. **Create dedicated callback** (don't add to monolithic function):
```python
@app.callback(
    Output("interactive-values-store", "data", allow_duplicate=True),
    Input({"type": "graph", "index": ALL}, "clickData"),
    Input({"type": "graph", "index": ALL}, "selectedData"),
    State({"type": "graph", "index": ALL}, "id"),
    State({"type": "stored-metadata-component", "index": ALL}, "data"),
    State("interactive-values-store", "data"),
    prevent_initial_call=True
)
def update_filters_from_graph_interactions(
    click_data_list,
    selected_data_list,
    graph_ids,
    stored_metadata,
    current_interactive_values
):
    """Update interactive-values-store when user clicks/selects on scatter plots"""

    # Determine which graph triggered
    triggered_idx = ctx.triggered_id["index"]

    # Find metadata for triggered graph
    graph_metadata = next((m for m in stored_metadata if m["index"] == triggered_idx), None)
    if not graph_metadata or graph_metadata.get("visu_type", "").lower() != "scatter":
        raise dash.exceptions.PreventUpdate

    # Extract filter values from click/selected data
    if "clickData" in ctx.triggered_prop_ids[0]:
        # Single point click
        filter_values = extract_click_filters(click_data_list[...])
    elif "selectedData" in ctx.triggered_prop_ids[0]:
        # Multi-point selection
        filter_values = extract_selection_filters(selected_data_list[...])

    # Update store (pattern-matching propagates to all components)
    updated_store = current_interactive_values.copy()
    updated_store[triggered_idx] = filter_values

    return updated_store
```

2. **Let pattern-matching handle propagation**: Existing component callbacks already listen to `interactive-values-store`:
   - Card components: `patch_card_with_filters()`
   - Figure components: `patch_figure_interactive()`
   - Table components: Infinite scroll callback
   - MultiQC components: Pattern-matching callback

3. **Avoid full rebuild**: Don't recreate all components - just update the store and let individual component callbacks handle their own updates (more efficient than original monolithic approach)

#### Key Differences from Original:

| Original CLEARME | Modern Approach |
|------------------|-----------------|
| Monolithic callback handling all inputs | Dedicated callback for graph interactions |
| Full dashboard rebuild on interaction | Store update + pattern-matching propagation |
| Tight coupling to draggable items | Loose coupling via store pattern |
| Scatter plot check inside large function | Early return in focused callback |
| Returns new children for all components | Returns only store update |

#### Why It Was Disabled:

Lines 2772-2835 in the active code show:
```python
# TODO: Re-enable graph interactions later
# Input({"type": "graph", "index": ALL}, "clickData"),
# Input({"type": "graph", "index": ALL}, "selectedData"),
```

Likely disabled during the pattern-matching refactor to avoid the monolithic rebuild pattern. The helper functions (`refresh_children_based_on_*`) still exist but need adaptation to the new store-based architecture.

---

### 2. Duplicate Component

**Status**: Needs full reimplementation

**Original Location**: Lines 2235-2576 (~340 lines) in CLEARME section

**User Action**: User clicks duplicate button on a component's action menu

#### Complete Algorithm (9 Steps):

##### Step 1: Permission Check

**Security**: Verify user has editor permission before allowing duplication

```python
from depictio.dash.api_calls import (
    api_call_check_project_permission,
    api_call_get_dashboard
)

# Get dashboard and project info
dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
if not dashboard_data:
    logger.warning(f"Dashboard {dashboard_id} not found - blocking duplicate operation")
    raise dash.exceptions.PreventUpdate

project_id = dashboard_data.get("project_id")
if not project_id:
    logger.warning(f"Dashboard {dashboard_id} has no project - blocking duplicate operation")
    raise dash.exceptions.PreventUpdate

# Verify editor permission
has_editor_permission = api_call_check_project_permission(
    project_id=str(project_id),
    token=TOKEN,
    required_permission="editor"
)

if not has_editor_permission:
    logger.warning(
        f"User attempted to duplicate component without editor permission on project {project_id}"
    )
    raise dash.exceptions.PreventUpdate
```

##### Step 2: Find Original Component

```python
triggered_index = ctx.triggered_id["index"]
logger.info(f"Duplicate button clicked for component: box-{triggered_index}")

# Find component in draggable children
component_to_duplicate = None
for child in draggable_children:
    child_id = get_component_id(child)  # Utility function from utils.py
    if child_id == f"box-{triggered_index}":
        component_to_duplicate = child
        break

if component_to_duplicate is None:
    logger.error(f"No component found with id 'box-{triggered_index}' to duplicate")
    return dash.no_update, dash.no_update, dash.no_update, dash.no_update
```

##### Step 3: Deep Copy Component

**Critical**: Must use `deepcopy` to avoid reference sharing

```python
import copy

# Create completely independent copy
duplicated_component = copy.deepcopy(component_to_duplicate)

# Generate new unique ID (UUID-based)
new_index = generate_unique_index()  # From utils.py
child_id = f"box-{new_index}"

logger.info(f"Generated new component ID: {child_id}")

# Update top-level component ID
duplicated_component["props"]["id"] = child_id
```

##### Step 4: Clone Metadata

**Critical**: Component metadata must be duplicated with new index

```python
# Find original component's metadata
metadata = None
for metadata_child in stored_metadata:
    if metadata_child["index"] == triggered_index:
        metadata = metadata_child.copy()  # Shallow copy of dict
        logger.info(f"Found metadata for duplication: {metadata}")
        break

if metadata is None:
    logger.warning(f"No metadata found for index {triggered_index}")
    return dash.no_update, dash.no_update, dash.no_update, dash.no_update

# Update metadata with new index
metadata["index"] = new_index

# Create new Store component for metadata
import dash_core_components as dcc
new_store = dcc.Store(
    id={"type": "stored-metadata-component", "index": new_index},
    data=metadata
)

# Add store to duplicated component's children
# Handle both list and dict children structures
if type(duplicated_component["props"]["children"]["props"]["children"]) is list:
    duplicated_component["props"]["children"]["props"]["children"].append(new_store)
elif type(duplicated_component["props"]["children"]["props"]["children"]) is dict:
    duplicated_component["props"]["children"]["props"]["children"]["props"]["children"].append(new_store)
```

##### Step 5: Update Nested IDs Recursively

**Critical**: All nested component IDs must be updated to avoid conflicts

```python
def update_nested_ids(component, old_index, new_index):
    """
    Recursively update all pattern-matching IDs in component tree.

    Updates IDs like:
      {"type": "btn-done", "index": old} → {"type": "btn-done", "index": new}
      {"type": "edit-box-button", "index": old} → {"type": "edit-box-button", "index": new}
      etc.

    Implementation exists in draggable.py line 126.
    """
    # Traverse component tree
    # Find all dict IDs with "index" key
    # Replace old_index with new_index
    # Continue recursively through children
    pass

# Apply to duplicated component
update_nested_ids(duplicated_component, triggered_index, new_index)
logger.info(f"Updated all nested IDs from {triggered_index} to {new_index}")
```

**Components that need ID updates**:
- Action buttons (edit, duplicate, remove)
- Stored metadata components
- Figure render triggers
- Interactive component stores
- Any pattern-matching components

##### Step 6: Calculate Collision-Free Layout

**Critical**: Must preserve original dimensions but place in non-overlapping position

```python
# Clean existing layouts (remove corrupted entries)
existing_layouts = clean_layout_data(draggable_layouts)  # From utils.py

# Find original component's layout to preserve dimensions
original_layout = None
original_component_id = f"box-{triggered_index}"

for layout in existing_layouts:
    if layout.get("i") == original_component_id:
        original_layout = layout
        logger.info(f"Found original layout: {original_layout}")
        break

if original_layout:
    # Preserve original dimensions (user may have customized)
    original_w = original_layout.get("w", 24)
    original_h = original_layout.get("h", 20)

    logger.info(
        f"Preserving original layout dimensions: w={original_w}, h={original_h}"
    )

    # Find bottom-most position of all existing components
    max_bottom = 0
    for layout in existing_layouts:
        if isinstance(layout, dict) and "y" in layout and "h" in layout:
            bottom = layout["y"] + layout["h"]
            max_bottom = max(max_bottom, bottom)

    # Place duplicate at bottom-left (guaranteed collision-free)
    new_x = 0
    new_y = max_bottom

    logger.info(f"Placing duplicate at bottom: x={new_x}, y={new_y}")

    # Create new layout entry
    new_layout = {
        "i": f"box-{new_index}",
        "x": new_x,
        "y": new_y,
        "w": original_w,  # Preserve width
        "h": original_h,  # Preserve height
        "moved": False,
        "static": False
    }
else:
    # Fallback: use component type defaults
    new_layout = calculate_new_layout_position(
        metadata.get("component_type", "figure"),
        existing_layouts,
        new_index,
        len(existing_layouts)
    )
    logger.warning("Could not find original layout, using defaults")
```

**Layout Placement Strategy**:
- **Goal**: Avoid overlaps with existing components
- **Method**: Place at `y = max(all_components_bottom)` and `x = 0`
- **Benefit**: Guaranteed collision-free, user can reposition after creation

##### Step 7: Handle Responsive Scaling

**IMPORTANT**: Skip responsive scaling corrections for duplicates

```python
# DO NOT call fix_responsive_scaling() for duplicate operations
# Reason: Preserve user's custom component sizes
# The fix was resetting custom sizes back to defaults

logger.info(
    "DUPLICATE - Skipping responsive scaling corrections to preserve custom component sizes"
)

# If user has resized the original component, the duplicate should inherit
# that custom size, not revert to the default component dimensions
```

**Why skip**:
- `fix_responsive_scaling()` was designed to fix grid breakpoint bugs
- For duplicates, we want to preserve user customizations
- Original may have custom dimensions that should be inherited

##### Step 8: Update Children with Patch

**Use Dash Patch for efficient updates** (only adds one component, doesn't rebuild all):

```python
from dash import Patch

# Create patch object for efficient partial update
children_patch = Patch()
children_patch.append(duplicated_component)

logger.info(f"Added duplicated component to children patch: {child_id}")
```

**Why Patch**:
- More efficient than returning full children list
- Only adds the new component
- Avoids re-rendering existing components
- Preserves component state (scroll position, zoom, etc.)

##### Step 9: Update Layouts and Storage

```python
# Add new layout to existing layouts
existing_layouts.append(new_layout)

# Update stored layouts for persistence
state_stored_draggable_layouts[dashboard_id] = existing_layouts

logger.info(
    f"Duplicated component with new id 'box-{new_index}' and assigned layout {new_layout}"
)

# Return outputs
return (
    children_patch,                    # Partial update - only adds new component
    existing_layouts,                  # Updated layouts
    state_stored_draggable_layouts,   # Updated storage
    dash.no_update                     # Don't update edit parent index
)
```

#### Original Callback Signature:

```python
@app.callback(
    Output("draggable", "items"),
    Output("draggable", "currentLayout"),
    Output("stored-draggable-layouts", "data"),
    Output("current-edit-parent-index", "data"),
    Input({"type": "duplicate-box-button", "index": ALL}, "n_clicks"),
    State({"type": "stored-metadata-component", "index": ALL}, "data"),
    State({"type": "component-container", "index": ALL}, "children"),
    State("draggable", "items"),
    State("draggable", "currentLayout"),
    State("stored-draggable-layouts", "data"),
    State("url", "pathname"),
    State("local-store", "data"),
    State("unified-edit-mode-button", "checked"),
    prevent_initial_call=True
)
```

#### Critical Helper Functions Required:

1. **`generate_unique_index()`** - From utils.py
   - Generates UUID-based unique index
   - Format: `str(uuid.uuid4())`
   - Ensures no ID collisions

2. **`update_nested_ids(component, old_index, new_index)`** - From draggable.py line 126
   - Recursively traverses component tree
   - Finds all pattern-matching IDs
   - Updates `{"type": "...", "index": old}` → `{"type": "...", "index": new}`

3. **`clean_layout_data(layouts)`** - From utils.py
   - Normalizes layout properties
   - Removes corrupted entries
   - Ensures consistent `moved`/`static` properties

4. **`get_component_id(component)`** - From utils.py
   - Extracts component ID from various formats
   - Handles both native Dash components and JSON representations
   - Returns string ID or None

5. **`calculate_new_layout_position(type, existing, id, n)`** - From draggable.py line 30
   - Calculates position for new layout item
   - Uses component type to determine default dimensions
   - Finds next available grid position

#### Edge Cases and Error Handling:

##### A. Multiple Rapid Clicks

**Problem**: User double-clicks duplicate button

```python
# Check if button was actually clicked (not initialization)
triggered_button_clicks = ctx.triggered[0]["value"]
if not triggered_button_clicks or triggered_button_clicks == 0:
    logger.debug("Button not actually clicked (0 clicks), skipping")
    return dash.no_update, dash.no_update, dash.no_update, dash.no_update

# Handle multiple triggers - only process first
if len(ctx.triggered) > 1:
    logger.debug(
        f"Multiple triggers detected ({len(ctx.triggered)}), processing only the first one"
    )
    first_trigger_id = ctx.triggered[0]["prop_id"]
    current_trigger_id = f'{{"index":"{ctx.triggered_id["index"]}","type":"duplicate-box-button"}}.n_clicks'
    if first_trigger_id != current_trigger_id:
        logger.debug(f"Skipping duplicate trigger: {current_trigger_id}")
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
```

##### B. Missing Metadata

**Problem**: Component exists but has no metadata entry

```python
if metadata is None:
    logger.warning(f"No metadata found for index {triggered_index}")
    logger.warning("Cannot duplicate component without metadata")
    return dash.no_update, dash.no_update, dash.no_update, dash.no_update
```

##### C. Component Not Found

**Problem**: Triggered index doesn't match any component

```python
if component_to_duplicate is None:
    logger.error(f"No component found with id 'box-{triggered_index}' to duplicate")
    logger.error(f"Available components: {[get_component_id(c) for c in draggable_children]}")
    return dash.no_update, dash.no_update, dash.no_update, dash.no_update
```

##### D. No Permission

**Problem**: User lacks editor permission

```python
if not has_editor_permission:
    logger.warning(
        f"User attempted to duplicate component without editor permission on project {project_id}"
    )
    # Show error notification to user (optional)
    raise dash.exceptions.PreventUpdate
```

##### E. Dashboard Not Found

**Problem**: Dashboard ID is invalid

```python
dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
if not dashboard_data:
    logger.warning(f"Dashboard {dashboard_id} not found - blocking duplicate operation")
    raise dash.exceptions.PreventUpdate
```

#### Component Types That Need Special Handling:

| Component Type | Considerations |
|----------------|----------------|
| **Figure** | Most common, straightforward duplication |
| **Card** | Simple, no special handling |
| **Table** | Check infinite scroll state preservation |
| **MultiQC** | Verify file references are copied |
| **Interactive** | Ensure dropdown/slider values are preserved |

#### Testing Checklist (When Reimplementing):

- [ ] Duplicate creates exact copy with new unique ID
- [ ] Duplicated component has same dimensions as original
- [ ] Duplicate placed at bottom of grid (collision-free)
- [ ] Metadata correctly cloned with new index
- [ ] All nested IDs updated (buttons, stores, triggers)
- [ ] Permission check prevents unauthorized duplication
- [ ] Multiple rapid clicks don't create multiple duplicates
- [ ] Works for all component types (card, figure, table, multiqc)
- [ ] Duplicate inherits original's custom size (not defaults)
- [ ] Layouts stored correctly in localStorage
- [ ] Component stores render correctly (no blank components)
- [ ] Duplicated component is immediately draggable/resizable
- [ ] Duplicate can be edited independently from original
- [ ] Duplicate can be removed independently from original
- [ ] Duplicate can itself be duplicated (recursive duplication)

---

## Helper Code Patterns (Reference Only)

These patterns were used throughout CLEARME but are preserved in active code or utils.

### Layout Restoration on Dashboard Load

**Purpose**: Restore layouts from localStorage, remove orphaned entries

**Pattern**:
```python
# Check if we have stored layouts for this dashboard
if dashboard_id in state_stored_draggable_layouts:
    # Get stored layouts
    stored_layouts = state_stored_draggable_layouts[dashboard_id]

    # Normalize format (handle legacy dict format)
    if isinstance(stored_layouts, dict):
        raw_layouts = stored_layouts.get("lg", [])
    else:
        raw_layouts = stored_layouts

    # Clean corrupted entries
    cleaned_layouts = clean_layout_data(raw_layouts)

    # Remove orphaned layouts (no matching component)
    component_ids = {get_component_id(child) for child in draggable_children}
    matched_layouts = [
        layout for layout in cleaned_layouts
        if layout.get("i") in component_ids
    ]

    draggable_layouts = matched_layouts
    logger.info(
        f"Restored {len(matched_layouts)} layouts from storage "
        f"(removed {len(cleaned_layouts) - len(matched_layouts)} orphaned)"
    )
```

**When used**:
- Dashboard initial load
- Dashboard refresh
- After component removal

### Missing Layout Generation

**Purpose**: Generate layouts for components loaded from DB but missing layout data

**Pattern**:
```python
# Build set of existing layout IDs
existing_layout_ids = {layout.get("i") for layout in draggable_layouts}

# Check each component's metadata
missing_layouts = []
for metadata in stored_metadata:
    component_index = metadata.get("index")
    if not component_index:
        continue

    # Check if this component has a layout
    box_id = f"box-{component_index}"
    if box_id not in existing_layout_ids:
        logger.info(f"Generating missing layout for component: {component_index}")

        # Generate layout based on component type
        component_type = metadata.get("component_type", "card")
        new_layout = calculate_new_layout_position(
            component_type,
            draggable_layouts + missing_layouts,  # Include previously generated
            component_index,
            len(draggable_layouts) + len(missing_layouts)
        )
        missing_layouts.append(new_layout)
        logger.info(f"Generated layout - {box_id}: {new_layout}")

# Add generated layouts
if missing_layouts:
    draggable_layouts.extend(missing_layouts)
    state_stored_draggable_layouts[dashboard_id] = draggable_layouts
    logger.info(f"Added {len(missing_layouts)} missing layouts")
```

**When used**:
- Dashboard restore from database
- Component saved without layout
- Layout corruption recovery

### Theme Extraction with Fallbacks

**Purpose**: Safely extract theme from store with multiple fallback strategies

**Pattern**:
```python
# Default fallback
theme = "light"

if theme_store:
    if isinstance(theme_store, dict):
        # Handle empty dict case
        if theme_store == {}:
            theme = "light"
        else:
            # Try new key first, then legacy key
            theme = theme_store.get("colorScheme", theme_store.get("theme", "light"))
    elif isinstance(theme_store, str) and theme_store in ["light", "dark"]:
        # Direct string format
        theme = theme_store
    else:
        logger.warning(
            f"Invalid theme_store value: {theme_store}, using default light theme"
        )
        theme = "light"
else:
    # Race condition: theme_store not populated yet
    logger.warning(
        "Theme store not populated during dashboard render, using light theme fallback"
    )
    theme = "light"

logger.info(f"Using theme: {theme}")
```

**Fallback hierarchy**:
1. `theme_store["colorScheme"]` (new format)
2. `theme_store["theme"]` (legacy format)
3. `"light"` (default fallback)

### Metadata Merging from Multiple Sources

**Purpose**: Combine metadata from 3 different stores during component creation

**Pattern**:
```python
# Step 1: Start with base metadata from component
child_metadata = tmp_stored_metadata[0].copy()  # Base metadata
child_index = child_metadata["index"]

# Step 2: Merge workflow/DC from local-store-components-metadata
if components_metadata_store and child_index in components_metadata_store:
    component_selections = components_metadata_store[child_index]

    # Only update if values are present
    if "wf_id" in component_selections and component_selections["wf_id"]:
        child_metadata["wf_id"] = component_selections["wf_id"]
    if "dc_id" in component_selections and component_selections["dc_id"]:
        child_metadata["dc_id"] = component_selections["dc_id"]
    if "wf_tag" in component_selections:
        child_metadata["wf_tag"] = component_selections.get("wf_tag")
    if "dc_tag" in component_selections:
        child_metadata["dc_tag"] = component_selections.get("dc_tag")

    logger.info(
        f"Merged workflow/DC: wf_id={child_metadata.get('wf_id')}, "
        f"dc_id={child_metadata.get('dc_id')}"
    )

# Step 3: Merge figure parameters from dict_kwargs stores
for idx, kwargs_id in enumerate(dict_kwargs_ids):
    if kwargs_id and kwargs_id.get("index") == child_index:
        kwargs_value = dict_kwargs_values[idx]
        if kwargs_value:
            child_metadata["dict_kwargs"] = kwargs_value
            logger.info(f"Merged figure params: {len(kwargs_value)} parameters")
        break
```

**Three sources**:
1. **stored-metadata-component**: Component type, mode, basic config
2. **local-store-components-metadata**: Workflow/DC selections from stepper
3. **dict_kwargs stores**: Figure visualization parameters

### Auto-Promotion for Joined Data Collections

**Purpose**: Automatically convert single DC to joined format if join config exists

**Pattern**:
```python
# Check if DC is already in joined format
if "--" not in str(dc_value):  # Single DC (not "dc_id--join_dc_id")
    logger.info(f"Checking if DC {dc_value} has join configuration")

    try:
        # Fetch DC specs from API
        TOKEN = local_data.get("access_token")
        dc_specs_response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_value}",
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=10.0
        )

        if dc_specs_response.status_code == 200:
            dc_specs = dc_specs_response.json()
            join_config = dc_specs.get("config", {}).get("join")

            # Check if join configuration exists
            if join_config and join_config.get("with_dc_id"):
                with_dc_ids = join_config["with_dc_id"]
                if with_dc_ids and len(with_dc_ids) > 0:
                    # Construct joined DC ID: "base_dc--join_target_dc"
                    join_target_id = with_dc_ids[0]  # Use first join target
                    joined_dc_id = f"{dc_value}--{join_target_id}"

                    logger.info(
                        f"AUTO-PROMOTION - DC has join config, "
                        f"promoting {dc_value} → {joined_dc_id}"
                    )

                    # Replace single DC with joined DC
                    dc_value = joined_dc_id
                else:
                    logger.info("DC has join config but no targets")
            else:
                logger.info("DC has no join configuration")
        else:
            logger.warning(
                f"Failed to fetch DC specs: {dc_specs_response.status_code}"
            )

    except Exception as join_check_error:
        logger.warning(f"Error checking for joins: {join_check_error}")
        # Continue with original dc_value if check fails

else:
    logger.info(f"DC is already in joined format: {dc_value}")

# Use dc_value (now potentially promoted to joined format)
child_metadata["dc_id"] = dc_value
```

**Benefits**:
- Transparent to user
- Automatically handles related data collections
- Enables cross-DC analysis without manual selection

---

## Why These Were Disabled

### Graph Interactions

**Evidence from active code** (lines 2772-2835):
```python
# TODO: Re-enable graph interactions later
# Input({"type": "graph", "index": ALL}, "clickData"),
# Input({"type": "graph", "index": ALL}, "selectedData"),
```

**Reason**: Disabled during pattern-matching refactor
- Monolithic `populate_draggable` was causing full dashboard rebuilds
- Pattern-matching architecture is more efficient (only affected components update)
- Graph interaction functions still exist but need adaptation to store pattern

### Duplicate Component

**Evidence**: No replacement callback found in active code

**Reason**: Likely removed during modularization effort
- Complex 9-step algorithm needed careful extraction
- Not critical for MVP (can be added later)
- User confirmed should be documented for restoration

---

## Recommended Implementation Order

When restoring these features, implement in this order:

1. **First: Duplicate Component**
   - Self-contained feature
   - No dependencies on other new features
   - Clear user value (quick component replication)
   - Can be implemented as standalone callback in new file: `duplicate_component.py`

2. **Second: Graph Interactions (clickData)**
   - Start with simpler single-point click
   - Test with scatter plots only
   - Verify store pattern integration
   - Monitor performance impact

3. **Third: Graph Interactions (selectedData)**
   - Build on clickData implementation
   - Handle multi-value filters
   - Test with lasso and box selection tools
   - Verify all component types handle multi-filters

4. **Future: relayoutData handling**
   - Advanced feature, not in original implementation
   - Consider use cases (progressive loading, zoom-dependent detail)
   - May require backend API changes

---

## Related Files

### Functions/Modules Referenced:
- `draggable_scenarios/graphs_interactivity.py` - Graph interaction handlers
- `draggable_scenarios/interactive_component_update.py` - Responsive scaling fixes
- `depictio/dash/utils.py` - Helper functions (clean_layout_data, get_component_id, generate_unique_index)
- `depictio/dash/layouts/edit.py` - Edit component functions (enable_box_edit_mode, render_raw_children)
- `depictio/dash/api_calls.py` - API permission checks

### Active Callbacks (Still Working):
- `store_wf_dc_selection` (line 248) - Metadata store management
- `update_interactive_values_store` (line 2765) - Interactive filter management
- `update_grid_edit_mode` (line 3309) - Edit mode controls
- `enable_edit_mode_from_welcome_message` (line 3495) - Welcome message interaction
- `trigger_add_button_from_message` (line 3509) - Add component message interaction

---

## Questions for Implementation

When implementing these features, consider:

1. **Graph Interactions**:
   - Should we support relayoutData or skip it?
   - Should non-scatter plots eventually be supported?
   - How to handle filter conflicts (click vs dropdown filters)?
   - Should graph filters be clearable individually?

2. **Duplicate Component**:
   - Should duplicate inherit parent's filters/state?
   - Should there be a "duplicate all" feature?
   - Should duplicate open in edit mode immediately?
   - How to handle duplicate of already-duplicated components?

3. **Testing Strategy**:
   - Manual testing sufficient or need E2E tests?
   - Performance testing with many components?
   - Browser compatibility testing?

---

## Conclusion

This document provides complete specifications for restoring graph interactions and duplicate component functionality. Both features were working in the original monolithic callback and can be reimplemented using modern pattern-matching architecture.

**Key Takeaway**: The code exists in CLEARME section with full implementation details. This document extracts the essential logic and adapts it for modern architecture.
