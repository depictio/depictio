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


def create_auto_theme_button():
    """Create a button to reset theme to automatic detection"""
    return dmc.Button(
        "🔄 Auto",
        id="auto-theme-button",
        variant="subtle",
        size="xs",
        # title="Reset to automatic theme detection based on system preference",
        style={"marginTop": "5px", "display": "none"},  # Hidden by default
    )


def create_theme_controls():
    """Create complete theme control group with switch and auto button"""
    return dmc.Stack(
        [
            create_theme_switch(),
            create_auto_theme_button(),
        ],
        gap="xs",
        align="center",
    )


def register_theme_callbacks(app):
    """Register theme-related callbacks"""

    # Add Mantine figure templates for Plotly when theme system initializes
    dmc.add_figure_templates()  # type: ignore[unresolved-attribute]

    # Enhanced automatic theme detection with system preference monitoring
    app.clientside_callback(
        """
        function(triggerId) {
            console.log('🎨 === AUTOMATIC THEME DETECTION START ===');
            console.log('Theme detection trigger ID:', triggerId);
            console.log('⏰ Timestamp:', new Date().toISOString());

            // Early detection to set theme immediately
            if (!triggerId) {
                console.log('🎨 No trigger ID, running early theme detection');
            }

            // Manage page classes for FOUC prevention
            const body = document.body;

            // Check if this is an auth page
            const isAuthPage = window.location.pathname === '/auth' || document.getElementById('auth-background');

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

            // Function to detect current system theme
            function getSystemTheme() {
                const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                return prefersDark ? 'dark' : 'light';
            }

            // Check for saved theme preference first
            const savedTheme = localStorage.getItem('depictio-theme');
            console.log('Saved theme preference:', savedTheme);

            // Get current system theme
            const systemTheme = getSystemTheme();
            console.log('System theme preference:', systemTheme);

            // Determine final theme
            let finalTheme;
            if (savedTheme) {
                // User has explicitly set a preference
                finalTheme = savedTheme;
                console.log('Using saved theme:', finalTheme);
            } else {
                // No saved preference, use system theme
                finalTheme = systemTheme;
                console.log('Using system theme:', finalTheme);

                // Save the detected system theme as the initial preference
                localStorage.setItem('depictio-theme', finalTheme);
            }

            // Set up automatic system theme change listener
            const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

            // Remove any existing listener to avoid duplicates
            if (window.depictioThemeListener) {
                mediaQuery.removeListener(window.depictioThemeListener);
            }

            // Create new listener for system theme changes
            window.depictioThemeListener = function(e) {
                console.log('🎨 System theme changed to:', e.matches ? 'dark' : 'light');

                // Only auto-update if user hasn't manually overridden the theme
                const currentSaved = localStorage.getItem('depictio-theme');
                const currentSystem = e.matches ? 'dark' : 'light';

                // Check if current saved theme matches the previous system preference
                // If so, update to new system preference
                const wasPreviouslyAuto = !localStorage.getItem('depictio-theme-manual-override');

                if (wasPreviouslyAuto) {
                    console.log('Auto-updating theme to match system:', currentSystem);
                    localStorage.setItem('depictio-theme', currentSystem);

                    // Trigger theme update by dispatching a custom event
                    window.dispatchEvent(new CustomEvent('depictio-theme-changed', {
                        detail: { theme: currentSystem, source: 'system-auto' }
                    }));
                } else {
                    console.log('Theme manual override detected, not auto-updating');
                }
            };

            // Add the listener
            mediaQuery.addListener(window.depictioThemeListener);

            console.log('🎨 === AUTOMATIC THEME DETECTION END ===');
            console.log('Final theme:', finalTheme);
            console.log('⏰ Detection complete at:', new Date().toISOString());

            // Store the theme completion state for other callbacks to check
            window.depictioThemeDetectionComplete = true;
            window.depictioCurrentTheme = finalTheme;

            return finalTheme;
        }
        """,
        Output("theme-store", "data"),
        Input("theme-detection-trigger", "id"),  # Use theme-detection-trigger to run immediately
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

    # Handle manual theme switch toggle with override tracking
    app.clientside_callback(
        """
        function(checked) {
            const theme = checked ? 'dark' : 'light';

            console.log('🎨 === MANUAL THEME SWITCH ===');
            console.log('Switch checked:', checked);
            console.log('Manual theme selection:', theme);

            // Store theme preference with timestamp to indicate manual selection
            localStorage.setItem('depictio-theme', theme);
            localStorage.setItem('depictio-theme-timestamp', Date.now().toString());

            // Mark as manual override to prevent automatic system updates
            localStorage.setItem('depictio-theme-manual-override', 'true');

            console.log('Theme saved with manual override flag');

            return theme;
        }
        """,
        Output("theme-store", "data", allow_duplicate=True),
        Input("theme-switch", "checked"),
        prevent_initial_call=True,
    )

    # Handle auto theme button - reset to system preference
    app.clientside_callback(
        """
        function(n_clicks) {
            if (!n_clicks) {
                return window.dash_clientside.no_update;
            }

            console.log('🎨 === RESET TO AUTO THEME ===');

            // Remove manual override flag
            localStorage.removeItem('depictio-theme-manual-override');

            // Detect current system theme
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const systemTheme = prefersDark ? 'dark' : 'light';

            console.log('Resetting to automatic theme detection');
            console.log('Current system theme:', systemTheme);

            // Save the system theme as preference
            localStorage.setItem('depictio-theme', systemTheme);

            console.log('Auto theme detection re-enabled');

            return systemTheme;
        }
        """,
        Output("theme-store", "data", allow_duplicate=True),
        Input("auto-theme-button", "n_clicks"),
        prevent_initial_call=True,
    )

    # Listen for automatic theme changes from system
    app.clientside_callback(
        """
        function() {
            console.log('🎨 Setting up automatic theme change listener');

            // Listen for custom theme change events
            function handleAutoThemeChange(event) {
                if (event.detail && event.detail.source === 'system-auto') {
                    console.log('🎨 Received automatic theme change:', event.detail.theme);

                    // Update the theme store through a hidden trigger
                    const themeStore = document.getElementById('theme-store');
                    if (themeStore) {
                        // Dispatch a change event to trigger Dash callbacks
                        const changeEvent = new Event('change', { bubbles: true });
                        themeStore.value = event.detail.theme;
                        themeStore.dispatchEvent(changeEvent);
                    }
                }
            }

            // Remove existing listener if any
            if (window.depictioAutoThemeHandler) {
                window.removeEventListener('depictio-theme-changed', window.depictioAutoThemeHandler);
            }

            // Add new listener
            window.depictioAutoThemeHandler = handleAutoThemeChange;
            window.addEventListener('depictio-theme-changed', handleAutoThemeChange);

            return window.dash_clientside.no_update;
        }
        """,
        Output("dummy-resize-output", "children", allow_duplicate=True),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )

    # Update MantineProvider based on theme store (following DMC demo pattern)
    @app.callback(
        Output("mantine-provider", "forceColorScheme"),
        Input("theme-store", "data"),
        prevent_initial_call=False,  # Allow initial call to set theme on page load
    )
    def update_mantine_theme(theme_data):
        return theme_data or "light"

    # Update navbar logo based on theme
    @app.callback(
        Output("navbar-logo-content", "src"),
        Input("theme-store", "data"),
        prevent_initial_call=False,  # Allow initial call to set correct logo on page load
    )
    def update_navbar_logo(theme_data):
        theme = theme_data or "light"
        logo_src = dash.get_asset_url(
            "images/logos/logo_white.svg" if theme == "dark" else "images/logos/logo_black.svg"
        )
        return logo_src

    # Update auth modal logos and theme styling with client-side callback
    app.clientside_callback(
        """
        function(theme_data) {
            const theme = theme_data || 'light';
            const logoSrc = theme === 'dark' ? '/assets/images/logos/logo_white.svg' : '/assets/images/logos/logo_black.svg';

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

            // Function to update CSS variables for theme
            function updateThemeVariables(theme, textColor, backgroundColor) {
                const root = document.documentElement;
                const surfaceColor = theme === 'dark' ? '#25262b' : '#ffffff';
                const borderColor = theme === 'dark' ? '#373A40' : '#dee2e6';

                // Update CSS custom properties
                root.style.setProperty('--app-bg-color', backgroundColor);
                root.style.setProperty('--app-text-color', textColor);
                root.style.setProperty('--app-surface-color', surfaceColor);
                root.style.setProperty('--app-border-color', borderColor);

                // Add theme class to body for additional styling
                document.body.classList.remove('theme-light', 'theme-dark');
                document.body.classList.add(`theme-${theme}`);

                console.log(`✅ Updated CSS variables for ${theme} theme`);
                return true;
            }

            // Function to inject non-background theme styles (keeping only text colors and component-specific styles)
            function injectNonBackgroundCSS(theme, textColor) {
                let themeStyleElement = document.getElementById('dynamic-theme-styles');
                if (!themeStyleElement) {
                    themeStyleElement = document.createElement('style');
                    themeStyleElement.id = 'dynamic-theme-styles';
                    document.head.appendChild(themeStyleElement);
                }

                const themeCSS = `
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

                    /* Draggable box content - only text colors */
                    .react-grid-item .mantine-Text-root,
                    .react-grid-item [data-mantine="Text"],
                    #draggable .react-grid-item .mantine-Text-root,
                    #draggable .react-grid-item [data-mantine="Text"] {
                        color: ${textColor} !important;
                    }

                    /* Profile text */
                    #user-info-placeholder .mantine-Text-root {
                        color: ${textColor} !important;
                    }

                    /* Offcanvas title and close button */
                    #offcanvas-parameters .offcanvas-title,
                    .dashboard-offcanvas .offcanvas-title,
                    .offcanvas .offcanvas-title {
                        color: ${textColor} !important;
                    }

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

                    /* DataTable styling for all components */
                    .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner table th,
                    .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner table td {
                        background-color: var(--app-surface-color, #ffffff) !important;
                        color: var(--app-text-color, #000000) !important;
                        padding: 4px 8px !important;
                        font-size: 11px !important;
                        max-width: 150px !important;
                        border: 1px solid var(--app-border-color, #ddd) !important;
                    }

                    /* Specific header styling */
                    .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner table th {
                        font-weight: bold !important;
                        text-align: center !important;
                    }

                    /* Modal footer theme styling */
                    .mantine-Modal-content .mantine-Stack-root:last-child {
                        background-color: var(--app-surface-color, #f9f9f9) !important;
                        border-top: 1px solid var(--app-border-color, #e0e0e0) !important;
                    }

                    /* Figure component backgrounds */
                    .mantine-Card-root[id*="figure-component"],
                    div[id*="figure-component"] {
                        background-color: var(--app-surface-color, #ffffff) !important;
                    }

                    /* Card component backgrounds */
                    .mantine-Card-root[id*="card-component"],
                    div[id*="card-component"] {
                        background-color: var(--app-surface-color, #ffffff) !important;
                        border-color: var(--app-border-color, #ddd) !important;
                    }
                `;

                themeStyleElement.textContent = themeCSS;
                console.log('✅ Injected non-background theme CSS');
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

                // Update CSS variables for theme (handles backgrounds via CSS)
                updateThemeVariables(theme, textColor, backgroundColor);

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

                // Update project management header elements (text colors only)
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

                // Update auth modal specifically
                const authModalContent = document.querySelector('.auth-modal-content');
                if (authModalContent) {
                    const modalBg = theme === 'dark'
                        ? 'rgba(37, 38, 43, 0.95)'
                        : 'rgba(255, 255, 255, 0.95)';
                    const modalShadow = theme === 'dark'
                        ? '0 8px 32px rgba(0, 0, 0, 0.3)'
                        : '0 8px 32px rgba(0, 0, 0, 0.1)';

                    safeApplyStyles(authModalContent, {
                        'background': modalBg,
                        'color': textColor,
                        'box-shadow': modalShadow
                    });
                    console.log('✅ Updated auth modal styling');
                }

                // Inject non-background theme styles (text colors and components)
                injectNonBackgroundCSS(theme, textColor);

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
                'fontWeight': 'bold',
                'fontSize': '24px',
                'textAlign': 'center',
                'flex': '1'  // Take remaining space
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


def register_theme_bridge_callback(app):
    """Register the universal theme bridge callback for dashboard figure updates."""
    import time

    from dash import Input, Output

    @app.callback(
        Output("theme-relay-store", "data"),
        Input("theme-store", "data"),
        prevent_initial_call=False,  # Allow initial call to set default theme
    )
    def sync_theme_relay(theme_data):
        """Bridge theme-store to a relay that can be safely used everywhere."""
        theme = theme_data or "light"
        return {"theme": theme, "timestamp": time.time()}
