#!/usr/bin/env python3
"""
Test the depictio implementation of the hybrid approach
"""

import sys
import uuid

import dash
import dash_draggable
from dash import Input, Output, dcc, html

# Add the depictio package to the path
sys.path.insert(0, "/Users/tweber/Gits/workspaces/depictio-workspace/depictio")

# Test the enable_box_edit_mode function with DashboardItem
try:
    from depictio.dash.layouts.draggable import map_numerical_ids_to_uuids
    from depictio.dash.layouts.edit import enable_box_edit_mode

    print("✅ Successfully imported depictio modules")
except ImportError as e:
    print(f"❌ Failed to import depictio modules: {e}")
    sys.exit(1)


def generate_unique_index():
    return str(uuid.uuid4())


def create_test_app():
    app = dash.Dash(__name__)

    # Create test metadata similar to depictio format
    uuid1 = generate_unique_index()
    uuid2 = generate_unique_index()

    # Mock component data
    test_box_1 = {
        "props": {
            "id": {"index": uuid1},
            "children": [
                html.H3("Test Component 1"),
                html.P(f"UUID: {uuid1[:8]}..."),
                html.P("🟢 Created with enable_box_edit_mode"),
            ],
        }
    }

    test_box_2 = {
        "props": {
            "id": {"index": uuid2},
            "children": [
                html.H3("Test Component 2"),
                html.P(f"UUID: {uuid2[:8]}..."),
                html.P("🔵 Created with enable_box_edit_mode"),
            ],
        }
    }

    # Test the enable_box_edit_mode function
    print("=== Testing enable_box_edit_mode with DashboardItem ===")
    print(f"UUIDs: {uuid1}, {uuid2}")

    try:
        child1 = enable_box_edit_mode(
            test_box_1,
            switch_state=True,
            dashboard_id="test-dashboard",
            component_data={"component_type": "figure"},
            TOKEN="test-token",
        )

        child2 = enable_box_edit_mode(
            test_box_2,
            switch_state=True,
            dashboard_id="test-dashboard",
            component_data={"component_type": "figure"},
            TOKEN="test-token",
        )

        print("✅ enable_box_edit_mode created DashboardItem successfully")
        print(f"Child 1 type: {type(child1)}")
        print(f"Child 2 type: {type(child2)}")

        # Verify DashboardItem has required properties
        child1_props = child1.to_plotly_json()
        print(
            f"Child 1 has required props: i={child1_props['props'].get('i')}, w={child1_props['props'].get('w')}, h={child1_props['props'].get('h')}"
        )

        # Test the UUID mapping function
        test_layouts = {
            "lg": [
                {"i": "0", "x": 0, "y": 0, "w": 6, "h": 4},
                {"i": "1", "x": 6, "y": 0, "w": 6, "h": 4},
            ]
        }

        uuid_map = {0: f"box-{uuid1}", 1: f"box-{uuid2}"}

        uuid_layouts = map_numerical_ids_to_uuids(test_layouts, uuid_map)

        print("✅ UUID mapping function works")
        print(f"Original layouts: {test_layouts}")
        print(f"UUID layouts: {uuid_layouts}")

        # Verify the mapping worked
        assert uuid_layouts["lg"][0]["i"] == f"box-{uuid1}"
        assert uuid_layouts["lg"][1]["i"] == f"box-{uuid2}"
        print("✅ UUID mapping preserved identities correctly")

        # Create the app layout
        app.layout = html.Div(
            [
                html.H1("🧪 Depictio Implementation Test"),
                html.Div(
                    [
                        html.H3("✅ Test Results:"),
                        html.Ul(
                            [
                                html.Li("enable_box_edit_mode creates DashboardItem ✅"),
                                html.Li("UUID mapping function works ✅"),
                                html.Li("UUID identities preserved ✅"),
                                html.Li("Integration with depictio codebase ✅"),
                            ]
                        ),
                    ],
                    style={"background": "#f0f8ff", "padding": "15px", "margin": "10px 0"},
                ),
                html.H3("🎯 Live Demo:"),
                dcc.Store(id="session-storage", storage_type="session"),
                html.Div(
                    id="layout-display",
                    style={"background": "#f5f5f5", "padding": "10px", "margin": "10px 0"},
                ),
                dash_draggable.ResponsiveGridLayout(
                    id="test-grid",
                    children=[child1, child2],
                    isDraggable=True,
                    isResizable=True,
                    save=False,
                    clearSavedLayout=False,
                ),
            ]
        )

        @app.callback(
            [Output("layout-display", "children"), Output("session-storage", "data")],
            Input("test-grid", "layouts"),
            prevent_initial_call=True,
        )
        def update_layout_display(layouts):
            if not layouts:
                return "No layout data", {}

            # Test the UUID mapping in a callback
            uuid_map = {0: f"box-{uuid1}", 1: f"box-{uuid2}"}
            uuid_layouts = map_numerical_ids_to_uuids(layouts, uuid_map)

            display = [
                html.H4("📊 Layout Analysis:"),
                html.P("❌ Raw Layout (numerical IDs):"),
                html.Pre(str(layouts["lg"]) if "lg" in layouts else "No lg layout"),
                html.P("✅ UUID Layout (preserved identities):"),
                html.Pre(str(uuid_layouts["lg"]) if "lg" in uuid_layouts else "No lg layout"),
                html.P("🎉 UUID mapping working in live callback!"),
            ]

            return display, {"layouts": uuid_layouts, "uuid_map": uuid_map}

        return app

    except Exception as e:
        print(f"❌ Error testing depictio implementation: {e}")
        import traceback

        traceback.print_exc()
        return None


if __name__ == "__main__":
    app = create_test_app()
    if app:
        print("🎉 Depictio implementation test successful!")
        print("🚀 Starting test server...")
        app.run(debug=True, port=8070)
    else:
        print("❌ Test failed")
