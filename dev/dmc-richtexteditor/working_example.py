"""
DMC RichTextEditor Working Example
Based on the user's working configuration
"""

import dash
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State, callback

app = dash.Dash(__name__)

# Content from the working example
content = """<h2 style="text-align: center;">Welcome to Mantine rich text editor</h2><p><code>RichTextEditor</code> component focuses on usability and is designed to be as simple as possible to bring a familiar editing experience to regular users. <code>RichTextEditor</code> is based on <a href="https://tiptap.dev/" rel="noopener noreferrer" target="_blank">Tiptap.dev</a> and supports all of its features:</p><ul><li>General text formatting: <strong>bold</strong>, <em>italic</em>, <u>underline</u>, <s>strike-through</s> </li><li>Headings (h1-h6)</li><li>Sub and super scripts (<sup>&lt;sup /&gt;</sup> and <sub>&lt;sub /&gt;</sub> tags)</li><li>Ordered and bullet lists</li><li>Text align&nbsp;</li><li>And all <a href="https://tiptap.dev/extensions" target="_blank" rel="noopener noreferrer">other extensions</a></li></ul>"""

app.layout = dmc.MantineProvider(
    [
        dmc.Title("DMC RichTextEditor Working Example", order=1),
        dmc.Space(h=20),
        # Working RichTextEditor configuration
        html.Div(
            [
                dmc.Title("Working Configuration", order=3),
                dmc.RichTextEditor(
                    id="working-editor",
                    html=content,
                    toolbar={
                        "sticky": True,
                        "controlsGroups": [
                            [
                                "Bold",
                                "Italic",
                                "Underline",
                                "Strikethrough",
                                "ClearFormatting",
                                "Highlight",
                                "Code",
                            ],
                            ["H1", "H2", "H3", "H4"],
                            [
                                "Blockquote",
                                "Hr",
                                "BulletList",
                                "OrderedList",
                                "Subscript",
                                "Superscript",
                            ],
                            ["Link", "Unlink"],
                            ["AlignLeft", "AlignCenter", "AlignJustify", "AlignRight"],
                            ["Undo", "Redo"],
                        ],
                    },
                ),
            ],
            style={"border": "1px solid #ccc", "padding": "20px", "margin": "20px"},
        ),
        # Test with minimal configuration
        html.Div(
            [
                dmc.Title("Minimal Configuration", order=3),
                dmc.RichTextEditor(
                    id="minimal-editor",
                    html="<p>Simple test content</p>",
                    toolbar={
                        "controlsGroups": [
                            ["Bold", "Italic", "Underline"],
                            ["H1", "H2", "H3"],
                        ],
                    },
                ),
            ],
            style={"border": "1px solid #ccc", "padding": "20px", "margin": "20px"},
        ),
        # Test with no toolbar
        html.Div(
            [
                dmc.Title("No Toolbar Configuration", order=3),
                dmc.RichTextEditor(
                    id="no-toolbar-editor",
                    html="<p>Content without toolbar</p>",
                ),
            ],
            style={"border": "1px solid #ccc", "padding": "20px", "margin": "20px"},
        ),
        # Output area
        html.Div(id="output", style={"margin": "20px", "padding": "10px", "background": "#f5f5f5"}),
    ]
)


@callback(
    Output("output", "children"),
    [
        Input("working-editor", "html"),
        Input("minimal-editor", "html"),
        Input("no-toolbar-editor", "html"),
    ],
    prevent_initial_call=True,
)
def update_output(working_val, minimal_val, no_toolbar_val):
    """Test callback to see if values can be serialized without circular references"""
    ctx = dash.callback_context
    if not ctx.triggered:
        return "No updates"

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    trigger_value = ctx.triggered[0]["value"]

    try:
        # Test serialization
        import json

        json.dumps({"value": trigger_value})  # This will fail if there are circular references

        return html.Div(
            [
                html.P(f"✅ Content from {trigger_id} successfully serialized"),
                html.P(f"Length: {len(str(trigger_value))} characters"),
                html.Details(
                    [
                        html.Summary("Content (click to expand)"),
                        html.Pre(
                            str(trigger_value)[:500] + "..."
                            if len(str(trigger_value)) > 500
                            else str(trigger_value)
                        ),
                    ]
                ),
            ]
        )

    except Exception as e:
        return html.Div(
            [
                html.P(f"❌ Serialization error from {trigger_id}:", style={"color": "red"}),
                html.P(str(e), style={"color": "red"}),
            ]
        )


if __name__ == "__main__":
    print("Testing DMC RichTextEditor...")
    print(f"DMC version: {dmc.__version__ if hasattr(dmc, '__version__') else 'unknown'}")
    print(f"RichTextEditor available: {hasattr(dmc, 'RichTextEditor')}")

    app.run(debug=True, port=8054)
