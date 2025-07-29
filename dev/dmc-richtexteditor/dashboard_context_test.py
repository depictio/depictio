"""
Test RichTextEditor in the context of a dashboard with draggable components.
This should recreate the exact conditions that cause the circular reference.
"""

import dash
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate

app = dash.Dash(__name__, suppress_callback_exceptions=True)

# Simulate your dashboard layout with multiple components and stores
app.layout = dmc.MantineProvider(
    [
        html.H1("Dashboard Context Circular Reference Test"),
        # Simulate multiple stores like in your dashboard
        dcc.Store(id="local-store", data={"dashboard_config": "test"}),
        dcc.Store(id="layout-store", data={}),
        dcc.Store(id="component-store", data={}),
        # Simulate draggable container
        html.Div(
            [
                html.H3("Draggable Container (Simulated)"),
                # Test adding text component to dashboard context
                dmc.Button("Add Text Component to Dashboard", id="add-text-btn", n_clicks=0),
                html.Div(
                    id="dashboard-container",
                    children="Click button to add text component",
                    style={
                        "border": "2px dashed #ddd",
                        "padding": "20px",
                        "minHeight": "400px",
                        "marginTop": "20px",
                    },
                ),
            ]
        ),
        html.Hr(),
        html.Div(id="debug-info"),
    ]
)


# This callback simulates your exact pattern - adding a text component to dashboard
@app.callback(
    [
        Output("dashboard-container", "children"),
        Output("layout-store", "data"),
        Output("component-store", "data"),
    ],
    Input("add-text-btn", "n_clicks"),
    [
        State("local-store", "data"),
        State("layout-store", "data"),
        State("component-store", "data"),
        # State("dashboard-container", "children")  # ← CIRCULAR REFERENCE SOURCE - REMOVED!
    ],
    prevent_initial_call=True,
)
def add_text_component_to_dashboard(n_clicks, local_data, layout_data, component_data):
    if not n_clicks:
        raise PreventUpdate

    try:
        # Create text component with metadata store (your exact pattern)
        component_id = f"text-{n_clicks}"

        # Create metadata store - CRITICAL: avoid storing DOM references
        metadata_store = dcc.Store(
            id={"type": "stored-metadata-component", "index": component_id},
            data={
                "index": component_id,
                "component_type": "text",
                "title": f"Text Component {n_clicks}",
                # POTENTIAL ISSUE: Don't store existing_children (DOM reference)
                # "existing_children": existing_children,  # ← CIRCULAR REFERENCE SOURCE
            },
        )

        # Create RichTextEditor
        rich_editor = dmc.RichTextEditor(
            id={"type": "text-editor", "index": component_id},
            html=f"<p>Text component #{n_clicks} content</p>",
            style={"minHeight": "200px", "border": "1px solid #ddd", "marginBottom": "10px"},
        )

        # Create text component wrapper
        text_component = html.Div(
            [
                html.H5(f"Text Component {n_clicks}"),
                rich_editor,
                metadata_store,
            ],
            style={
                "border": "1px solid #ccc",
                "padding": "10px",
                "marginBottom": "10px",
                "backgroundColor": "#f9f9f9",
            },
        )

        # Update layout store - CRITICAL: avoid storing DOM references
        new_layout_data = layout_data.copy() if layout_data else {}
        new_layout_data[component_id] = {
            "type": "text",
            "position": {"x": 0, "y": n_clicks * 100, "w": 6, "h": 4},
            # DON'T STORE: "component_ref": text_component  # ← CIRCULAR REFERENCE
        }

        # Update component store - CRITICAL: avoid storing DOM references
        # KEY INSIGHT: The circular reference occurs when existing components (with React Fiber references)
        # are passed through State parameters in callbacks. Solution: rebuild from data, not DOM.
        new_component_data = component_data.copy() if component_data else {}
        new_component_data[component_id] = {
            "type": "text",
            "title": f"Text Component {n_clicks}",
            # DON'T STORE: "dom_element": rich_editor  # ← CIRCULAR REFERENCE
            # DON'T STORE: "container": existing_children  # ← CIRCULAR REFERENCE
        }

        # Build ALL components from scratch using the component store data
        # This avoids circular references by not reusing existing DOM elements
        all_components = []
        for comp_id, comp_data in new_component_data.items():
            if comp_data["type"] == "text":
                # Recreate each component fresh (no circular references)
                comp_metadata_store = dcc.Store(
                    id={"type": "stored-metadata-component", "index": comp_id},
                    data={
                        "index": comp_id,
                        "component_type": "text",
                        "title": comp_data["title"],
                    },
                )

                comp_editor = dmc.RichTextEditor(
                    id={"type": "text-editor", "index": comp_id},
                    html=f"<p>{comp_data['title']} content</p>",
                    style={
                        "minHeight": "200px",
                        "border": "1px solid #ddd",
                        "marginBottom": "10px",
                    },
                )

                comp_wrapper = html.Div(
                    [
                        html.H5(comp_data["title"]),
                        comp_editor,
                        comp_metadata_store,
                    ],
                    style={
                        "border": "1px solid #ccc",
                        "padding": "10px",
                        "marginBottom": "10px",
                        "backgroundColor": "#f9f9f9",
                    },
                )

                all_components.append(comp_wrapper)

        new_children = all_components

        return new_children, new_layout_data, new_component_data

    except Exception as e:
        error_msg = f"Error adding text component: {str(e)}"
        print(error_msg)  # Debug print
        return f"ERROR: {error_msg}", {}, {}


# Debug callback to monitor what's happening
@app.callback(
    Output("debug-info", "children"),
    [
        Input("add-text-btn", "n_clicks"),
        Input("layout-store", "data"),
        Input("component-store", "data"),
    ],
    prevent_initial_call=True,
)
def debug_dashboard_state(n_clicks, layout_data, component_data):
    return html.Div(
        [
            html.P(f"Components added: {n_clicks}"),
            html.P(f"Layout store keys: {list(layout_data.keys()) if layout_data else 'None'}"),
            html.P(
                f"Component store keys: {list(component_data.keys()) if component_data else 'None'}"
            ),
            html.P("Check browser console for circular reference errors."),
        ]
    )


if __name__ == "__main__":
    print("Testing circular reference in dashboard context...")
    print("This simulates adding text components to your dashboard.")
    print("Watch browser console for circular reference errors.")
    app.run(debug=True, port=8056)
