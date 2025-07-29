#!/usr/bin/env python3
"""
Test to verify if Dash v3 overrides custom IDs with numerical indices
"""

import json
import uuid

import dash
import dash_draggable
from dash import Input, Output, html


def generate_unique_index():
    return str(uuid.uuid4())


def create_test_app():
    app = dash.Dash(__name__)

    # Generate UUIDs
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    uuid3 = generate_unique_index()

    print(f"Dash version: {dash.__version__}")
    print(f"UUID 1: {uuid1}")
    print(f"UUID 2: {uuid2}")
    print(f"UUID 3: {uuid3}")

    # Create custom IDs
    custom_id1 = f"box-{uuid1}"
    custom_id2 = f"box-{uuid2}"
    custom_id3 = f"box-{uuid3}"

    print(f"Custom ID 1: {custom_id1}")
    print(f"Custom ID 2: {custom_id2}")
    print(f"Custom ID 3: {custom_id3}")

    # Initial layout with custom IDs
    initial_layout = {
        "lg": [
            {"i": custom_id1, "x": 0, "y": 0, "w": 4, "h": 4},
            {"i": custom_id2, "x": 4, "y": 0, "w": 4, "h": 4},
            {"i": custom_id3, "x": 8, "y": 0, "w": 4, "h": 4},
        ]
    }

    # Initial children with custom IDs
    initial_children = [
        html.Div(
            id=custom_id1,
            children=[
                html.H3("Component 1"),
                html.P(f"Expected ID: {custom_id1}"),
                html.P(id=f"actual-id-{custom_id1}", children="Loading actual ID..."),
            ],
            style={"border": "1px solid #ccc", "padding": "10px", "background": "#f9f9f9"},
        ),
        html.Div(
            id=custom_id2,
            children=[
                html.H3("Component 2"),
                html.P(f"Expected ID: {custom_id2}"),
                html.P(id=f"actual-id-{custom_id2}", children="Loading actual ID..."),
            ],
            style={"border": "1px solid #ccc", "padding": "10px", "background": "#f0f0f0"},
        ),
        html.Div(
            id=custom_id3,
            children=[
                html.H3("Component 3"),
                html.P(f"Expected ID: {custom_id3}"),
                html.P(id=f"actual-id-{custom_id3}", children="Loading actual ID..."),
            ],
            style={"border": "1px solid #ccc", "padding": "10px", "background": "#e0e0e0"},
        ),
    ]

    app.layout = html.Div(
        [
            html.H1(f"Dash {dash.__version__} Index Override Test"),
            html.Div(id="layout-output"),
            html.Div(id="children-output"),
            html.Hr(),
            dash_draggable.ResponsiveGridLayout(
                id="draggable-grid",
                children=initial_children,
                layouts=initial_layout,
                clearSavedLayout=False,
                isDraggable=True,
                isResizable=True,
                save=False,
                style={"height": "400px", "border": "2px solid #333"},
            ),
        ]
    )

    # Callback to monitor layout changes and check what IDs are actually used
    @app.callback(
        Output("layout-output", "children"),
        Input("draggable-grid", "layouts"),
        prevent_initial_call=True,
    )
    def update_layout_output(layouts):
        if layouts:
            layout_info = []
            for breakpoint, layout_list in layouts.items():
                layout_info.append(html.H4(f"Breakpoint: {breakpoint}"))
                for item in layout_list:
                    layout_info.append(
                        html.P(
                            f"Item ID: {item.get('i', 'NO ID')} - Position: x={item.get('x')}, y={item.get('y')}"
                        )
                    )

            return html.Div(
                [
                    html.H3("Layout Data:"),
                    html.Div(layout_info),
                    html.H4("Raw Layout JSON:"),
                    html.Pre(json.dumps(layouts, indent=2)),
                ]
            )
        return "No layout data"

    # Callback to monitor children changes
    @app.callback(
        Output("children-output", "children"),
        Input("draggable-grid", "children"),
        prevent_initial_call=True,
    )
    def update_children_output(children):
        if children:
            children_info = []
            for i, child in enumerate(children):
                if hasattr(child, "id"):
                    actual_id = child.id
                elif isinstance(child, dict) and "props" in child:
                    actual_id = child["props"].get("id", "NO ID")
                else:
                    actual_id = "UNKNOWN"

                children_info.append(html.P(f"Child {i}: ID = {actual_id}"))

            return html.Div([html.H3("Children Data:"), html.Div(children_info)])
        return "No children data"

    return app


if __name__ == "__main__":
    app = create_test_app()
    print("Starting index override test...")
    app.run_server(debug=True, port=8053)
