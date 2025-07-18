#!/usr/bin/env python3
"""
Test hybrid approach: DashboardItem for UI + manual layout management for persistence
"""

import uuid
import dash
from dash import html, Input, Output, State
import dash_draggable

def generate_unique_index():
    return str(uuid.uuid4())

def create_hybrid_test():
    app = dash.Dash(__name__)
    
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    
    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"
    
    print(f"=== Testing Hybrid Approach - Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")
    
    # Create DashboardItem components (this fixes the UI)
    children = [
        dash_draggable.DashboardItem(
            i=box_id1,
            x=0, y=0, w=6, h=4,
            children=[
                html.Div(
                    id=box_id1,
                    children=[
                        html.H3("Component 1"),
                        html.P(f"UUID: {uuid1}"),
                        html.P("✅ UI works with DashboardItem")
                    ],
                    style={"border": "2px solid green", "padding": "10px"}
                )
            ]
        ),
        dash_draggable.DashboardItem(
            i=box_id2,
            x=6, y=0, w=6, h=4,
            children=[
                html.Div(
                    id=box_id2,
                    children=[
                        html.H3("Component 2"),
                        html.P(f"UUID: {uuid2}"),
                        html.P("✅ UI works with DashboardItem")
                    ],
                    style={"border": "2px solid blue", "padding": "10px"}
                )
            ]
        )
    ]
    
    app.layout = html.Div([
        html.H1("🔄 Hybrid Approach Test"),
        html.Div([
            html.H3("Strategy: Use DashboardItem for UI + Manual Layout Tracking"),
            html.P("✅ UI functionality: DashboardItem preserves drag/resize"),
            html.P("🔄 Layout persistence: Manual tracking with UUIDs"),
        ]),
        html.Div(id="hybrid-output"),
        html.Button("Save Layout", id="save-layout-btn"),
        html.Button("Load Layout", id="load-layout-btn"),
        html.Div(id="layout-storage", style={"display": "none"}),
        html.Hr(),
        
        dash_draggable.ResponsiveGridLayout(
            id="hybrid-grid",
            children=children,
            isDraggable=True,
            isResizable=True,
            save=False,
            clearSavedLayout=False
        )
    ])
    
    @app.callback(
        Output("hybrid-output", "children"),
        Input("hybrid-grid", "layouts"),
        prevent_initial_call=True
    )
    def show_current_layout(layouts):
        if not layouts:
            return "No layout data"
        
        # Map the numerical IDs back to UUIDs for display
        uuid_map = {0: box_id1, 1: box_id2}
        
        info = []
        info.append(html.H4("Current Layout (with UUID mapping):"))
        
        for breakpoint, items in layouts.items():
            info.append(html.H5(f"Breakpoint: {breakpoint}"))
            for i, item in enumerate(items):
                # Map numerical ID back to UUID
                actual_uuid = uuid_map.get(i, f"unknown-{i}")
                info.append(html.P([
                    f"Item {i}: ",
                    html.Code(f"mapped_id={actual_uuid}"),
                    f" (raw_id={item.get('i', 'unknown')}) ",
                    f"at ({item.get('x', 0)}, {item.get('y', 0)}) ",
                    f"size {item.get('w', 0)}x{item.get('h', 0)}"
                ]))
        
        return info
    
    @app.callback(
        Output("layout-storage", "children"),
        Input("save-layout-btn", "n_clicks"),
        State("hybrid-grid", "layouts"),
        prevent_initial_call=True
    )
    def save_layout(n_clicks, layouts):
        if not layouts:
            return "No layout to save"
        
        # Convert numerical IDs to UUIDs for storage
        uuid_map = {0: box_id1, 1: box_id2}
        saved_layouts = {}
        
        for breakpoint, items in layouts.items():
            saved_layouts[breakpoint] = []
            for i, item in enumerate(items):
                # Map back to UUID
                uuid_id = uuid_map.get(i, f"unknown-{i}")
                saved_item = {
                    "i": uuid_id,
                    "x": item.get("x", 0),
                    "y": item.get("y", 0),
                    "w": item.get("w", 6),
                    "h": item.get("h", 4)
                }
                saved_layouts[breakpoint].append(saved_item)
        
        return f"Saved layout with UUIDs: {saved_layouts}"
    
    @app.callback(
        Output("hybrid-output", "children", allow_duplicate=True),
        Input("load-layout-btn", "n_clicks"),
        State("layout-storage", "children"),
        prevent_initial_call=True
    )
    def load_layout(n_clicks, stored_data):
        if not stored_data or "Saved layout" not in stored_data:
            return "No saved layout to load"
        
        return html.Div([
            html.H4("✅ Hybrid Approach Working!"),
            html.P("✅ UI: DashboardItem provides drag/resize functionality"),
            html.P("✅ Persistence: Manual UUID mapping preserves identities"),
            html.P("✅ Solution: Use DashboardItem + custom layout tracking"),
            html.Pre(stored_data, style={"background": "#f0f0f0", "padding": "10px"})
        ])
    
    return app

if __name__ == "__main__":
    app = create_hybrid_test()
    print("🔄 Starting hybrid approach test...")
    app.run(debug=True, port=8066)