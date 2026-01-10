# Dash Component Development Workflow

Workflow for developing Dash components in depictio.

## Directory Structure

```
depictio/dash/modules/{component}_component/
├── __init__.py
├── frontend.py           # UI rendering functions
├── design_ui.py          # Design mode interface
├── utils.py              # Helper functions
├── state_manager.py      # State management (if needed)
└── callbacks/
    ├── __init__.py
    └── {feature}_callbacks.py
```

## Phase 1: Design

1. **Component requirements**
   - What data does it display/manage?
   - What interactions are needed?
   - How does it fit in the dashboard grid?

2. **UI/UX design**
   - Layout structure
   - Interactive elements
   - Theme compatibility requirements

## Phase 2: Implementation

### Step 1: Create Frontend

```python
# depictio/dash/modules/{component}_component/frontend.py
import dash_mantine_components as dmc
from dash import html, dcc

def render_component(component_data: dict, theme: str = "light") -> dmc.Paper:
    """Render the component UI."""
    return dmc.Paper(
        children=[
            dmc.Text(component_data.get("title", "Component")),
            # Component content
        ],
        style={
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "color": "var(--app-text-color, #000000)",
            "padding": "16px",
            "borderRadius": "8px",
        },
        shadow="sm",
    )

def render_component_wrapper(component_id: str, component_data: dict) -> html.Div:
    """Wrapper for the component with store for state."""
    return html.Div(
        id={"type": "component-wrapper", "index": component_id},
        children=[
            dcc.Store(
                id={"type": "component-store", "index": component_id},
                data=component_data
            ),
            render_component(component_data),
        ]
    )
```

### Step 2: Create Design UI

```python
# depictio/dash/modules/{component}_component/design_ui.py
import dash_mantine_components as dmc

def render_design_panel(component_id: str, current_config: dict) -> dmc.Stack:
    """Render the design/configuration panel."""
    return dmc.Stack(
        children=[
            dmc.Text("Component Settings", fw=500),
            dmc.TextInput(
                id={"type": "component-title-input", "index": component_id},
                label="Title",
                value=current_config.get("title", ""),
                style={"color": "var(--app-text-color)"}
            ),
            # More configuration options
        ],
        gap="md"
    )
```

### Step 3: Create Callbacks

```python
# depictio/dash/modules/{component}_component/callbacks/main_callbacks.py
from dash import callback, Input, Output, State, MATCH
from dash.exceptions import PreventUpdate

@callback(
    Output({"type": "component-wrapper", "index": MATCH}, "children"),
    Input({"type": "component-store", "index": MATCH}, "data"),
    prevent_initial_call=True
)
def update_component(data):
    """Update component when data changes."""
    if not data:
        raise PreventUpdate
    from ..frontend import render_component
    return render_component(data)
```

### Step 4: Register Callbacks

```python
# depictio/dash/modules/{component}_component/__init__.py
from .frontend import render_component, render_component_wrapper
from .design_ui import render_design_panel

# Import callbacks to register them
from .callbacks import main_callbacks

__all__ = [
    "render_component",
    "render_component_wrapper",
    "render_design_panel",
]
```

## Phase 3: Theme Compatibility

### CSS Variables (MANDATORY)

```python
# Always use these CSS variables
style = {
    "backgroundColor": "var(--app-surface-color, #ffffff)",
    "color": "var(--app-text-color, #000000)",
    "borderColor": "var(--app-border-color, #ddd)",
}

# For DMC components, use theme prop where available
dmc.Paper(
    ...,
    withBorder=True,
    # Let Mantine handle theming
)
```

### Testing Themes

1. Switch to light theme - verify appearance
2. Switch to dark theme - verify appearance
3. Check text readability
4. Check contrast ratios
5. Verify icons/images are visible

## Phase 4: Validation

1. **Type checking**
   ```bash
   ty check depictio/dash/modules/{component}_component/
   ```

2. **Visual testing**
   - Test in dashboard editor
   - Test in dashboard viewer
   - Test resize/drag behavior

3. **Callback testing**
   - Verify state updates
   - Check for race conditions
   - Test error handling

## Best Practices

### DMC 2.0+ Components
- Use `dmc.Paper` for containers
- Use `dmc.Stack` and `dmc.Group` for layout
- Use `dmc.Text` instead of `html.P`
- Use `dmc.Button` with proper variants
- Use `dmc.TextInput`, `dmc.Select` for forms

### State Management
- Use `dcc.Store` for component state
- Use pattern-matching callbacks for dynamic IDs
- Avoid circular callback dependencies
- Use `prevent_initial_call=True` appropriately

### Performance
- Lazy load heavy components
- Use `clientside_callback` for simple updates
- Debounce rapid updates
- Cache expensive computations

## Example Components

Reference existing components:
- Figure: `depictio/dash/modules/figure_component/`
- Table: `depictio/dash/modules/table_component/`
- Card: `depictio/dash/modules/card_component/`
