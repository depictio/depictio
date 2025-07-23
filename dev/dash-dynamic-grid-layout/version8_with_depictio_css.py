#!/usr/bin/env python3

"""
Version 8: Test with Depictio CSS
=================================

This version uses the working prototype but adds the depictio CSS to see
if the CSS is causing the drag performance issues.
"""

import dash
import dash_dynamic_grid_layout as dgl
from dash import html

# Initialize app with access to depictio assets
app = dash.Dash(__name__, assets_folder="../../../depictio/dash/assets")


# Simple colored divs for testing
def create_simple_div(component_id, color, text):
    return dgl.DraggableWrapper(
        id=f"item-{component_id}",
        children=[
            html.Div(
                [
                    html.H4(f"Box {component_id}", style={"margin": "0", "padding": "10px"}),
                    html.P(text, style={"margin": "5px", "padding": "5px"}),
                ],
                style={
                    "backgroundColor": color,
                    "border": "2px solid #333",
                    "borderRadius": "5px",
                    "height": "100%",
                    "boxSizing": "border-box",
                    "color": "white" if color in ["#ff4444", "#4444ff"] else "black",
                },
            )
        ],
        handleText="Drag",
        handleBackground="#666666",
        handleColor="white",
    )


# Create 6 simple test items
test_items = [
    create_simple_div("1", "#ff4444", "Red Box - Test dragging over other boxes"),
    create_simple_div("2", "#44ff44", "Green Box - Watch for freezing"),
    create_simple_div("3", "#4444ff", "Blue Box - Move quickly between boxes"),
    create_simple_div("4", "#ffff44", "Yellow Box - Test grid compaction"),
    create_simple_div("5", "#ff44ff", "Magenta Box - Observe delays"),
    create_simple_div("6", "#44ffff", "Cyan Box - Check smooth dragging"),
]

# Simple 2x3 grid layout (matching online demo structure)
simple_layout = [
    {"i": "item-1", "x": 0, "y": 0, "w": 2, "h": 2},
    {"i": "item-2", "x": 2, "y": 0, "w": 2, "h": 2},
    {"i": "item-3", "x": 4, "y": 0, "w": 2, "h": 2},
    {"i": "item-4", "x": 0, "y": 2, "w": 3, "h": 2},
    {"i": "item-5", "x": 3, "y": 2, "w": 3, "h": 2},
    {"i": "item-6", "x": 6, "y": 0, "w": 6, "h": 4},
]

app.layout = html.Div(
    [
        html.H1(
            "Drag Test WITH Depictio CSS",
            style={"textAlign": "center", "fontFamily": "Arial, sans-serif", "margin": "20px"},
        ),
        html.P(
            "Instructions: Test if drag performance degrades with CSS loaded. Compare to version 7.",
            style={
                "textAlign": "center",
                "fontFamily": "Arial, sans-serif",
                "margin": "10px",
                "fontSize": "14px",
            },
        ),
        html.Div(
            [
                dgl.DashGridLayout(
                    id="css-test-grid",
                    items=test_items,
                    itemLayout=simple_layout,
                    cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
                    rowHeight=150,
                    showRemoveButton=False,
                    showResizeHandles=True,
                    className="draggable-grid-container",  # This will pick up your CSS classes
                )
            ],
            style={
                "width": "90%",
                "margin": "0 auto",
                "padding": "20px",
            },
        ),
        html.Div(
            [
                html.H3("Performance Comparison:", style={"fontFamily": "Arial, sans-serif"}),
                html.Ul(
                    [
                        html.Li("Compare drag smoothness to Version 7 (no CSS)"),
                        html.Li("Test rapid movements between boxes"),
                        html.Li("Check for any freezing or delays"),
                        html.Li("Note: This loads your draggable-grid.css file"),
                    ],
                    style={"fontFamily": "Arial, sans-serif", "fontSize": "14px"},
                ),
            ],
            style={
                "width": "90%",
                "margin": "20px auto",
                "padding": "20px",
                "backgroundColor": "#ffe6e6",  # Light red background to indicate CSS test
                "borderRadius": "5px",
            },
        ),
    ]
)

if __name__ == "__main__":
    print("🎨 CSS Performance Test - Version 8")
    print("📍 Open http://127.0.0.1:8062 in your browser")
    print("🔍 Testing with Depictio CSS loaded")
    print("⚖️  Compare performance to Version 7")

    app.run(debug=True, host="127.0.0.1", port=8062)
