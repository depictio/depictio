"""
Test different RichTextEditor configurations to avoid circular JSON structure error
"""

import dash
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State, callback

app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    [
        dmc.Title("Circular JSON Fix Tests", order=1),
        dmc.Space(h=20),
        # Test 1: Minimal configuration
        dmc.Title("Test 1: Minimal Configuration", order=3),
        html.Div(
            [
                dmc.RichTextEditor(
                    id="editor-minimal",
                    html="<p>Minimal configuration test</p>",
                    style={"minHeight": "150px"},
                )
            ],
            style={"border": "1px solid #ccc", "padding": "10px", "margin": "10px"},
        ),
        # Test 2: No extensions
        dmc.Title("Test 2: No Extensions", order=3),
        html.Div(
            [
                dmc.RichTextEditor(
                    id="editor-no-ext",
                    html="<p>No extensions test</p>",
                    style={"minHeight": "150px"},
                    toolbar={
                        "controlsGroups": [
                            ["Bold", "Italic", "Underline"],
                            ["H1", "H2", "H3"],
                        ]
                    },
                )
            ],
            style={"border": "1px solid #ccc", "padding": "10px", "margin": "10px"},
        ),
        # Test 3: Simple toolbar
        dmc.Title("Test 3: Simple Toolbar", order=3),
        html.Div(
            [
                dmc.RichTextEditor(
                    id="editor-simple",
                    html="<p>Simple toolbar test</p>",
                    style={"minHeight": "150px"},
                    toolbar={"controlsGroups": [["Bold", "Italic"]]},
                )
            ],
            style={"border": "1px solid #ccc", "padding": "10px", "margin": "10px"},
        ),
        # Output
        html.Div(id="output", style={"margin": "20px", "padding": "10px", "background": "#f5f5f5"}),
        # Store for testing serialization
        dcc.Store(id="test-store"),
    ]
)


@callback(
    [Output("output", "children"), Output("test-store", "data")],
    [
        Input("editor-minimal", "html"),
        Input("editor-no-ext", "html"),
        Input("editor-simple", "html"),
    ],
    prevent_initial_call=True,
)
def update_output(minimal_val, no_ext_val, simple_val):
    """Test if we can serialize the editor values without circular references"""
    ctx = dash.callback_context
    if not ctx.triggered:
        return "No updates", {}

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    trigger_value = ctx.triggered[0]["value"]

    try:
        # Try to serialize the value
        test_data = {
            "editor": trigger_id,
            "content": trigger_value,
            "length": len(str(trigger_value)) if trigger_value else 0,
        }

        return html.Div(
            [
                html.P(f"✅ Successfully serialized content from: {trigger_id}"),
                html.P(f"Content length: {test_data['length']} characters"),
                html.Pre(
                    str(trigger_value)[:200] + "..."
                    if len(str(trigger_value)) > 200
                    else str(trigger_value)
                ),
            ]
        ), test_data

    except Exception as e:
        return html.Div(
            [
                html.P(f"❌ Serialization error from {trigger_id}:", style={"color": "red"}),
                html.P(str(e), style={"color": "red"}),
            ]
        ), {"error": str(e)}


if __name__ == "__main__":
    app.run(debug=True, port=8052)
