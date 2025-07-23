#!/usr/bin/env python3

"""
Version 7: Absolute Minimal Drag Test
====================================

This is the most minimal possible test to isolate the drag freezing issue.
No external CSS, no complex components, just basic divs.
"""

import dash
import dash_dynamic_grid_layout as dgl
from dash import html

# Bare minimum Dash app - no external CSS or JS
app = dash.Dash(__name__, assets_ignore=".*")


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
            "Minimal Drag Test - No CSS/Assets",
            style={"textAlign": "center", "fontFamily": "Arial, sans-serif", "margin": "20px"},
        ),
        html.P(
            "Instructions: Try dragging boxes over each other quickly. Watch for any freezing or delays.",
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
                    id="minimal-grid",
                    items=test_items,
                    itemLayout=simple_layout,
                    cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},  # Match online demo
                    rowHeight=150,  # Much larger row height like online demo
                    # compactType="horizontal",  # Match online demo
                    showRemoveButton=False,
                    showResizeHandles=True,
                    # style={
                    #     "height": "800px",  # Fixed height like online demo
                    #     "border": "1px solid #ccc",
                    #     "backgroundColor": "#f9f9f9",
                    # },
                )
            ],
        ),
        html.Div(
            [
                html.H3("Test Scenarios:", style={"fontFamily": "Arial, sans-serif"}),
                html.Ul(
                    [
                        html.Li("Drag red box over green box quickly"),
                        html.Li("Move blue box in front of yellow box"),
                        html.Li("Try rapid back-and-forth movements"),
                        html.Li("Drag from one end of grid to the other"),
                    ],
                    style={"fontFamily": "Arial, sans-serif", "fontSize": "14px"},
                ),
            ],
            style={
                "width": "90%",
                "margin": "20px auto",
                "padding": "20px",
                "backgroundColor": "#f0f0f0",
                "borderRadius": "5px",
            },
        ),
    ]
)

if __name__ == "__main__":
    print("🔬 Minimal Drag Test - Version 7")
    print("📍 Open http://127.0.0.1:8061 in your browser")
    print("🚫 No CSS, no assets, no external dependencies")
    print("🎯 Pure library behavior test")

    app.run(debug=True, host="127.0.0.1", port=8061)
