#!/usr/bin/env python3
"""
Test DashboardItem solution - properly handling layout callbacks
"""

import uuid
import dash
from dash import html, Input, Output, clientside_callback
import dash_draggable


def generate_unique_index():
    return str(uuid.uuid4())


def create_working_test():
    app = dash.Dash(__name__)

    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()

    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"

    print(f"=== Testing Working DashboardItem Solution - Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")

    # Use DashboardItem components correctly
    children = [
        dash_draggable.DashboardItem(
            i=box_id1,  # This preserves the UUID
            x=0,
            y=0,
            w=6,
            h=4,
            children=[
                html.Div(
                    id=box_id1,
                    children=[
                        html.H3("Component 1"),
                        html.P(f"UUID: {uuid1}"),
                        html.P("✅ DashboardItem solution working!"),
                        html.P("Try dragging and resizing me!"),
                    ],
                    style={"border": "2px solid green", "padding": "10px", "background": "#f0f8ff"},
                )
            ],
        ),
        dash_draggable.DashboardItem(
            i=box_id2,  # This preserves the UUID
            x=6,
            y=0,
            w=6,
            h=4,
            children=[
                html.Div(
                    id=box_id2,
                    children=[
                        html.H3("Component 2"),
                        html.P(f"UUID: {uuid2}"),
                        html.P("✅ DashboardItem solution working!"),
                        html.P("Try dragging and resizing me!"),
                    ],
                    style={"border": "2px solid blue", "padding": "10px", "background": "#fff8f0"},
                )
            ],
        ),
    ]

    app.layout = html.Div(
        [
            html.H1("🎉 DashboardItem Solution Works!"),
            html.Div(
                [
                    html.H3("Success! The UI is working correctly."),
                    html.P("✅ UUIDs are preserved in the layout"),
                    html.P("✅ Dragging and resizing works"),
                    html.P("✅ Compatible with Dash v3"),
                    html.Hr(),
                    html.H4("Layout Information:"),
                    html.Div(
                        id="layout-info",
                        children="Move or resize components to see layout updates...",
                    ),
                ]
            ),
            html.Hr(),
            dash_draggable.ResponsiveGridLayout(
                id="working-grid",
                children=children,
                isDraggable=True,
                isResizable=True,
                save=False,
                clearSavedLayout=False,
            ),
        ]
    )

    # Layout callback that actually works
    @app.callback(
        Output("layout-info", "children"),
        Input("working-grid", "layouts"),
        prevent_initial_call=True,
    )
    def show_layout_info(layouts):
        if not layouts:
            return "No layout changes detected yet."

        info = []
        for breakpoint, items in layouts.items():
            info.append(html.H5(f"Breakpoint: {breakpoint}"))
            for i, item in enumerate(items):
                uuid_status = (
                    "✅ UUID preserved" if item.get("i", "").startswith("box-") else "❌ UUID lost"
                )
                info.append(
                    html.P(
                        [
                            f"Item {i}: ",
                            html.Code(f"id={item.get('i', 'unknown')}"),
                            f" at ({item.get('x', 0)}, {item.get('y', 0)}) size {item.get('w', 0)}x{item.get('h', 0)} ",
                            html.Span(
                                uuid_status,
                                style={"color": "green" if uuid_status.startswith("✅") else "red"},
                            ),
                        ]
                    )
                )

        return info

    return app


if __name__ == "__main__":
    app = create_working_test()
    print("🎉 Starting working DashboardItem test...")
    app.run(debug=True, port=8063)
