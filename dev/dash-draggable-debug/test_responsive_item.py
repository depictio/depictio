#!/usr/bin/env python3
"""
Test DashboardItemResponsive which should work with ResponsiveGridLayout
"""

import uuid

import dash
import dash_draggable
from dash import Input, Output, html


def generate_unique_index():
    return str(uuid.uuid4())


def create_responsive_test():
    app = dash.Dash(__name__)

    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()

    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"

    print(f"=== Testing DashboardItemResponsive - Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")

    # Use DashboardItemResponsive with ResponsiveGridLayout
    children = [
        dash_draggable.DashboardItemResponsive(
            id=box_id1,  # This component accepts id prop
            x=0,
            y=0,
            w=6,
            h=4,
            children=[
                html.Div(
                    [
                        html.H3("Component 1"),
                        html.P(f"ID: {box_id1}"),
                        html.P("✅ Using DashboardItemResponsive"),
                    ],
                    style={"border": "2px solid green", "padding": "10px"},
                )
            ],
        ),
        dash_draggable.DashboardItemResponsive(
            id=box_id2,  # This component accepts id prop
            x=6,
            y=0,
            w=6,
            h=4,
            children=[
                html.Div(
                    [
                        html.H3("Component 2"),
                        html.P(f"ID: {box_id2}"),
                        html.P("✅ Using DashboardItemResponsive"),
                    ],
                    style={"border": "2px solid blue", "padding": "10px"},
                )
            ],
        ),
    ]

    app.layout = html.Div(
        [
            html.H1("🎯 DashboardItemResponsive Test"),
            html.Div(id="responsive-output"),
            html.Hr(),
            dash_draggable.ResponsiveGridLayout(
                id="responsive-grid",
                children=children,
                isDraggable=True,
                isResizable=True,
                save=False,
                clearSavedLayout=False,
            ),
        ]
    )

    @app.callback(
        Output("responsive-output", "children"),
        Input("responsive-grid", "layouts"),
        prevent_initial_call=True,
    )
    def show_layout(layouts):
        if not layouts:
            return "No layout data"

        info = []
        for breakpoint, items in layouts.items():
            info.append(html.H4(f"Breakpoint: {breakpoint}"))
            for i, item in enumerate(items):
                uuid_preserved = (
                    item.get("i", "").startswith("box-") and len(item.get("i", "")) > 10
                )
                status = "✅ UUID preserved" if uuid_preserved else "❌ UUID lost"
                info.append(
                    html.P(
                        [
                            f"Item {i}: ",
                            html.Code(f"id={item.get('i', 'unknown')}"),
                            f" at ({item.get('x', 0)}, {item.get('y', 0)}) ",
                            html.Span(
                                status, style={"color": "green" if uuid_preserved else "red"}
                            ),
                        ]
                    )
                )

        return info

    return app


if __name__ == "__main__":
    app = create_responsive_test()
    print("🎯 Starting DashboardItemResponsive test...")
    app.run(debug=True, port=8065)
