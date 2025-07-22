"""
Simple Markdown Text Input Component Prototype

A lightweight text input component that supports basic markdown heading syntax (#, ##, ###)
Perfect for dashboard section delimiters and categorization.
"""

import dash
import dash_mantine_components as dmc
from dash import Dash, Input, Output, State, callback, html, dcc, clientside_callback
from dash_iconify import DashIconify
import re

app = Dash(__name__, suppress_callback_exceptions=True)


def create_markdown_input(
    component_id, placeholder="# Section Title", initial_value="# Dashboard Section"
):
    """Create a simple markdown input component with live preview."""

    return html.Div(
        [
            # Input and preview container
            dmc.Stack(
                [
                    # Textarea for markdown input
                    dmc.Textarea(
                        id={"type": "markdown-input", "index": component_id},
                        placeholder=placeholder,
                        value=initial_value,
                        autosize=True,
                        minRows=1,
                        maxRows=3,
                        style={"fontFamily": "monospace", "fontSize": "14px"},
                    ),
                    # Live preview area
                    html.Div(
                        id={"type": "markdown-preview", "index": component_id},
                        children=render_markdown_to_dash(initial_value),
                        style={
                            "minHeight": "30px",
                            "padding": "8px",
                            "border": "1px solid var(--app-border-color, #ddd)",
                            "borderRadius": "4px",
                            "backgroundColor": "var(--app-surface-color, #f9f9f9)",
                            "marginTop": "4px",
                        },
                    ),
                    # Component controls
                    dmc.Group(
                        [
                            dmc.Button(
                                "H1",
                                size="xs",
                                variant="light",
                                color="blue",
                                id={"type": "h1-btn", "index": component_id},
                            ),
                            dmc.Button(
                                "H2",
                                size="xs",
                                variant="light",
                                color="blue",
                                id={"type": "h2-btn", "index": component_id},
                            ),
                            dmc.Button(
                                "H3",
                                size="xs",
                                variant="light",
                                color="blue",
                                id={"type": "h3-btn", "index": component_id},
                            ),
                            dmc.Button(
                                "H4",
                                size="xs",
                                variant="light",
                                color="blue",
                                id={"type": "h4-btn", "index": component_id},
                            ),
                            dmc.Button(
                                "H5",
                                size="xs",
                                variant="light",
                                color="blue",
                                id={"type": "h5-btn", "index": component_id},
                            ),
                            dmc.Button(
                                "Clear",
                                size="xs",
                                variant="light",
                                color="red",
                                id={"type": "clear-btn", "index": component_id},
                            ),
                        ],
                        gap="xs",
                        style={"marginTop": "4px"},
                    ),
                ],
                gap="xs",
            ),
            # Store for component data
            dcc.Store(
                id={"type": "markdown-store", "index": component_id},
                data={"text": initial_value, "html": ""},
            ),
        ],
        style={
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "8px",
            "padding": "12px",
            "marginBottom": "10px",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
        },
    )


def markdown_to_html(text):
    """Convert simple markdown headers to HTML."""
    if not text:
        return ""

    # Simple markdown to HTML conversion for headers only
    lines = text.split("\n")
    html_lines = []

    for line in lines:
        line = line.strip()
        if line.startswith("### "):
            html_lines.append(f'<h3 style="margin: 8px 0; color: #495057;">{line[4:]}</h3>')
        elif line.startswith("## "):
            html_lines.append(f'<h2 style="margin: 10px 0; color: #343a40;">{line[3:]}</h2>')
        elif line.startswith("# "):
            html_lines.append(f'<h1 style="margin: 12px 0; color: #212529;">{line[2:]}</h1>')
        elif line:
            html_lines.append(f'<p style="margin: 4px 0; color: #6c757d;">{line}</p>')

    return "".join(html_lines) if html_lines else '<p style="color: #adb5bd;">Start typing...</p>'


def render_markdown_to_dash(text):
    """Convert simple markdown to DMC components."""
    if not text:
        return dmc.Text("Start typing...", c="dimmed", size="sm")

    lines = text.split("\n")
    dash_components = []

    for line in lines:
        line = line.strip()
        if line.startswith("##### "):
            dash_components.append(
                dmc.Title(line[6:], order=5, c="dark", style={"margin": "4px 0"})
            )
        elif line.startswith("#### "):
            dash_components.append(
                dmc.Title(line[5:], order=4, c="dark", style={"margin": "6px 0"})
            )
        elif line.startswith("### "):
            dash_components.append(
                dmc.Title(line[4:], order=3, c="dark", style={"margin": "8px 0"})
            )
        elif line.startswith("## "):
            dash_components.append(
                dmc.Title(line[3:], order=2, c="dark", style={"margin": "10px 0"})
            )
        elif line.startswith("# "):
            dash_components.append(
                dmc.Title(line[2:], order=1, c="dark", style={"margin": "12px 0"})
            )
        elif line:
            dash_components.append(dmc.Text(line, c="gray", style={"margin": "4px 0"}))

    return (
        dash_components if dash_components else [dmc.Text("Start typing...", c="dimmed", size="sm")]
    )


# Test layout with multiple markdown inputs
app.layout = dmc.MantineProvider(
    [
        dmc.Container(
            [
                dmc.Title("Simple Markdown Text Input Prototype", order=1),
                dmc.Text(
                    "Perfect for dashboard section delimiters with # header syntax", c="dimmed"
                ),
                dmc.Space(h="md"),
                # Demo section
                dmc.Alert(
                    "Type # for H1, ## for H2, ### for H3. Live preview shows how it will appear in your dashboard.",
                    title="How to use",
                    icon=DashIconify(icon="material-symbols:info"),
                    color="blue",
                ),
                dmc.Space(h="lg"),
                # Multiple markdown inputs to simulate dashboard sections
                dmc.Title("Dashboard Preview", order=2),
                create_markdown_input(
                    "section-1", "# Main Section Title", "# Data Analysis Dashboard"
                ),
                # Simulated dashboard content
                dmc.Grid(
                    [
                        dmc.GridCol(
                            [
                                dmc.Card(
                                    [
                                        dmc.Text("Chart Component", fw=500),
                                        dmc.Text("Sample visualization", size="sm", c="dimmed"),
                                    ],
                                    withBorder=True,
                                    shadow="sm",
                                    radius="md",
                                    p="md",
                                )
                            ],
                            span=6,
                        ),
                        dmc.GridCol(
                            [
                                dmc.Card(
                                    [
                                        dmc.Text("Table Component", fw=500),
                                        dmc.Text("Sample data table", size="sm", c="dimmed"),
                                    ],
                                    withBorder=True,
                                    shadow="sm",
                                    radius="md",
                                    p="md",
                                )
                            ],
                            span=6,
                        ),
                    ]
                ),
                create_markdown_input("section-2", "## Sub-section", "## Key Metrics"),
                # More simulated content
                dmc.Grid(
                    [
                        dmc.GridCol(
                            [
                                dmc.Card(
                                    [
                                        dmc.Text("Metric 1", fw=500),
                                        dmc.Text("42", size="xl", c="blue"),
                                    ],
                                    withBorder=True,
                                    shadow="sm",
                                    radius="md",
                                    p="md",
                                )
                            ],
                            span=4,
                        ),
                        dmc.GridCol(
                            [
                                dmc.Card(
                                    [
                                        dmc.Text("Metric 2", fw=500),
                                        dmc.Text("89%", size="xl", c="green"),
                                    ],
                                    withBorder=True,
                                    shadow="sm",
                                    radius="md",
                                    p="md",
                                )
                            ],
                            span=4,
                        ),
                        dmc.GridCol(
                            [
                                dmc.Card(
                                    [
                                        dmc.Text("Metric 3", fw=500),
                                        dmc.Text("156", size="xl", c="orange"),
                                    ],
                                    withBorder=True,
                                    shadow="sm",
                                    radius="md",
                                    p="md",
                                )
                            ],
                            span=4,
                        ),
                    ]
                ),
                create_markdown_input("section-3", "### Notes", "### Additional Information"),
                dmc.Card(
                    [
                        dmc.Text("Notes Section", fw=500),
                        dmc.Text(
                            "This would be where additional context or documentation appears.",
                            size="sm",
                        ),
                    ],
                    withBorder=True,
                    shadow="sm",
                    radius="md",
                    p="md",
                ),
                dmc.Space(h="xl"),
                # Technical details
                dmc.Card(
                    [
                        dmc.Title("Component Features", order=3),
                        dmc.List(
                            [
                                dmc.ListItem("Real-time markdown preview"),
                                dmc.ListItem("Header shortcuts (H1, H2, H3 buttons)"),
                                dmc.ListItem("Lightweight - just textarea + JavaScript"),
                                dmc.ListItem("Perfect for dashboard section delimiters"),
                                dmc.ListItem("No circular reference issues"),
                                dmc.ListItem("Theme-aware styling"),
                            ]
                        ),
                    ],
                    withBorder=True,
                    p="lg",
                ),
            ],
            size="lg",
        )
    ]
)


# Server-side callback for real-time markdown preview
@callback(
    Output({"type": "markdown-preview", "index": dash.ALL}, "children"),
    Input({"type": "markdown-input", "index": dash.ALL}, "value"),
    prevent_initial_call=True,
)
def update_markdown_preview(text_values):
    """Update markdown preview using DMC components."""
    if not text_values:
        return [dmc.Text("Start typing...", c="dimmed", size="sm")]

    previews = []
    for text in text_values:
        previews.append(render_markdown_to_dash(text))

    return previews


# Header button callbacks
@callback(
    Output({"type": "markdown-input", "index": dash.MATCH}, "value"),
    [
        Input({"type": "h1-btn", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "h2-btn", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "h3-btn", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "h4-btn", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "h5-btn", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "clear-btn", "index": dash.MATCH}, "n_clicks"),
    ],
    State({"type": "markdown-input", "index": dash.MATCH}, "value"),
    prevent_initial_call=True,
)
def handle_button_clicks(
    h1_clicks, h2_clicks, h3_clicks, h4_clicks, h5_clicks, clear_clicks, current_value
):
    """Handle header button clicks and clear button."""
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if "h1-btn" in button_id:
        return "# "
    elif "h2-btn" in button_id:
        return "## "
    elif "h3-btn" in button_id:
        return "### "
    elif "h4-btn" in button_id:
        return "#### "
    elif "h5-btn" in button_id:
        return "##### "
    elif "clear-btn" in button_id:
        return ""

    return dash.no_update


# Store markdown content for persistence
@callback(
    Output({"type": "markdown-store", "index": dash.MATCH}, "data"),
    Input({"type": "markdown-input", "index": dash.MATCH}, "value"),
    prevent_initial_call=True,
)
def store_markdown_content(text):
    """Store markdown content and converted HTML."""
    html_output = markdown_to_html(text)
    return {"text": text, "html": html_output}


if __name__ == "__main__":
    print("Running Simple Markdown Text Input Prototype...")
    print("Features:")
    print("- Real-time markdown preview for headers (#, ##, ###)")
    print("- Header shortcut buttons")
    print("- Perfect for dashboard section delimiters")
    print("- Lightweight implementation with no dependencies")
    print("- No circular reference issues")
    print("Running on http://127.0.0.1:8060/")
    app.run(debug=True, port=8060)
