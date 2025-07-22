"""
Isolate the RichTextEditor circular reference issue.
Test different RichTextEditor configurations to find the problematic pattern.
"""

import dash
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate

app = dash.Dash(__name__, suppress_callback_exceptions=True)

app.layout = dmc.MantineProvider(
    [
        html.H1("RichTextEditor Circular Reference Isolation"),
        html.Hr(),
        html.H3("Test 1: Static RichTextEditor (No Callbacks)"),
        dmc.RichTextEditor(
            id="static-editor",
            html="<p>Static content - no callbacks</p>",
            style={"minHeight": "200px", "border": "1px solid #ddd"},
        ),
        html.Hr(),
        html.H3("Test 2: RichTextEditor with Callback"),
        dmc.RichTextEditor(
            id="callback-editor",
            html="<p>Editor with callback</p>",
            style={"minHeight": "200px", "border": "1px solid #ddd"},
        ),
        html.Div(id="callback-output"),
        html.Hr(),
        html.H3("Test 3: Dynamically Created RichTextEditor"),
        dmc.Button("Create Dynamic Editor", id="create-btn", n_clicks=0),
        html.Div(id="dynamic-container"),
        html.Hr(),
        html.H3("Test 4: RichTextEditor with MATCH Pattern"),
        dmc.Button("Create MATCH Editor", id="create-match-btn", n_clicks=0),
        html.Div(id="match-container"),
        html.Hr(),
        html.H3("Test 5: RichTextEditor with Complex HTML Content"),
        dmc.Button("Load Complex Content", id="complex-btn", n_clicks=0),
        html.Div(id="complex-container"),
        html.Hr(),
        html.H3("Test 6: Multiple RichTextEditors"),
        dmc.Button("Create Multiple Editors", id="multiple-btn", n_clicks=0),
        html.Div(id="multiple-container"),
        html.Hr(),
        html.Div(id="debug-output", style={"padding": "10px", "backgroundColor": "#f0f0f0"}),
    ]
)


# Test 2: Simple callback
@app.callback(
    Output("callback-output", "children"),
    Input("callback-editor", "html"),
    prevent_initial_call=True,
)
def update_callback_output(html_content):
    return f"Content length: {len(str(html_content))}"


# Test 3: Dynamic creation
@app.callback(
    Output("dynamic-container", "children"),
    Input("create-btn", "n_clicks"),
    prevent_initial_call=True,
)
def create_dynamic_editor(n_clicks):
    if not n_clicks:
        raise PreventUpdate

    try:
        editor = dmc.RichTextEditor(
            id=f"dynamic-editor-{n_clicks}",
            html=f"<p>Dynamic editor #{n_clicks}</p>",
            style={"minHeight": "200px", "border": "1px solid #ddd"},
        )
        return editor
    except Exception as e:
        return f"Error creating dynamic editor: {str(e)}"


# Test 4: MATCH pattern
@app.callback(
    Output("match-container", "children"),
    Input("create-match-btn", "n_clicks"),
    prevent_initial_call=True,
)
def create_match_editor(n_clicks):
    if not n_clicks:
        raise PreventUpdate

    try:
        editor = dmc.RichTextEditor(
            id={"type": "match-editor", "index": n_clicks},
            html=f"<p>MATCH pattern editor #{n_clicks}</p>",
            style={"minHeight": "200px", "border": "1px solid #ddd"},
        )
        return editor
    except Exception as e:
        return f"Error creating MATCH editor: {str(e)}"


# Test 5: Complex HTML content
@app.callback(
    Output("complex-container", "children"),
    Input("complex-btn", "n_clicks"),
    prevent_initial_call=True,
)
def create_complex_editor(n_clicks):
    if not n_clicks:
        raise PreventUpdate

    # Complex HTML that might cause issues
    complex_html = """
    <div>
        <h1>Complex Content</h1>
        <p>This is a paragraph with <strong>bold</strong> and <em>italic</em> text.</p>
        <ul>
            <li>List item 1</li>
            <li>List item 2 with <a href="#">link</a></li>
        </ul>
        <blockquote>This is a quote</blockquote>
    </div>
    """

    try:
        editor = dmc.RichTextEditor(
            id=f"complex-editor-{n_clicks}",
            html=complex_html,
            style={"minHeight": "200px", "border": "1px solid #ddd"},
            toolbar={
                "controlsGroups": [
                    ["Bold", "Italic", "Underline"],
                    ["H1", "H2", "H3"],
                    ["BulletList", "OrderedList"],
                    ["Link", "Blockquote"],
                ]
            },
        )
        return editor
    except Exception as e:
        return f"Error creating complex editor: {str(e)}"


# Test 6: Multiple editors
@app.callback(
    Output("multiple-container", "children"),
    Input("multiple-btn", "n_clicks"),
    prevent_initial_call=True,
)
def create_multiple_editors(n_clicks):
    if not n_clicks:
        raise PreventUpdate

    try:
        editors = []
        for i in range(3):
            editor = dmc.RichTextEditor(
                id=f"multi-editor-{n_clicks}-{i}",
                html=f"<p>Multi editor #{n_clicks}-{i}</p>",
                style={"minHeight": "150px", "border": "1px solid #ddd", "marginBottom": "10px"},
            )
            editors.append(editor)

        return html.Div(editors)
    except Exception as e:
        return f"Error creating multiple editors: {str(e)}"


# Debug callback to track which operations cause issues
@app.callback(
    Output("debug-output", "children"),
    [
        Input("create-btn", "n_clicks"),
        Input("create-match-btn", "n_clicks"),
        Input("complex-btn", "n_clicks"),
        Input("multiple-btn", "n_clicks"),
    ],
    prevent_initial_call=True,
)
def debug_operations(create_n, match_n, complex_n, multiple_n):
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    trigger_id = ctx.triggered_id
    return f"Last operation: {trigger_id} - Check browser console for any circular reference errors"


if __name__ == "__main__":
    print("Testing RichTextEditor for circular reference issues...")
    print("Click each button and monitor browser console for errors.")
    print("The circular reference might occur during dynamic creation or content updates.")
    app.run(debug=True, port=8055)
