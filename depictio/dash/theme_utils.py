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
        onLabel=DashIconify(icon="ph:moon-fill", width=16),
        offLabel=DashIconify(icon="ph:sun-fill", width=16),
        style={"marginBottom": "10px"},
    )


def register_theme_callbacks(app):
    """Register theme-related callbacks"""

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
            
            console.log('Theme switch clicked! New theme:', theme);
            
            // Store theme preference
            localStorage.setItem('depictio-theme', theme);
            
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

    # Update all figure templates based on theme using client-side callback
    app.clientside_callback(
        """
        function(theme_data) {
            console.log('=== PLOTLY THEME UPDATE START ===');
            
            const theme = theme_data || 'light';
            const template = theme === 'dark' ? 'plotly_dark' : 'plotly_white';
            
            console.log('Plotly theme:', theme, 'template:', template);
            
            // Find all Plotly graphs and update their templates
            // Try multiple selectors to find graphs
            const selectors = [
                '.js-plotly-plot',
                '[data-testid="graph"]',
                '.dash-graph',
                '[id*="graph"]'
            ];
            
            let graphs = [];
            selectors.forEach(selector => {
                const found = document.querySelectorAll(selector);
                console.log(`Selector "${selector}" found:`, found.length, 'graphs');
                graphs = graphs.concat(Array.from(found));
            });
            
            // Remove duplicates
            graphs = [...new Set(graphs)];
            console.log('Total unique Plotly graphs found:', graphs.length);
            
            // Wait a bit for graphs to fully load, then try again if none found
            if (graphs.length === 0) {
                console.log('No graphs found immediately, waiting 500ms and trying again...');
                setTimeout(() => {
                    const retryGraphs = document.querySelectorAll('.js-plotly-plot, .dash-graph, [id*="graph"]');
                    console.log('Retry found:', retryGraphs.length, 'graphs');
                    retryGraphs.forEach((graph, index) => {
                        if (graph && window.Plotly) {
                            console.log('Retry updating graph', index, 'template to', template);
                            const update = { 'template': template };
                            window.Plotly.relayout(graph, update).catch(err => {
                                console.log('Retry Plotly relayout error for graph', index, ':', err);
                            });
                        }
                    });
                }, 500);
            } else {
                graphs.forEach((graph, index) => {
                    if (window.Plotly && graph) {
                        console.log('Updating graph', index, 'template to', template);
                        console.log('Graph element:', graph);
                        console.log('Graph has layout:', !!graph.layout);
                        
                        if (window.Plotly && graph.layout) {
                            window.Plotly.relayout(graph, {'template': template});
                        }
                    }
                });
            }
            
            console.log('=== PLOTLY THEME UPDATE END ===');
            
            return window.dash_clientside.no_update;
        }
        """,
        Output("dummy-plotly-output", "children", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )

    # Client-side callback for theme updates - using page-content as reliable output
    app.clientside_callback(
        """
        function(theme_data) {
            console.log('=== THEME CALLBACK START ===');
            console.log('Input theme_data:', theme_data);
            
            const theme = theme_data || 'light';
            console.log('Resolved theme:', theme);
            
            const textColor = theme === 'dark' ? '#ffffff' : '#000000';
            const backgroundColor = theme === 'dark' ? '#1a1b1e' : '#ffffff';
            
            console.log('Colors - text:', textColor, 'background:', backgroundColor);
            
            // Force update page-content with direct styles
            const pageContent = document.getElementById('page-content');
            console.log('Page content element found:', !!pageContent);
            if (pageContent) {
                pageContent.style.backgroundColor = backgroundColor + ' !important';
                pageContent.style.color = textColor + ' !important';
                console.log('Applied styles to page-content');
            }
            
            // Update all possible title elements with stronger CSS override
            const allTitles = document.querySelectorAll('h1, h2, h3, h4, h5, h6, [data-mantine="Title"]');
            console.log('Found title elements:', allTitles.length);
            allTitles.forEach((title, index) => {
                title.style.setProperty('color', textColor, 'important');
                title.style.setProperty('fill', textColor, 'important');
                console.log('Updated title', index, 'current color:', window.getComputedStyle(title).color);
            });
            
            console.log('Theme callback executing with theme:', theme);
            
            // Try broader selectors for NavLinks
            const navLinkSelectors = [
                '[data-mantine="NavLink"]',
                '.mantine-NavLink-root', 
                '[class*="NavLink"]',
                '#sidebar a',
                '#sidebar-content *'
            ];
            
            let foundNavLinks = [];
            navLinkSelectors.forEach(selector => {
                const elements = document.querySelectorAll(selector);
                console.log(`Selector "${selector}" found:`, elements.length);
                foundNavLinks = foundNavLinks.concat(Array.from(elements));
            });
            
            // Update all NavLink-related elements
            foundNavLinks.forEach((link, index) => {
                console.log(`Processing NavLink ${index}:`, link.tagName, link.className);
                
                // Update the link itself
                link.style.color = textColor + ' !important';
                
                // Find and update all text content within
                const textElements = link.querySelectorAll('*');
                textElements.forEach(el => {
                    if (el.textContent && el.textContent.trim()) {
                        el.style.color = textColor + ' !important';
                    }
                });
                
                // Update icons within the link
                const icons = link.querySelectorAll('svg, [class*="iconify"], [class*="icon"]');
                icons.forEach(icon => {
                    icon.style.color = textColor + ' !important';
                    if (icon.tagName === 'SVG') {
                        icon.style.fill = textColor + ' !important';
                    }
                });
            });
            
            // Try broader selectors for Text elements
            const textSelectors = [
                '[data-mantine="Text"]',
                '.mantine-Text-root',
                '[class*="Text"]',
                '#sidebar span',
                '#sidebar div'
            ];
            
            textSelectors.forEach(selector => {
                const elements = document.querySelectorAll(selector);
                console.log(`Text selector "${selector}" found:`, elements.length);
                elements.forEach((text, index) => {
                    if (text.textContent && text.textContent.trim()) {
                        text.style.color = textColor + ' !important';
                        console.log(`Updated text element ${index}:`, text.textContent.substring(0, 20));
                    }
                });
            });
            
            // Simple header update
            const headerContent = document.getElementById('header-content');
            if (headerContent) {
                headerContent.style.setProperty('background-color', backgroundColor, 'important');
            }
            
            const appShellHeaders = document.querySelectorAll('.mantine-AppShell-header');
            appShellHeaders.forEach(header => {
                header.style.setProperty('background-color', backgroundColor, 'important');
            });
            
            // Inject CSS styles for stronger overrides
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
                
                /* Sidebar */
                #sidebar,
                .mantine-AppShell-navbar {
                    background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                }
                
                /* NavLinks - fix non-selected visibility in dark mode */
                #sidebar .mantine-NavLink-root,
                #sidebar [data-mantine="NavLink"],
                .mantine-AppShell-navbar .mantine-NavLink-root,
                .mantine-AppShell-navbar [data-mantine="NavLink"] {
                    color: ${textColor} !important;
                }
                
                /* NavLink labels and icons */
                #sidebar .mantine-NavLink-label,
                #sidebar .mantine-NavLink-root .mantine-Text-root,
                #sidebar [data-mantine="NavLink"] .mantine-Text-root,
                .mantine-AppShell-navbar .mantine-NavLink-label,
                .mantine-AppShell-navbar .mantine-NavLink-root .mantine-Text-root,
                .mantine-AppShell-navbar [data-mantine="NavLink"] .mantine-Text-root {
                    color: ${textColor} !important;
                }
                
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
                
                /* Draggable cards */
                .react-grid-item .card,
                .react-grid-item [data-mantine="Card"] {
                    background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                }
                
                /* Profile text */
                #user-info-placeholder .mantine-Text-root {
                    color: ${textColor} !important;
                }
            `;
            
            themeStyleElement.textContent = themeCSS;
            console.log('Injected dynamic CSS styles');
            
            // Set CSS custom properties for broader coverage
            document.documentElement.style.setProperty('--app-bg-color', backgroundColor);
            document.documentElement.style.setProperty('--app-text-color', textColor);
            
            console.log('=== THEME CALLBACK END ===');
            
            // Return the new background color for page-content
            return {
                'background-color': backgroundColor + ' !important',
                'color': textColor + ' !important'
            };
        }
        """,
        Output("page-content", "style", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )


# Note: DMC figure templates are available via plotly.io.templates
# They can be accessed as "mantine_light" and "mantine_dark"
