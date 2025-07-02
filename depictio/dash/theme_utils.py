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

    # Add Mantine figure templates for Plotly when theme system initializes
    try:
        dmc.add_figure_templates()
    except Exception as e:
        print(f"Warning: Could not add Mantine figure templates: {e}")
        # Fallback - use standard Plotly templates

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

            console.log('=== MANUAL THEME SWITCH DEBUG ===');
            console.log('Switch checked:', checked);
            console.log('Manual theme switch clicked! New theme:', theme);

            // Store theme preference with timestamp to indicate manual selection
            localStorage.setItem('depictio-theme', theme);
            localStorage.setItem('depictio-theme-timestamp', Date.now().toString());

            console.log('🔧 Stored manual theme preference:', theme);

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

    # Update auth modal logos and theme styling with client-side callback
    app.clientside_callback(
        """
        function(theme_data) {
            const theme = theme_data || 'light';
            const logoSrc = theme === 'dark' ? '/assets/logo_white.svg' : '/assets/logo_black.svg';

            console.log('🎨 Updating auth modal theme:', theme);

            // Update logos with retry mechanism for timing issues
            function updateLogos() {
                console.log('🔍 Looking for logo elements...');

                // Update login logo if it exists
                const loginLogo = document.getElementById('auth-modal-logo-login');
                if (loginLogo) {
                    console.log('🖼️ Found and updating login logo to:', logoSrc);
                    loginLogo.src = logoSrc;
                } else {
                    console.log('❌ Login logo element not found');
                }

                // Update register logo if it exists
                const registerLogo = document.getElementById('auth-modal-logo-register');
                if (registerLogo) {
                    console.log('🖼️ Found and updating register logo to:', logoSrc);
                    registerLogo.src = logoSrc;
                } else {
                    console.log('❌ Register logo element not found');
                }

                // Also try to find any img elements inside the auth modal
                const authModal = document.querySelector('.auth-modal-content');
                if (authModal) {
                    const allLogos = authModal.querySelectorAll('img[src*="logo"]');
                    console.log('🎯 Found', allLogos.length, 'logo images in auth modal');
                    allLogos.forEach((logo, index) => {
                        console.log(`🖼️ Updating logo ${index} from ${logo.src} to ${logoSrc}`);
                        logo.src = logoSrc;
                    });
                }
            }

            // Try immediately
            updateLogos();

            // Retry after a short delay in case elements aren't rendered yet
            setTimeout(updateLogos, 100);

            // Also retry when form changes (login/register switch)
            setTimeout(updateLogos, 500);

            // Set up mutation observer to catch when modal content changes
            const modalContent = document.querySelector('.auth-modal-content');
            if (modalContent && !modalContent.hasAttribute('data-logo-observer')) {
                modalContent.setAttribute('data-logo-observer', 'true');
                const observer = new MutationObserver(function(mutations) {
                    let shouldUpdate = false;
                    mutations.forEach(function(mutation) {
                        if (mutation.type === 'childList') {
                            // Check if any img elements were added/changed
                            mutation.addedNodes.forEach(function(node) {
                                if (node.nodeType === Node.ELEMENT_NODE) {
                                    if (node.tagName === 'IMG' || node.querySelector('img')) {
                                        shouldUpdate = true;
                                    }
                                }
                            });
                        }
                    });
                    if (shouldUpdate) {
                        console.log('🔄 Modal content changed, updating logos...');
                        setTimeout(updateLogos, 50);
                    }
                });

                observer.observe(modalContent, {
                    childList: true,
                    subtree: true
                });
                console.log('👀 Set up mutation observer for modal content changes');
            }

            // Update auth modal background and text colors
            const authModal = document.querySelector('.auth-modal-content');
            const authModalParent = document.querySelector('[data-mantine="Modal"]');

            if (authModal) {
                console.log('📋 Updating auth modal styling');

                if (theme === 'dark') {
                    authModal.style.background = 'rgba(37, 38, 43, 0.95)';
                    authModal.style.color = '#C1C2C5';
                    authModal.style.boxShadow = '0 8px 32px rgba(0, 0, 0, 0.3)';
                } else {
                    authModal.style.background = 'rgba(255, 255, 255, 0.95)';
                    authModal.style.color = '#000000';
                    authModal.style.boxShadow = '0 8px 32px rgba(0, 0, 0, 0.1)';
                }

                // Update all text elements inside auth modal
                const textElements = authModal.querySelectorAll('.mantine-Title-root, [data-mantine="Title"], .mantine-Text-root, [data-mantine="Text"]');
                textElements.forEach(element => {
                    element.style.color = theme === 'dark' ? '#C1C2C5' : '#000000';
                });

                // Update form elements
                const inputs = authModal.querySelectorAll('.mantine-TextInput-input, .mantine-PasswordInput-input');
                const labels = authModal.querySelectorAll('.mantine-TextInput-label, .mantine-PasswordInput-label');

                inputs.forEach(input => {
                    if (theme === 'dark') {
                        input.style.backgroundColor = '#25262b';
                        input.style.color = '#C1C2C5';
                        input.style.borderColor = '#373A40';
                    } else {
                        input.style.backgroundColor = '#ffffff';
                        input.style.color = '#000000';
                        input.style.borderColor = '#ced4da';
                    }
                });

                labels.forEach(label => {
                    label.style.color = theme === 'dark' ? '#C1C2C5' : '#000000';
                });
            }

            // Update the mantine provider attribute for proper theme cascade
            const mantineProvider = document.querySelector('[data-mantine-color-scheme]');
            if (mantineProvider) {
                mantineProvider.setAttribute('data-mantine-color-scheme', theme);
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output("auth-modal-logo-login", "src", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call=True,
    )

    # Update Plotly figure templates when theme changes
    app.clientside_callback(
        """
        function(theme_data) {
            console.log('=== PLOTLY THEME UPDATE ===');
            console.log('Theme data received:', theme_data);

            const theme = theme_data || 'light';
            const template = theme === 'dark' ? 'plotly_dark' : 'plotly_white';
            console.log('Using template:', template);

            // Check if Plotly is available
            if (!window.Plotly) {
                console.log('Plotly not available, skipping update');
                return window.dash_clientside.no_update;
            }

            console.log('Plotly available, proceeding with update');

            // Find graphs and force complete redraw
            const graphs = document.querySelectorAll('.js-plotly-plot');
            console.log('Found', graphs.length, 'Plotly graphs');

            // Use minimal delay to ensure graphs are ready but keep it responsive
            const delay = 1;

            setTimeout(() => {
                graphs.forEach(async (graph, index) => {
                    console.log('Processing graph', index);

                    try {
                        // Force a complete purge and redraw
                        console.log('Purging and redrawing graph', index);

                        // Get current data and create new layout with template
                        const currentData = graph.data || [];
                        const currentLayout = graph.layout || {};

                        // Create completely new layout object with template
                        const newLayout = {
                            ...currentLayout,
                            template: template,
                            // Force background colors that match Plotly dark theme
                            paper_bgcolor: theme === 'dark' ? '#111111' : '#ffffff',
                            plot_bgcolor: theme === 'dark' ? '#111111' : '#ffffff'
                        };

                        console.log('New layout for graph', index, ':', newLayout);

                        // Use newPlot for complete recreation
                        const result = await window.Plotly.newPlot(graph, currentData, newLayout, {
                            responsive: true,
                            displayModeBar: true
                        });

                        console.log('Plotly.newPlot completed for graph', index);

                        // Verify the update worked
                        console.log('Final layout template:', graph.layout?.template);
                        console.log('Final layout paper_bgcolor:', graph.layout?.paper_bgcolor);
                        console.log('Final layout plot_bgcolor:', graph.layout?.plot_bgcolor);

                    } catch (err) {
                        console.error('Error updating graph', index, ':', err);

                        // Fallback: try simpler relayout approach
                        try {
                            console.log('Trying fallback relayout for graph', index);
                            await window.Plotly.relayout(graph, {
                                'template': template,
                                'paper_bgcolor': theme === 'dark' ? '#111111' : '#ffffff',
                                'plot_bgcolor': theme === 'dark' ? '#111111' : '#ffffff'
                            });
                            console.log('Fallback relayout completed for graph', index);
                        } catch (fallbackErr) {
                            console.error('Fallback also failed for graph', index, ':', fallbackErr);
                        }
                    }
                });
            }, delay);

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

                /* Dashboard header grid */
                #header-content .mantine-Grid-root,
                .mantine-AppShell-header .mantine-Grid-root {
                    background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                }

                /* Dashboard title */
                #dashboard-title,
                #header-content [data-mantine="Title"],
                .mantine-AppShell-header [data-mantine="Title"] {
                    color: ${textColor} !important;
                }

                /* Dashboard header text (not badges - they keep their colors) */
                #header-content .mantine-Text-root,
                .mantine-AppShell-header .mantine-Text-root {
                    color: ${textColor} !important;
                }

                /* Dashboard header badges - keep their original colors, don't force theme colors */
                #header-content .mantine-Badge-root,
                .mantine-AppShell-header .mantine-Badge-root {
                    /* Badges keep their original colored backgrounds and white text */
                }

                /* Sidebar */
                #sidebar,
                .mantine-AppShell-navbar {
                    background-color: ${theme === 'dark' ? '#25262b' : '#ffffff'} !important;
                }

                /* NavLinks - only fix dark mode visibility, preserve colors in light mode */
                ${theme === 'dark' ? `
                #sidebar .mantine-NavLink-root,
                #sidebar [data-mantine="NavLink"],
                .mantine-AppShell-navbar .mantine-NavLink-root,
                .mantine-AppShell-navbar [data-mantine="NavLink"] {
                    /* Only override in dark mode for visibility */
                }

                /* NavLink labels - only fix dark mode visibility */
                #sidebar .mantine-NavLink-label,
                #sidebar .mantine-NavLink-root .mantine-Text-root,
                #sidebar [data-mantine="NavLink"] .mantine-Text-root,
                .mantine-AppShell-navbar .mantine-NavLink-label,
                .mantine-AppShell-navbar .mantine-NavLink-root .mantine-Text-root,
                .mantine-AppShell-navbar [data-mantine="NavLink"] .mantine-Text-root {
                    color: #C1C2C5 !important;
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

    # Dedicated callback for dashboard-title to trigger draggable updates
    app.clientside_callback(
        """
        function(theme_data) {
            console.log('=== DASHBOARD TITLE THEME TRIGGER ===');
            console.log('Theme data:', theme_data);

            const theme = theme_data || 'light';
            const textColor = theme === 'dark' ? '#ffffff' : '#000000';

            // Return a style object that changes with theme to trigger draggable
            return {
                'color': textColor,
                'data-theme': theme,  // Add a data attribute that changes
                'display': 'none'  // Keep it hidden
            };
        }
        """,
        Output("dashboard-title", "style", allow_duplicate=True),
        Input("theme-store", "data"),
        prevent_initial_call="initial_duplicate",
    )


# Note: DMC figure templates are now loaded via dmc.add_figure_templates()
# They are applied both during figure creation and via client-side updates
# Templates used: "mantine_light" and "mantine_dark"
