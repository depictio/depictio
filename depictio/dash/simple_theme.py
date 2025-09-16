"""
Simple DMC-native theme management for Depictio.

This replaces the complex CSS-based theme system with DMC's built-in theming.
Uses MantineProvider's forceColorScheme for native theme support.
"""

import dash_mantine_components as dmc
from dash import Input, Output, clientside_callback
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
        prevent_initial_call=True,
    )

    # Handle manual theme switch with localStorage storage
    clientside_callback(
        """
        function(checked) {
            const theme = checked ? 'dark' : 'light';

            console.log('🎨 Manual theme switch:', theme);

            // Store preference in localStorage
            localStorage.setItem('depictio-theme', theme);
            localStorage.setItem('depictio-theme-manual-override', 'true');

            return theme;
        }
        """,
        Output("theme-store", "data", allow_duplicate=True),
        Input("theme-switch", "checked"),
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

    # Update navbar logo based on theme (minimal styling needed)
    @app.callback(
        Output("navbar-logo-content", "src"),
        Input("theme-store", "data"),
        prevent_initial_call=False,
    )
    def update_navbar_logo(theme_data):
        """Update navbar logo for theme."""
        import dash

        theme = theme_data or "light"
        logo_src = dash.get_asset_url(
            "images/logos/logo_white.svg" if theme == "dark" else "images/logos/logo_black.svg"
        )
        return logo_src

    # Disable theme switch on dashboard pages only
    # @app.callback(
    #     Output("theme-switch", "disabled"),
    #     Input("url", "pathname"),
    #     prevent_initial_call=False,
    # )
    # def disable_theme_switch_on_dashboard(pathname):
    #     """Disable theme switch only on dashboard pages."""
    #     return pathname and pathname.startswith("/dashboard/")

    # Simple Plotly template update (replace complex JS approach)
    # clientside_callback(
    #     """
    #     function(theme_data) {
    #         const theme = theme_data || 'light';

    #         // Simple Plotly template update
    #         if (window.Plotly) {
    #             const template = theme === 'dark' ? 'plotly_dark' : 'plotly_white';

    #             // Find and update all Plotly graphs
    #             const graphs = document.querySelectorAll('.js-plotly-plot');
    #             graphs.forEach(graph => {
    #                 try {
    #                     window.Plotly.relayout(graph, {
    #                         'template': template
    #                     });
    #                 } catch (e) {
    #                     console.log('Could not update graph template:', e);
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
