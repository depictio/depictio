"""
Comprehensive API test for DMC RichTextEditor to find correct syntax
"""

import dash
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State, callback

# Test different API syntaxes based on common patterns
test_configs = [
    # Config 1: Basic with value
    {
        "name": "Basic with value",
        "config": {
            "id": "editor1",
            "value": "<p>Test content</p>",
        },
    },
    # Config 2: With html property
    {
        "name": "With html property",
        "config": {
            "id": "editor2",
            "html": "<p>Test content</p>",
        },
    },
    # Config 3: With content property
    {
        "name": "With content property",
        "config": {
            "id": "editor3",
            "content": "<p>Test content</p>",
        },
    },
    # Config 4: With toolbar as controls
    {
        "name": "Toolbar as controls",
        "config": {
            "id": "editor4",
            "value": "<p>Test content</p>",
            "controls": [
                ["bold", "italic", "underline"],
                ["h1", "h2", "h3"],
            ],
        },
    },
    # Config 5: With toolbar object
    {
        "name": "Toolbar as object",
        "config": {
            "id": "editor5",
            "value": "<p>Test content</p>",
            "toolbar": {"controls": [["bold", "italic"]]},
        },
    },
    # Config 6: With extensions
    {
        "name": "With extensions",
        "config": {"id": "editor6", "value": "<p>Test content</p>", "extensions": ["StarterKit"]},
    },
]

app = dash.Dash(__name__)


def create_test_editor(config_dict):
    """Create a test editor with error handling"""
    try:
        editor = dmc.RichTextEditor(**config_dict["config"])
        return html.Div(
            [html.H4(f"✅ {config_dict['name']}", style={"color": "green"}), editor, html.Hr()]
        )
    except Exception as e:
        return html.Div(
            [
                html.H4(f"❌ {config_dict['name']}", style={"color": "red"}),
                html.P(f"Error: {str(e)}"),
                html.Hr(),
            ]
        )


app.layout = dmc.MantineProvider(
    [
        dmc.Title("DMC RichTextEditor API Test", order=1),
        dmc.Space(h=20),
        html.Div(
            [
                html.P("Testing different API configurations:"),
                *[create_test_editor(config) for config in test_configs],
            ]
        ),
        dmc.Space(h=20),
        html.H3("Manual Test Area"),
        html.P("Try creating a RichTextEditor manually:"),
        html.Div(id="manual-test"),
        html.H3("Output"),
        html.Div(id="output"),
    ]
)


@callback(
    Output("manual-test", "children"),
    Input("manual-test", "id"),  # Dummy trigger
)
def manual_test(_):
    """Manual test with the simplest possible config"""
    try:
        # Try the absolute simplest configuration
        return dmc.RichTextEditor(id="manual-editor")
    except Exception as e:
        return html.P(f"Manual test failed: {e}", style={"color": "red"})


# Test different value properties
for i, config in enumerate(test_configs):
    if hasattr(dmc, "RichTextEditor"):
        try:

            @callback(
                Output("output", "children", allow_duplicate=True),
                Input(config["config"]["id"], "value"),
                prevent_initial_call=True,
            )
            def update_output(value, config_name=config["name"]):
                return html.Div(
                    [
                        html.P(f"Content from {config_name}:"),
                        html.Pre(str(value)[:100] + "..." if len(str(value)) > 100 else str(value)),
                    ]
                )
        except:
            pass  # Skip if property doesn't exist

if __name__ == "__main__":
    print("Testing DMC RichTextEditor configurations...")
    print(f"DMC version available: {dmc.__version__ if hasattr(dmc, '__version__') else 'unknown'}")
    print(f"RichTextEditor available: {hasattr(dmc, 'RichTextEditor')}")

    if hasattr(dmc, "RichTextEditor"):
        # Try to inspect the component
        try:
            rte = dmc.RichTextEditor()
            print(f"RichTextEditor created successfully")
            print(
                f"Available props: {list(rte._prop_names) if hasattr(rte, '_prop_names') else 'unknown'}"
            )
        except Exception as e:
            print(f"Error creating RichTextEditor: {e}")

    app.run(debug=True, port=8053)
