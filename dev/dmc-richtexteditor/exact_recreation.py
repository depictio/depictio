"""
Exact recreation of the text_component pattern to identify the circular reference.
This recreates the exact structure that's causing the issue.
"""

import dash
import dash_mantine_components as dmc
from dash import dcc, html, Input, Output, State, MATCH
from dash.exceptions import PreventUpdate

app = dash.Dash(__name__, suppress_callback_exceptions=True)

app.layout = dmc.MantineProvider(
    [
        html.Div(
            [
                html.H1("Exact Text Component Recreation"),
                # Controls (from design_text function)
                dmc.TextInput(
                    label="Component Title",
                    id={"type": "input-text-title", "index": "test"},
                    value="Text Component",
                ),
                dmc.Switch(
                    label="Show Title",
                    id={"type": "switch-text-show-title", "index": "test"},
                    checked=True,
                ),
                dmc.Switch(
                    label="Show Toolbar",
                    id={"type": "switch-text-show-toolbar", "index": "test"},
                    checked=True,
                ),
                dmc.Button(
                    "Apply Settings",
                    id={"type": "btn-apply-text-settings", "index": "test"},
                    n_clicks=0,
                ),
                # Container for the component
                html.Div(
                    "Click Apply Settings to load component",
                    id={"type": "component-container", "index": "test"},
                    style={
                        "border": "1px dashed #ddd",
                        "padding": "20px",
                        "marginTop": "20px",
                        "minHeight": "300px",
                    },
                ),
                # Local store (as in original)
                dcc.Store(id="local-store", data={"some": "existing_data"}),
                html.Hr(),
                html.Div(
                    id="debug-info",
                    style={"marginTop": "20px", "padding": "10px", "backgroundColor": "#f0f0f0"},
                ),
            ]
        )
    ]
)


# Exact recreation of the problematic callback
@app.callback(
    Output({"type": "component-container", "index": MATCH}, "children"),
    [
        Input({"type": "btn-apply-text-settings", "index": MATCH}, "n_clicks"),
        State({"type": "input-text-title", "index": MATCH}, "value"),
        State({"type": "switch-text-show-title", "index": MATCH}, "checked"),
        State({"type": "switch-text-show-toolbar", "index": MATCH}, "checked"),
        State({"type": "btn-apply-text-settings", "index": MATCH}, "id"),
        State("local-store", "data"),
    ],
    prevent_initial_call=True,
)
def update_text_component_exact(n_clicks, title, show_title, show_toolbar, id, data):
    """
    Exact recreation of update_text_component from frontend.py
    """
    if not data or not n_clicks or n_clicks == 0:
        # Return the frame as in original
        return build_text_frame_exact(index=id["index"])

    try:
        # Build the text component with configuration options (exact as original)
        text_kwargs = {
            "index": id["index"],
            "title": title if show_title else None,
            "content": "<p>Start typing your content here...</p>",
            "stepper": True,
            "show_toolbar": show_toolbar,
            "show_title": show_title,
        }
        new_text = build_text_exact(**text_kwargs)
        return new_text
    except Exception as e:
        # Fallback as in original
        return html.Div(
            [
                html.H5("Text Component (Fallback Mode)" if show_title else None),
                dcc.Textarea(
                    id={"type": "text-editor-fallback", "index": id["index"]},
                    placeholder="Enter your text content here...",
                    style={"width": "100%", "minHeight": "200px"},
                    value="<p>Start typing your content here...</p>",
                ),
                html.Div(f"Error: {str(e)}", style={"color": "red", "fontSize": "12px"}),
            ]
        )


def build_text_frame_exact(index, children=None):
    """Exact recreation of build_text_frame from utils.py"""
    if not children:
        return html.Div(
            "Configure your text component using the edit menu",
            style={
                "textAlign": "center",
                "color": "#999",
                "fontSize": "14px",
                "fontStyle": "italic",
                "padding": "20px",
                "minHeight": "150px",
                "border": "1px solid #ddd",
                "borderRadius": "4px",
            },
        )
    else:
        return html.Div(
            children=children,
            style={
                "width": "100%",
                "height": "100%",
                "padding": "5px",
                "border": "1px solid #ddd",
                "borderRadius": "4px",
                "backgroundColor": "#ffffff",
            },
        )


def build_text_exact(**kwargs):
    """
    Exact recreation of build_text from utils.py - THIS IS WHERE THE CIRCULAR REFERENCE OCCURS
    """
    # Extract parameters exactly as in original
    index = kwargs.get("index")
    title = kwargs.get("title", "Text Component")
    content = kwargs.get("content", "")
    stepper = kwargs.get("stepper", False)
    show_toolbar = kwargs.get("show_toolbar", True)
    show_title = kwargs.get("show_title", True)

    if stepper:
        index = f"{index}-tmp"

    # THIS IS THE PROBLEMATIC PART - Create metadata store component
    store_component = dcc.Store(
        id={
            "type": "stored-metadata-component",
            "index": str(index),
        },
        data={
            "index": str(str(index).replace("-tmp", "") if stepper else index),
            "component_type": "text",
            "title": title,
            "content": content,
            "parent_index": None,  # This could be problematic if it contains complex objects
            "show_toolbar": show_toolbar,
            "show_title": show_title,
            # SUSPECTED CIRCULAR REFERENCE SOURCE:
            # The original code might be storing complex objects or component references here
        },
    )

    # Clean content as in original
    clean_content = str(content) if content else "<p>Start typing your content here...</p>"

    # Create the RichTextEditor with exact configuration
    text_editor = dmc.RichTextEditor(
        id={
            "type": "text-editor",
            "index": str(index),
        },
        html=clean_content,
        style={
            "minHeight": "200px",
            "width": "100%",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "6px",
        },
        # Toolbar configuration as in original
        toolbar={
            "controlsGroups": [
                ["Bold", "Italic", "Underline"],
                ["H1", "H2", "H3"],
                ["BulletList", "OrderedList"],
            ]
        }
        if show_toolbar
        else None,
    )

    # Create the main content exactly as original
    text_content = html.Div(
        [
            html.H5(
                title,
                style={
                    "marginBottom": "10px",
                    "color": "var(--app-text-color, #000000)",
                    "fontWeight": "bold",
                },
            )
            if title and show_title
            else None,
            None,  # toolbar_info in original
            text_editor,
            store_component,  # ← THE CIRCULAR REFERENCE IS LIKELY HERE
        ]
    )

    # Build the text component with frame as in original
    text_component = build_text_frame_exact(index=index, children=text_content)

    # For stepper mode with loading (exact as original)
    if stepper:
        return html.Div(
            dcc.Loading(
                children=text_component,
                type="dot",
                color="#E6779F",
                delay_show=100,
                delay_hide=800,
            ),
            id={"index": index},  # ← ANOTHER POTENTIAL CIRCULAR REFERENCE SOURCE
        )
    else:
        return text_component


# Debug callback to show what's happening
@app.callback(
    Output("debug-info", "children"),
    Input({"type": "btn-apply-text-settings", "index": MATCH}, "n_clicks"),
    prevent_initial_call=True,
)
def debug_callback(n_clicks):
    return f"Button clicked {n_clicks} times. Check browser console for circular reference errors."


if __name__ == "__main__":
    print("Running exact text component recreation...")
    print("This should reproduce the circular reference error.")
    print("Check browser console after clicking 'Apply Settings'")
    app.run_server(debug=True, port=8054)
