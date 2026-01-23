"""
Progressive loading system for Depictio dashboards.

This module implements a multi-phase progressive loading strategy to optimize
dashboard rendering performance and provide visual feedback during data loading.

Features:
    - Skeleton components that display while actual components load
    - Animated Depictio logo loading indicator with SVG pulse animation
    - Incremental figure loading via pattern-matching callbacks
    - Smart loading progress display with fade transitions
    - Performance optimization settings to disable animations

Skeleton Component Types:
    - create_skeleton_component: Generic overlay skeleton with loader
    - create_figure_placeholder: Lightweight figure loading placeholder
    - create_card_placeholder: Minimal card loading placeholder
    - create_interactive_placeholder: Controls/filter loading placeholder

Performance Considerations:
    - Skeleton components use fixed positioning for overlay effects
    - SVG content is loaded once at module import time
    - Animations can be disabled via settings.performance.disable_animations
    - Clientside callbacks handle most visual effects for responsiveness
"""

import base64
import os

import dash
import dash_mantine_components as dmc
from dash import Input, Output, dcc, get_app, html

from depictio.api.v1.configs.config import settings
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
    logger.debug(f"Creating skeleton for component type: {component_type}")
    component_metadata = get_component_metadata(component_type)

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


def create_figure_placeholder(component_uuid: str) -> html.Div:
    """
    Create a lightweight placeholder for figure components during initial render.

    PERFORMANCE OPTIMIZATION (Phase 5B):
    This is a minimal placeholder that reduces initial React rendering burden.
    Unlike create_skeleton_component(), this doesn't create a full modal overlay.

    The actual figure component will be loaded incrementally via pattern-matching callback.

    Args:
        component_uuid (str): UUID of the figure component

    Returns:
        html.Div: Lightweight placeholder with loading indicator
    """
    return html.Div(
        [
            dmc.Center(
                dmc.Stack(
                    [
                        dmc.Loader(
                            type="bars",
                            color="blue",
                            size="md",
                        ),
                        dmc.Text(
                            "Loading visualization...",
                            size="sm",
                            c="gray",
                        ),
                    ],
                    align="center",
                    gap="xs",
                ),
                style={"height": "100%", "minHeight": "200px"},
            )
        ],
        id={
            "type": "figure-placeholder",
            "index": component_uuid,
        },  # Changed "uuid" to "index" for consistency
        style={
            "width": "100%",
            "height": "100%",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "border": "1px dashed var(--app-border-color, #ddd)",
            "borderRadius": "8px",
        },
    )


def create_card_placeholder(component_uuid: str) -> html.Div:
    """
    Create a lightweight placeholder for card components during initial render.

    PERFORMANCE OPTIMIZATION (Phase 5B):
    Cards are simpler than figures, so use a minimal loading indicator.

    Args:
        component_uuid (str): UUID of the card component

    Returns:
        html.Div: Lightweight placeholder with loading indicator
    """
    return html.Div(
        [
            dmc.Center(
                dmc.Stack(
                    [
                        dmc.Loader(
                            type="dots",
                            color="green",
                            size="sm",
                        ),
                        dmc.Text(
                            "Loading card...",
                            size="xs",
                            c="gray",
                        ),
                    ],
                    align="center",
                    gap="xs",
                ),
                style={"height": "100%", "minHeight": "150px"},
            )
        ],
        id={
            "type": "card-placeholder",
            "index": component_uuid,
        },  # Changed "uuid" to "index" for consistency
        style={
            "width": "100%",
            "height": "100%",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "border": "1px dashed var(--app-border-color, #ddd)",
            "borderRadius": "6px",
        },
    )


def create_interactive_placeholder(component_uuid: str) -> html.Div:
    """
    Create a lightweight placeholder for interactive components during initial render.

    PERFORMANCE OPTIMIZATION (Phase 5B):
    Interactive components include filters, controls, etc.

    Args:
        component_uuid (str): UUID of the interactive component

    Returns:
        html.Div: Lightweight placeholder with loading indicator
    """
    return html.Div(
        [
            dmc.Center(
                dmc.Stack(
                    [
                        dmc.Loader(
                            type="oval",
                            color="violet",
                            size="md",
                        ),
                        dmc.Text(
                            "Loading controls...",
                            size="sm",
                            c="gray",
                        ),
                    ],
                    align="center",
                    gap="xs",
                ),
                style={"height": "100%", "minHeight": "180px"},
            )
        ],
        id={
            "type": "interactive-placeholder",
            "index": component_uuid,
        },  # Changed "uuid" to "index" for consistency
        style={
            "width": "100%",
            "height": "100%",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "border": "1px dashed var(--app-border-color, #ddd)",
            "borderRadius": "8px",
        },
    )


# =============================================================================
# PROGRESSIVE LOADING DISPLAY COMPONENTS
# =============================================================================


def _load_svg_content() -> str | None:
    """
    Load the animated favicon SVG content at module import time.

    Attempts to read the SVG file from the assets directory. The SVG is used
    for the animated Depictio logo in the loading progress display.

    Returns:
        The SVG content as a string, or None if the file could not be loaded.
    """
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


def create_inline_svg_logo() -> html.Div | html.Img:
    """
    Create an inline SVG logo component for animation using embedded content.

    Returns either an embedded SVG (preferred for animation control) or falls
    back to an img tag if the SVG content couldn't be loaded at import time.

    Returns:
        A Div containing the SVG container and trigger interval, or an Img fallback.
    """
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
                    interval=10,  # Fire once after 100ms
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


def create_loading_progress_display(dashboard_id: str) -> html.Div:
    """
    Create a loading display with animated Depictio logo and fade transitions.

    Creates a centered modal-like overlay with the animated Depictio logo.
    Includes CSS for fade-in/fade-out animations. If animations are disabled
    via settings, returns a hidden empty div.

    Args:
        dashboard_id: Unique identifier for the dashboard being loaded.

    Returns:
        A Div containing the loading progress display, or an empty hidden Div
        if animations are disabled.
    """

    # PERFORMANCE OPTIMIZATION: Return empty div if animations disabled
    if settings.performance.disable_animations:
        return html.Div(
            id={"type": "loading-progress-container", "dashboard": dashboard_id},
            style={"display": "none"},
        )

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


def register_figure_loading_callback(app: dash.Dash) -> None:
    """
    Register callback to load figure components incrementally.

    This callback implements Phase 5B performance optimization by loading figure
    components progressively via dcc.Interval triggers, reducing the initial
    React render burden into smaller chunks.

    Each figure placeholder has a dcc.Interval that fires once with a staggered
    delay. This callback builds the actual figure component when triggered.

    Args:
        app: The Dash application instance.
    """
    from dash import ALL, Input, Output, State, callback_context, no_update

    from depictio.dash.component_metadata import get_build_functions
    from depictio.dash.layouts.edit import enable_box_edit_mode

    # Get figure build function
    build_functions = get_build_functions()
    figure_build_function = build_functions.get("figure")

    if not figure_build_function:
        logger.warning(
            "⚠️  PHASE 5B: Figure build function not found, skipping callback registration"
        )
        return

    @app.callback(
        # CRITICAL FIX: Use "index" instead of "uuid" for consistency with pattern-matching
        Output({"type": "figure-container", "index": ALL}, "children"),
        Input({"type": "figure-load-trigger", "index": ALL}, "n_intervals"),
        State({"type": "figure-metadata-store", "index": ALL}, "data"),
        State({"type": "figure-container", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def load_figure_component(n_intervals_list, metadata_list, container_ids):
        """
        Load figure component when interval fires.

        Args:
            n_intervals_list: List of n_intervals for each trigger
            metadata_list: List of component metadata for each figure
            container_ids: List of container IDs

        Returns:
            List of figure components (or no_update for non-triggered figures)
        """
        ctx = callback_context
        if not ctx.triggered:
            return [no_update] * len(container_ids)

        # Find which interval triggered
        trigger_id = ctx.triggered_id
        if not trigger_id or trigger_id.get("type") != "figure-load-trigger":
            return [no_update] * len(container_ids)

        # CRITICAL FIX: Use "index" key consistently (changed from "uuid")
        triggered_index = trigger_id.get("index")

        # Build output list
        outputs = []
        for i, (n_intervals, metadata, container_id) in enumerate(
            zip(n_intervals_list, metadata_list, container_ids)
        ):
            # CRITICAL FIX: Use "index" key consistently (changed from "uuid")
            container_index = container_id.get("index")

            # Only build the figure that was triggered
            if container_index == triggered_index and n_intervals and n_intervals > 0:
                try:
                    # Build the actual figure component
                    figure_component = figure_build_function(**metadata)

                    # Wrap with enable_box_edit_mode like in render_dashboard
                    wrapped_component = enable_box_edit_mode(
                        figure_component,
                        switch_state=metadata.get("edit_components_button", False),
                        dashboard_id=metadata.get("dashboard_id"),
                        component_data=metadata,
                        TOKEN=metadata.get("access_token"),
                    )

                    outputs.append(wrapped_component)
                    logger.info(
                        f"✅ PROGRESSIVE LOADING: Figure {container_index} loaded successfully"
                    )

                except Exception as e:
                    logger.error(
                        f"❌ PROGRESSIVE LOADING: Error loading figure {container_index}: {e}"
                    )
                    # Return placeholder on error
                    outputs.append(no_update)
            else:
                # Keep placeholder for non-triggered figures
                outputs.append(no_update)

        return outputs


def register_progressive_loading_callbacks(app: dash.Dash) -> None:
    """
    Register all progressive loading visual effects and callbacks.

    Registers:
    - Component-specific loading callbacks for figure, card, and interactive types
    - SVG logo animation injection via clientside callback
    - Dashboard loading monitor to hide progress display when components load

    If settings.performance.disable_animations is True, animation callbacks
    are skipped for better performance.

    Args:
        app: The Dash application instance.
    """

    logger.debug("Registering simple progressive loading callbacks")

    # PERFORMANCE OPTIMIZATION (Phase 5B): Register callbacks to load components incrementally
    from depictio.dash.layouts.draggable_scenarios.progressive_loading_component import (
        register_component_loading_callback,
    )

    # Register callbacks for each component type
    for component_type in ["figure", "card", "interactive"]:
        register_component_loading_callback(app, component_type)

    # PERFORMANCE OPTIMIZATION: Check settings to control animations
    if settings.performance.disable_animations:
        logger.info(
            "⚡ PERFORMANCE: SVG animations disabled via settings.performance.disable_animations"
        )
        return

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
    # PERFORMANCE OPTIMIZATION: Skip loading progress if animations disabled
    if settings.performance.disable_animations:
        return

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
        # Output("progress-monitor", "data"),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )

    logger.debug("Progressive loading callbacks registered successfully")
