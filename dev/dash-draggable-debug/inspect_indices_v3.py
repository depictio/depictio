#!/usr/bin/env python3
"""
Inspect how indices are handled internally - Fixed for Dash v3
"""

import uuid

import dash
import dash_draggable
from dash import Input, Output, html


def generate_unique_index():
    return str(uuid.uuid4())


def create_inspection_app():
    app = dash.Dash(__name__)

    # Generate UUIDs
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()

    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"

    print(f"=== Dash {dash.__version__} Index Inspection ===")
    print(f"Expected Box ID 1: {box_id1}")
    print(f"Expected Box ID 2: {box_id2}")

    # Create layout
    layout = {
        "lg": [
            {"i": box_id1, "x": 0, "y": 0, "w": 6, "h": 4},
            {"i": box_id2, "x": 6, "y": 0, "w": 6, "h": 4},
        ]
    }

    # Create children with very specific IDs to test
    children = [
        html.Div(
            id=box_id1,
            children=[
                html.H3("Component 1"),
                html.P(f"My ID should be: {box_id1}"),
                html.P(id="actual-id-1", children="Checking..."),
            ],
            style={"border": "2px solid red", "padding": "10px"},
        ),
        html.Div(
            id=box_id2,
            children=[
                html.H3("Component 2"),
                html.P(f"My ID should be: {box_id2}"),
                html.P(id="actual-id-2", children="Checking..."),
            ],
            style={"border": "2px solid blue", "padding": "10px"},
        ),
    ]

    app.layout = html.Div(
        [
            html.H1(f"Index Inspection - Dash {dash.__version__}"),
            html.Div(id="layout-inspection"),
            html.Hr(),
            dash_draggable.ResponsiveGridLayout(
                id="inspection-grid",
                children=children,
                layouts=layout,
                isDraggable=True,
                isResizable=True,
                save=False,
                clearSavedLayout=False,
            ),
        ]
    )

    # Clientside callback to inspect the actual DOM
    app.clientside_callback(
        """
        function(layouts) {
            if (!layouts) return "No layout data";
            
            var debugInfo = [];
            debugInfo.push("=== Layout Data ===");
            for (var breakpoint in layouts) {
                debugInfo.push("Breakpoint: " + breakpoint);
                var items = layouts[breakpoint];
                for (var i = 0; i < items.length; i++) {
                    var item = items[i];
                    debugInfo.push("  Item " + i + ": i=" + item.i + ", x=" + item.x + ", y=" + item.y);
                }
            }
            
            debugInfo.push("\\n=== DOM Inspection ===");
            var gridElement = document.getElementById('inspection-grid');
            if (gridElement) {
                var childElements = gridElement.querySelectorAll('[id^="box-"]');
                for (var i = 0; i < childElements.length; i++) {
                    var element = childElements[i];
                    debugInfo.push("DOM Element " + i + ": id=" + element.id);
                }
            }
            
            return debugInfo.join("\\n");
        }
        """,
        Output("layout-inspection", "children"),
        Input("inspection-grid", "layouts"),
    )

    return app


if __name__ == "__main__":
    app = create_inspection_app()
    print("Starting inspection app...")
    # Use app.run for Dash v3
    app.run(debug=True, port=8055)
