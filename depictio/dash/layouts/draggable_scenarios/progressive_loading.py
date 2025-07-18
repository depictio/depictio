"""
Simple progressive loading for Depictio dashboards - just like the prototype.
"""

import dash_mantine_components as dmc
from dash import Input, Output, html

from depictio.api.v1.configs.logging_init import logger


def create_loading_progress_display(dashboard_id: str):
    """Create a simple progress display for the loading process."""
    return html.Div(
        [
            dmc.Stack(
                [
                    dmc.Text("Loading dashboard components...", size="sm", c="gray"),
                    dmc.Progress(
                        value=20,  # Static progress for simplicity
                        color="blue",
                        size="sm",
                        style={"width": "100%"},
                        animated=True,
                    ),
                ],
                gap="xs",
            )
        ],
        id={"type": "loading-progress-container", "dashboard": dashboard_id},
        style={
            "position": "fixed",
            "top": "70px",
            "left": "50%",
            "transform": "translateX(-50%)",
            "zIndex": 1000,
            "backgroundColor": "rgba(255, 255, 255, 0.95)",
            "padding": "10px 20px",
            "borderRadius": "8px",
            "boxShadow": "0 2px 10px rgba(0,0,0,0.1)",
            "minWidth": "300px",
            "display": "block",
        },
    )


def register_progressive_loading_callbacks(app):
    """Register simple progressive loading visual effects - just like the prototype."""

    logger.info("Registering simple progressive loading callbacks")

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

                    // Initially hide the component
                    component.style.opacity = '0';
                    component.style.transform = 'translateY(20px)';
                    component.style.transition = 'opacity 0.6s ease-in-out, transform 0.6s ease-in-out';

                    setTimeout(() => {
                        console.log(`Showing component ${index}...`);

                        // Fade in the component
                        component.style.opacity = '1';
                        component.style.transform = 'translateY(0)';

                        console.log(`Component ${index} animation applied`);
                    }, delay);
                });

                // Hide loading progress bar after all components are shown
                const totalComponents = draggableComponents.length;
                const totalTime = totalComponents * 300 + 800; // Add 800ms buffer

                setTimeout(() => {
                    console.log('🎉 All components loaded, hiding progress bar');

                    const progressContainers = document.querySelectorAll('[id*="loading-progress-container"]');
                    progressContainers.forEach(container => {
                        container.style.transition = 'opacity 0.5s ease-in-out';
                        container.style.opacity = '0';
                        setTimeout(() => {
                            container.style.display = 'none';
                        }, 500);
                    });

                }, totalTime);

            }, 100); // Small delay to ensure DOM is ready

            return window.dash_clientside.no_update;
        }
        """,
        Output("dummy-output", "children", allow_duplicate=True),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )

    logger.info("Simple progressive loading callbacks registered successfully")
