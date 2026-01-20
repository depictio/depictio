"""
Simple DMC-native theme management for Depictio.

This replaces the complex CSS-based theme system with DMC's built-in theming.
Uses MantineProvider's forceColorScheme for native theme support.
"""

import dash_mantine_components as dmc
from dash import Input, Output, State
from dash_iconify import DashIconify


def create_theme_switch():
    """Create the theme switch component using DMC styling."""
    return dmc.Switch(
        id="theme-switch",
        size="lg",
        onLabel=DashIconify(icon="ph:sun-fill", width=16),
        offLabel=DashIconify(icon="ph:moon-fill", width=16),
        styles={
            "root": {"marginBottom": "10px"},
        },
    )


def create_auto_theme_button():
    """Create a button to reset theme to system preference."""
    return dmc.Button(
        "🔄 Auto",
        id="auto-theme-button",
        variant="subtle",
        size="xs",
        styles={
            "root": {
                "marginTop": "5px",
                "display": "none",  # Hidden by default
            }
        },
    )


def create_theme_controls():
    """Create complete theme control group."""
    return dmc.Stack(
        [
            create_theme_switch(),
            create_auto_theme_button(),
        ],
        gap="xs",
        align="center",
    )


def register_simple_theme_system(app):
    """Register the simplified DMC-native theme management system."""

    from depictio.api.v1.configs.logging_init import logger

    dmc.add_figure_templates()  # type: ignore[unresolved-attribute]

    # Move theme callbacks to clientside for instant response
    app.clientside_callback(
        """
        function(theme_data) {
            console.log('🔥 CLIENTSIDE THEME: Setting MantineProvider.forceColorScheme to', theme_data || 'light');
            return theme_data || 'light';
        }
        """,
        Output("mantine-provider", "forceColorScheme"),
        Input("theme-store", "data"),
        prevent_initial_call=False,
    )

    # Sync switch state with current theme - clientside
    app.clientside_callback(
        """
        function(theme_data) {
            console.log('🔧 CLIENTSIDE THEME SWITCH: Setting checked to', theme_data === 'dark');
            return theme_data === 'dark';
        }
        """,
        Output("theme-switch", "checked"),
        Input("theme-store", "data"),
        prevent_initial_call=False,
    )

    # Handle manual theme switch - dcc.Store handles localStorage automatically
    app.clientside_callback(
        """
        function(checked, current_theme) {
            // CRITICAL: If checked is undefined/null, the switch component doesn't have a valid state yet
            // This happens when the component is being recreated during navigation
            if (checked === undefined || checked === null) {
                console.log('🚫 Switch state is undefined/null - ignoring spurious callback during component recreation');
                return window.dash_clientside.no_update;
            }

            const newTheme = checked ? 'dark' : 'light';

            console.log('🎨 Theme switch callback fired - checked:', checked, 'newTheme:', newTheme, 'current_theme:', current_theme);

            // Only update if theme is actually changing
            // This prevents spurious updates when switch is reset on page navigation
            if (newTheme === current_theme) {
                console.log('🚫 Theme unchanged - skipping update to prevent reset loop');
                return window.dash_clientside.no_update;
            }

            console.log('✅ Theme changed from', current_theme, 'to', newTheme);

            // No need to manually write to localStorage - dcc.Store with storage_type="local" handles this
            // Theme will be automatically persisted and reloaded by Dash

            return newTheme;
        }
        """,
        Output("theme-store", "data", allow_duplicate=True),
        Input("theme-switch", "checked"),
        State("theme-store", "data"),
        prevent_initial_call=True,
    )

    # Re-apply theme on URL navigation to ensure MantineProvider stays synchronized
    app.clientside_callback(
        """
        function(pathname, theme_data) {
            console.log('🔄 URL Navigation triggered for path:', pathname);
            console.log('🔄 Theme data from State:', theme_data, 'Type:', typeof theme_data);

            // IMPORTANT: Only update if we have a valid theme value
            // This prevents accidentally resetting to 'light' on navigation

            let theme = theme_data;

            // If theme_data is undefined/null/empty string, check localStorage directly
            if (!theme) {
                console.warn('⚠️ theme_data is falsy, checking localStorage directly');
                const storageKey = 'theme-store';  // dcc.Store uses component ID as localStorage key
                const storedData = localStorage.getItem(storageKey);
                console.log('📦 localStorage raw value:', storedData);

                if (storedData) {
                    try {
                        // dcc.Store stores JSON, so parse it
                        const parsed = JSON.parse(storedData);
                        theme = parsed;
                        console.log('✅ Successfully loaded theme from localStorage:', theme);
                    } catch (e) {
                        console.error('❌ Failed to parse localStorage data:', e);
                        // Don't update - let existing theme stay
                        console.log('🚫 Not updating - keeping existing MantineProvider theme');
                        return window.dash_clientside.no_update;
                    }
                } else {
                    console.warn('⚠️ No localStorage data found');
                    // Don't update - let existing theme stay (don't force default to light)
                    console.log('🚫 Not updating - keeping existing MantineProvider theme');
                    return window.dash_clientside.no_update;
                }
            }

            // Only update if we have a valid theme string
            if (theme === 'light' || theme === 'dark') {
                console.log('✅ Applying theme:', theme);
                return theme;
            } else {
                console.error('❌ Invalid theme value:', theme);
                console.log('🚫 Not updating - keeping existing MantineProvider theme');
                return window.dash_clientside.no_update;
            }
        }
        """,
        Output("mantine-provider", "forceColorScheme", allow_duplicate=True),
        Input("url", "pathname"),
        State("theme-store", "data"),
        prevent_initial_call=True,
    )

    # Initialize theme from localStorage or system preference
    # clientside_callback(
    #     """
    #     function() {
    #         console.log('🎨 Simple theme initialization');

    #         // Check saved preference
    #         const savedTheme = localStorage.getItem('depictio-theme');
    #         if (savedTheme) {
    #             console.log('Using saved theme:', savedTheme);
    #             return savedTheme;
    #         }

    #         // Use system preference
    #         const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    #         const systemTheme = prefersDark ? 'dark' : 'light';
    #         console.log('Using system theme:', systemTheme);

    #         // Save as initial preference
    #         localStorage.setItem('depictio-theme', systemTheme);

    #         return systemTheme;
    #     }
    #     """,
    #     Output("theme-store", "data", allow_duplicate=True),
    #     Input("url", "pathname"),  # Trigger on page load
    #     prevent_initial_call=True,
    # )

    # Handle auto theme button - reset to system preference
    # clientside_callback(
    #     """
    #     function(n_clicks) {
    #         if (!n_clicks) {
    #             return window.dash_clientside.no_update;
    #         }

    #         console.log('🎨 Resetting to auto theme');

    #         // Remove manual override
    #         localStorage.removeItem('depictio-theme-manual-override');

    #         // Get system theme
    #         const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    #         const systemTheme = prefersDark ? 'dark' : 'light';

    #         // Save system theme
    #         localStorage.setItem('depictio-theme', systemTheme);

    #         return systemTheme;
    #     }
    #     """,
    #     Output("theme-store", "data", allow_duplicate=True),
    #     Input("auto-theme-button", "n_clicks"),
    #     prevent_initial_call=True,
    # )

    # Theme-aware logo callback - shared logic for all logos
    # Uses a single JavaScript function to update multiple logo elements
    logo_callback_js = """
        function(theme_data) {
            const theme = theme_data || 'light';
            return theme === 'dark'
                ? '/assets/images/logos/logo_white.svg'
                : '/assets/images/logos/logo_black.svg';
        }
    """

    # Register logo callbacks for each logo element
    logo_outputs = [
        "navbar-logo-content",
        "header-powered-by-logo",
        "auth-modal-logo-login",
        "auth-modal-logo-register",
    ]

    for logo_id in logo_outputs:
        app.clientside_callback(
            logo_callback_js,
            Output(logo_id, "src"),
            Input("theme-store", "data"),
            prevent_initial_call=False,
        )

    # Disable theme switch on dashboard pages only
    # @app.callback(
    #     Output("theme-switch", "disabled"),
    #     Input("url", "pathname"),
    #     prevent_initial_call=False,
    # )
    # def disable_theme_switch_on_dashboard(pathname):
    #     """Disable theme switch only on dashboard pages."""
    #     return pathname and pathname.startswith("/dashboard/")

    # Disable clientside Plotly template update - let server-side Patch handle it
    # clientside_callback(
    #     """
    #     function(theme_data) {
    #         const theme = theme_data || 'light';

    #         // Use mantine templates added by dmc.add_figure_templates()
    #         const template = theme === 'dark' ? 'mantine_dark' : 'mantine_light';

    #         console.log('🎨 PLOTLY THEME UPDATE: Setting template to', template, 'for theme:', theme);

    #         // Simple Plotly template update
    #         if (window.Plotly) {
    #             // Find and update all Plotly graphs
    #             const graphs = document.querySelectorAll('.js-plotly-plot');
    #             console.log('🔍 Found', graphs.length, 'Plotly graphs to update');

    #             graphs.forEach((graph, index) => {
    #                 try {
    #                     window.Plotly.relayout(graph, {
    #                         'template': template
    #                     });
    #                     console.log('✅ Updated graph', index, 'with template:', template);
    #                 } catch (e) {
    #                     console.log('❌ Could not update graph', index, 'template:', e);
    #                 }
    #             });
    #         }

    #         return window.dash_clientside.no_update;
    #     }
    #     """,
    #     Output("dummy-plotly-output", "children", allow_duplicate=True),
    #     Input("theme-store", "data"),
    #     prevent_initial_call=True,
    # )

    logger.info("🔥 THEME SYSTEM: Simple DMC-native theme system registered")
