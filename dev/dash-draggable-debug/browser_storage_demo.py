#!/usr/bin/env python3
"""
Browser storage demo to visualize layouts in session storage
"""

import uuid
import dash
from dash import html, Input, Output, State, dcc
import dash_draggable
import json

def generate_unique_index():
    return str(uuid.uuid4())

def create_browser_storage_demo():
    app = dash.Dash(__name__)
    
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    uuid3 = generate_unique_index()
    
    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"
    box_id3 = f"box-{uuid3}"
    
    print(f"=== Browser Storage Demo - Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}, {box_id3}")
    
    # Test multiple components with DashboardItem
    children = [
        dash_draggable.DashboardItem(
            i=box_id1,
            x=0, y=0, w=4, h=4,
            children=[
                html.Div([
                    html.H4("Component 1"),
                    html.P(f"Short UUID: {uuid1[:8]}..."),
                    html.P("🔴 Red component"),
                    html.Small("Drag me!")
                ], style={"border": "2px solid red", "padding": "10px", "background": "#fff0f0", "textAlign": "center"})
            ]
        ),
        dash_draggable.DashboardItem(
            i=box_id2,
            x=4, y=0, w=4, h=4,
            children=[
                html.Div([
                    html.H4("Component 2"),
                    html.P(f"Short UUID: {uuid2[:8]}..."),
                    html.P("🔵 Blue component"),
                    html.Small("Resize me!")
                ], style={"border": "2px solid blue", "padding": "10px", "background": "#f0f0ff", "textAlign": "center"})
            ]
        ),
        dash_draggable.DashboardItem(
            i=box_id3,
            x=8, y=0, w=4, h=4,
            children=[
                html.Div([
                    html.H4("Component 3"),
                    html.P(f"Short UUID: {uuid3[:8]}..."),
                    html.P("🟢 Green component"),
                    html.Small("Move me!")
                ], style={"border": "2px solid green", "padding": "10px", "background": "#f0fff0", "textAlign": "center"})
            ]
        )
    ]
    
    app.layout = html.Div([
        html.H1("📱 Browser Session Storage Demo"),
        html.Div([
            html.H3("Instructions:"),
            html.Ol([
                html.Li("Drag and resize the components above"),
                html.Li("Watch the session storage update below"),
                html.Li("Open browser DevTools -> Application -> Session Storage"),
                html.Li("Look for keys starting with 'dash_' to see stored data"),
            ]),
        ], style={"background": "#f9f9f9", "padding": "15px", "margin": "10px 0"}),
        
        # Live storage display
        html.H3("📊 Live Session Storage Data:"),
        html.Div(id="storage-display", style={"background": "#f5f5f5", "padding": "10px", "margin": "10px 0", "border": "1px solid #ccc"}),
        
        html.Hr(),
        
        # Session storage components
        dcc.Store(id="session-storage", storage_type="session"),
        
        dash_draggable.ResponsiveGridLayout(
            id="demo-grid",
            children=children,
            isDraggable=True,
            isResizable=True,
            save=False,
            clearSavedLayout=False
        )
    ])
    
    @app.callback(
        [Output("storage-display", "children"),
         Output("session-storage", "data")],
        Input("demo-grid", "layouts"),
        prevent_initial_call=True
    )
    def update_storage_display(layouts):
        if not layouts:
            return "No layout data", {}
        
        # Map numerical IDs to UUIDs
        uuid_map = {0: box_id1, 1: box_id2, 2: box_id3}
        
        # Create UUID-based layout
        uuid_layouts = {}
        for breakpoint, items in layouts.items():
            uuid_layouts[breakpoint] = []
            for i, item in enumerate(items):
                uuid_id = uuid_map.get(i, f"unknown-{i}")
                uuid_item = {
                    "i": uuid_id,
                    "x": item.get("x", 0),
                    "y": item.get("y", 0),
                    "w": item.get("w", 4),
                    "h": item.get("h", 4)
                }
                uuid_layouts[breakpoint].append(uuid_item)
        
        # Create display
        display_components = []
        
        # Raw vs UUID comparison
        display_components.append(html.H4("🔍 Raw vs UUID Layouts:"))
        
        for breakpoint in ["lg", "md", "sm"]:
            if breakpoint in layouts:
                display_components.append(html.H5(f"Breakpoint: {breakpoint}"))
                
                # Raw layout
                display_components.append(html.P("❌ Raw Layout (numerical IDs):"))
                for i, item in enumerate(layouts[breakpoint]):
                    display_components.append(html.Div([
                        html.Code(f"Item {i}: id={item.get('i', 'unknown')} at ({item.get('x', 0)}, {item.get('y', 0)}) size {item.get('w', 0)}x{item.get('h', 0)}")
                    ], style={"marginLeft": "20px", "color": "red"}))
                
                # UUID layout
                display_components.append(html.P("✅ UUID Layout (preserved identities):"))
                for i, item in enumerate(uuid_layouts[breakpoint]):
                    short_uuid = item['i'].split('-')[1][:8] if '-' in item['i'] else item['i'][:8]
                    display_components.append(html.Div([
                        html.Code(f"Item {i}: id={short_uuid}... at ({item.get('x', 0)}, {item.get('y', 0)}) size {item.get('w', 0)}x{item.get('h', 0)}")
                    ], style={"marginLeft": "20px", "color": "green"}))
        
        # JSON display
        display_components.append(html.H4("📋 JSON Data for Session Storage:"))
        display_components.append(html.Details([
            html.Summary("Click to expand JSON data"),
            html.Pre(
                json.dumps(uuid_layouts, indent=2),
                style={"background": "#fff", "padding": "10px", "border": "1px solid #ddd", "fontSize": "12px"}
            )
        ]))
        
        # Storage instructions
        display_components.append(html.Div([
            html.H4("🔧 Browser DevTools Instructions:"),
            html.Ol([
                html.Li("Press F12 to open DevTools"),
                html.Li("Go to Application tab"),
                html.Li("Click Session Storage in the left panel"),
                html.Li("Look for your domain"),
                html.Li("Find keys starting with 'dash_demo_layouts'"),
            ])
        ], style={"background": "#e8f4f8", "padding": "10px", "margin": "10px 0"}))
        
        # Store the data
        storage_data = {
            "raw_layouts": layouts,
            "uuid_layouts": uuid_layouts,
            "uuid_map": uuid_map,
            "timestamp": str(uuid.uuid4())[:8]
        }
        
        return display_components, storage_data
    
    # Clientside callback to store in browser sessionStorage with custom key
    app.clientside_callback(
        """
        function(data) {
            if (data) {
                // Store with multiple keys for easy inspection
                sessionStorage.setItem('dash_demo_layouts', JSON.stringify(data.uuid_layouts));
                sessionStorage.setItem('dash_demo_raw', JSON.stringify(data.raw_layouts));
                sessionStorage.setItem('dash_demo_mapping', JSON.stringify(data.uuid_map));
                
                console.log('🎯 Stored layout data in sessionStorage:');
                console.log('UUID Layouts:', data.uuid_layouts);
                console.log('Raw Layouts:', data.raw_layouts);
                console.log('UUID Mapping:', data.uuid_map);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("demo-grid", "style"),
        Input("session-storage", "data")
    )
    
    return app

if __name__ == "__main__":
    app = create_browser_storage_demo()
    print("📱 Starting browser storage demo...")
    print("💡 Open browser DevTools -> Application -> Session Storage to see stored layouts")
    print("🔧 Look for keys: 'dash_demo_layouts', 'dash_demo_raw', 'dash_demo_mapping'")
    app.run(debug=True, port=8069)