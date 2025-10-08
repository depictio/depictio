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
                    /* Footer starts COMPLETELY HIDDEN and adjusts based on AppShell state - High specificity */
                    body #notes-footer-content, html #notes-footer-content {
                        height: 0px !important;
                        overflow: hidden !important;
                        transition: height 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.4s cubic-bezier(0.4, 0, 0.2, 1), left 0.3s ease, visibility 0s linear 0.4s !important;
                        opacity: 0 !important;
                        position: fixed !important;
                        bottom: 0 !important;
                        left: 220px !important;  /* Default sidebar width */
                        right: 0 !important;
                        z-index: 1000 !important;
                        background: var(--app-bg-secondary, rgba(0, 0, 0, 0.02)) !important;
                        backdrop-filter: blur(10px) !important;
                        border-top: 1px solid var(--app-border-color, #e9ecef) !important;
                        display: block !important;  /* Ensure it exists but is invisible */
                        visibility: hidden !important;  /* Additional layer of hiding */
                    }

                    /* When sidebar is collapsed - Multiple selectors for maximum compatibility */
                    [data-navbar-collapsed="true"] #notes-footer-content,
                    .mantine-AppShell-root[data-navbar-collapsed="true"] #notes-footer-content,
                    body.sidebar-collapsed #notes-footer-content,
                    .sidebar-collapsed #notes-footer-content,
                    #notes-footer-content.sidebar-collapsed {
                        left: 0px !important;
                    }

                    /* Expanded state when toggled - High specificity - Override hidden state */
                    body #notes-footer-content.footer-visible, html #notes-footer-content.footer-visible {
                        height: 265px !important;
                        opacity: 1 !important;
                        overflow: visible !important;
                        visibility: visible !important;  /* Override hidden visibility */
                        transition: height 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.4s cubic-bezier(0.4, 0, 0.2, 1), visibility 0s ease !important;
                    }

                    /* Full screen mode - covers entire page-content area - ONLY when explicitly toggled */
                    body #notes-footer-content.footer-fullscreen, html #notes-footer-content.footer-fullscreen {
                        position: fixed !important;
                        top: calc(var(--app-shell-header-height, 87px)) !important; /* Account for app header */
                        left: 0px !important;
                        right: 0px !important;
                        bottom: 0px !important;
                        height: auto !important;
                        width: 100vw !important;
                        z-index: 9999 !important;
                        opacity: 1 !important;
                        overflow: visible !important;
                        visibility: visible !important;  /* Override hidden visibility */
                        background: var(--app-bg-color, #ffffff) !important;
                        border: none !important;
                        display: flex !important;
                        flex-direction: column !important;
                        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1) !important;
                    }

                    /* Hide page content when notes is in full screen - ONLY when body has notes-fullscreen class */
                    body.notes-fullscreen #page-content > *:not(#notes-footer-content) {
                        display: none !important;
                    }

                    /* Adjust editor height for full screen - ONLY when footer has fullscreen class */
                    #notes-footer-content.footer-fullscreen .mantine-RichTextEditor-root {
                        height: calc(100vh - var(--app-shell-header-height, 87px) - 48px - 20px) !important;
                        max-height: none !important;
                    }

                    /* Ensure editor container takes full remaining space */
                    #notes-footer-content.footer-fullscreen #notes-editor-container {
                        flex: 1 !important;
                        display: flex !important;
                        flex-direction: column !important;
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
            const appShell = document.querySelector('.mantine-AppShell-root');
            const body = document.body;

            if (footer) {
                if (is_collapsed) {
                    // When collapsed: set left to 0px for full width
                    footer.style.setProperty('left', '0px', 'important');
                    // Also add CSS classes for additional styling hooks
                    footer.classList.add('sidebar-collapsed');
                    if (appShell) appShell.setAttribute('data-navbar-collapsed', 'true');
                    body.classList.add('sidebar-collapsed');
                } else {
                    // When expanded: set left to sidebar width
                    footer.style.setProperty('left', '220px', 'important');
                    footer.classList.remove('sidebar-collapsed');
                    if (appShell) appShell.setAttribute('data-navbar-collapsed', 'false');
                    body.classList.remove('sidebar-collapsed');
                }
                console.log('Footer left position set to:', footer.style.left);
                console.log('Footer classes:', footer.className);
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output("notes-footer-content", "data-collapse-response"),
        Input("sidebar-collapsed", "data"),
        prevent_initial_call=False,
    )

    # Toggle notes footer visibility and fullscreen mode
    @app.callback(
        [
            Output("notes-footer-content", "className"),
            Output("page-content", "className", allow_duplicate=True),
        ],
        [
            Input("toggle-notes-button", "n_clicks"),
            Input("collapse-notes-button", "n_clicks"),
            Input("fullscreen-notes-button", "n_clicks"),
        ],
        [
            State("notes-footer-content", "className"),
            State("page-content", "className"),
        ],
        prevent_initial_call=True,
    )
    def toggle_notes_footer(
        toggle_clicks, collapse_clicks, fullscreen_clicks, current_footer_class, current_page_class
    ):
        """Toggle footer visibility and fullscreen mode when buttons are clicked."""
        from dash import callback_context

        ctx = callback_context
        if not ctx.triggered:
            return current_footer_class or "", current_page_class or ""

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"Notes footer triggered by: {trigger_id}")
        logger.info(
            f"Toggle clicks: {toggle_clicks}, Collapse clicks: {collapse_clicks}, Fullscreen clicks: {fullscreen_clicks}"
        )

        current_footer_class = current_footer_class or ""
        current_page_class = current_page_class or ""

        logger.info(
            f"Current footer class: '{current_footer_class}', page class: '{current_page_class}'"
        )

        if trigger_id == "toggle-notes-button":
            if (
                "footer-visible" in current_footer_class
                or "footer-fullscreen" in current_footer_class
            ):
                # Hide footer completely
                new_page_class = current_page_class.replace("notes-fullscreen", "").strip()
                logger.info(f"Hiding footer. New classes: footer='', page='{new_page_class}'")
                return "", new_page_class
            else:
                # Show footer in normal mode
                logger.info(
                    f"Showing footer in normal mode. New classes: footer='footer-visible', page='{current_page_class}'"
                )
                return "footer-visible", current_page_class

        elif trigger_id == "collapse-notes-button" and collapse_clicks:
            # Collapse button always hides the footer if it's visible
            if (
                "footer-visible" in current_footer_class
                or "footer-fullscreen" in current_footer_class
            ):
                # Hide footer completely
                new_page_class = current_page_class.replace("notes-fullscreen", "").strip()
                logger.info(f"Collapsing footer. New classes: footer='', page='{new_page_class}'")
                return "", new_page_class
            else:
                # If footer is not visible, do nothing
                logger.info("Footer already collapsed, no action needed")
                return current_footer_class, current_page_class

        elif trigger_id == "fullscreen-notes-button" and fullscreen_clicks:
            if "footer-fullscreen" in current_footer_class:
                # Exit fullscreen, go to normal footer mode
                new_page_class = current_page_class.replace("notes-fullscreen", "").strip()
                logger.info(
                    f"Exiting fullscreen. New classes: footer='footer-visible', page='{new_page_class}'"
                )
                return "footer-visible", new_page_class
            else:
                # Enter fullscreen mode (only if footer is currently visible)
                if "footer-visible" in current_footer_class:
                    new_page_class = f"{current_page_class} notes-fullscreen".strip()
                    logger.info(
                        f"Entering fullscreen. New classes: footer='footer-fullscreen', page='{new_page_class}'"
                    )
                    return "footer-fullscreen", new_page_class
                else:
                    # If footer is not visible, show it first in normal mode
                    logger.info("Footer not visible, showing in normal mode first")
                    return "footer-visible", current_page_class

        logger.info(
            f"No action taken. Returning current classes: footer='{current_footer_class}', page='{current_page_class}'"
        )
        return current_footer_class, current_page_class

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

    # Update button icons based on footer state
    @app.callback(
        [
            Output("toggle-notes-button", "children"),
            Output("collapse-notes-button", "children"),
            Output("fullscreen-notes-button", "children"),
        ],
        Input("notes-footer-content", "className"),
        prevent_initial_call=True,
    )
    def update_button_icons(footer_class):
        """Update button icons based on footer visibility and fullscreen state."""
        footer_class = footer_class or ""

        # Toggle button icon (for the main toggle button in the UI)
        if "footer-visible" in footer_class or "footer-fullscreen" in footer_class:
            toggle_icon = DashIconify(icon="material-symbols:expand-more", width=35, color="gray")
        else:
            toggle_icon = DashIconify(icon="material-symbols:edit-note", width=35, color="gray")

        # Collapse button icon (points down when footer is open, indicating collapse action)
        collapse_icon = DashIconify(icon="material-symbols:expand-more", width=20, color="gray")

        # Fullscreen button icon
        if "footer-fullscreen" in footer_class:
            fullscreen_icon = DashIconify(
                icon="material-symbols:close-fullscreen", width=20, color="gray"
            )
        else:
            fullscreen_icon = DashIconify(
                icon="material-symbols:fullscreen", width=20, color="gray"
            )

        return toggle_icon, collapse_icon, fullscreen_icon


def create_notes_footer(dashboard_data=None):
    """Create the notes footer component with RichTextEditor."""
    # Load existing notes content if available
    initial_notes_content = "<p>Start writing your notes, documentation, or analysis here...</p><p><br></p><p><br></p><p><br></p>"
    if dashboard_data and dashboard_data.get("notes_content"):
        initial_notes_content = dashboard_data["notes_content"]

    return html.Div(
        [
            # Simple header with fullscreen button
            html.Div(
                [
                    dmc.Group(
                        [
                            # Left side - Title
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
                                align="center",
                            ),
                            # Right side - Toggle collapse and Fullscreen buttons
                            dmc.Group(
                                [
                                    dmc.ActionIcon(
                                        DashIconify(
                                            icon="material-symbols:expand-more",
                                            width=20,
                                            color="gray",
                                        ),
                                        id="collapse-notes-button",
                                        variant="subtle",
                                        color="gray",
                                        size="sm",
                                    ),
                                    dmc.ActionIcon(
                                        DashIconify(
                                            icon="material-symbols:fullscreen",
                                            width=20,
                                            color="gray",
                                        ),
                                        id="fullscreen-notes-button",
                                        variant="subtle",
                                        color="gray",
                                        size="sm",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        justify="space-between",
                        align="center",
                        style={"width": "100%"},
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
                        style={"maxHeight": "250px", "overflowY": "auto"},
                        # style={"minHeight": "200px", "maxHeight": "250px", "overflowY": "auto"},
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
        className="",  # Explicitly start with empty className to ensure it's hidden
    )
