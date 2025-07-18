#!/usr/bin/env python3
"""
Test DashboardItemResponsive with session storage
"""

import uuid
import dash
from dash import html, Input, Output, State, dcc
import dash_draggable

def generate_unique_index():
    return str(uuid.uuid4())

def create_responsive_storage_test():
    app = dash.Dash(__name__)
    
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()
    
    box_id1 = f"box-{uuid1}"
    box_id2 = f"box-{uuid2}"
    
    print(f"=== Testing DashboardItemResponsive with Storage - Dash {dash.__version__} ===")
    print(f"Expected IDs: {box_id1}, {box_id2}")
    
    # Use DashboardItemResponsive with ResponsiveGridLayout
    children = [
        dash_draggable.DashboardItemResponsive(
            id=box_id1,  # This component accepts id prop
            x=0, y=0, w=6, h=4,
            children=[
                html.Div([
                    html.H3("Component 1"),
                    html.P(f"ID: {box_id1}"),
                    html.P("✅ Using DashboardItemResponsive"),
                    html.P("Drag me around!")
                ], style={"border": "2px solid green", "padding": "10px", "background": "#f0f8ff"})
            ]
        ),
        dash_draggable.DashboardItemResponsive(
            id=box_id2,  # This component accepts id prop
            x=6, y=0, w=6, h=4,
            children=[
                html.Div([
                    html.H3("Component 2"),
                    html.P(f"ID: {box_id2}"),
                    html.P("✅ Using DashboardItemResponsive"),
                    html.P("Resize me!")
                ], style={"border": "2px solid blue", "padding": "10px", "background": "#fff8f0"})
            ]
        )
    ]
    
    app.layout = html.Div([
        html.H1("🎯 DashboardItemResponsive with Session Storage"),
        html.Div([
            html.H3("Testing: DashboardItemResponsive Component"),
            html.P("🎯 This component accepts 'id' prop and should work with ResponsiveGridLayout"),
            html.P("💾 Session storage: Check browser DevTools -> Application -> Session Storage"),
        ]),
        html.Div(id="responsive-output"),
        html.Button("Test UUID Preservation", id="test-uuid-btn", style={"margin": "5px"}),
        html.Hr(),
        
        # Session storage components
        dcc.Store(id="session-storage", storage_type="session"),
        html.Div(id="storage-display", style={"background": "#f5f5f5", "padding": "10px", "margin": "10px 0"}),
        html.Hr(),
        
        dash_draggable.ResponsiveGridLayout(
            id="responsive-grid",
            children=children,
            isDraggable=True,
            isResizable=True,
            save=False,
            clearSavedLayout=False
        )
    ])
    
    @app.callback(
        [Output("responsive-output", "children"),
         Output("session-storage", "data")],
        Input("responsive-grid", "layouts"),
        prevent_initial_call=True
    )
    def update_layout_and_storage(layouts):
        if not layouts:
            return "No layout data", {}
        
        info = []
        info.append(html.H4("📊 Layout Analysis:"))
        
        all_uuid_preserved = True
        
        for breakpoint, items in layouts.items():
            info.append(html.H5(f"Breakpoint: {breakpoint}"))
            for i, item in enumerate(items):
                item_id = item.get('i', 'unknown')
                uuid_preserved = item_id.startswith('box-') and len(item_id) > 10
                if not uuid_preserved:
                    all_uuid_preserved = False
                
                status = "✅ UUID preserved" if uuid_preserved else "❌ UUID lost"
                status_color = "green" if uuid_preserved else "red"
                
                info.append(html.P([
                    f"Item {i}: ",
                    html.Code(f"id={item_id}"),
                    f" at ({item.get('x', 0)}, {item.get('y', 0)}) ",
                    f"size {item.get('w', 0)}x{item.get('h', 0)} ",
                    html.Span(status, style={"color": status_color, "fontWeight": "bold"})
                ]))
        
        # Overall status
        overall_status = "✅ SUCCESS: All UUIDs preserved!" if all_uuid_preserved else "❌ FAILURE: Some UUIDs lost"
        status_color = "green" if all_uuid_preserved else "red"
        info.append(html.H4(overall_status, style={"color": status_color}))
        
        # Store the layout data
        storage_data = {
            "layouts": layouts,
            "uuid_preserved": all_uuid_preserved,
            "timestamp": str(uuid.uuid4())[:8],
            "expected_ids": [box_id1, box_id2]
        }
        
        return info, storage_data
    
    @app.callback(
        Output("storage-display", "children"),
        Input("session-storage", "data")
    )
    def display_storage(storage_data):
        if not storage_data:
            return html.P("No data in session storage")
        
        return html.Div([
            html.H4("📱 Session Storage Contents:"),
            html.P(f"UUID Preserved: {storage_data.get('uuid_preserved', 'unknown')}"),
            html.P(f"Expected IDs: {storage_data.get('expected_ids', [])}"),
            html.Details([
                html.Summary("Click to see full layout data"),
                html.Pre(
                    str(storage_data.get('layouts', {})),
                    style={"background": "#fff", "padding": "10px", "border": "1px solid #ccc", "fontSize": "12px"}
                )
            ]),
            html.P("💡 Check browser DevTools -> Application -> Session Storage for full data")
        ])
    
    @app.callback(
        Output("responsive-output", "children", allow_duplicate=True),
        Input("test-uuid-btn", "n_clicks"),
        State("session-storage", "data"),
        prevent_initial_call=True
    )
    def test_uuid_preservation(n_clicks, storage_data):
        if not storage_data:
            return "No layout data to test"
        
        uuid_preserved = storage_data.get('uuid_preserved', False)
        
        if uuid_preserved:
            return html.Div([
                html.H4("🎉 DashboardItemResponsive WORKS!", style={"color": "green"}),
                html.P("✅ UUID identities preserved"),
                html.P("✅ No manual mapping needed"),
                html.P("✅ This is the cleanest solution!"),
            ])
        else:
            return html.Div([
                html.H4("❌ DashboardItemResponsive doesn't work", style={"color": "red"}),
                html.P("❌ UUID identities lost"),
                html.P("🔄 Need to use hybrid approach instead"),
            ])
    
    # Add clientside callback to also store in browser sessionStorage
    app.clientside_callback(
        """
        function(data) {
            if (data) {
                sessionStorage.setItem('dash_responsive_layouts', JSON.stringify(data));
                console.log('Stored responsive layout data:', data);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("responsive-output", "style"),
        Input("session-storage", "data")
    )
    
    return app

if __name__ == "__main__":
    app = create_responsive_storage_test()
    print("🎯 Starting DashboardItemResponsive with session storage...")
    print("💡 Open browser DevTools -> Application -> Session Storage to see stored layouts")
    app.run(debug=True, port=8068)