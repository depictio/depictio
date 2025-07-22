"""
Test specifically for circular references in stored data structures.
This script tests what happens when we store various types of data in dcc.Store.
"""

import json

import dash
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate

app = dash.Dash(__name__, suppress_callback_exceptions=True)

app.layout = dmc.MantineProvider(
    [
        html.Div(
            [
                html.H1("Data Structure Circular Reference Test"),
                html.H3("Test: Storing Component IDs in Store"),
                dmc.Button("Test Component ID Storage", id="test-id-btn", n_clicks=0),
                html.Div(id="test-id-result"),
                dcc.Store(id="test-id-store", data={}),
                html.Hr(),
                html.H3("Test: Storing Callback Context"),
                dmc.Button("Test Callback Context Storage", id="test-context-btn", n_clicks=0),
                html.Div(id="test-context-result"),
                dcc.Store(id="test-context-store", data={}),
                html.Hr(),
                html.H3("Test: Storing MATCH Pattern Data"),
                dmc.Button(
                    "Test MATCH Pattern Storage",
                    id={"type": "test-match-btn", "index": 1},
                    n_clicks=0,
                ),
                html.Div(id={"type": "test-match-result", "index": 1}),
                dcc.Store(id={"type": "test-match-store", "index": 1}, data={}),
                html.Hr(),
                html.H3("Test: Deep Nested Object Storage"),
                dmc.Button("Test Deep Nested Storage", id="test-nested-btn", n_clicks=0),
                html.Div(id="test-nested-result"),
                dcc.Store(id="test-nested-store", data={}),
                html.Hr(),
                html.H3("Safe Alternative Pattern"),
                dmc.Button("Test Safe Pattern", id="test-safe-btn", n_clicks=0),
                html.Div(id="test-safe-result"),
                dcc.Store(id="test-safe-store", data={}),
            ]
        )
    ]
)


# Test 1: Storing Component IDs
@app.callback(
    [Output("test-id-result", "children"), Output("test-id-store", "data")],
    Input("test-id-btn", "n_clicks"),
    State("test-id-btn", "id"),
    prevent_initial_call=True,
)
def test_component_id_storage(n_clicks, button_id):
    """Test storing component ID objects - POTENTIAL CIRCULAR REFERENCE"""
    try:
        # This is what the original code does - storing component ID dict
        store_data = {
            "button_id": button_id,  # ← PROBLEMATIC: Component ID object
            "n_clicks": n_clicks,
            "metadata": {
                "stored_id": button_id,  # ← PROBLEMATIC: Nested component ID
                "timestamp": "now",
            },
        }

        # Try to serialize to detect circular reference
        json_str = json.dumps(store_data)
        return f"✅ ID Storage Test Passed. Data: {json_str[:100]}...", store_data

    except (TypeError, ValueError) as e:
        return f"❌ ID Storage Test Failed: {str(e)}", {}


# Test 2: Storing Callback Context
@app.callback(
    [Output("test-context-result", "children"), Output("test-context-store", "data")],
    Input("test-context-btn", "n_clicks"),
    prevent_initial_call=True,
)
def test_callback_context_storage(n_clicks):
    """Test storing callback context - POTENTIAL CIRCULAR REFERENCE"""
    try:
        # This accesses dash.callback_context which might contain DOM references
        ctx = callback_context

        store_data = {
            "triggered_id": ctx.triggered_id,  # ← PROBLEMATIC: May contain DOM refs
            "triggered": ctx.triggered,  # ← PROBLEMATIC: May contain DOM refs
            "n_clicks": n_clicks,
        }

        json_str = json.dumps(store_data)
        return f"✅ Context Storage Test Passed. Data: {json_str[:100]}...", store_data

    except (TypeError, ValueError) as e:
        return f"❌ Context Storage Test Failed: {str(e)}", {}


# Test 3: Storing MATCH Pattern Data
@app.callback(
    [
        Output({"type": "test-match-result", "index": MATCH}, "children"),
        Output({"type": "test-match-store", "index": MATCH}, "data"),
    ],
    Input({"type": "test-match-btn", "index": MATCH}, "n_clicks"),
    State({"type": "test-match-btn", "index": MATCH}, "id"),
    prevent_initial_call=True,
)
def test_match_pattern_storage(n_clicks, button_id):
    """Test storing MATCH pattern IDs - POTENTIAL CIRCULAR REFERENCE"""
    try:
        store_data = {
            "match_id": button_id,  # ← PROBLEMATIC: MATCH pattern ID object
            "n_clicks": n_clicks,
            "pattern_data": {
                "type": button_id["type"],  # Safe: string value
                "index": button_id["index"],  # Safe: primitive value
                "full_id": button_id,  # ← PROBLEMATIC: Full ID object
            },
        }

        json_str = json.dumps(store_data)
        return f"✅ MATCH Storage Test Passed. Data: {json_str[:100]}...", store_data

    except (TypeError, ValueError) as e:
        return f"❌ MATCH Storage Test Failed: {str(e)}", {}


# Test 4: Deep Nested Object Storage
@app.callback(
    [Output("test-nested-result", "children"), Output("test-nested-store", "data")],
    Input("test-nested-btn", "n_clicks"),
    State("test-nested-btn", "id"),
    prevent_initial_call=True,
)
def test_deep_nested_storage(n_clicks, button_id):
    """Test storing deeply nested objects that might create circular refs"""
    try:
        # Simulate the original text component metadata structure
        store_data = {
            "index": "test-index",
            "component_type": "text",
            "title": "Test Title",
            "content": "<p>Test content</p>",
            "parent_index": None,
            "show_toolbar": True,
            "show_title": True,
            # The problem: storing complex nested objects
            "config": {
                "editor_settings": {
                    "toolbar": {
                        "controlsGroups": [
                            ["Bold", "Italic", "Underline"],
                            ["H1", "H2", "H3"],
                            ["BulletList", "OrderedList"],
                        ]
                    }
                },
                # This could be the circular reference source:
                "metadata": {
                    "component_id": {"type": "text-editor", "index": "test-index"},  # ← PROBLEMATIC
                    "nested_config": None,  # Could point back to parent
                },
            },
        }

        # Make it circular to test detection
        store_data["config"]["metadata"]["nested_config"] = store_data["config"]  # ← CIRCULAR!

        json_str = json.dumps(store_data)
        return f"✅ Nested Storage Test Passed. Data: {json_str[:100]}...", store_data

    except (TypeError, ValueError) as e:
        return f"❌ Nested Storage Test Failed: {str(e)}", {}


# Test 5: Safe Alternative Pattern
@app.callback(
    [Output("test-safe-result", "children"), Output("test-safe-store", "data")],
    Input("test-safe-btn", "n_clicks"),
    State("test-safe-btn", "id"),
    prevent_initial_call=True,
)
def test_safe_storage_pattern(n_clicks, button_id):
    """Test safe storage pattern that avoids circular references"""
    try:
        # Safe pattern: only store primitive values and simple structures
        store_data = {
            # Safe: primitive values only
            "component_index": "test-index",
            "component_type": "text",
            "title": "Test Title",
            "content": "<p>Test content</p>",
            "show_toolbar": True,
            "show_title": True,
            # Safe: extract only primitive values from component IDs
            "button_type": button_id.get("type", "unknown")
            if isinstance(button_id, dict)
            else str(button_id),
            "n_clicks": n_clicks,
            # Safe: simple configuration without references
            "toolbar_config": ["Bold", "Italic", "Underline", "H1", "H2", "H3"],
            # Safe: timestamp instead of complex context
            "last_updated": n_clicks,  # Simple counter instead of complex context
        }

        json_str = json.dumps(store_data)
        return f"✅ Safe Storage Test Passed. Data: {json_str[:100]}...", store_data

    except (TypeError, ValueError) as e:
        return f"❌ Safe Storage Test Failed: {str(e)}", {}


if __name__ == "__main__":
    print("Testing data structures for circular references...")
    print("Click each button to test different storage patterns.")
    app.run(debug=True, port=8053)
