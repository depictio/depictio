#!/usr/bin/env python3
"""
Debug why DashboardItem isn't preserving the 'i' prop in layouts
"""

import uuid
import dash
from dash import html, Input, Output, clientside_callback
import dash_draggable

def generate_unique_index():
    return str(uuid.uuid4())

def create_debug_app():
    app = dash.Dash(__name__)
    
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    
    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"
    
    print(f"=== Debugging DashboardItem - Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")
    
    # Test with explicit debug
    children = [
        dash_draggable.DashboardItem(
            i=box_id1,
            x=0, y=0, w=6, h=4,
            children=[
                html.Div(
                    id=box_id1,
                    children=[
                        html.H3("Component 1"),
                        html.P(f"DashboardItem.i = {box_id1}"),
                        html.P("If this shows UUID in layout, it's working")
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
                        html.P(f"DashboardItem.i = {box_id2}"),
                        html.P("If this shows UUID in layout, it's working")
                    ],
                    style={"border": "2px solid blue", "padding": "10px"}
                )
            ]
        )
    ]
    
    app.layout = html.Div([
        html.H1("🔍 Debug DashboardItem Layout Data"),
        html.Div(id="debug-output"),
        html.Button("Debug Layout Data", id="debug-button"),
        html.Hr(),
        
        dash_draggable.ResponsiveGridLayout(
            id="debug-grid",
            children=children,
            isDraggable=True,
            isResizable=True,
            save=False,
            clearSavedLayout=False
        )
    ])
    
    # Comprehensive debug callback
    app.clientside_callback(
        f"""
        function(n_clicks, layouts, children) {{
            if (!n_clicks) return "Click debug button";
            
            var result = [];
            result.push("=== COMPREHENSIVE DEBUG ===");
            result.push("Expected UUID 1: {box_id1}");
            result.push("Expected UUID 2: {box_id2}");
            result.push("");
            
            // Debug children structure
            result.push("=== CHILDREN STRUCTURE ===");
            if (children) {{
                result.push("Children count: " + children.length);
                children.forEach(function(child, index) {{
                    result.push("Child " + index + ":");
                    result.push("  Type: " + (child.type || "unknown"));
                    result.push("  Namespace: " + (child.namespace || "unknown"));
                    if (child.props) {{
                        result.push("  Props.i: " + (child.props.i || "undefined"));
                        result.push("  Props.x: " + (child.props.x || "undefined"));
                        result.push("  Props.y: " + (child.props.y || "undefined"));
                        result.push("  Props.w: " + (child.props.w || "undefined"));
                        result.push("  Props.h: " + (child.props.h || "undefined"));
                    }}
                }});
            }}
            
            result.push("");
            
            // Debug layout structure  
            result.push("=== LAYOUT STRUCTURE ===");
            if (layouts) {{
                for (var breakpoint in layouts) {{
                    result.push("Breakpoint: " + breakpoint);
                    var items = layouts[breakpoint];
                    for (var i = 0; i < items.length; i++) {{
                        var item = items[i];
                        result.push("  Item " + i + ":");
                        result.push("    i: " + (item.i || "undefined"));
                        result.push("    x: " + (item.x || "undefined"));
                        result.push("    y: " + (item.y || "undefined"));
                        result.push("    w: " + (item.w || "undefined"));
                        result.push("    h: " + (item.h || "undefined"));
                        
                        var hasUUID = item.i && item.i.startsWith("box-") && item.i.length > 10;
                        result.push("    UUID Status: " + (hasUUID ? "✅ PRESENT" : "❌ MISSING"));
                    }}
                }}
            }} else {{
                result.push("No layout data");
            }}
            
            return result.join("\\n");
        }}
        """,
        Output("debug-output", "children"),
        Input("debug-button", "n_clicks"),
        Input("debug-grid", "layouts"),
        Input("debug-grid", "children")
    )
    
    return app

if __name__ == "__main__":
    app = create_debug_app()
    print("🔍 Starting comprehensive debug...")
    app.run(debug=True, port=8064)