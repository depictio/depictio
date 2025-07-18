#!/usr/bin/env python3
"""
Debug the JavaScript behavior with detailed clientside callbacks
"""

import uuid
import dash
from dash import html, Input, Output, State, clientside_callback
import dash_draggable

def generate_unique_index():
    return str(uuid.uuid4())

def create_debug_app():
    app = dash.Dash(__name__)
    
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    
    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"
    
    print(f"=== Dash {dash.__version__} JavaScript Debug ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")
    
    layout = {
        "lg": [
            {"i": box_id1, "x": 0, "y": 0, "w": 6, "h": 4},
            {"i": box_id2, "x": 6, "y": 0, "w": 6, "h": 4}
        ]
    }
    
    children = [
        html.Div(
            id=box_id1,
            children=[html.H3("Component 1"), html.P(f"ID: {box_id1}")],
            style={"border": "2px solid red", "padding": "10px"}
        ),
        html.Div(
            id=box_id2,
            children=[html.H3("Component 2"), html.P(f"ID: {box_id2}")],
            style={"border": "2px solid blue", "padding": "10px"}
        )
    ]
    
    app.layout = html.Div([
        html.H1(f"JavaScript Debug - Dash {dash.__version__}"),
        html.Div(id="debug-output"),
        html.Button("Debug Components", id="debug-button"),
        html.Hr(),
        
        dash_draggable.ResponsiveGridLayout(
            id="debug-grid",
            children=children,
            layouts=layout,
            isDraggable=True,
            isResizable=True,
            save=False,
            clearSavedLayout=False
        )
    ])
    
    # Detailed clientside callback to investigate
    app.clientside_callback(
        f"""
        function(n_clicks, layouts, children) {{
            if (!n_clicks) return "Click debug button to inspect";
            
            var debugInfo = [];
            
            // Debug the layouts prop
            debugInfo.push("=== LAYOUTS PROP ===");
            debugInfo.push("Expected ID 1: {box_id1}");
            debugInfo.push("Expected ID 2: {box_id2}");
            
            if (layouts) {{
                for (var breakpoint in layouts) {{
                    debugInfo.push("Breakpoint: " + breakpoint);
                    var items = layouts[breakpoint];
                    for (var i = 0; i < items.length; i++) {{
                        var item = items[i];
                        debugInfo.push("  Layout Item " + i + ": i=" + item.i + ", x=" + item.x + ", y=" + item.y);
                        debugInfo.push("    Is UUID format: " + (item.i.startsWith("box-") && item.i.length > 20));
                    }}
                }}
            }} else {{
                debugInfo.push("No layouts data");
            }}
            
            // Debug the children prop
            debugInfo.push("\\n=== CHILDREN PROP ===");
            if (children) {{
                debugInfo.push("Children count: " + children.length);
                for (var i = 0; i < children.length; i++) {{
                    var child = children[i];
                    debugInfo.push("Child " + i + ": " + JSON.stringify(child, null, 2));
                }}
            }} else {{
                debugInfo.push("No children data");
            }}
            
            // Debug the actual DOM
            debugInfo.push("\\n=== DOM INSPECTION ===");
            var gridElement = document.getElementById('debug-grid');
            if (gridElement) {{
                debugInfo.push("Grid element found");
                
                // Look for react-grid-layout elements
                var gridItems = gridElement.querySelectorAll('.react-grid-item');
                debugInfo.push("React grid items found: " + gridItems.length);
                
                for (var i = 0; i < gridItems.length; i++) {{
                    var item = gridItems[i];
                    debugInfo.push("Grid item " + i + ":");
                    debugInfo.push("  data-grid key: " + item.getAttribute('data-grid'));
                    debugInfo.push("  style: " + item.getAttribute('style'));
                    
                    // Look for child elements
                    var childDiv = item.querySelector('div[id^="box-"]');
                    if (childDiv) {{
                        debugInfo.push("  Child div ID: " + childDiv.id);
                    }} else {{
                        debugInfo.push("  No child div with box- ID found");
                    }}
                }}
            }} else {{
                debugInfo.push("Grid element not found");
            }}
            
            return debugInfo.join("\\n");
        }}
        """,
        Output("debug-output", "children"),
        Input("debug-button", "n_clicks"),
        State("debug-grid", "layouts"),
        State("debug-grid", "children")
    )
    
    return app

if __name__ == "__main__":
    app = create_debug_app()
    print("Starting JavaScript debug app...")
    if hasattr(app, 'run_server'):
        app.run_server(debug=True, port=8056)
    else:
        app.run(debug=True, port=8056)