#!/usr/bin/env python3
"""
Test using data-grid attribute approach
"""

import uuid
import dash
from dash import html, Input, Output, clientside_callback
import dash_draggable


def generate_unique_index():
    return str(uuid.uuid4())


def create_data_grid_test():
    app = dash.Dash(__name__)

    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()

    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"

    print(f"=== Testing data-grid attribute with Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")

    # Use data-grid attribute approach
    children = [
        html.Div(
            id=box_id1,
            children=[
                html.H3("Component 1"),
                html.P(f"ID: {box_id1}"),
                html.P("✅ Using data-grid attribute"),
            ],
            style={"border": "2px solid green", "padding": "10px"},
            **{"data-grid": {"i": box_id1, "x": 0, "y": 0, "w": 6, "h": 4}},
        ),
        html.Div(
            id=box_id2,
            children=[
                html.H3("Component 2"),
                html.P(f"ID: {box_id2}"),
                html.P("✅ Using data-grid attribute"),
            ],
            style={"border": "2px solid blue", "padding": "10px"},
            **{"data-grid": {"i": box_id2, "x": 6, "y": 0, "w": 6, "h": 4}},
        ),
    ]

    app.layout = html.Div(
        [
            html.H1(f"🎯 Data-Grid Test - Dash {dash.__version__}"),
            html.Div(id="data-grid-output"),
            html.Button("Test Data-Grid", id="test-data-grid"),
            html.Hr(),
            dash_draggable.ResponsiveGridLayout(
                id="data-grid-grid",
                children=children,
                isDraggable=True,
                isResizable=True,
                save=False,
                clearSavedLayout=False,
            ),
        ]
    )

    app.clientside_callback(
        f"""
        function(n_clicks, layouts) {{
            if (!n_clicks) return "Click 'Test Data-Grid' button";
            
            var result = [];
            result.push("=== DATA-GRID TEST RESULTS ===");
            result.push("Expected ID 1: {box_id1}");
            result.push("Expected ID 2: {box_id2}");
            result.push("");
            
            if (layouts && layouts.lg) {{
                result.push("✅ Layout data received!");
                layouts.lg.forEach(function(item, index) {{
                    var isUUID = item.i.startsWith("box-") && item.i.length > 20;
                    var status = isUUID ? "✅ CORRECT" : "❌ WRONG";
                    result.push("Item " + index + ": " + status + " - ID: " + item.i);
                }});
                
                var allCorrect = layouts.lg.every(function(item) {{
                    return item.i.startsWith("box-") && item.i.length > 20;
                }});
                
                result.push("");
                if (allCorrect) {{
                    result.push("🎉 DATA-GRID SOLUTION WORKS!");
                    result.push("✅ All items have correct UUID-based IDs!");
                }} else {{
                    result.push("❌ Still having issues with some IDs");
                }}
            }} else {{
                result.push("❌ No layout data received");
            }}
            
            return result.join("\\n");
        }}
        """,
        Output("data-grid-output", "children"),
        Input("test-data-grid", "n_clicks"),
        Input("data-grid-grid", "layouts"),
    )

    return app


if __name__ == "__main__":
    app = create_data_grid_test()
    print("🎯 Starting data-grid test...")
    app.run(debug=True, port=8062)
