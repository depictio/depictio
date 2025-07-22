"""
Simple dash-quill text editor prototype to replace DMC RichTextEditor.
This should avoid the circular reference issues we encountered with DMC.
"""

import dash
import dash_mantine_components as dmc
import dash_quill as dq
from dash import Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate

app = dash.Dash(__name__, suppress_callback_exceptions=True)

# Test the same dashboard context that caused circular reference issues
app.layout = dmc.MantineProvider(
    [
        html.H1("Dash-Quill Text Editor Test"),
        # Control panel
        dmc.Card(
            [
                dmc.CardSection(
                    [
                        html.H3("Test Controls"),
                        dmc.Group(
                            [
                                dmc.Button(
                                    "Add Text Component",
                                    id="add-text-btn",
                                    color="green",
                                    n_clicks=0,
                                ),
                                dmc.Button("Clear All", id="clear-btn", color="red", n_clicks=0),
                            ],
                            gap="sm",
                        ),
                        html.Hr(),
                        # Configuration options
                        html.H4("Editor Configuration:"),
                        dmc.Group(
                            [
                                dmc.Switch(
                                    label="Show Toolbar", id="show-toolbar-switch", checked=True
                                ),
                                dmc.Switch(
                                    label="Enable Markdown",
                                    id="enable-markdown-switch",
                                    checked=True,
                                ),
                                dmc.Switch(label="Read Only", id="readonly-switch", checked=False),
                            ],
                            gap="md",
                        ),
                    ],
                    style={"padding": "1rem"},
                )
            ],
            withBorder=True,
            style={"marginBottom": "20px"},
        ),
        # Storage for components (avoiding circular references)
        dcc.Store(id="components-store", data={}),
        dcc.Store(id="layout-store", data={}),
        # Dashboard container
        html.Div(
            [
                html.H3("Dashboard Container"),
                html.Div(
                    id="dashboard-container",
                    children="Click 'Add Text Component' to add editors",
                    style={
                        "border": "2px dashed #ddd",
                        "padding": "20px",
                        "minHeight": "400px",
                        "marginTop": "10px",
                        "backgroundColor": "#f9f9f9",
                    },
                ),
            ]
        ),
        html.Hr(),
        # Debug info
        html.Div(id="debug-info", children="Debug info will appear here..."),
    ]
)


# Main callback to test dash-quill in dashboard context
@app.callback(
    [
        Output("dashboard-container", "children"),
        Output("components-store", "data"),
        Output("debug-info", "children"),
    ],
    [
        Input("add-text-btn", "n_clicks"),
        Input("clear-btn", "n_clicks"),
        Input({"type": "quill-editor", "index": dash.ALL}, "value"),
    ],
    [
        State("show-toolbar-switch", "checked"),
        State("enable-markdown-switch", "checked"),
        State("readonly-switch", "checked"),
        State("components-store", "data"),
    ],
    prevent_initial_call=True,
)
def manage_text_components(
    add_clicks,
    clear_clicks,
    editor_values,
    show_toolbar,
    enable_markdown,
    readonly,
    components_data,
):
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # Initialize components data
    if not components_data:
        components_data = {"components": {}, "counter": 0}

    try:
        if button_id == "clear-btn":
            return (
                "Click 'Add Text Component' to add editors",
                {"components": {}, "counter": 0},
                "All components cleared",
            )

        elif button_id == "add-text-btn":
            # Add new text component
            components_data["counter"] += 1
            component_id = f"text-{components_data['counter']}"

            # Store metadata (NO DOM references - this is key!)
            components_data["components"][component_id] = {
                "id": component_id,
                "title": f"Text Component {components_data['counter']}",
                "content": f"<p>This is text component #{components_data['counter']}</p>",
                "show_toolbar": show_toolbar,
                "enable_markdown": enable_markdown,
                "readonly": readonly,
            }

        elif "quill-editor" in button_id:
            # Update editor content in storage
            editor_ids = [
                ctx.triggered[i]["prop_id"].split(".")[0]
                for i in range(len(ctx.triggered))
                if "quill-editor" in ctx.triggered[i]["prop_id"]
            ]

            for i, editor_id in enumerate(editor_ids):
                # Extract component ID from the triggered editor
                import json

                try:
                    editor_dict = json.loads(editor_id.replace("'", '"'))
                    comp_id = editor_dict["index"]
                    if comp_id in components_data["components"]:
                        components_data["components"][comp_id]["content"] = editor_values[i]
                except:
                    pass

        # Build all components from data (avoiding circular references)
        dashboard_components = []

        for comp_id, comp_data in components_data["components"].items():
            # Create quill editor
            editor = dq.Quill(
                id={"type": "quill-editor", "index": comp_id},
                value=comp_data["content"],
                # readOnly=comp_data["readonly"],
                # theme="snow" if comp_data["show_toolbar"] else "bubble",
                modules={
                    "toolbar": [
                        ["bold", "italic", "underline", "strike"],
                        [{"header": [1, 2, 3, False]}],
                        [{"list": "ordered"}, {"list": "bullet"}],
                        ["code-block", "link"],
                        ["clean"],
                    ]
                    if comp_data["show_toolbar"]
                    else []
                },
                # style={
                #     "minHeight": "200px",
                #     "marginBottom": "10px"
                # }
            )

            # Create component wrapper
            component = html.Div(
                [
                    html.H5(comp_data["title"], style={"marginBottom": "10px"}),
                    editor,
                    dmc.Badge(f"ID: {comp_id}", color="blue", size="sm"),
                ],
                style={
                    "border": "1px solid #ccc",
                    "padding": "15px",
                    "marginBottom": "15px",
                    "backgroundColor": "#fff",
                    "borderRadius": "5px",
                },
            )

            dashboard_components.append(component)

        if not dashboard_components:
            dashboard_components = "Click 'Add Text Component' to add editors"

        # Debug info
        debug_info = html.Div(
            [
                html.P(f"Total components: {len(components_data['components'])}"),
                html.P(f"Last action: {button_id}"),
                html.P(
                    f"Configuration: Toolbar={show_toolbar}, Markdown={enable_markdown}, ReadOnly={readonly}"
                ),
                html.Details(
                    [
                        html.Summary("Component Data (click to expand)"),
                        html.Pre(str(components_data["components"])),
                    ]
                ),
            ]
        )

        return dashboard_components, components_data, debug_info

    except Exception as e:
        error_msg = f"Error: {str(e)}"
        return (
            html.Div(error_msg, style={"color": "red"}),
            components_data,
            html.Div(error_msg, style={"color": "red"}),
        )


if __name__ == "__main__":
    print("Testing dash-quill as DMC RichTextEditor replacement...")
    print("This should avoid circular reference issues.")
    print("Running on http://127.0.0.1:8058/")
    app.run(debug=True, port=8058)
