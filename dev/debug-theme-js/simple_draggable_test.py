#!/usr/bin/env python3
"""
Simple dash-draggable test for custom IDs
Compatible with both DMC 0.12 and DMC 2.0+
"""

import dash
import dash_draggable
import dash_mantine_components as dmc
from dash import Input, Output, dcc, html

# Show packages version 
print("Dash version:", dash.__version__)
print("Dash-Draggable version:", dash_draggable.__version__)
print("Dash-Mantine-Components version:", dmc.__version__)

# Initialize the Dash app
app = dash.Dash(__name__)

# Simple layout focused only on draggable testing
app.layout = dmc.MantineProvider(
    id="mantine-provider",
    children=[
        dcc.Store(id="layout-store", data={}),
        html.Div(
            style={"padding": "20px"},
            children=[
                html.H1("🔧 Simple Dash-Draggable Test"),
                html.P("Testing custom IDs with ResponsiveGridLayout"),
                html.Hr(),
                
                # Debug info
                html.Div([
                    html.H4("Debug Info:"),
                    html.P("Component IDs: 'card-A', 'card-B'"),
                    html.P("Layout IDs: 'card-A', 'card-B'"),
                    html.P("Expected: Cards should position side-by-side on startup"),
                ]),
                
                # The draggable layout
                dash_draggable.ResponsiveGridLayout(
                    id="test-draggable",
                    clearSavedLayout=True,  # Clear any saved layout
                    save=False,  # Disable client-side auto-save to prevent ID override
                    layouts={},  # Will be set by callback
                    isDraggable=True,
                    isResizable=True,
                    children=[
                        # Card A - should be on left
                        html.Div(
                            id="card-A",
                            **{"data-grid": {"i": "card-A", "x": 0, "y": 0, "w": 6, "h": 8}},
                            children=[
                                dmc.Card([
                                    dmc.Text("Card A", size="xl", style={"fontWeight": "bold"}),
                                    dmc.Text("This should be on the LEFT"),
                                    dmc.Text("Background: Light Blue"),
                                ], style={
                                    "height": "100%",
                                    "backgroundColor": "#e3f2fd",
                                    "border": "2px solid #1976d2",
                                    "padding": "15px"
                                })
                            ]
                        ),
                        
                        # Card B - should be on right  
                        html.Div(
                            id="card-B",
                            **{"data-grid": {"i": "card-B", "x": 6, "y": 0, "w": 6, "h": 8}},
                            children=[
                                dmc.Card([
                                    dmc.Text("Card B", size="xl", style={"fontWeight": "bold"}),
                                    dmc.Text("This should be on the RIGHT"),
                                    dmc.Text("Background: Light Green"),
                                ], style={
                                    "height": "100%", 
                                    "backgroundColor": "#e8f5e8",
                                    "border": "2px solid #388e3c",
                                    "padding": "15px"
                                })
                            ]
                        ),
                    ],
                    style={
                        "width": "100%",
                        "height": "400px",
                        "margin": "20px 0",
                        "border": "1px dashed #ccc"
                    },
                ),
                
                html.Hr(),
                html.H4("Console Output:"),
                html.P("Check terminal for layout debug information"),
                html.Div(id="layout-debug-output"),
            ],
        )
    ],
)


# Initialize the custom layout
@app.callback(
    Output("test-draggable", "layouts"),
    Input("mantine-provider", "id"),  # Trigger on app startup
    prevent_initial_call=False,
)
def set_initial_layout(_):
    """Set the initial custom layout"""
    layout = {
        "lg": [
            {"i": "card-A", "x": 0, "y": 0, "w": 6, "h": 8},
            {"i": "card-B", "x": 6, "y": 0, "w": 6, "h": 8},
        ]
    }
    print(f"🎯 SETTING INITIAL LAYOUT: {layout}")
    return layout


# Alternative approach: Try using save=False to prevent client-side overrides


# Monitor layout changes
@app.callback(
    [Output("layout-store", "data"), Output("layout-debug-output", "children")],
    Input("test-draggable", "layouts"),
    prevent_initial_call=True,
)
def monitor_layout_changes(layouts):
    """Monitor and display layout changes"""
    print(f"📐 LAYOUT CHANGED: {layouts}")
    
    # Create debug output
    debug_info = []
    if layouts:
        for breakpoint, items in layouts.items():
            debug_info.append(html.H5(f"Breakpoint: {breakpoint}"))
            for item in items:
                item_id = item.get('i', 'unknown')
                x, y, w, h = item.get('x', 0), item.get('y', 0), item.get('w', 1), item.get('h', 1)
                debug_info.append(
                    html.P(f"  {item_id}: x={x}, y={y}, w={w}, h={h}")
                )
    else:
        debug_info.append(html.P("No layout data received"))
    
    return layouts or {}, debug_info


if __name__ == "__main__":
    print("=" * 50)
    print("🧪 SIMPLE DRAGGABLE TEST")
    print("=" * 50)
    print("Expected behavior:")
    print("1. Card A (blue) should appear on LEFT")
    print("2. Card B (green) should appear on RIGHT") 
    print("3. Both cards should be draggable and resizable")
    print("4. Console should show custom IDs 'card-A', 'card-B'")
    print("=" * 50)
    print("Running on: http://127.0.0.1:8053")
    app.run(debug=True, host="127.0.0.1", port=8053)