"""
Debug script to identify circular reference issues with DMC.RichTextEditor.
This recreates the text_component callbacks step by step to isolate the problem.
"""

import dash
import dash_mantine_components as dmc
from dash import dcc, html, Input, Output, State, MATCH, callback_context
from dash.exceptions import PreventUpdate

# Initialize the Dash app
app = dash.Dash(__name__)

# Simple layout with a RichTextEditor to test
app.layout = html.Div(
    [
        html.H1("DMC RichTextEditor Circular Reference Debug"),
        # Test 1: Basic RichTextEditor - minimal setup
        html.H3("Test 1: Basic RichTextEditor"),
        dmc.RichTextEditor(
            id="basic-editor", html="<p>Basic editor content</p>", style={"minHeight": "200px"}
        ),
        # Test 2: RichTextEditor with Store - potential circular ref source
        html.H3("Test 2: RichTextEditor with Store"),
        dmc.RichTextEditor(
            id="editor-with-store",
            html="<p>Editor with store content</p>",
            style={"minHeight": "200px"},
        ),
        dcc.Store(id="editor-store", data={"content": "initial"}),
        # Test 3: Match pattern IDs - like original implementation
        html.H3("Test 3: MATCH Pattern IDs"),
        dmc.RichTextEditor(
            id={"type": "text-editor", "index": "test-1"},
            html="<p>MATCH pattern editor</p>",
            style={"minHeight": "200px"},
        ),
        dcc.Store(
            id={"type": "stored-metadata-component", "index": "test-1"},
            data={
                "index": "test-1",
                "component_type": "text",
                "content": "<p>MATCH pattern editor</p>",
            },
        ),
        # Test 4: Complex callback with multiple states - original pattern
        html.H3("Test 4: Complex Configuration"),
        html.Div(
            [
                dmc.TextInput(
                    label="Title",
                    id={"type": "input-text-title", "index": "test-2"},
                    value="Test Title",
                ),
                dmc.Switch(
                    label="Show Title",
                    id={"type": "switch-text-show-title", "index": "test-2"},
                    checked=True,
                ),
                dmc.Switch(
                    label="Show Toolbar",
                    id={"type": "switch-text-show-toolbar", "index": "test-2"},
                    checked=True,
                ),
                dmc.Button(
                    "Apply Settings",
                    id={"type": "btn-apply-text-settings", "index": "test-2"},
                    n_clicks=0,
                ),
            ]
        ),
        html.Div(
            id={"type": "component-container", "index": "test-2"},
            children="Click Apply to load editor",
            style={
                "border": "1px dashed #ddd",
                "padding": "20px",
                "marginTop": "10px",
                "minHeight": "200px",
            },
        ),
        # Debug output
        html.Div(
            id="debug-output",
            style={"marginTop": "20px", "padding": "10px", "backgroundColor": "#f0f0f0"},
        ),
    ]
)


# Callback 1: Basic editor change - should be safe
@app.callback(
    Output("debug-output", "children"), Input("basic-editor", "html"), prevent_initial_call=True
)
def debug_basic_editor(html_content):
    return f"Basic editor content: {html_content[:50]}..."


# Callback 2: Editor with store interaction - potential issue
@app.callback(
    Output("editor-store", "data"), Input("editor-with-store", "html"), prevent_initial_call=True
)
def update_editor_store(html_content):
    # This might cause circular reference if we store complex objects
    return {"content": html_content, "timestamp": dash.callback_context.triggered_id}


# Callback 3: Complex callback similar to original - main suspect
@app.callback(
    Output({"type": "component-container", "index": MATCH}, "children"),
    Input({"type": "btn-apply-text-settings", "index": MATCH}, "n_clicks"),
    State({"type": "input-text-title", "index": MATCH}, "value"),
    State({"type": "switch-text-show-title", "index": MATCH}, "checked"),
    State({"type": "switch-text-show-toolbar", "index": MATCH}, "checked"),
    State({"type": "btn-apply-text-settings", "index": MATCH}, "id"),
    prevent_initial_call=True,
)
def update_text_component_debug(n_clicks, title, show_title, show_toolbar, btn_id):
    if not n_clicks:
        raise PreventUpdate

    # Recreate the problematic component structure
    index = btn_id["index"]

    # This is the suspected problematic part - complex nested structure
    store_component = dcc.Store(
        id={"type": "stored-metadata-component", "index": f"{index}-dynamic"},
        data={
            "index": index,
            "component_type": "text",
            "title": title,
            "content": "<p>Dynamic content</p>",
            "show_toolbar": show_toolbar,
            "show_title": show_title,
            # Potential circular reference: storing the button ID
            "trigger_id": btn_id,  # ← This might be the problem!
        },
    )

    # Create RichTextEditor
    editor = dmc.RichTextEditor(
        id={"type": "text-editor", "index": f"{index}-dynamic"},
        html="<p>Dynamic editor content</p>",
        style={"minHeight": "200px"},
        toolbar={"controlsGroups": [["Bold", "Italic", "Underline"], ["H1", "H2", "H3"]]}
        if show_toolbar
        else None,
    )

    return html.Div(
        [
            html.H5(title) if show_title else None,
            editor,
            store_component,  # ← Storing complex nested data might cause circular ref
        ]
    )


if __name__ == "__main__":
    app.run_server(debug=True, port=8051)
