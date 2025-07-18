#!/usr/bin/env python3
"""
Test using DashboardItem component correctly (without id prop)
"""

import uuid
import dash
from dash import html, Input, Output, clientside_callback
import dash_draggable

def generate_unique_index():
    return str(uuid.uuid4())

def create_dashboard_item_test():
    app = dash.Dash(__name__)
    
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    
    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"
    
    print(f"=== Testing DashboardItem (Fixed) with Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")
    
    # Use DashboardItem components with only the 'i' prop (no id prop)
    children = [
        dash_draggable.DashboardItem(
            i=box_id1,  # ← Only use 'i' prop, no 'id' prop
            x=0, y=0, w=6, h=4,
            children=[
                html.Div(
                    id=box_id1,  # ← Put id on the inner div
                    children=[
                        html.H3("Component 1"),
                        html.P(f"ID: {box_id1}"),
                        html.P("✅ Using DashboardItem with only 'i' prop")
                    ],
                    style={"border": "2px solid green", "padding": "10px"}
                )
            ]
        ),
        dash_draggable.DashboardItem(
            i=box_id2,  # ← Only use 'i' prop, no 'id' prop
            x=6, y=0, w=6, h=4,
            children=[
                html.Div(
                    id=box_id2,  # ← Put id on the inner div
                    children=[
                        html.H3("Component 2"),
                        html.P(f"ID: {box_id2}"),
                        html.P("✅ Using DashboardItem with only 'i' prop")
                    ],
                    style={"border": "2px solid blue", "padding": "10px"}
                )
            ]
        )
    ]
    
    app.layout = html.Div([
        html.H1(f"🎯 DashboardItem Test (Fixed) - Dash {dash.__version__}"),
        html.Div(id="dashboard-item-output"),
        html.Button("Test DashboardItem", id="test-dashboard-item"),
        html.Hr(),
        
        dash_draggable.ResponsiveGridLayout(
            id="dashboard-item-grid",
            children=children,
            isDraggable=True,
            isResizable=True,
            save=False,
            clearSavedLayout=False
        )
    ])
    
    app.clientside_callback(
        f"""
        function(n_clicks, layouts) {{
            if (!n_clicks) return "Click 'Test DashboardItem' button";
            
            var result = [];
            result.push("=== DASHBOARD ITEM TEST RESULTS (FIXED) ===");
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
                    result.push("🎉 DASHBOARD ITEM SOLUTION WORKS!");
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
        Output("dashboard-item-output", "children"),
        Input("test-dashboard-item", "n_clicks"),
        Input("dashboard-item-grid", "layouts")
    )
    
    return app

if __name__ == "__main__":
    app = create_dashboard_item_test()
    print("🎯 Starting DashboardItem test (fixed)...")
    app.run(debug=True, port=8061)