"""
Simple progressive loading for Depictio dashboards - just like the prototype.
Includes skeleton components for progressive loading.
"""

import base64
import os

import dash_mantine_components as dmc
from dash import Input, Output, dcc, get_app, html

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import (
    get_component_display_name,
    get_component_metadata,
)

# =============================================================================
# SKELETON COMPONENTS FOR PROGRESSIVE LOADING
# =============================================================================


def create_skeleton_component(component_type: str) -> html.Div:
    """
    Create a skeleton component of the specified type.

    Args:
        component_type (str): The type of component
        component_uuid (str, optional): The UUID of the component (unused but kept for compatibility)
        component_metadata (dict, optional): Component metadata (unused but kept for compatibility)

    Returns:
        dmc.Center: A skeleton loader component
    """
    logger.info(f"Creating skeleton for component type: {component_type}")
    component_metadata = get_component_metadata(component_type)
    # logger.info(f"Component metadata: {component_metadata}")

    return html.Div(
        dmc.Center(
            dmc.Stack(
                [
                    dmc.Loader(
                        type="dots",
                        color=component_metadata.get(
                            "color", "gray"
                        ),  # Default to gray if not found
                        size="lg",
                    ),
                    dmc.Text(
                        f"Loading {get_component_display_name(component_type)}...",  # Use display name
                        size="sm",
                    ),
                ],
                align="center",
                gap="sm",
            ),
        ),
        style={
            "position": "fixed",  # Use fixed positioning instead of absolute
            "top": "0px",
            "left": "0px",
            "right": "0px",
            "bottom": "0px",
            "width": "100%",
            "height": "100%",
            "backgroundColor": "var(--app-surface-color, rgba(255, 255, 255, 0.95))",  # Semi-transparent to debug
            "backdropFilter": "blur(2px)",  # Add blur effect to hide content behind
            "zIndex": "9999",  # Very high z-index to ensure it's above everything
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "overflow": "hidden",  # Prevent any content from overflowing
        },
    )


# =============================================================================
# PROGRESSIVE LOADING DISPLAY COMPONENTS
# =============================================================================


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
    """Create a loading display with animated Depictio logo, real-time loading status and fade transitions."""
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
            # Just the animated Depictio logo
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
        id={"type": "loading-progress-container", "dashboard": dashboard_id},
        className="loading-progress-fade-in",  # Start with fade-in animation
        style={
            "position": "fixed",
            "top": "50%",
            "left": "50%",
            "transform": "translate(-50%, -50%)",
            "zIndex": 9999,  # Higher z-index to ensure it's above everything
            "backgroundColor": "var(--app-surface-color, rgba(255, 255, 255, 0.98))",
            "padding": "40px 50px",
            "borderRadius": "12px",
            "boxShadow": "0 8px 25px rgba(0,0,0,0.15)",
            "minWidth": "500px",
            "display": "block",
            "border": "1px solid var(--app-border-color, #ddd)",
            "opacity": "1 !important",  # Always visible initially
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

    # Smart callback to hide loading progress when components are actually loaded
    app.clientside_callback(
        """
        function(pathname) {
            // Only run on dashboard pages
            if (!pathname || !pathname.startsWith('/dashboard/')) {
                return window.dash_clientside.no_update;
            }

            console.log('🚀 Starting dashboard loading monitor...');

            // Function to check if all components are loaded
            function checkComponentsLoaded() {
                // Look for Dash loading spinners - these are the main indicators
                const dashLoadingSpinners = document.querySelectorAll('._dash-loading');

                // Look for our custom skeleton components (but exclude the progress display itself)
                const allSkeletons = document.querySelectorAll('[style*="z-index: 9999"]');
                const progressContainers = document.querySelectorAll('[id*="loading-progress-container"]');

                // Filter out progress containers from skeleton count
                const customSkeletons = Array.from(allSkeletons).filter(skeleton => {
                    return !Array.from(progressContainers).some(container =>
                        container.contains(skeleton) || skeleton.contains(container)
                    );
                });

                const totalLoading = dashLoadingSpinners.length + customSkeletons.length;

                console.log('🔍 Loading status:', {
                    dashSpinners: dashLoadingSpinners.length,
                    customSkeletons: customSkeletons.length,
                    totalLoading: totalLoading
                });

                // If no loading components are found, components are ready
                if (totalLoading === 0) {
                    console.log('✅ All components loaded, hiding progress display');
                    hideProgressDisplay();
                    return true;
                }

                return false;
            }

            // Function to hide progress display with animation
            function hideProgressDisplay() {
                const progressContainers = document.querySelectorAll('[id*="loading-progress-container"]');
                console.log('Found', progressContainers.length, 'progress containers to hide');

                progressContainers.forEach(container => {
                    // Remove fade-in class and add fade-out class to trigger animation
                    container.classList.remove('loading-progress-fade-in');
                    container.classList.add('loading-progress-fade-out');

                    // After animation completes, hide the element
                    setTimeout(() => {
                        container.style.display = 'none';
                        console.log('✅ Progress container hidden');
                    }, 300); // Match the CSS animation duration
                });
            }

            // Start monitoring with initial delay to let Dash initialize
            setTimeout(() => {
                console.log('🔍 Starting component load monitoring...');

                // Check immediately first
                if (checkComponentsLoaded()) {
                    return;
                }

                // Set up polling to check loading status
                const checkInterval = setInterval(() => {
                    if (checkComponentsLoaded()) {
                        clearInterval(checkInterval);
                    }
                }, 200); // Check every 200ms (less frequent)

                // Shorter fallback timeout - hide after 5 seconds maximum
                setTimeout(() => {
                    console.log('⏰ Fallback timeout reached, hiding progress display');
                    clearInterval(checkInterval);
                    hideProgressDisplay();
                }, 5000); // 5 second fallback (reduced from 10)

            }, 300); // Shorter initial delay (reduced from 500ms)

            return window.dash_clientside.no_update;
        }
        """,
        Output("dummy-output", "children", allow_duplicate=True),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )

    logger.info("Progressive loading callbacks registered successfully")
