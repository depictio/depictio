#!/usr/bin/env python3
"""
Test the React key fix for UUID ID issue
"""

import uuid

import dash
import dash_draggable
from dash import Input, Output, clientside_callback, html


def generate_unique_index():
    return str(uuid.uuid4())

def create_fix_test_app():
    app = dash.Dash(__name__)
    
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    
    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"
    
    print(f"=== Testing Fix with Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")
    
    layout = {
        "lg": [
            {"i": box_id1, "x": 0, "y": 0, "w": 6, "h": 4},
            {"i": box_id2, "x": 6, "y": 0, "w": 6, "h": 4}
        ]
    }
    
    # THE FIX: Add explicit key prop matching the id
    children = [
        html.Div(
            id=box_id1,
            key=box_id1,  # ← This should fix the issue
            children=[
                html.H3("Component 1"),
                html.P(f"ID: {box_id1}"),
                html.P(f"Key: {box_id1}"),
                html.P("✅ Should work with explicit key!")
            ],
            style={"border": "2px solid green", "padding": "10px"}
        ),
        html.Div(
            id=box_id2,
            key=box_id2,  # ← This should fix the issue
            children=[
                html.H3("Component 2"),
                html.P(f"ID: {box_id2}"),
                html.P(f"Key: {box_id2}"),
                html.P("✅ Should work with explicit key!")
            ],
            style={"border": "2px solid blue", "padding": "10px"}
        )
    ]
    
    app.layout = html.Div([
        html.H1(f"🔧 Fix Test - Dash {dash.__version__}"),
        html.Div(id="fix-test-output"),
        html.Button("Test Fix", id="test-fix-button"),
        html.Hr(),
        
        dash_draggable.ResponsiveGridLayout(
            id="fix-test-grid",
            children=children,
            layouts=layout,
            isDraggable=True,
            isResizable=True,
            save=False,
            clearSavedLayout=False
        )
    ])
    
    # Test the fix
    app.clientside_callback(
        f"""
        function(n_clicks, layouts) {{
            if (!n_clicks) return "Click 'Test Fix' button";
            
            var result = [];
            result.push("=== FIX TEST RESULTS ===");
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
                    result.push("🎉 FIX SUCCESSFUL! All items have correct UUID-based IDs!");
                }} else {{
                    result.push("❌ Fix failed - some items still have numerical IDs");
                }}
            }} else {{
                result.push("❌ No layout data received");
            }}
            
            return result.join("\\n");
        }}
        """,
        Output("fix-test-output", "children"),
        Input("test-fix-button", "n_clicks"),
        Input("fix-test-grid", "layouts")
    )
    
    return app

if __name__ == "__main__":
    app = create_fix_test_app()
    print("🔧 Starting fix test app...")
    # if hasattr(app, 'run_server'):
    #     app.run_server(debug=True, port=8057)
    # else:
    app.run(debug=True, port=8057)