"""
Notes footer layout for Depictio dashboards.

This module provides a toggle-based footer with RichTextEditor for dashboard notes and documentation.
The footer respects the collapsible sidebar layout using CSS variables automatically.
"""

import dash_mantine_components as dmc
from dash import Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger


def register_callbacks_notes_footer(app):
    """Register callbacks for the notes footer functionality."""

    # Simple CSS injection for footer styling that works with AppShell
    app.clientside_callback(
        """
        function(appshell_id) {
            // Inject CSS styles for footer that integrates with AppShell layout
            if (!document.getElementById('notes-footer-styles')) {
                var style = document.createElement('style');
                style.id = 'notes-footer-styles';
                style.innerHTML = `
                    /* Footer starts hidden and adjusts based on AppShell state - High specificity */
                    body #notes-footer-content, html #notes-footer-content {
                        height: 0px;
                        overflow: hidden;
                        transition: height 0.3s ease, opacity 0.3s ease !important;
                        opacity: 0 !important;
                        position: fixed;
                        bottom: 0;
                        left: 220px;  /* Default sidebar width */
                        right: 0;
                        z-index: 1000;
                        background: var(--app-bg-secondary, rgba(0, 0, 0, 0.02));
                        backdrop-filter: blur(10px);
                        border-top: 1px solid var(--app-border-color, #e9ecef);
                    }

                    /* When sidebar is collapsed (AppShell adds data-navbar-collapsed) */
                    [data-navbar-collapsed="true"] #notes-footer-content,
                    .mantine-AppShell-root[data-navbar-collapsed="true"] #notes-footer-content {
                        left: 0px !important;
                    }

                    /* Alternative approach using body classes if data attributes not available */
                    body.sidebar-collapsed #notes-footer-content,
                    .sidebar-collapsed #notes-footer-content {
                        left: 0px !important;
                    }

                    /* Expanded state when toggled - High specificity */
                    body #notes-footer-content.footer-visible, html #notes-footer-content.footer-visible {
                        height: 300px !important;
                        opacity: 1 !important;
                        overflow: visible !important;
                        transition: height 0.3s ease, opacity 0.3s ease !important;
                    }

                    /* Override any conflicting transitions - High specificity */
                    body #notes-footer-content, html #notes-footer-content {
                        will-change: height, opacity !important;
                    }

                    /* Ensure child elements don't interfere */
                    #notes-footer-content > * {
                        transition: opacity 0.2s ease-in-out !important;
                    }

                    /* Mobile responsive */
                    @media (max-width: 768px) {
                        #notes-footer-content {
                            left: 0px !important;
                        }
                    }
                `;
                document.head.appendChild(style);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("page-content", "data-notes-css-injected"),
        Input("page-content", "id"),
        prevent_initial_call=False,
    )

    # Simple callback to adjust footer positioning based on sidebar state
    app.clientside_callback(
        """
        function(is_collapsed) {
            console.log('Footer adjusting to sidebar collapse state:', is_collapsed);

            const footer = document.querySelector('#notes-footer-content');
            if (footer) {
                if (is_collapsed) {
                    footer.style.left = '0px';  // Full width when collapsed
                } else {
                    footer.style.left = '220px';  // Offset by sidebar width when expanded
                }
                console.log('Footer left position set to:', footer.style.left);
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output("notes-footer-content", "data-collapse-response"),
        Input("sidebar-collapsed", "data"),
        prevent_initial_call=False,
    )

    # Toggle notes footer visibility
    @app.callback(
        Output("notes-footer-content", "className"),
        Input("toggle-notes-button", "n_clicks"),
        State("notes-footer-content", "className"),
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
    @app.callback(
        Output("notes-editor-store", "data"),
        Input("notes-rich-text-editor", "html"),
        prevent_initial_call=True,
    )
    def store_notes_content(editor_html):
        """Store notes content when it changes."""
        logger.info(f"Storing notes content: {editor_html[:100] if editor_html else ''}...")
        return editor_html

    # Update toggle button text based on footer state
    @app.callback(
        Output("toggle-notes-button", "children"),
        Input("notes-footer-content", "className"),
        prevent_initial_call=True,
    )
    def update_toggle_button_text(footer_class):
        """Update button text based on footer visibility."""
        is_visible = footer_class and "footer-visible" in footer_class

        if is_visible:
            return DashIconify(icon="material-symbols:expand-less", width=35, color="gray")
        else:
            return DashIconify(icon="material-symbols:edit-note", width=35, color="gray")


def create_notes_footer(dashboard_data=None):
    """Create the notes footer component with RichTextEditor."""
    # Load existing notes content if available
    initial_notes_content = (
        "<p>Start writing your notes, documentation, or analysis here...\n\n\n</p>"
    )
    if dashboard_data and dashboard_data.get("notes_content"):
        initial_notes_content = dashboard_data["notes_content"]

    return html.Div(
        [
            # Simple header
            html.Div(
                [
                    dmc.Group(
                        [
                            DashIconify(
                                icon="material-symbols:edit-note",
                                width=20,
                                style={"color": "var(--app-text-color, #000000)"},
                            ),
                            dmc.Text(
                                "Notes & Documentation",
                                fw="bold",
                                style={"color": "var(--app-text-color, #000000)"},
                            ),
                        ],
                        gap="xs",
                        justify="center",
                        align="center",
                    )
                ],
                id="notes-footer-header",
                style={
                    "padding": "8px 16px",
                    "backgroundColor": "var(--app-bg-secondary, rgba(0, 0, 0, 0.01))",
                    "minHeight": "32px",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                },
            ),
            # Storage for editor content
            dcc.Store(id="notes-editor-store", data=initial_notes_content),
            # Editor content area
            html.Div(
                [
                    dmc.RichTextEditor(
                        id="notes-rich-text-editor",
                        html=initial_notes_content,
                        style={"minHeight": "200px", "maxHeight": "250px", "overflowY": "auto"},
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
                id="notes-editor-container",
                style={
                    "padding": "10px 16px",
                    # "backgroundColor": "var(--app-bg-secondary, rgba(0, 0, 0, 0.01))",
                },
            ),
        ],
        id="notes-footer-content",
    )
