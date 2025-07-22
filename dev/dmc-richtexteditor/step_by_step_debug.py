"""
Step-by-step debug to identify the exact source of circular reference.
Run each test individually by uncommenting the relevant section.
"""

import dash
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate

app = dash.Dash(__name__, suppress_callback_exceptions=True)


# =============================================================================
# TEST 1: Pure RichTextEditor (Baseline)
# =============================================================================
def test_1_baseline():
    return dmc.MantineProvider(
        [
            html.H2("TEST 1: Baseline - Pure RichTextEditor"),
            dmc.RichTextEditor(
                id="test-1-editor",
                html="<p>Pure editor - no callbacks</p>",
                style={"minHeight": "200px"},
            ),
            html.Div(id="test-1-output"),
        ]
    )


# =============================================================================
# TEST 2: RichTextEditor + Simple Callback
# =============================================================================
def test_2_simple_callback():
    return dmc.MantineProvider(
        [
            html.H2("TEST 2: RichTextEditor + Simple Callback"),
            dmc.RichTextEditor(
                id="test-2-editor",
                html="<p>Editor with simple callback</p>",
                style={"minHeight": "200px"},
            ),
            html.Div(id="test-2-output"),
        ]
    )


@app.callback(
    Output("test-2-output", "children"), Input("test-2-editor", "html"), prevent_initial_call=True
)
def test_2_callback(html_content):
    return f"Content length: {len(str(html_content))}"


# =============================================================================
# TEST 3: RichTextEditor + dcc.Store
# =============================================================================
def test_3_with_store():
    return dmc.MantineProvider(
        [
            html.H2("TEST 3: RichTextEditor + dcc.Store"),
            dmc.RichTextEditor(
                id="test-3-editor", html="<p>Editor with store</p>", style={"minHeight": "200px"}
            ),
            dcc.Store(id="test-3-store", data={"initial": "value"}),
            html.Div(id="test-3-output"),
        ]
    )


@app.callback(
    Output("test-3-store", "data"), Input("test-3-editor", "html"), prevent_initial_call=True
)
def test_3_callback(html_content):
    # Simple data - should be safe
    return {"content": str(html_content), "length": len(str(html_content))}


# =============================================================================
# TEST 4: MATCH Pattern IDs
# =============================================================================
def test_4_match_pattern():
    return dmc.MantineProvider(
        [
            html.H2("TEST 4: MATCH Pattern IDs"),
            dmc.RichTextEditor(
                id={"type": "test-4-editor", "index": "1"},
                html="<p>Editor with MATCH pattern</p>",
                style={"minHeight": "200px"},
            ),
            dcc.Store(
                id={"type": "test-4-store", "index": "1"}, data={"type": "test", "index": "1"}
            ),
            html.Div(id="test-4-output"),
        ]
    )


@app.callback(
    Output({"type": "test-4-store", "index": MATCH}, "data"),
    Input({"type": "test-4-editor", "index": MATCH}, "html"),
    State({"type": "test-4-editor", "index": MATCH}, "id"),
    prevent_initial_call=True,
)
def test_4_callback(html_content, editor_id):
    # Storing the editor_id might cause circular reference
    return {
        "content": str(html_content),
        "editor_id": editor_id,  # ← Potential problem: storing component ID
        "length": len(str(html_content)),
    }


# =============================================================================
# TEST 5: Callback Context Storage (Most Likely Culprit)
# =============================================================================
def test_5_callback_context():
    return dmc.MantineProvider(
        [
            html.H2("TEST 5: Callback Context Storage"),
            dmc.Button("Trigger Update", id="test-5-button", n_clicks=0),
            html.Div(id="test-5-container"),
            dcc.Store(id="test-5-store", data={}),
        ]
    )


@app.callback(
    Output("test-5-container", "children"),
    Output("test-5-store", "data"),
    Input("test-5-button", "n_clicks"),
    State("test-5-button", "id"),
    prevent_initial_call=True,
)
def test_5_callback(n_clicks, button_id):
    if not n_clicks:
        raise PreventUpdate

    # Create RichTextEditor dynamically
    editor = dmc.RichTextEditor(
        id={"type": "test-5-dynamic-editor", "index": n_clicks},
        html=f"<p>Dynamic editor #{n_clicks}</p>",
        style={"minHeight": "200px"},
    )

    # Store component ID and callback context - LIKELY CIRCULAR REFERENCE SOURCE
    store_data = {
        "button_id": button_id,  # ← Component ID storage
        "n_clicks": n_clicks,
        "editor_config": {
            "id": {"type": "test-5-dynamic-editor", "index": n_clicks},  # ← Another ID storage
            "html": f"<p>Dynamic editor #{n_clicks}</p>",
        },
    }

    return editor, store_data


# =============================================================================
# TEST 6: Complex Nested Structure (Original Pattern)
# =============================================================================
def test_6_original_pattern():
    return dmc.MantineProvider(
        [
            html.H2("TEST 6: Original Pattern Recreation"),
            dmc.TextInput(
                id={"type": "test-6-title", "index": "1"}, label="Title", value="Test Title"
            ),
            dmc.Button("Apply Settings", id={"type": "test-6-apply", "index": "1"}, n_clicks=0),
            html.Div(id={"type": "test-6-container", "index": "1"}),
            dcc.Store(id="test-6-local-store", data={"some": "data"}),
        ]
    )


@app.callback(
    Output({"type": "test-6-container", "index": MATCH}, "children"),
    Input({"type": "test-6-apply", "index": MATCH}, "n_clicks"),
    State({"type": "test-6-title", "index": MATCH}, "value"),
    State({"type": "test-6-apply", "index": MATCH}, "id"),
    State("test-6-local-store", "data"),  # ← External store state
    prevent_initial_call=True,
)
def test_6_callback(n_clicks, title, button_id, store_data):
    if not n_clicks:
        raise PreventUpdate

    index = button_id["index"]

    # Recreate the exact problematic structure from original
    metadata_store = dcc.Store(
        id={"type": "test-6-metadata", "index": f"{index}-tmp"},
        data={
            "index": str(index),
            "component_type": "text",
            "title": title,
            "content": "<p>Start typing...</p>",
            "parent_index": None,
            "show_toolbar": True,
            "show_title": True,
            # PROBLEMATIC: Storing complex objects with potential DOM references
            "trigger_context": button_id,  # ← Component ID storage
            "store_data": store_data,  # ← External store data
        },
    )

    editor = dmc.RichTextEditor(
        id={"type": "test-6-editor", "index": f"{index}-tmp"},
        html="<p>Start typing your content here...</p>",
        style={
            "minHeight": "200px",
            "width": "100%",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "6px",
        },
        toolbar={
            "controlsGroups": [
                ["Bold", "Italic", "Underline"],
                ["H1", "H2", "H3"],
                ["BulletList", "OrderedList"],
            ]
        },
    )

    return html.Div(
        [
            html.H5(title) if title else None,
            editor,
            metadata_store,  # ← This combination likely causes the circular reference
        ]
    )


# =============================================================================
# APP LAYOUT - Choose which test to run
# =============================================================================

# Uncomment ONE test at a time to isolate the issue:

# app.layout = test_1_baseline()        # Start here - should work fine
# app.layout = test_2_simple_callback() # Simple callback - should work
# app.layout = test_3_with_store()      # With store - might show issues
# app.layout = test_4_match_pattern()   # MATCH patterns - likely problematic
# app.layout = test_5_callback_context() # Dynamic creation - very likely problematic
app.layout = test_6_original_pattern()  # Full original pattern - most likely to fail

if __name__ == "__main__":
    print("Running step-by-step debug...")
    print("Uncomment different tests in the layout section to isolate the circular reference.")
    app.run(debug=True, port=8052)
