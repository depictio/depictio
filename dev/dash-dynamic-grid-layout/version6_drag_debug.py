#!/usr/bin/env python3

"""
Prototype Version 6: Debug Drag Freezing Issue
============================================

This prototype focuses on debugging the drag "freezing" issue that occurs when dragging
a box in front of another box. The problem appears to be related to react-grid-layout's
dynamic repositioning causing temporary delays.

Key features to test:
1. Minimal CSS to avoid transition interference
2. Debug logging for drag events
3. Different animation settings
4. Grid compaction behavior analysis

Usage: python version6_drag_debug.py
"""

import dash
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
from dash import Input, Output, State, callback, dcc, html
from dash_iconify import DashIconify

# Initialize the Dash app with assets disabled
app = dash.Dash(__name__, assets_ignore=".*")


# Test components with different content types
def create_test_component(component_id, title, content_type="simple"):
    """Create test components with different content types"""

    if content_type == "simple":
        content = dmc.Card(
            [
                dmc.CardSection(
                    [
                        dmc.Title(title, order=4),
                        dmc.Text("Simple content for drag testing", size="sm"),
                        dmc.Space(h=20),
                        dmc.Button("Test Button", color="blue", variant="light"),
                    ],
                    p="md",
                )
            ],
            shadow="sm",
            radius="md",
            withBorder=True,
        )

    elif content_type == "complex":
        content = dmc.Card(
            [
                dmc.CardSection(
                    [
                        dmc.Title(title, order=4),
                        dmc.Stack(
                            [
                                dmc.Progress(value=75, color="blue", size="sm"),
                                dmc.Group(
                                    [
                                        dmc.Badge("Status", color="green"),
                                        dmc.Badge("Active", color="blue"),
                                    ]
                                ),
                                dmc.Textarea(
                                    placeholder="Sample textarea content...",
                                    value="This is sample content for testing drag interactions",
                                    minRows=3,
                                ),
                                dmc.Group(
                                    [
                                        dmc.Button("Action 1", size="sm", variant="outline"),
                                        dmc.Button("Action 2", size="sm", variant="filled"),
                                    ]
                                ),
                            ],
                            gap="sm",
                        ),
                    ],
                    p="md",
                )
            ],
            shadow="sm",
            radius="md",
            withBorder=True,
        )

    # Create drag handle
    drag_handle = dmc.ActionIcon(
        DashIconify(icon="mdi:drag", width=16),
        id=f"drag-handle-{component_id}",
        variant="subtle",
        color="gray",
        size="sm",
        className="react-grid-dragHandle",  # This class tells DashGridLayout it's a drag handle
        style={
            "position": "absolute",
            "top": "8px",
            "right": "8px",
            "zIndex": 1000,
            "cursor": "grab",
        },
    )

    # Wrapper with relative positioning for the drag handle
    wrapper_content = html.Div(
        [
            content,
            drag_handle,
        ],
        style={
            "position": "relative",
            "height": "100%",
            "width": "100%",
        },
    )

    return dgl.DraggableWrapper(
        id=f"component-{component_id}",
        children=[wrapper_content],
        handleText="Drag",
    )


# Create initial layout (96 columns, rowHeight=10)
initial_layout = [
    {"i": "component-1", "x": 0, "y": 0, "w": 32, "h": 18},
    {"i": "component-2", "x": 32, "y": 0, "w": 32, "h": 18},
    {"i": "component-3", "x": 64, "y": 0, "w": 32, "h": 18},
    {"i": "component-4", "x": 0, "y": 18, "w": 48, "h": 24},
    {"i": "component-5", "x": 48, "y": 18, "w": 48, "h": 24},
    {"i": "component-6", "x": 0, "y": 42, "w": 32, "h": 18},
    {"i": "component-7", "x": 32, "y": 42, "w": 32, "h": 18},
    {"i": "component-8", "x": 64, "y": 42, "w": 32, "h": 18},
]

# Create test components
test_components = [
    create_test_component("1", "Simple Component 1", "simple"),
    create_test_component("2", "Complex Component 2", "complex"),
    create_test_component("3", "Simple Component 3", "simple"),
    create_test_component("4", "Complex Component 4", "complex"),
    create_test_component("5", "Simple Component 5", "simple"),
    create_test_component("6", "Complex Component 6", "complex"),
    create_test_component("7", "Simple Component 7", "simple"),
    create_test_component("8", "Complex Component 8", "complex"),
]

# App layout
app.layout = dmc.MantineProvider(
    [
        dmc.Container(
            [
                dmc.Title("Drag Debug Prototype - Version 6", order=1, ta="center", mb="lg"),
                # Debug controls
                dmc.Card(
                    [
                        dmc.CardSection(
                            [
                                dmc.Title("Debug Controls", order=3),
                                dmc.Group(
                                    [
                                        dmc.Switch(
                                            id="debug-logging",
                                            label="Enable Debug Logging",
                                            checked=True,
                                        ),
                                        dmc.Switch(
                                            id="compact-mode",
                                            label="Enable Grid Compaction",
                                            checked=True,
                                        ),
                                        dmc.Switch(
                                            id="show-remove-buttons",
                                            label="Show Remove Buttons",
                                            checked=True,
                                        ),
                                        dmc.Switch(
                                            id="show-resize-handles",
                                            label="Show Resize Handles",
                                            checked=True,
                                        ),
                                    ],
                                    gap="md",
                                ),
                            ],
                            p="sm",
                        )
                    ],
                    mb="md",
                    withBorder=True,
                ),
                # Debug log display
                dmc.Card(
                    [
                        dmc.CardSection(
                            [
                                dmc.Title("Debug Log", order=4),
                                html.Div(
                                    id="debug-log",
                                    style={
                                        "height": "120px",
                                        "overflowY": "auto",
                                        "backgroundColor": "#f8f9fa",
                                        "padding": "8px",
                                        "fontFamily": "monospace",
                                        "fontSize": "12px",
                                        "border": "1px solid #dee2e6",
                                        "borderRadius": "4px",
                                    },
                                ),
                            ],
                            p="sm",
                        )
                    ],
                    mb="md",
                    withBorder=True,
                ),
                # Grid layout
                html.Div(
                    [
                        dgl.DashGridLayout(
                            id="drag-debug-grid",
                            items=test_components,  # Use items instead of children
                            itemLayout=initial_layout,  # Use itemLayout instead of layouts
                            cols={"lg": 96, "md": 80, "sm": 48, "xs": 32, "xxs": 16},
                            rowHeight=10,
                            compactType="vertical",  # Try different compact types
                            showRemoveButton=True,
                            showResizeHandles=True,
                            # Responsive breakpoints
                            breakpoints={"lg": 1200, "md": 996, "sm": 768, "xs": 480, "xxs": 0},
                            className="drag-debug-grid",
                            style={"width": "100%", "minHeight": "800px"},
                        )
                    ],
                    style={
                        "minHeight": "800px",
                        "border": "1px solid #dee2e6",
                        "borderRadius": "8px",
                        "padding": "10px",
                        "backgroundColor": "#ffffff",
                    },
                ),
                # Layout state display
                dmc.Card(
                    [
                        dmc.CardSection(
                            [
                                dmc.Title("Current Layout State", order=4),
                                html.Pre(
                                    id="layout-state",
                                    style={
                                        "fontSize": "11px",
                                        "maxHeight": "200px",
                                        "overflowY": "auto",
                                    },
                                ),
                            ],
                            p="sm",
                        )
                    ],
                    mt="md",
                    withBorder=True,
                ),
            ],
            size="xl",
            p="md",
        ),
        # Store for debug messages
        dcc.Store(id="debug-messages", data=[]),
        # Interval for clearing old debug messages
        dcc.Interval(id="debug-interval", interval=10000, n_intervals=0),
    ],
    id="mantine-provider",
)


# Callback to handle layout changes and debug logging
@callback(
    [
        Output("debug-log", "children"),
        Output("layout-state", "children"),
        Output("debug-messages", "data"),
    ],
    [Input("drag-debug-grid", "currentLayout"), Input("debug-interval", "n_intervals")],
    [State("debug-logging", "checked"), State("debug-messages", "data")],
)
def update_debug_info(current_layout, n_intervals, debug_enabled, debug_messages):
    """Update debug information and layout state"""
    import json
    from datetime import datetime

    if debug_messages is None:
        debug_messages = []

    # Clear old messages every 10 intervals (100 seconds)
    if n_intervals > 0 and n_intervals % 10 == 0:
        debug_messages = debug_messages[-50:]  # Keep last 50 messages

    # Add new debug message if layout changed
    if current_layout and debug_enabled:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        debug_messages.append(f"[{timestamp}] Layout updated: {len(current_layout)} items")

        # Keep only last 100 messages
        debug_messages = debug_messages[-100:]

    # Format debug log
    debug_log_content = html.Div(
        [html.Div(msg, style={"marginBottom": "2px"}) for msg in debug_messages[-20:]]
    )

    # Format layout state
    layout_state = json.dumps(current_layout, indent=2) if current_layout else "No layout data"

    return debug_log_content, layout_state, debug_messages


# Note: This component doesn't support transitionDuration property
# Animation behavior is handled internally by the library


# Callback to update grid compaction
@callback(Output("drag-debug-grid", "compactType"), Input("compact-mode", "checked"))
def update_compact_mode(enabled):
    """Update grid compaction mode"""
    return "vertical" if enabled else None


# Callback to update remove buttons visibility
@callback(Output("drag-debug-grid", "showRemoveButton"), Input("show-remove-buttons", "checked"))
def update_remove_buttons(enabled):
    """Update remove buttons visibility"""
    return enabled


# Callback to update resize handles visibility
@callback(Output("drag-debug-grid", "showResizeHandles"), Input("show-resize-handles", "checked"))
def update_resize_handles(enabled):
    """Update resize handles visibility"""
    return enabled


# Callback to log drag events
@callback(
    Output("debug-messages", "data", allow_duplicate=True),
    [Input("drag-debug-grid", "currentLayout")],
    [State("debug-messages", "data"), State("debug-logging", "checked")],
    prevent_initial_call=True,
)
def log_drag_events(current_layout, debug_messages, debug_enabled):
    """Log drag events for debugging"""
    if not debug_enabled or not current_layout:
        return debug_messages or []

    from datetime import datetime

    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    if debug_messages is None:
        debug_messages = []

    debug_messages.append(f"[{timestamp}] DRAG EVENT: Layout change detected!")

    # Analyze layout for overlaps or conflicts
    positions = {}
    conflicts = []

    for item in current_layout:
        key = f"{item['x']},{item['y']}"
        if key in positions:
            conflicts.append(
                f"Conflict at ({item['x']}, {item['y']}): {positions[key]} vs {item['i']}"
            )
        positions[key] = item["i"]

    if conflicts:
        for conflict in conflicts:
            debug_messages.append(f"[{timestamp}] CONFLICT: {conflict}")

    return debug_messages[-100:]  # Keep last 100 messages


if __name__ == "__main__":
    print("🚀 Starting Drag Debug Prototype - Version 6")
    print("📍 Open http://127.0.0.1:8060 in your browser")
    print("🔧 Debug the drag freezing issue with this clean prototype")
    print("📊 Use the debug controls to analyze drag behavior")
    print("🎯 Focus: Test drag freezing when moving boxes over each other")
    print("⚡ Key settings: compactType, showRemoveButton, showResizeHandles")

    app.run(debug=True, host="127.0.0.1", port=8060)
