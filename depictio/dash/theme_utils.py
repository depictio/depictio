"""Theme utilities for Depictio Dash application"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output
from dash_iconify import DashIconify


def create_theme_switch():
    """Create the theme switch component"""
    return dmc.Switch(
        id="theme-switch",
        size="lg",
        onLabel=DashIconify(icon="ph:sun-fill", width=16),  # Dark mode ON = show sun
        offLabel=DashIconify(icon="ph:moon-fill", width=16),  # Light mode OFF = show moon
        style={"marginBottom": "10px"},
    )


def register_theme_callbacks(app):
    """Register theme-related callbacks"""

    # Add Mantine figure templates for Plotly when theme system initializes
    dmc.add_figure_templates()

    # Initialize theme based on system preference (following DMC demo pattern)
    app.clientside_callback(
        """
        function(pathname) {
            // Manage page classes for FOUC prevention
            const body = document.body;

            // Check if this is an auth page
            const isAuthPage = pathname === '/auth' || document.getElementById('auth-background');

            if (isAuthPage) {
                body.classList.add('auth-page');
                body.classList.remove('page-loaded');
            } else {
                body.classList.remove('auth-page');
                // Small delay to ensure content is loaded
                setTimeout(() => {
                    body.classList.add('page-loaded');
                }, 50);
            }

            // Check for saved theme preference first
            const savedTheme = localStorage.getItem('depictio-theme');
            if (savedTheme) {
                return savedTheme;
            }

            // Otherwise check system preference
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            return prefersDark ? 'dark' : 'light';
        }
        """,
        Output("theme-store", "data"),
        Input("url", "pathname"),
        prevent_initial_call=False,
    )

    # Update switch state based on theme store
    @app.callback(
        Output("theme-switch", "checked"),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )
    def sync_switch_state(theme_data):
        return theme_data == "dark"

    # Handle theme switch toggle (following DMC demo pattern)
    app.clientside_callback(
        """
        function(checked) {
            const theme = checked ? 'dark' : 'light';

            console.log('=== THEME SWITCH DEBUG ===');
            console.log('Switch checked:', checked);
            console.log('Theme switch clicked! New theme:', theme);
            console.log('Storing in localStorage:', theme);

            // Store theme preference
            localStorage.setItem('depictio-theme', theme);

            console.log('localStorage after set:', localStorage.getItem('depictio-theme'));

            return theme;
        }
        """,
        Output("theme-store", "data", allow_duplicate=True),
        Input("theme-switch", "checked"),
        prevent_initial_call=True,
    )

    # Update MantineProvider based on theme store (following DMC demo pattern)
    @app.callback(
        Output("mantine-provider", "forceColorScheme"),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )
    def update_mantine_theme(theme_data):
        return theme_data or "light"

    # Update navbar logo based on theme
    @app.callback(
        Output("navbar-logo-content", "src"),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )
    def update_navbar_logo(theme_data):
        theme = theme_data or "light"
        logo_src = dash.get_asset_url("logo_white.svg" if theme == "dark" else "logo_black.svg")
        return logo_src

    # Update auth modal logos with client-side callback
    app.clientside_callback(
        """
        function(theme_data) {
            const theme = theme_data || 'light';
            const logoSrc = theme === 'dark' ? '/assets/logo_white.svg' : '/assets/logo_black.svg';

            // Update login logo if it exists
            const loginLogo = document.getElementById('auth-modal-logo-login');
            if (loginLogo) {
                loginLogo.src = logoSrc;
            }

            // Update register logo if it exists
            const registerLogo = document.getElementById('auth-modal-logo-register');
            if (registerLogo) {
                registerLogo.src = logoSrc;
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output("auth-modal-logo-login", "src", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )

    # Update Plotly figure templates when theme changes using Mantine templates
    app.clientside_callback(
        """
        function(theme_data) {
            console.log('📊 === PLOTLY MANTINE THEME UPDATE ===');
            console.log('Theme data received:', theme_data);

            try {
                const theme = theme_data || 'light';
                const template = theme === 'dark' ? 'mantine_dark' : 'mantine_light';
                console.log('Using Mantine template:', template);

                // Check if Plotly is available
                if (!window.Plotly) {
                    console.log('Plotly not available, skipping update');
                    return window.dash_clientside.no_update;
                }

                console.log('Plotly available, proceeding with Mantine template update');

                // Find graphs and force complete redraw
                const graphs = document.querySelectorAll('.js-plotly-plot');
                console.log('Found', graphs.length, 'Plotly graphs');

                if (graphs.length === 0) {
                    console.log('No graphs found, skipping update');
                    return window.dash_clientside.no_update;
                }

                // Use minimal delay to ensure graphs are ready but keep it responsive
                setTimeout(() => {
                    graphs.forEach(async (graph, index) => {
                        console.log(`Processing graph ${index} with template: ${template}`);

                        try {
                            // Get current data and layout
                            const currentData = graph.data || [];
                            const currentLayout = graph.layout || {};

                            // Create new layout with Mantine template
                            const newLayout = {
                                ...currentLayout,
                                template: template,
                                // Let Mantine templates handle the colors
                            };

                            console.log(`New layout for graph ${index}:`, newLayout);

                            // Use newPlot for complete recreation with Mantine template
                            await window.Plotly.newPlot(graph, currentData, newLayout, {
                                responsive: true,
                                displayModeBar: true
                            });

                            console.log(`✅ Plotly.newPlot completed for graph ${index} with ${template}`);

                            // Verify the update worked
                            console.log('Final layout template:', graph.layout?.template);

                        } catch (err) {
                            console.error(`❌ Error updating graph ${index}:`, err);

                            // Fallback: try simpler relayout approach
                            try {
                                console.log(`Trying fallback relayout for graph ${index}`);
                                await window.Plotly.relayout(graph, {
                                    'template': template
                                });
                                console.log(`✅ Fallback relayout completed for graph ${index}`);
                            } catch (fallbackErr) {
                                console.error(`❌ Fallback also failed for graph ${index}:`, fallbackErr);
                            }
                        }
                    });
                }, 10); // Small delay to ensure DOM is ready

                console.log('📊 === PLOTLY MANTINE THEME UPDATE END ===');
                return window.dash_clientside.no_update;

            } catch (error) {
                console.error('❌ Plotly theme callback error:', error);
                return window.dash_clientside.no_update;
            }
        }
        """,
        Output("dummy-plotly-output", "children", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )

    # Client-side callback for theme updates - single modular callback with working NavLink icon handling
    app.clientside_callback(
        """
        function(theme_data) {
            // === MODULAR JAVASCRIPT FUNCTIONS ===

            // Function to safely apply styles with error handling
            function safeApplyStyles(element, styles) {
                if (!element) return false;
                try {
                    Object.keys(styles).forEach(prop => {
                        element.style.setProperty(prop, styles[prop], 'important');
                    });
                    return true;
                } catch (error) {
                    console.error('Error applying styles:', error);
                    return false;
                }
            }

            // Function to handle NavLink icon theming (from working debug app)
            function updateNavLinkIcons(theme) {
                const iconColor = theme === 'dark' ? '#ffffff' : '#000000';
                console.log(`🎨 Updating NavLink icons for theme: ${theme}, color: ${iconColor}`);

                try {
                    // Find all NavLinks with pattern matching support
                    const navLinks = document.querySelectorAll('.mantine-NavLink-root, [data-mantine="NavLink"]');
                    console.log(`Found ${navLinks.length} NavLinks`);

                    navLinks.forEach((navLink, index) => {
                        const isActive = navLink.getAttribute('data-active') === 'true';
                        const icons = navLink.querySelectorAll('svg, [class*="iconify"], .iconify');

                        console.log(`NavLink ${index}: active=${isActive}, icons=${icons.length}`);

                        icons.forEach(icon => {
                            if (isActive) {
                                // Active NavLink: clear forced styles to show original color
                                icon.style.color = '';
                                icon.style.fill = '';
                                console.log('  🟠 Preserved active NavLink icon color');
                            } else {
                                // Inactive NavLink: use theme color
                                icon.style.color = iconColor + ' !important';
                                icon.style.fill = iconColor + ' !important';
                                console.log(`  ⚫⚪ Applied theme color: ${iconColor}`);
                            }

                            // Handle SVG paths
                            if (icon.tagName === 'SVG') {
                                const paths = icon.querySelectorAll('path');
                                paths.forEach(path => {
                                    if (!isActive) {
                                        path.style.fill = iconColor + ' !important';
                                    } else {
                                        path.style.fill = 'currentColor';
                                    }
                                });
                            }
                        });
                    });

                    return true;
                } catch (error) {
                    console.error('❌ NavLink icon update error:', error);
                    return false;
                }
            }

            // Function to inject comprehensive CSS styles
            function injectThemeCSS(theme, textColor, backgroundColor) {
                let themeStyleElement = document.getElementById('dynamic-theme-styles');
                if (!themeStyleElement) {
                    themeStyleElement = document.createElement('style');
                    themeStyleElement.id = 'dynamic-theme-styles';
                    document.head.appendChild(themeStyleElement);
                }

                const themeCSS = `
                    /* Core theme elements */
                    #page-content {
                        background-color: ${backgroundColor} !important;
                        color: ${textColor} !important;
                    }

                    /* Headers - fix visibility in dark mode */
                    #header-content,
                    .mantine-AppShell-header {
                        background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                        color: ${textColor} !important;
                    }

                    /* Header text elements */
                    #header-content .mantine-Text-root,
                    #header-content [data-mantine="Text"],
                    .mantine-AppShell-header .mantine-Text-root,
                    .mantine-AppShell-header [data-mantine="Text"] {
                        color: ${textColor} !important;
                    }

                    /* Dashboard title */
                    #dashboard-title,
                    #header-content [data-mantine="Title"],
                    .mantine-AppShell-header [data-mantine="Title"] {
                        color: ${textColor} !important;
                    }

                    /* Sidebar */
                    #sidebar,
                    .mantine-AppShell-navbar {
                        background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                    }

                    /* NavLink labels - only fix dark mode visibility */
                    ${theme === 'dark' ? `
                    #sidebar .mantine-NavLink-label,
                    #sidebar .mantine-NavLink-root .mantine-Text-root,
                    #sidebar [data-mantine="NavLink"] .mantine-Text-root,
                    .mantine-AppShell-navbar .mantine-NavLink-label,
                    .mantine-AppShell-navbar .mantine-NavLink-root .mantine-Text-root,
                    .mantine-AppShell-navbar [data-mantine="NavLink"] .mantine-Text-root {
                        color: #C1C2C5 !important;
                    }

                    /* NavLink icons - only inactive ones should use theme color in dark mode */
                    #sidebar .mantine-NavLink-root:not(.mantine-NavLink-active) .iconify,
                    #sidebar .mantine-NavLink-root:not(.mantine-NavLink-active) [class*="iconify"],
                    #sidebar .mantine-NavLink-root:not(.mantine-NavLink-active) svg,
                    .mantine-AppShell-navbar .mantine-NavLink-root:not(.mantine-NavLink-active) .iconify,
                    .mantine-AppShell-navbar .mantine-NavLink-root:not(.mantine-NavLink-active) [class*="iconify"],
                    .mantine-AppShell-navbar .mantine-NavLink-root:not(.mantine-NavLink-active) svg {
                        color: #C1C2C5 !important;
                        fill: #C1C2C5 !important;
                    }` : ''}

                    /* Avatar container text - fix visibility in dark mode */
                    #sidebar .mantine-Avatar-root + *,
                    #sidebar .mantine-Avatar-root ~ *,
                    .mantine-AppShell-navbar .mantine-Avatar-root + *,
                    .mantine-AppShell-navbar .mantine-Avatar-root ~ * {
                        color: ${textColor} !important;
                    }

                    /* Avatar text containers */
                    #sidebar [id*="avatar"] .mantine-Text-root,
                    #sidebar [class*="avatar"] .mantine-Text-root,
                    .mantine-AppShell-navbar [id*="avatar"] .mantine-Text-root,
                    .mantine-AppShell-navbar [class*="avatar"] .mantine-Text-root {
                        color: ${textColor} !important;
                    }

                    /* Draggable boxes - ResponsiveGridLayout items */
                    .react-grid-item,
                    .react-grid-item .card,
                    .react-grid-item [data-mantine="Card"],
                    #draggable .react-grid-item,
                    #draggable .react-grid-item > *,
                    #draggable .react-grid-item [class*="Card"] {
                        background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                        color: ${textColor} !important;
                    }

                    /* Draggable box content */
                    .react-grid-item .mantine-Text-root,
                    .react-grid-item [data-mantine="Text"],
                    #draggable .react-grid-item .mantine-Text-root,
                    #draggable .react-grid-item [data-mantine="Text"] {
                        color: ${textColor} !important;
                    }

                    /* Bootstrap card components in draggable items */
                    .react-grid-item .card-body,
                    .react-grid-item .card-header,
                    #draggable .card,
                    #draggable .card-body,
                    #draggable .card-header {
                        background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                        color: ${textColor} !important;
                    }

                    /* Profile text */
                    #user-info-placeholder .mantine-Text-root {
                        color: ${textColor} !important;
                    }

                    /* Dashboard offcanvas - Bootstrap component theming */
                    #offcanvas-parameters,
                    .dashboard-offcanvas,
                    .offcanvas {
                        background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                        color: ${textColor} !important;
                    }

                    /* Offcanvas header */
                    #offcanvas-parameters .offcanvas-header,
                    .dashboard-offcanvas .offcanvas-header,
                    .offcanvas .offcanvas-header {
                        background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                        color: ${textColor} !important;
                        border-bottom: 1px solid ${theme === 'dark' ? '#373A40' : '#dee2e6'} !important;
                    }

                    /* Offcanvas body */
                    #offcanvas-parameters .offcanvas-body,
                    .dashboard-offcanvas .offcanvas-body,
                    .offcanvas .offcanvas-body {
                        background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                        color: ${textColor} !important;
                    }

                    /* Offcanvas title */
                    #offcanvas-parameters .offcanvas-title,
                    .dashboard-offcanvas .offcanvas-title,
                    .offcanvas .offcanvas-title {
                        color: ${textColor} !important;
                    }

                    /* Offcanvas close button */
                    #offcanvas-parameters .btn-close,
                    .dashboard-offcanvas .btn-close,
                    .offcanvas .btn-close {
                        filter: ${theme === 'dark' ? 'invert(1) grayscale(100%) brightness(200%)' : 'none'} !important;
                    }

                    /* DMC Select component theming */
                    ${theme === 'dark' ? `
                    /* Select dropdown background and border */
                    .mantine-Select-dropdown {
                        background-color: #25262b !important;
                        border-color: #373A40 !important;
                    }
                    
                    /* Select options */
                    .mantine-Select-option {
                        background-color: #25262b !important;
                        color: #C1C2C5 !important;
                    }
                    
                    /* Select option hover state */
                    .mantine-Select-option:hover,
                    .mantine-Select-option[data-hovered="true"] {
                        background-color: #373A40 !important;
                        color: #ffffff !important;
                    }
                    
                    /* Select option selected state */
                    .mantine-Select-option[data-selected="true"] {
                        background-color: #228be6 !important;
                        color: #ffffff !important;
                    }
                    
                    /* Select input field */
                    .mantine-Select-input {
                        background-color: #25262b !important;
                        border-color: #373A40 !important;
                        color: #C1C2C5 !important;
                    }
                    
                    /* Select input placeholder */
                    .mantine-Select-input::placeholder {
                        color: #909296 !important;
                    }
                    
                    /* Select label */
                    .mantine-Select-label {
                        color: #C1C2C5 !important;
                    }
                    
                    /* Select description */
                    .mantine-Select-description {
                        color: #909296 !important;
                    }
                    ` : ''}
                `;

                themeStyleElement.textContent = themeCSS;
                console.log('✅ Injected comprehensive theme CSS');
                return true;
            }

            // === MAIN CALLBACK EXECUTION ===
            console.log('🎨 === THEME CALLBACK START ===');
            console.log('Input theme_data:', theme_data);

            try {
                const theme = theme_data || 'light';
                const textColor = theme === 'dark' ? '#ffffff' : '#000000';
                const backgroundColor = theme === 'dark' ? '#1a1b1e' : '#ffffff';

                console.log('Resolved theme:', theme);
                console.log('Colors - text:', textColor, 'background:', backgroundColor);

                // Update page-content with safe style application
                const pageContent = document.getElementById('page-content');
                if (pageContent) {
                    safeApplyStyles(pageContent, {
                        'background-color': backgroundColor,
                        'color': textColor
                    });
                    console.log('✅ Applied styles to page-content');
                }

                // Update titles with safe style application
                const allTitles = document.querySelectorAll('h1, h2, h3, h4, h5, h6, [data-mantine="Title"]');
                console.log(`Found ${allTitles.length} title elements`);
                allTitles.forEach((title, index) => {
                    safeApplyStyles(title, {
                        'color': textColor,
                        'fill': textColor
                    });
                });

                // Update NavLink icons with the working solution from debug app
                updateNavLinkIcons(theme);

                // Update headers
                const headerContent = document.getElementById('header-content');
                if (headerContent) {
                    safeApplyStyles(headerContent, {
                        'background-color': backgroundColor
                    });
                }

                const appShellHeaders = document.querySelectorAll('.mantine-AppShell-header');
                appShellHeaders.forEach(header => {
                    safeApplyStyles(header, {
                        'background-color': backgroundColor
                    });
                });

                // Update project management header elements
                const projectHeader = document.getElementById('permissions-manager-project-header');
                if (projectHeader) {
                    safeApplyStyles(projectHeader, {
                        'background-color': backgroundColor,
                        'color': textColor
                    });
                }
                
                const projectTitle = document.getElementById('permissions-manager-project-title');
                if (projectTitle) {
                    safeApplyStyles(projectTitle, {
                        'color': textColor
                    });
                }
                
                const projectDetails = document.getElementById('permissions-manager-project-details');
                if (projectDetails) {
                    safeApplyStyles(projectDetails, {
                        'color': textColor
                    });
                }

                // Inject comprehensive CSS styles
                injectThemeCSS(theme, textColor, backgroundColor);

                // Set CSS custom properties for broader coverage
                document.documentElement.style.setProperty('--app-bg-color', backgroundColor);
                document.documentElement.style.setProperty('--app-text-color', textColor);

                console.log('🎨 === THEME CALLBACK END ===');

                // Return the new background color for page-content
                return {
                    'background-color': backgroundColor + ' !important',
                    'color': textColor + ' !important'
                };

            } catch (error) {
                console.error('❌ Theme callback error:', error);
                return window.dash_clientside.no_update;
            }
        }
        """,
        Output("page-content", "style", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )


# Note: DMC figure templates are now loaded via dmc.add_figure_templates()
# They are applied both during figure creation and via client-side updates
# Templates used: "mantine_light" and "mantine_dark"
