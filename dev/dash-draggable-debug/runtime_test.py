#!/usr/bin/env python3
"""
Runtime test to examine actual component behavior in both versions
"""

import uuid

import dash
import dash_draggable
from dash import Input, Output, html


def generate_unique_index():
    return str(uuid.uuid4())


def run_runtime_test():
    app = dash.Dash(__name__)

    # Generate UUIDs
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()

    print(f"=== Runtime Test with Dash {dash.__version__} ===")
    print(f"UUID 1: {uuid1}")
    print(f"UUID 2: {uuid2}")

    # Create box IDs
    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"

    # Create layout
    layout = {
        "lg": [
            {"i": box_id1, "x": 0, "y": 0, "w": 6, "h": 4},
            {"i": box_id2, "x": 6, "y": 0, "w": 6, "h": 4},
        ]
    }

    # Create children
    children = [
        html.Div(
            id=box_id1,
            children=[
                html.H3("Component 1"),
                html.P(f"ID: {box_id1}"),
                html.Button("Test Button 1", id=f"btn-{uuid1}"),
                html.Div(id=f"status-{uuid1}", children="Ready"),
            ],
        ),
        html.Div(
            id=box_id2,
            children=[
                html.H3("Component 2"),
                html.P(f"ID: {box_id2}"),
                html.Button("Test Button 2", id=f"btn-{uuid2}"),
                html.Div(id=f"status-{uuid2}", children="Ready"),
            ],
        ),
    ]

    app.layout = html.Div(
        [
            html.H1(f"Runtime Test - Dash {dash.__version__}"),
            html.Div(id="debug-info"),
            html.Div(id="layout-debug"),
            html.Hr(),
            dash_draggable.ResponsiveGridLayout(
                id="grid",
                children=children,
                layouts=layout,
                isDraggable=True,
                isResizable=True,
                save=False,
                clearSavedLayout=False,
            ),
        ]
    )

    # Callback to monitor layout changes
    @app.callback(Output("layout-debug", "children"), Input("grid", "layouts"))
    def debug_layout(layouts):
        if layouts is None:
            return "No layout data"

        debug_items = []
        for breakpoint, items in layouts.items():
            debug_items.append(html.H4(f"Breakpoint: {breakpoint}"))
            for item in items:
                debug_items.append(html.P(f"Item: {item}"))

        return debug_items

    # Callbacks for buttons to test if they work
    @app.callback(
        Output(f"status-{uuid1}", "children"),
        Input(f"btn-{uuid1}", "n_clicks"),
        prevent_initial_call=True,
    )
    def btn1_clicked(n_clicks):
        return f"Button 1 clicked {n_clicks} times"

    @app.callback(
        Output(f"status-{uuid2}", "children"),
        Input(f"btn-{uuid2}", "n_clicks"),
        prevent_initial_call=True,
    )
    def btn2_clicked(n_clicks):
        return f"Button 2 clicked {n_clicks} times"

    # Debug callback
    @app.callback(Output("debug-info", "children"), Input("grid", "children"))
    def debug_children(children):
        if not children:
            return "No children"

        debug_info = []
        for i, child in enumerate(children):
            if hasattr(child, "id"):
                debug_info.append(html.P(f"Child {i}: id={child.id}"))
            else:
                debug_info.append(html.P(f"Child {i}: no id"))

        return debug_info

    return app


if __name__ == "__main__":
    app = run_runtime_test()
    print("Starting runtime test...")
    app.run_server(debug=True, port=8054)
