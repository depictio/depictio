"""
AppShell with CSS hover-revealed footer containing RichTextEditor

This prototype demonstrates a permanent RichTextEditor in a footer that:
- Reveals on hover over the bottom of the page (CSS-based)
- Shows as a single line initially
- Clicking "Notes & Documentation" toggles back to collapsed state
- No toggle button needed in header (clean UI)
"""

import dash
import dash_mantine_components as dmc
from dash import Dash, Input, Output, State, callback, dcc, html
from dash_iconify import DashIconify

app = Dash(__name__, suppress_callback_exceptions=True)

logo = "https://github.com/user-attachments/assets/c1ff143b-4365-4fd1-880f-3e97aab5c302"


# Create the RichTextEditor for the footer with hover reveal mechanism
def create_footer_editor():
    return html.Div(
        [
            # Simple header
            html.Div(
                [dmc.Text("Notes & Documentation", fw=500, c="dark", ta="center")],
                id="footer-header-line",
                style={
                    "padding": "8px 16px",
                    "borderTop": "1px solid var(--app-border-color, #e9ecef)",
                    "backgroundColor": "var(--app-surface-color, #f8f9fa)",
                    "minHeight": "32px",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                },
            ),
            # Storage for editor content
            dcc.Store(id="footer-editor-store", data=""),
            # Editor content area
            html.Div(
                [
                    dmc.RichTextEditor(
                        id="footer-rich-text-editor",
                        html="<p>Start writing your notes, documentation, or analysis here...</p>",
                        style={"minHeight": "200px", "maxHeight": "350px", "overflowY": "auto"},
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
                style={
                    "padding": "10px 16px",
                    "backgroundColor": "var(--app-surface-color, #f8f9fa)",
                    "borderTop": "1px solid var(--app-border-color, #e9ecef)",
                },
            ),
        ],
        id="footer-wrapper",
    )


layout = dmc.AppShell(
    [
        dmc.AppShellHeader(
            dmc.Group(
                [
                    dmc.Group(
                        [
                            dmc.Burger(
                                id="burger",
                                size="sm",
                                hiddenFrom="sm",
                                opened=False,
                            ),
                            dmc.Image(src=logo, h=40, flex=0),
                            dmc.Title("Depictio with Notes Footer", c="blue"),
                        ]
                    ),
                    dmc.Button(
                        [
                            DashIconify(icon="material-symbols:edit-note", width=16),
                            dmc.Text("Toggle Notes", ml="xs"),
                        ],
                        variant="subtle",
                        size="sm",
                        id="toggle-notes-button",
                        color="blue",
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
                            "The footer below contains a RichTextEditor for notes and documentation. "
                            "Hover over the footer to preview content, or click 'Notes & Documentation' to pin the expanded state.",
                            title="Hover-Revealed Notes Feature",
                            icon=DashIconify(icon="material-symbols:info"),
                            color="blue",
                        ),
                        # Add some content to show scrolling
                        html.Div(
                            [
                                dmc.Text(f"Sample content line {i}", style={"marginBottom": "10px"})
                                for i in range(10)
                            ]
                        ),
                    ],
                    fluid=True,
                    style={"paddingBottom": "100px"},
                )  # Add padding for footer
            ]
        ),
        # Footer with CSS hover reveal mechanism
        dmc.AppShellFooter(
            id="footer-content",
            children=create_footer_editor(),
            p=0,  # Remove padding to have full control
            style={
                "padding": "0",
                "transition": "height 0.3s ease-in-out",
                "overflow": "visible",
                "position": "fixed",
                "bottom": "0",
                "left": "0",  # Will be updated dynamically by JavaScript
                "right": "0",
                "zIndex": "10001",  # Above hover zone to ensure buttons are clickable
            },
        ),
    ],
    header={"height": 60},
    footer={"height": 0, "collapsed": True},  # Start completely hidden
    navbar={
        "width": 300,
        "breakpoint": "sm",
        "collapsed": {"mobile": True},
    },
    padding="md",
    id="appshell",
)

app.layout = dmc.MantineProvider([layout])


# Simple CSS injection for footer styling
@callback(
    Output("appshell", "style"),
    Input("appshell", "id"),
    prevent_initial_call=False,
)
def inject_footer_css(_):
    """Inject basic CSS styles for footer."""
    return {}


# Add CSS via clientside callback
app.clientside_callback(
    """
    function(appshell_id) {
        // Inject simple CSS styles for footer
        if (!document.getElementById('footer-styles')) {
            var style = document.createElement('style');
            style.id = 'footer-styles';
            style.innerHTML = `
                /* Footer starts hidden */
                #footer-content {
                    height: 0px;
                    overflow: hidden;
                    transition: height 0.3s ease-in-out;
                }

                /* Expanded state when toggled */
                #footer-content.footer-visible {
                    height: 300px !important;
                    overflow: visible;
                }
            `;
            document.head.appendChild(style);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("appshell", "data-css-injected"),
    Input("appshell", "id"),
    prevent_initial_call=False,
)


# Dynamic footer positioning based on sidebar state
app.clientside_callback(
    """
    function() {
        console.log('Setting up dynamic footer positioning');
        
        setTimeout(function() {
            const footer = document.querySelector('#footer-content');
            const navbar = document.querySelector('#navbar');
            
            function updateFooterPosition() {
                let leftOffset = 0;
                if (navbar) {
                    const navbarStyles = window.getComputedStyle(navbar);
                    const isNavbarVisible = navbarStyles.display !== 'none' && 
                                          navbarStyles.visibility !== 'hidden' &&
                                          navbarStyles.width !== '0px';
                    
                    if (isNavbarVisible) {
                        leftOffset = parseInt(navbarStyles.width) || 300;
                    }
                }
                
                if (footer) {
                    footer.style.left = leftOffset + 'px';
                }
            }
            
            updateFooterPosition();
            window.addEventListener('resize', updateFooterPosition);
            
            if (navbar) {
                const observer = new MutationObserver(function() {
                    setTimeout(updateFooterPosition, 100);
                });
                
                observer.observe(navbar, {
                    attributes: true,
                    attributeFilter: ['style', 'class']
                });
            }
        }, 100);
        
        return window.dash_clientside.no_update;
    }
    """,
    Output("footer-content", "data-positioning-initialized"),
    Input("appshell", "id"),
    prevent_initial_call=False,
)


# Toggle navbar (mobile)
@callback(
    Output("appshell", "navbar"),
    Input("burger", "opened"),
    State("appshell", "navbar"),
)
def toggle_navbar(opened, navbar):
    navbar["collapsed"] = {"mobile": not opened}
    return navbar


# Simple toggle notes footer
@callback(
    Output("footer-content", "className"),
    Input("toggle-notes-button", "n_clicks"),
    State("footer-content", "className"),
    prevent_initial_call=True,
)
def toggle_notes_footer(n_clicks, current_class):
    """Toggle footer visibility when toggle button is clicked."""
    if n_clicks:
        if current_class and "footer-visible" in current_class:
            return ""  # Hide footer
        else:
            return "footer-visible"  # Show footer
    return current_class or ""


# Handle editor content storage
@callback(
    Output("footer-editor-store", "data"),
    Input("footer-rich-text-editor", "html"),
    prevent_initial_call=True,
)
def store_editor_content(editor_html):
    """Store editor content when it changes."""
    return editor_html


# Update toggle button text based on footer state
@callback(
    Output("toggle-notes-button", "children"),
    Input("footer-content", "className"),
    prevent_initial_call=True,
)
def update_toggle_button_text(footer_class):
    """Update button text based on footer visibility."""
    is_visible = footer_class and "footer-visible" in footer_class

    if is_visible:
        return [
            DashIconify(icon="material-symbols:expand-less", width=16),
            dmc.Text("Hide Notes", ml="xs"),
        ]
    else:
        return [
            DashIconify(icon="material-symbols:edit-note", width=16),
            dmc.Text("Toggle Notes", ml="xs"),
        ]


if __name__ == "__main__":
    print("Running AppShell with toggle-based footer RichTextEditor prototype...")
    print("Features:")
    print("- Footer hidden by default, toggled via top-right button")
    print("- Dynamic positioning to respect sidebar state")
    print("- Clean toggle mechanism without complex hover interactions")
    print("- Rich text editor with full toolbar functionality")
    print("- No circular reference issues (editor is permanent)")
    print("Running on http://127.0.0.1:8059/")
    app.run(debug=True, port=8059)
