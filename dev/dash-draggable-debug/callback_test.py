#!/usr/bin/env python3
"""
Test callback behavior with UUID IDs in dash-draggable
"""

import uuid
import dash
from dash import html, Input, Output, State, callback
import dash_draggable
import json

def generate_unique_index():
    return str(uuid.uuid4())

def create_test_app():
    app = dash.Dash(__name__)
    
    # Generate UUIDs
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    
    print(f"Dash version: {dash.__version__}")
    print(f"UUID 1: {uuid1}")
    print(f"UUID 2: {uuid2}")
    
    # Initial layout
    initial_layout = {
        "lg": [
            {"i": f"box-{uuid1}", "x": 0, "y": 0, "w": 6, "h": 4},
            {"i": f"box-{uuid2}", "x": 6, "y": 0, "w": 6, "h": 4}
        ]
    }
    
    # Initial children
    initial_children = [
        html.Div(
            id=f"box-{uuid1}",
            children=[
                html.H3(f"Component 1"),
                html.P(f"UUID: {uuid1}"),
                html.Button("Click me", id=f"btn-{uuid1}"),
                html.Div(id=f"output-{uuid1}")
            ],
            style={"border": "1px solid #ccc", "padding": "10px", "background": "#f9f9f9"}
        ),
        html.Div(
            id=f"box-{uuid2}",
            children=[
                html.H3(f"Component 2"),
                html.P(f"UUID: {uuid2}"),
                html.Button("Click me", id=f"btn-{uuid2}"),
                html.Div(id=f"output-{uuid2}")
            ],
            style={"border": "1px solid #ccc", "padding": "10px", "background": "#f0f0f0"}
        )
    ]
    
    app.layout = html.Div([
        html.H1(f"Dash {dash.__version__} Callback Test"),
        html.Div(id="layout-output"),
        html.Div(id="debug-output"),
        html.Hr(),
        
        dash_draggable.ResponsiveGridLayout(
            id="draggable-grid",
            children=initial_children,
            layouts=initial_layout,
            clearSavedLayout=False,
            isDraggable=True,
            isResizable=True,
            save=False,
            style={"height": "400px", "border": "2px solid #333"}
        )
    ])
    
    # Callback for layout changes
    @app.callback(
        Output("layout-output", "children"),
        Input("draggable-grid", "layouts"),
        prevent_initial_call=True
    )
    def update_layout_output(layouts):
        if layouts:
            return html.Div([
                html.H3("Layout Updated:"),
                html.Pre(json.dumps(layouts, indent=2))
            ])
        return "No layout data"
    
    # Callback for buttons with UUID IDs
    @app.callback(
        Output(f"output-{uuid1}", "children"),
        Input(f"btn-{uuid1}", "n_clicks"),
        prevent_initial_call=True
    )
    def update_output1(n_clicks):
        return f"Button 1 clicked {n_clicks} times"
    
    @app.callback(
        Output(f"output-{uuid2}", "children"),
        Input(f"btn-{uuid2}", "n_clicks"),
        prevent_initial_call=True
    )
    def update_output2(n_clicks):
        return f"Button 2 clicked {n_clicks} times"
    
    # Debug callback to show component info
    @app.callback(
        Output("debug-output", "children"),
        Input("draggable-grid", "children"),
        prevent_initial_call=True
    )
    def debug_children(children):
        if children:
            child_ids = []
            for child in children:
                if hasattr(child, 'id'):
                    child_ids.append(child.id)
                elif isinstance(child, dict) and 'props' in child:
                    child_ids.append(child['props'].get('id', 'no-id'))
                else:
                    child_ids.append('unknown')
            
            return html.Div([
                html.H4("Debug Info:"),
                html.P(f"Children count: {len(children)}"),
                html.P(f"Child IDs: {child_ids}")
            ])
        return "No children data"
    
    return app

if __name__ == "__main__":
    app = create_test_app()
    print("Starting callback test...")
    app.run_server(debug=True, port=8052)