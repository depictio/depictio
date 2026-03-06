# Conditional Highlighting — Callback Architecture Report

## Overview

This prototype implements a conditional highlighting engine for Plotly scatter
plots using **5 callbacks** (2 slider-range, 2 toggle, 1 main). The design
prioritises simplicity and a single source of truth for the highlight mask.

---

## Callback Map

| # | Callback | Inputs | Outputs | Trigger |
|---|----------|--------|---------|---------|
| 1 | `_update_slider` (cond 1) | `cond-1-col`, `cond-1-abs` | slider min/max/step/value/marks | Column or abs toggle change |
| 2 | `_update_slider` (cond 2) | `cond-2-col`, `cond-2-abs` | slider min/max/step/value/marks | Column or abs toggle change |
| 3 | `_toggle` (cond 1) | `cond-1-enabled` | disabled state for col/op/abs/slider | Switch toggle |
| 4 | `_toggle` (cond 2) | `cond-2-enabled` | disabled state for col/op/abs/slider | Switch toggle |
| 5 | `update_main_view` | 15 Inputs (all controls) | figure, rowData, columnDefs, summary children, 2× condition display | Any control change |

### Data Flow Diagram

```
┌─────────────┐     ┌─────────────┐
│ Cond Column  │────▶│ Slider Range │  (callbacks 1-2, prevent_initial_call)
│ Cond Abs     │     │ min/max/step │
└─────────────┘     └──────┬──────┘
                           │ value
    ┌──────────────────────┼──────────────────────────┐
    │                      ▼                          │
    │  ┌──────────────────────────────────────────┐   │
    │  │         update_main_view (callback 5)    │   │
    │  │                                          │   │
    │  │  1. Compute highlight mask (AND logic)   │   │
    │  │  2. Build go.Figure with traces          │   │
    │  │  3. Build AG Grid rowData                │   │
    │  │  4. Build summary badges                 │   │
    │  └────┬────────┬────────┬───────────────────┘   │
    │       │        │        │                       │
    │       ▼        ▼        ▼                       │
    │   dcc.Graph  dag.AgGrid  dmc.Group (summary)    │
    │                                                 │
    │  ┌─────────────────────────────────────────┐    │
    │  │  Axis / Color / Scale selectors         │────┘
    │  │  Condition enables / operators / values  │
    │  └─────────────────────────────────────────┘
    └─────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Single main callback (not store-chained)

All three outputs (figure, table, summary) are computed in **one callback**.
This avoids:
- Extra serialisation through `dcc.Store`
- Race conditions between chained callbacks
- Duplicate computation of the highlight mask

**Trade-off**: the callback is heavy (figure + table + summary), but for
≤10 K rows this is sub-100 ms and fine for interactive use.

### 2. Slider range callbacks with `prevent_initial_call=True`

The layout hardcodes initial slider ranges matching the default data. The
slider-range callbacks only fire when the user changes the column or abs
toggle, avoiding an initial-load flash where the slider resets to the midpoint.

### 3. Highlight within groups (not override)

When a color column is set, each group keeps its assigned color. Highlighted
points get `opacity=0.9, size=8` with a white border; non-highlighted get
`opacity=0.12, size=5`. This preserves group identity while making the
selection visually prominent.

### 4. Threshold lines tied to axis

vline/hline are only drawn when the condition column matches the current x or y
axis. With `|abs|` enabled, symmetric lines are drawn at ±threshold.

---

## Adapting for Depictio

### Pattern-Matching Callbacks

The prototype uses static string IDs (`"cond-1-col"`, `"main-scatter"`).
Depictio uses **pattern-matching IDs** for multi-instance components:

```python
# Prototype (static)
Input("cond-1-col", "value")

# Depictio (pattern-matching)
Input({"type": "cond-col", "index": MATCH}, "value")
```

**Migration path**:
1. Replace static IDs with `{"type": ..., "index": ...}` dicts
2. Use `MATCH` for per-component callbacks, `ALL` for aggregation
3. The condition panels become a reusable component factory

### Store-Based State

For Depictio's multi-page architecture, the highlight mask should be persisted
in a `dcc.Store`:

```python
dcc.Store(id={"type": "highlight-store", "index": component_id})
```

This enables:
- Cross-component synchronisation (figure ↔ table ↔ card)
- Server-side caching for large datasets
- Undo/redo via store history

### Component Registration

Depictio's stepper system registers components via the API. The condition
highlighting config would be stored as part of the component metadata:

```python
class ConditionalHighlightConfig(BaseModel):
    conditions: list[Condition]  # max 2
    x_col: str
    y_col: str
    color_col: str | None
    x_scale: Literal["linear", "log"]
    y_scale: Literal["linear", "log"]

class Condition(BaseModel):
    column: str
    operator: Literal[">", "<", ">=", "<="]
    threshold: float
    use_absolute: bool = False
    enabled: bool = True
```

### Batch Rendering

Depictio uses batch figure rendering (all figures update in one callback via
`Serverside` caching). The highlight mask computation should happen during the
batch render, not as a separate callback chain.

### Clientside Callbacks

For instant UI feedback (slider drag → threshold line), consider a clientside
callback that updates only the `layout.shapes` of the figure without
re-rendering all traces:

```python
app.clientside_callback(
    """
    function(sliderVal, figure) {
        const newFig = {...figure};
        newFig.layout.shapes = [
            {type: 'line', x0: sliderVal, x1: sliderVal, ...}
        ];
        return newFig;
    }
    """,
    Output("figure", "figure"),
    Input("slider", "value"),
    State("figure", "figure"),
)
```

---

## Performance Considerations

| Dataset size | Current approach | Recommended for Depictio |
|-------------|-----------------|-------------------------|
| < 5 K rows  | Direct (current) | Same |
| 5–50 K rows | OK, may lag on slider drag | Debounce slider (200 ms), use `Patch()` for figure updates |
| 50 K–500 K  | Slow | WebGL (`Scattergl`), server-side aggregation, virtual AG Grid |
| > 500 K     | Not feasible client-side | Server-side compute + downsampled scatter, infinite-row AG Grid |

### Quick Wins

1. **`Patch()` for figure updates**: Instead of rebuilding the full figure,
   use `dash.Patch()` to update only `marker.opacity` arrays and `layout.shapes`.
2. **Debounced slider**: Use `dash.dcc.Slider` with `updatemode="mouseup"` to
   avoid firing on every pixel drag.
3. **WebGL traces**: Replace `go.Scatter` with `go.Scattergl` for > 10 K points.

---

## File Structure

```
dev/conditional-highlighting/
├── pyproject.toml          # uv-compatible project config
├── app.py                  # Entry point (Dash init + run)
├── data.py                 # Synthetic volcano data generator
├── layout.py               # DMC 2.0 AppShell layout
├── callbacks.py            # All 5 callbacks
├── assets/
│   └── custom.css          # AG Grid row highlight styles
└── CALLBACKS_REPORT.md     # This file
```

---

## Next Steps

1. **Categorical conditions**: Add `== / !=` operators for categorical columns
   with a `dmc.MultiSelect` instead of a slider
2. **Lasso/box select sync**: Plotly `selectedData` → AG Grid row selection
3. **Export**: Download highlighted rows as CSV/TSV
4. **Undo**: Store condition history for undo/redo
5. **Integration**: Port to Depictio's figure component system with
   pattern-matching IDs and store-based state
