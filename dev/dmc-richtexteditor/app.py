"""
DMC RichTextEditor Prototype

This prototype tests different configurations of dash-mantine-components RichTextEditor
to find the correct working configuration.

Based on DMC documentation: https://www.dash-mantine-components.com/components/richtexteditor
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, State, callback, dcc, html

# Initialize Dash app
app = dash.Dash(__name__)

# Test if RichTextEditor exists in DMC
print(f"DMC RichTextEditor available: {hasattr(dmc, 'RichTextEditor')}")

if hasattr(dmc, "RichTextEditor"):
    print(f"RichTextEditor type: {type(dmc.RichTextEditor)}")

app.layout = dmc.MantineProvider(
    html.Div(
        [
            dmc.Title("DMC RichTextEditor Prototype", order=1),
            dmc.Space(h=20),
            # Test 1: Basic RichTextEditor
            dmc.Title("Test 1: Basic Configuration", order=3),
            html.Div(
                id="test1-container",
                children="Loading Test 1...",
                style={"border": "1px solid #ccc", "padding": "20px", "margin": "10px"},
            ),
            # Test 2: With initial content
            dmc.Title("Test 2: With Initial Content", order=3),
            html.Div(
                id="test2-container",
                children="Loading Test 2...",
                style={"border": "1px solid #ccc", "padding": "20px", "margin": "10px"},
            ),
            # Test 3: With toolbar configuration
            dmc.Title("Test 3: With Toolbar Config", order=3),
            html.Div(
                id="test3-container",
                children="Loading Test 3...",
                style={"border": "1px solid #ccc", "padding": "20px", "margin": "10px"},
            ),
            # Test 4: Alternative text component as fallback
            dmc.Title("Test 4: Fallback Textarea", order=3),
            dmc.Textarea(
                id="test4-textarea",
                placeholder="This is a fallback DMC Textarea",
                value="<p>Initial HTML content</p>",
                minRows=8,
                style={"margin": "10px"},
            ),
            # Output area
            dmc.Space(h=20),
            dmc.Title("Content Output:", order=3),
            html.Div(
                id="output", style={"border": "1px solid #eee", "padding": "20px", "margin": "10px"}
            ),
        ]
    )
)


@callback(
    Output("test1-container", "children"),
    Input("test1-container", "id"),  # Dummy input to trigger on load
)
def test1_basic(_):
    """Test 1: Most basic RichTextEditor configuration"""
    try:
        if hasattr(dmc, "RichTextEditor"):
            editor = dmc.RichTextEditor(
                id="editor1", placeholder="Basic RichTextEditor - start typing..."
            )
            return html.Div([html.P("Basic RichTextEditor:"), editor])
        else:
            return html.P("❌ RichTextEditor not found in DMC", style={"color": "red"})
    except Exception as e:
        return html.P(f"❌ Error: {str(e)}", style={"color": "red"})


@callback(
    Output("test2-container", "children"),
    Input("test2-container", "id"),  # Dummy input to trigger on load
)
def test2_with_content(_):
    """Test 2: RichTextEditor with initial content"""
    try:
        if hasattr(dmc, "RichTextEditor"):
            editor = dmc.RichTextEditor(
                id="editor2",
                value="<p>Initial <strong>HTML</strong> content with <em>formatting</em>!</p>",
                placeholder="RichTextEditor with initial content",
            )
            return html.Div([html.P("RichTextEditor with initial content:"), editor])
        else:
            return html.P("❌ RichTextEditor not found in DMC", style={"color": "red"})
    except Exception as e:
        return html.P(f"❌ Error: {str(e)}", style={"color": "red"})


@callback(
    Output("test3-container", "children"),
    Input("test3-container", "id"),  # Dummy input to trigger on load
)
def test3_with_toolbar(_):
    """Test 3: RichTextEditor with toolbar configuration"""
    try:
        if hasattr(dmc, "RichTextEditor"):
            editor = dmc.RichTextEditor(
                id="editor3",
                value="<p>RichTextEditor with custom toolbar</p>",
                placeholder="Custom toolbar configuration",
                controls=[
                    ["bold", "italic", "underline", "strike"],
                    ["h1", "h2", "h3"],
                    ["unorderedList", "orderedList"],
                    ["link", "blockquote"],
                ],
            )
            return html.Div([html.P("RichTextEditor with custom toolbar:"), editor])
        else:
            return html.P("❌ RichTextEditor not found in DMC", style={"color": "red"})
    except Exception as e:
        return html.P(f"❌ Error: {str(e)}", style={"color": "red"})


@callback(
    Output("output", "children"),
    [
        Input("editor1", "value")
        if hasattr(dmc, "RichTextEditor")
        else Input("test4-textarea", "value"),
        Input("editor2", "value")
        if hasattr(dmc, "RichTextEditor")
        else Input("test4-textarea", "value"),
        Input("editor3", "value")
        if hasattr(dmc, "RichTextEditor")
        else Input("test4-textarea", "value"),
        Input("test4-textarea", "value"),
    ],
    prevent_initial_call=True,
)
def update_output(editor1_value, editor2_value, editor3_value, textarea_value):
    """Show the content from all editors"""
    ctx = dash.callback_context
    if not ctx.triggered:
        return "No content yet..."

    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
    triggered_value = ctx.triggered[0]["value"]

    return html.Div(
        [
            html.P(f"Content from {triggered_id}:"),
            html.Pre(str(triggered_value), style={"background": "#f5f5f5", "padding": "10px"}),
            html.P("Rendered HTML:"),
            html.Div(
                triggered_value,
                style={"border": "1px dashed #ccc", "padding": "10px", "background": "white"},
            )
            if triggered_value
            else html.P("Empty content"),
        ]
    )


if __name__ == "__main__":
    app.run(debug=True, port=8051)
