# Dash Component Generator

Create or modify Dash components following depictio conventions.

## Instructions

When working with Dash components:

1. **Understand the component type**:
   - `figure` - Plotly visualizations (`depictio/dash/modules/figure_component/`)
   - `table` - Data tables (`depictio/dash/modules/table_component/`)
   - `card` - Card widgets (`depictio/dash/modules/card_component/`)
   - `interactive` - Interactive controls (`depictio/dash/modules/interactive_component/`)
   - `text` - Text/markdown (`depictio/dash/modules/text_component/`)
   - `jbrowse` - Genomic browser (`depictio/dash/modules/jbrowse_component/`)

2. **Follow DMC 2.0+ requirements** (CRITICAL):
   - Use Dash Mantine Components for ALL UI elements
   - Never use Bootstrap components for new code
   - Ensure dark/light theme compatibility

3. **Theme compatibility** (MANDATORY):
   - Use CSS variables: `var(--app-bg-color)`, `var(--app-text-color)`, etc.
   - Never hardcode colors
   - Test in both light and dark themes

4. **Component structure**:
   - `frontend.py` - UI rendering functions
   - `design_ui.py` - Design mode interface
   - `callbacks/` - Dash callbacks
   - `utils.py` - Helper functions

5. **State management**:
   - Use dcc.Store for component state
   - Follow existing patterns in similar components

## Theme-Aware Example

```python
import dash_mantine_components as dmc

dmc.Paper(
    children=[...],
    style={
        "backgroundColor": "var(--app-surface-color, #ffffff)",
        "color": "var(--app-text-color, #000000)",
        "border": "1px solid var(--app-border-color, #ddd)",
    }
)
```

## Usage

`/dash-component <type> <description>` - Create/modify component

$ARGUMENTS
