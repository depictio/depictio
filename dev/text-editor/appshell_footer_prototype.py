"""
AppShell with collapsible footer containing RichTextEditor

This prototype demonstrates a permanent RichTextEditor in a collapsible footer
that can be used throughout the Depictio application without circular reference issues.
"""

import dash
import dash_mantine_components as dmc
from dash import Dash, Input, Output, State, callback, dcc, html
from dash_iconify import DashIconify

app = Dash(__name__, suppress_callback_exceptions=True)

logo = "https://github.com/user-attachments/assets/c1ff143b-4365-4fd1-880f-3e97aab5c302"


# Create the RichTextEditor for the footer
def create_footer_editor():
    return html.Div(
        [
            # Editor controls
            dmc.Group(
                [
                    dmc.Button(
                        "Notes & Documentation",
                        leftSection=DashIconify(icon="material-symbols:edit-note", width=16),
                        variant="subtle",
                        size="sm",
                        id="footer-editor-toggle",
                    ),
                    dmc.Group(
                        [
                            dmc.Button(
                                "Save",
                                leftSection=DashIconify(icon="material-symbols:save", width=14),
                                size="xs",
                                color="green",
                                variant="light",
                                id="footer-save-btn",
                            ),
                            dmc.Button(
                                "Clear",
                                leftSection=DashIconify(
                                    icon="material-symbols:clear-all", width=14
                                ),
                                size="xs",
                                color="red",
                                variant="light",
                                id="footer-clear-btn",
                            ),
                            dmc.Button(
                                "Export",
                                leftSection=DashIconify(icon="material-symbols:download", width=14),
                                size="xs",
                                color="blue",
                                variant="light",
                                id="footer-export-btn",
                            ),
                        ],
                        gap="xs",
                    ),
                ],
                justify="space-between",
                align="center",
                style={"marginBottom": "10px"},
            ),
            # Storage for editor content
            dcc.Store(id="footer-editor-store", data=""),
            # RichTextEditor
            html.Div(
                [
                    dmc.RichTextEditor(
                        id="footer-rich-text-editor",
                        html="<p>Start writing your notes, documentation, or analysis here...</p>",
                        style={"minHeight": "200px", "maxHeight": "400px", "overflowY": "auto"},
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
                id="footer-editor-container",
                style={"display": "block"},
            ),
        ]
    )


layout = dmc.AppShell(
    [
        dmc.AppShellHeader(
            dmc.Group(
                [
                    dmc.Burger(
                        id="burger",
                        size="sm",
                        hiddenFrom="sm",
                        opened=False,
                    ),
                    dmc.Image(src=logo, h=40, flex=0),
                    dmc.Title("Depictio with Collapsible Notes", c="blue"),
                    # Add footer toggle button in header
                    dmc.Group(
                        [
                            dmc.Button(
                                "Toggle Notes",
                                leftSection=DashIconify(icon="material-symbols:notes", width=16),
                                variant="light",
                                size="sm",
                                id="header-footer-toggle",
                            ),
                        ],
                        gap="sm",
                    ),
                ],
                h="100%",
                px="md",
                justify="space-between",
            )
        ),
        dmc.AppShellNavbar(
            id="navbar",
            children=[
                dmc.Title("Navigation", order=4, style={"marginBottom": "1rem"}),
                dmc.NavLink(
                    label="Dashboard",
                    leftSection=DashIconify(icon="material-symbols:dashboard", width=16),
                    active=True,
                ),
                dmc.NavLink(
                    label="Projects",
                    leftSection=DashIconify(icon="material-symbols:folder", width=16),
                ),
                dmc.NavLink(
                    label="Workflows",
                    leftSection=DashIconify(icon="material-symbols:workflow", width=16),
                ),
                dmc.NavLink(
                    label="Data Collections",
                    leftSection=DashIconify(icon="material-symbols:database", width=16),
                ),
                *[dmc.Skeleton(height=28, mt="sm", animate=False) for _ in range(8)],
            ],
            p="md",
        ),
        dmc.AppShellMain(
            [
                dmc.Container(
                    [
                        dmc.Title("Main Dashboard Content", order=2),
                        dmc.Text("This is where your dashboard components would be displayed."),
                        dmc.Space(h="md"),
                        # Sample dashboard content
                        dmc.Grid(
                            [
                                dmc.GridCol(
                                    [
                                        dmc.Card(
                                            [
                                                dmc.Text("Sample Card 1", fw=500),
                                                dmc.Text(
                                                    "Some dashboard content here",
                                                    size="sm",
                                                    c="dimmed",
                                                ),
                                            ],
                                            withBorder=True,
                                            shadow="sm",
                                            radius="md",
                                            p="lg",
                                        )
                                    ],
                                    span=4,
                                ),
                                dmc.GridCol(
                                    [
                                        dmc.Card(
                                            [
                                                dmc.Text("Sample Card 2", fw=500),
                                                dmc.Text(
                                                    "More dashboard content", size="sm", c="dimmed"
                                                ),
                                            ],
                                            withBorder=True,
                                            shadow="sm",
                                            radius="md",
                                            p="lg",
                                        )
                                    ],
                                    span=4,
                                ),
                                dmc.GridCol(
                                    [
                                        dmc.Card(
                                            [
                                                dmc.Text("Sample Card 3", fw=500),
                                                dmc.Text(
                                                    "Additional content", size="sm", c="dimmed"
                                                ),
                                            ],
                                            withBorder=True,
                                            shadow="sm",
                                            radius="md",
                                            p="lg",
                                        )
                                    ],
                                    span=4,
                                ),
                            ]
                        ),
                        dmc.Space(h="xl"),
                        dmc.Alert(
                            "The collapsible footer below contains a RichTextEditor for notes and documentation. "
                            "Toggle it using the button in the header or by clicking the footer bar.",
                            title="Notes Feature",
                            icon=DashIconify(icon="material-symbols:info"),
                            color="blue",
                        ),
                        # Add some content to show scrolling
                        html.Div(
                            [
                                dmc.Text(f"Sample content line {i}", style={"marginBottom": "10px"})
                                for i in range(20)
                            ]
                        ),
                    ],
                    fluid=True,
                    style={"paddingBottom": "100px"},
                )  # Add padding for footer
            ]
        ),
        # Collapsible Footer with RichTextEditor
        dmc.AppShellFooter(
            id="footer-content",
            children=create_footer_editor(),
            p="md",
            style={
                "borderTop": "2px solid var(--app-border-color, #e9ecef)",
                "backgroundColor": "var(--app-surface-color, #f8f9fa)",
                "transition": "height 0.3s ease-in-out",
            },
        ),
    ],
    header={"height": 60},
    footer={"height": 300, "collapsed": False},  # Start expanded to show the feature
    navbar={
        "width": 300,
        "breakpoint": "sm",
        "collapsed": {"mobile": True},
    },
    padding="md",
    id="appshell",
)

app.layout = dmc.MantineProvider(layout)


# Toggle navbar (mobile)
@callback(
    Output("appshell", "navbar"),
    Input("burger", "opened"),
    State("appshell", "navbar"),
)
def toggle_navbar(opened, navbar):
    navbar["collapsed"] = {"mobile": not opened}
    return navbar


# Toggle footer from header button
@callback(
    Output("appshell", "footer"),
    Input("header-footer-toggle", "n_clicks"),
    Input("footer-editor-toggle", "n_clicks"),
    State("appshell", "footer"),
    prevent_initial_call=True,
)
def toggle_footer(header_clicks, footer_clicks, current_footer):
    """Toggle footer visibility from header button or footer button."""
    if header_clicks or footer_clicks:
        # Toggle collapsed state
        current_footer["collapsed"] = not current_footer.get("collapsed", False)

        # Adjust height based on collapsed state
        if current_footer["collapsed"]:
            current_footer["height"] = 50  # Collapsed height - just show toggle bar
        else:
            current_footer["height"] = 300  # Expanded height

    return current_footer


# Handle editor content storage
@callback(
    Output("footer-editor-store", "data"),
    Input("footer-rich-text-editor", "html"),
    Input("footer-save-btn", "n_clicks"),
    prevent_initial_call=True,
)
def store_editor_content(editor_html, save_clicks):
    """Store editor content when it changes or save button is clicked."""
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if trigger_id == "footer-save-btn" and save_clicks:
        # Could implement actual saving logic here
        print(f"Saving editor content: {editor_html[:100] if editor_html else ''}...")
        return editor_html
    elif trigger_id == "footer-rich-text-editor":
        return editor_html

    return dash.no_update


# Clear editor content
@callback(
    Output("footer-rich-text-editor", "html"),
    Input("footer-clear-btn", "n_clicks"),
    prevent_initial_call=True,
)
def clear_editor(clear_clicks):
    """Clear the editor content."""
    if clear_clicks:
        return "<p>Start writing your notes, documentation, or analysis here...</p>"
    return dash.no_update


# Show/hide editor based on footer collapse state
@callback(
    Output("footer-editor-container", "style"),
    Output("footer-editor-toggle", "children"),
    Input("appshell", "footer"),
    prevent_initial_call=True,
)
def toggle_editor_visibility(footer_config):
    """Show/hide the editor container based on footer collapsed state."""
    is_collapsed = footer_config.get("collapsed", False)

    if is_collapsed:
        return (
            {"display": "none"},
            [DashIconify(icon="material-symbols:expand-less", width=16), " Show Notes"],
        )
    else:
        return (
            {"display": "block"},
            [DashIconify(icon="material-symbols:expand-more", width=16), " Hide Notes"],
        )


if __name__ == "__main__":
    print("Running AppShell with collapsible footer RichTextEditor prototype...")
    print("Features:")
    print("- Collapsible footer with RichTextEditor")
    print("- Toggle from header button or footer button")
    print("- Content storage and management")
    print("- No circular reference issues (editor is permanent, not dynamically created)")
    print("Running on http://127.0.0.1:8059/")
    app.run(debug=True, port=8059)
