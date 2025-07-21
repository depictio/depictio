#!/usr/bin/env python3
"""
Deeper investigation into the JavaScript component processing
"""

import uuid

import dash
import dash_draggable
from dash import Input, Output, html


def generate_unique_index():
    return str(uuid.uuid4())


def create_deep_debug_app():
    app = dash.Dash(__name__)

    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()

    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"

    print(f"=== Deep Debug with Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")

    layout = {
        "lg": [
            {"i": box_id1, "x": 0, "y": 0, "w": 6, "h": 4},
            {"i": box_id2, "x": 6, "y": 0, "w": 6, "h": 4},
        ]
    }

    # Test multiple approaches
    children = [
        html.Div(
            id=box_id1,
            key=box_id1,
            children=[html.H3("Component 1"), html.P(f"ID: {box_id1}")],
            style={"border": "2px solid red", "padding": "10px"},
            **{"data-grid": {"i": box_id1, "x": 0, "y": 0, "w": 6, "h": 4}},  # Try data-grid
        ),
        html.Div(
            id=box_id2,
            key=box_id2,
            children=[html.H3("Component 2"), html.P(f"ID: {box_id2}")],
            style={"border": "2px solid blue", "padding": "10px"},
            **{"data-grid": {"i": box_id2, "x": 6, "y": 0, "w": 6, "h": 4}},  # Try data-grid
        ),
    ]

    app.layout = html.Div(
        [
            html.H1(f"🔍 Deep Debug - Dash {dash.__version__}"),
            html.Div(id="deep-debug-output"),
            html.Button("Deep Debug", id="deep-debug-button"),
            html.Hr(),
            dash_draggable.ResponsiveGridLayout(
                id="deep-debug-grid",
                children=children,
                layouts=layout,
                isDraggable=True,
                isResizable=True,
                save=False,
                clearSavedLayout=False,
            ),
        ]
    )

    # Comprehensive debugging
    app.clientside_callback(
        f"""
        function(n_clicks, layouts, children) {{
            if (!n_clicks) return "Click 'Deep Debug' button";
            
            var result = [];
            result.push("=== DEEP DEBUG RESULTS ===");
            result.push("Expected ID 1: {box_id1}");
            result.push("Expected ID 2: {box_id2}");
            result.push("");
            
            // Debug the props passed to the component
            result.push("=== COMPONENT PROPS ===");
            var gridElement = document.getElementById('deep-debug-grid');
            if (gridElement && gridElement._dashprivate_layout) {{
                result.push("Grid has _dashprivate_layout: " + JSON.stringify(gridElement._dashprivate_layout));
            }}
            
            // Debug React children structure
            result.push("\\n=== CHILDREN STRUCTURE ===");
            if (children) {{
                result.push("Children count: " + children.length);
                children.forEach(function(child, index) {{
                    result.push("Child " + index + ":");
                    result.push("  Type: " + typeof child);
                    if (child && child.props) {{
                        result.push("  Props.id: " + child.props.id);
                        result.push("  Props.key: " + child.props.key);
                        result.push("  Props.data-grid: " + JSON.stringify(child.props["data-grid"]));
                    }}
                }});
            }}
            
            // Debug the layout structure
            result.push("\\n=== LAYOUT STRUCTURE ===");
            if (layouts) {{
                for (var breakpoint in layouts) {{
                    result.push("Breakpoint: " + breakpoint);
                    layouts[breakpoint].forEach(function(item, index) {{
                        result.push("  Item " + index + ": " + JSON.stringify(item));
                    }});
                }}
            }}
            
            // Debug the actual DOM structure
            result.push("\\n=== DOM STRUCTURE ===");
            if (gridElement) {{
                var reactGridItems = gridElement.querySelectorAll('.react-grid-item');
                result.push("React grid items found: " + reactGridItems.length);
                
                reactGridItems.forEach(function(item, index) {{
                    result.push("Grid item " + index + ":");
                    result.push("  data-grid: " + item.getAttribute('data-grid'));
                    result.push("  transform: " + item.style.transform);
                    
                    var childDiv = item.querySelector('div[id]');
                    if (childDiv) {{
                        result.push("  Child div ID: " + childDiv.id);
                    }}
                }});
            }}
            
            return result.join("\\n");
        }}
        """,
        Output("deep-debug-output", "children"),
        Input("deep-debug-button", "n_clicks"),
        Input("deep-debug-grid", "layouts"),
        Input("deep-debug-grid", "children"),
    )

    return app


if __name__ == "__main__":
    app = create_deep_debug_app()
    print("🔍 Starting deep debug app...")
    app.run(debug=True, port=8058)
