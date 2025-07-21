#!/usr/bin/env python3
"""
Trace exactly when and where UUID IDs get converted to numerical IDs
"""

import uuid
import dash
from dash import html, Input, Output, clientside_callback
import dash_draggable
import json


def generate_unique_index():
    return str(uuid.uuid4())


def create_trace_app():
    app = dash.Dash(__name__)

    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()

    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"

    print(f"=== Tracing Conversion with Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")

    layout = {
        "lg": [
            {"i": box_id1, "x": 0, "y": 0, "w": 6, "h": 4},
            {"i": box_id2, "x": 6, "y": 0, "w": 6, "h": 4},
        ]
    }

    # Test without layout first to see what happens
    children = [
        html.Div(
            id=box_id1,
            key=box_id1,
            children=[html.H3("Component 1"), html.P(f"ID: {box_id1}")],
            style={"border": "2px solid red", "padding": "10px"},
        ),
        html.Div(
            id=box_id2,
            key=box_id2,
            children=[html.H3("Component 2"), html.P(f"ID: {box_id2}")],
            style={"border": "2px solid blue", "padding": "10px"},
        ),
    ]

    app.layout = html.Div(
        [
            html.H1(f"🔍 Trace Conversion - Dash {dash.__version__}"),
            html.Div(id="trace-output"),
            html.Button("Trace Without Layout", id="trace-no-layout"),
            html.Button("Trace With Layout", id="trace-with-layout"),
            html.Hr(),
            # Test 1: No layout provided
            html.H3("Test 1: No initial layout"),
            dash_draggable.ResponsiveGridLayout(
                id="grid-no-layout",
                children=children,
                # layouts=None,  # No layout provided
                isDraggable=True,
                isResizable=True,
                save=False,
                clearSavedLayout=False,
            ),
            html.Hr(),
            # Test 2: With layout
            html.H3("Test 2: With initial layout"),
            dash_draggable.ResponsiveGridLayout(
                id="grid-with-layout",
                children=children,
                layouts=layout,
                isDraggable=True,
                isResizable=True,
                save=False,
                clearSavedLayout=False,
            ),
        ]
    )

    # Trace without layout
    app.clientside_callback(
        """
        function(n_clicks, layouts) {
            if (!n_clicks) return "Click 'Trace Without Layout'";
            
            var result = [];
            result.push("=== TRACE WITHOUT LAYOUT ===");
            
            if (layouts) {
                for (var breakpoint in layouts) {
                    result.push("Breakpoint: " + breakpoint);
                    layouts[breakpoint].forEach(function(item, index) {
                        result.push("  Item " + index + ": " + JSON.stringify(item));
                    });
                }
            } else {
                result.push("No layout data");
            }
            
            return result.join("\\n");
        }
        """,
        Output("trace-output", "children"),
        Input("trace-no-layout", "n_clicks"),
        Input("grid-no-layout", "layouts"),
    )

    # Trace with layout
    app.clientside_callback(
        """
        function(n_clicks, layouts) {
            if (!n_clicks) return "Click 'Trace With Layout'";
            
            var result = [];
            result.push("=== TRACE WITH LAYOUT ===");
            
            if (layouts) {
                for (var breakpoint in layouts) {
                    result.push("Breakpoint: " + breakpoint);
                    layouts[breakpoint].forEach(function(item, index) {
                        result.push("  Item " + index + ": " + JSON.stringify(item));
                    });
                }
            } else {
                result.push("No layout data");
            }
            
            return result.join("\\n");
        }
        """,
        Output("trace-output", "children"),
        Input("trace-with-layout", "n_clicks"),
        Input("grid-with-layout", "layouts"),
    )

    return app


if __name__ == "__main__":
    app = create_trace_app()
    print("🔍 Starting trace app...")
    app.run(debug=True, port=8059)
