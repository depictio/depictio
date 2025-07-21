"""
Simple progressive loading for Depictio dashboards - just like the prototype.
"""

import base64
import os

import dash_mantine_components as dmc
from dash import Input, Output, dcc, get_app, html

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.colors import colors


def _load_svg_content():
    """Load SVG content at module import time."""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Go up from draggable_scenarios -> layouts -> dash -> assets
        assets_dir = os.path.join(current_dir, "..", "..", "assets")
        svg_path = os.path.join(assets_dir, "images/icons/animated_favicon.svg")

        with open(svg_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"Could not find images/icons/animated_favicon.svg at {svg_path}")
        return None


# Load SVG content once at module import
SVG_CONTENT = _load_svg_content()


def create_inline_svg_logo():
    """Create an inline SVG logo component for animation using embedded content."""
    if SVG_CONTENT:
        return html.Div(
            [
                html.Div(
                    id="svg-logo-container",
                    className="custom-loader",
                    style={
                        "width": "120px",
                        "height": "120px",
                        "display": "inline-block",
                    },
                ),
                # Interval to trigger the clientside callback
                dcc.Interval(
                    id="svg-trigger",
                    interval=100,  # Fire once after 100ms
                    n_intervals=0,
                    max_intervals=1,
                ),
            ]
        )
    else:
        # Fallback to img tag if SVG content couldn't be loaded
        return html.Img(
            src=get_app().get_asset_url("images/icons/animated_favicon.svg"),
            className="custom-loader",
            style={
                "width": "120px",
                "height": "120px",
            },
        )


def create_loading_progress_display(dashboard_id: str):
    """Create a loading display with animated Depictio logo and fade transitions."""
    # CSS for fade animations
    fade_css = """
    @keyframes fadeIn {
        from { opacity: 0; transform: translate(-50%, -50%) scale(0.9); }
        to { opacity: 1; transform: translate(-50%, -50%) scale(1); }
    }

    @keyframes fadeOut {
        from { opacity: 1; transform: translate(-50%, -50%) scale(1); }
        to { opacity: 0; transform: translate(-50%, -50%) scale(0.9); }
    }

    .loading-progress-fade-in {
        animation: fadeIn 0.3s ease-out forwards;
    }

    .loading-progress-fade-out {
        animation: fadeOut 0.3s ease-in forwards;
    }
    """

    return html.Div(
        [
            # CSS for fade animations using html.Link with data URI
            html.Link(
                rel="stylesheet",
                href="data:text/css;base64," + base64.b64encode(fade_css.encode()).decode(),
            ),
            dmc.Stack(
                [
                    dmc.Text(
                        "Loading dashboard components...",
                        size="md",
                        c="gray",
                        style={"textAlign": "center", "fontWeight": 500},
                    ),
                    # Animated Depictio logo
                    html.Div(
                        [
                            html.Div(
                                [
                                    # Animated Depictio logo with pulsing effect
                                    dmc.Center(create_inline_svg_logo()),
                                ],
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "width": "100%",
                                    "height": "120px",
                                },
                            ),
                        ],
                        style={
                            "position": "relative",
                            "width": "100%",
                        },
                    ),
                ],
                gap="md",
            ),
        ],
        id={"type": "loading-progress-container", "dashboard": dashboard_id},
        className="loading-progress-fade-in",  # Start with fade-in animation
        style={
            "position": "fixed",
            "top": "50%",
            "left": "50%",
            "transform": "translate(-50%, -50%)",
            "zIndex": 1000,
            "backgroundColor": "rgba(255, 255, 255, 0.98)",
            "padding": "40px 50px",
            "borderRadius": "12px",
            "boxShadow": "0 8px 25px rgba(0,0,0,0.15)",
            "minWidth": "500px",
            "display": "block",
            "border": f"1px solid {colors['purple']}",
        },
    )


def create_fade_out_progress_display(dashboard_id: str):
    """Create a fade-out version of the loading progress display."""
    # CSS for fade animations
    fade_css = """
    @keyframes fadeOut {
        from { opacity: 1; transform: translate(-50%, -50%) scale(1); }
        to { opacity: 0; transform: translate(-50%, -50%) scale(0.9); }
    }

    .loading-progress-fade-out {
        animation: fadeOut 0.3s ease-in forwards;
    }
    """

    return html.Div(
        [
            # CSS for fade animations using html.Link with data URI
            html.Link(
                rel="stylesheet",
                href="data:text/css;base64," + base64.b64encode(fade_css.encode()).decode(),
            ),
            dmc.Stack(
                [
                    dmc.Text(
                        "Loading dashboard components...",
                        size="md",
                        c="gray",
                        style={"textAlign": "center", "fontWeight": 500},
                    ),
                    # Animated Depictio logo
                    html.Div(
                        [
                            html.Div(
                                [
                                    # Animated Depictio logo with pulsing effect
                                    dmc.Center(create_inline_svg_logo()),
                                ],
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "width": "100%",
                                    "height": "120px",
                                },
                            ),
                        ],
                        style={
                            "position": "relative",
                            "width": "100%",
                        },
                    ),
                ],
                gap="md",
            ),
        ],
        id={"type": "loading-progress-container", "dashboard": dashboard_id},
        className="loading-progress-fade-out",  # Fade-out animation
        style={
            "position": "fixed",
            "top": "50%",
            "left": "50%",
            "transform": "translate(-50%, -50%)",
            "zIndex": 1000,
            "backgroundColor": "rgba(255, 255, 255, 0.98)",
            "padding": "40px 50px",
            "borderRadius": "12px",
            "boxShadow": "0 8px 25px rgba(0,0,0,0.15)",
            "minWidth": "500px",
            "display": "block",
            "border": f"1px solid {colors['purple']}",
        },
    )


def register_progressive_loading_callbacks(app):
    """Register simple progressive loading visual effects - just like the prototype."""

    logger.info("Registering simple progressive loading callbacks")

    # Clientside callback for SVG logo animation
    # Prepare SVG content with proper escaping for f-string
    escaped_svg_content = ""
    if SVG_CONTENT:
        escaped_svg_content = SVG_CONTENT.replace("`", "\\`").replace("$", "\\$")

    app.clientside_callback(
        f"""
        function(n_intervals) {{
            if (n_intervals === 0) return window.dash_clientside.no_update;

            console.log('🎨 Injecting animated SVG logo...');

            const container = document.getElementById('svg-logo-container');
            if (container && !container.querySelector('svg')) {{
                console.log('🔍 Container found, injecting SVG content...');

                // Embedded SVG content
                const svgContent = `{escaped_svg_content}`;

                if (svgContent) {{
                    container.innerHTML = svgContent;

                    // Add CSS for animation
                    if (!document.getElementById('svg-animation-styles')) {{
                        const style = document.createElement('style');
                        style.id = 'svg-animation-styles';
                        style.textContent = `
                            @keyframes pulse {{
                                0%, 100% {{ transform: scale(1); }}
                                50% {{ transform: scale(1.1); }}
                            }}

                            /* Sequential animation with 0.1s delays - faster */
                            #shape-1, path#shape-1 {{
                                transform-origin: center;
                                transform-box: fill-box;
                                animation: pulse 1.0s ease-in-out infinite;
                                animation-delay: 0s;
                            }}

                            #shape-2, path#shape-2 {{
                                transform-origin: center;
                                transform-box: fill-box;
                                animation: pulse 1.0s ease-in-out infinite;
                                animation-delay: 0.1s;
                            }}

                            #shape-3, path#shape-3 {{
                                transform-origin: center;
                                transform-box: fill-box;
                                animation: pulse 1.0s ease-in-out infinite;
                                animation-delay: 0.2s;
                            }}

                            #shape-4, path#shape-4 {{
                                transform-origin: center;
                                transform-box: fill-box;
                                animation: pulse 1.0s ease-in-out infinite;
                                animation-delay: 0.3s;
                            }}

                            #shape-5, path#shape-5 {{
                                transform-origin: center;
                                transform-box: fill-box;
                                animation: pulse 1.0s ease-in-out infinite;
                                animation-delay: 0.4s;
                            }}

                            #shape-6, path#shape-6 {{
                                transform-origin: center;
                                transform-box: fill-box;
                                animation: pulse 1.0s ease-in-out infinite;
                                animation-delay: 0.5s;
                            }}

                            #shape-7, path#shape-7 {{
                                transform-origin: center;
                                transform-box: fill-box;
                                animation: pulse 1.0s ease-in-out infinite;
                                animation-delay: 0.6s;
                            }}


                            .custom-loader {{
                                width: 120px;
                                height: 120px;
                                margin: auto;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                overflow: visible;
                            }}

                            .custom-loader svg {{
                                width: 100px;
                                height: 100px;
                                transform: scale(0.8);
                                overflow: visible;
                            }}
                        `;
                        document.head.appendChild(style);
                    }}

                    console.log('✅ SVG injected and animated!');

                    // Debug: Check if shapes are found and analyze their positions
                    const shapes = container.querySelectorAll('[id^="shape-"]');
                    console.log('🔍 Found shapes:', shapes.length);
                    shapes.forEach((shape, index) => {{
                        console.log(`Shape ${{index + 1}}:`, shape.id, shape.tagName);
                        if (shape.getBBox) {{
                            const bbox = shape.getBBox();
                            const centerX = bbox.x + bbox.width / 2;
                            const centerY = bbox.y + bbox.height / 2;
                            console.log(`  Position: center(${{centerX.toFixed(0)}}, ${{centerY.toFixed(0)}})`);
                        }}
                    }});

                    // Check for any other path elements that might be triangles
                    const allPaths = container.querySelectorAll('path');
                    console.log('🔍 Total paths found:', allPaths.length);
                    allPaths.forEach((path, index) => {{
                        console.log(`Path ${{index + 1}}:`, path.id || 'no-id', path.getAttribute('style'));
                    }});
                }} else {{
                    console.log('❌ No SVG content available');
                    container.innerHTML = '<img src="/assets/images/icons/animated_favicon.svg" style="width: 100px; height: 100px;" alt="Depictio Logo" />';
                }}
            }} else {{
                console.log('❌ Container not found or SVG already loaded');
            }}

            return window.dash_clientside.no_update;
        }}
        """,
        Output("svg-logo-container", "children", allow_duplicate=True),
        Input("svg-trigger", "n_intervals"),
        prevent_initial_call=True,
    )

    # Simple clientside callback for loading animation effects
    app.clientside_callback(
        """
        function(pathname) {
            console.log('🔄 Progressive loading triggered for path:', pathname);

            // Only run on dashboard pages
            if (!pathname || !pathname.startsWith('/dashboard/')) {
                return window.dash_clientside.no_update;
            }

            // Wait for DOM to be ready
            setTimeout(() => {
                console.log('🔍 Looking for dashboard components...');

                // Find all draggable components
                const draggableComponents = document.querySelectorAll('[id^="box-"]');
                console.log('Found', draggableComponents.length, 'draggable components');

                // Add progressive loading animation to each component
                draggableComponents.forEach((component, index) => {
                    const delay = (index + 1) * 300; // Stagger by 300ms

                    // Initially hide the component content and show skeleton
                    component.style.opacity = '0';
                    component.style.transform = 'translateY(20px)';
                    component.style.transition = 'opacity 0.6s ease-in-out, transform 0.6s ease-in-out';

                    // Add loading overlay inside the component
                    const contentDiv = component.querySelector('[id^="content-"]');
                    if (contentDiv) {
                        // Create loading overlay with working spinner
                        const loadingOverlay = document.createElement('div');
                        loadingOverlay.id = `loading-overlay-${index}`;
                        loadingOverlay.style.cssText = `
                            position: absolute;
                            top: 0;
                            left: 0;
                            right: 0;
                            bottom: 0;
                            background: rgba(255, 255, 255, 0.9);
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            z-index: 1000;
                            border-radius: 5px;
                        `;

                        // Create spinner and text
                        const spinnerContainer = document.createElement('div');
                        spinnerContainer.style.cssText = 'text-align: center;';

                        const spinner = document.createElement('div');
                        // Use different colors for each component to create rainbow effect
                        const depictioColors = ['#9966CC', '#7A5DC7', '#6495ED', '#45B8AC', '#8BC34A', '#F9CB40', '#F68B33'];
                        const spinnerColor = depictioColors[index % depictioColors.length];
                        spinner.style.cssText = `
                            width: 32px;
                            height: 32px;
                            border: 3px solid #f3f3f3;
                            border-top: 3px solid ${spinnerColor};
                            border-radius: 50%;
                            animation: spin 1s linear infinite;
                            margin: 0 auto 10px auto;
                        `;

                        const text = document.createElement('div');
                        text.textContent = 'Loading component...';
                        text.style.cssText = 'color: #666; font-size: 14px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;';

                        // Add CSS animations if not already added
                        if (!document.querySelector('#loading-animations-css')) {
                            const style = document.createElement('style');
                            style.id = 'loading-animations-css';
                            style.textContent = `
                                @keyframes spin {
                                    0% { transform: rotate(0deg); }
                                    100% { transform: rotate(360deg); }
                                }
                                @keyframes logoSpin {
                                    0% { transform: rotate(0deg); }
                                    100% { transform: rotate(360deg); }
                                }
                                @keyframes triangleRotate {
                                    0% { transform: rotate(0deg); opacity: 0.6; }
                                    50% { opacity: 1; }
                                    100% { transform: rotate(360deg); opacity: 0.6; }
                                }
                                @keyframes shimmer {
                                    0% { transform: translateX(-100%); }
                                    100% { transform: translateX(100%); }
                                }
                                @keyframes trianglePulse {
                                    0%, 100% { transform: scale(1); opacity: 0.7; }
                                    50% { transform: scale(1.5); opacity: 1; }
                                }
                            `;
                            document.head.appendChild(style);
                        }

                        spinnerContainer.appendChild(spinner);
                        spinnerContainer.appendChild(text);
                        loadingOverlay.appendChild(spinnerContainer);

                        // Make content div relative for overlay positioning
                        contentDiv.style.position = 'relative';
                        contentDiv.appendChild(loadingOverlay);

                        // Show the component with loading overlay
                        component.style.opacity = '1';
                        component.style.transform = 'translateY(0)';

                        // After delay, remove loading overlay
                        setTimeout(() => {
                            console.log(`Removing loading overlay for component ${index}...`);

                            // Fade out loading overlay
                            loadingOverlay.style.transition = 'opacity 0.3s ease-in-out';
                            loadingOverlay.style.opacity = '0';

                            setTimeout(() => {
                                // Remove loading overlay completely
                                if (loadingOverlay.parentNode) {
                                    loadingOverlay.parentNode.removeChild(loadingOverlay);
                                }
                                console.log(`Component ${index} fully loaded`);

                                // If this is the last component, hide the progress bar
                                if (index === draggableComponents.length - 1) {
                                    console.log('🎉 All components loaded, hiding progress bar');

                                    const progressContainers = document.querySelectorAll('[id*="loading-progress-container"]');
                                    progressContainers.forEach(container => {
                                        // Remove fade-in class and add fade-out class to trigger animation
                                        container.classList.remove('loading-progress-fade-in');
                                        container.classList.add('loading-progress-fade-out');

                                        // After animation completes, hide the element
                                        setTimeout(() => {
                                            container.style.display = 'none';
                                        }, 300); // Match the CSS animation duration
                                    });
                                }
                            }, 300);

                        }, delay);
                    } else {
                        // Fallback: just show the component normally
                        setTimeout(() => {
                            component.style.opacity = '1';
                            component.style.transform = 'translateY(0)';
                        }, delay);
                    }
                });

            }, 100); // Small delay to ensure DOM is ready

            return window.dash_clientside.no_update;
        }
        """,
        Output("dummy-output", "children", allow_duplicate=True),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )

    logger.info("Simple progressive loading callbacks registered successfully")
