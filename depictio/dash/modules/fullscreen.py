"""
Fullscreen functionality for dashboard charts.

This module handles:
- Fullscreen toggle buttons for charts
- Fullscreen mode CSS styling
- Graph resizing for fullscreen mode
- Exit fullscreen functionality
"""

from typing import Any

from dash import MATCH, Input, Output, State, html

from depictio.api.v1.configs.logging_init import logger


def register_fullscreen_callbacks(app: Any) -> None:
    """
    Register callbacks for chart fullscreen functionality.

    Args:
        app: The Dash application instance
    """
    logger.info("📺 REGISTERING FULLSCREEN CALLBACKS")

    # Simplified fullscreen toggle callback
    app.clientside_callback(
        """
        function(n_clicks, button_id) {
            console.log('🖥️ Fullscreen button clicked:', n_clicks);

            if (!n_clicks || n_clicks === 0) {
                return window.dash_clientside.no_update;
            }

            // Find the button element
            const componentIndex = button_id.index;
            const allButtons = document.querySelectorAll('button[id*="chart-fullscreen-btn"]');

            let button = null;
            for (let btn of allButtons) {
                try {
                    const btnId = JSON.parse(btn.getAttribute('id'));
                    if (btnId.index === componentIndex) {
                        button = btn;
                        break;
                    }
                } catch (e) {
                    continue;
                }
            }

            if (!button) {
                console.error('🖥️ Button not found');
                return window.dash_clientside.no_update;
            }

            // CRITICAL: Must apply fullscreen to the grid item, not a child element
            // This is because grid items have transforms, which break position:fixed behavior
            const gridItem = button.closest('.react-grid-item');

            if (!gridItem) {
                console.error('🖥️ Grid item not found');
                return window.dash_clientside.no_update;
            }

            console.log('🖥️ Grid item found:', gridItem.className);

            // Toggle fullscreen on the grid item
            const isFullscreen = gridItem.classList.contains('chart-fullscreen-active');

            if (isFullscreen) {
                // Exit fullscreen
                console.log('Exiting fullscreen');
                gridItem.classList.remove('chart-fullscreen-active');
                document.body.classList.remove('fullscreen-mode');

                // Resize Plotly after exiting
                setTimeout(() => {
                    const plotlyDiv = gridItem.querySelector('.js-plotly-plot');
                    if (plotlyDiv && window.Plotly) {
                        window.Plotly.Plots.resize(plotlyDiv);
                    }
                }, 100);
            } else {
                // Enter fullscreen
                console.log('Entering fullscreen');
                gridItem.classList.add('chart-fullscreen-active');
                document.body.classList.add('fullscreen-mode');

                // Resize Plotly for fullscreen
                setTimeout(() => {
                    const plotlyDiv = gridItem.querySelector('.js-plotly-plot');
                    if (plotlyDiv && window.Plotly) {
                        window.Plotly.Plots.resize(plotlyDiv);
                    }
                }, 100);
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output({"type": "chart-fullscreen-btn", "index": MATCH}, "n_clicks"),
        Input({"type": "chart-fullscreen-btn", "index": MATCH}, "n_clicks"),
        State({"type": "chart-fullscreen-btn", "index": MATCH}, "id"),
        prevent_initial_call=True,
    )

    logger.info("✅ FULLSCREEN CALLBACKS REGISTERED SUCCESSFULLY")


def create_fullscreen_button(chart_index: str) -> html.Button:
    """
    DEPRECATED: This function is no longer used.

    Fullscreen buttons are now created in depictio.dash.layouts.edit.py as part of
    the component action icon group (alongside edit, remove, metadata buttons).

    This function is kept for backwards compatibility but should not be called.
    """
    # Return empty div - button is created in edit.py now
    return html.Div()


def get_fullscreen_css() -> str:
    """
    Get CSS styles for fullscreen functionality.

    Returns:
        str: CSS styles for fullscreen charts
    """
    return """
    /* Fullscreen chart container styles */
    .chart-fullscreen {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        width: 100vw !important;
        height: 100vh !important;
        z-index: 9999 !important;
        background-color: var(--app-bg-color, #ffffff) !important;
        padding: 20px !important;
    }

    /* Show fullscreen button on hover */
    .figure-container:hover .chart-fullscreen-btn {
        opacity: 1 !important;
    }

    /* Fullscreen button hover effect */
    .chart-fullscreen-btn:hover {
        background: rgba(0, 0, 0, 0.9) !important;
    }

    /* Ensure fullscreen charts take full space */
    .chart-fullscreen .js-plotly-plot {
        width: 100% !important;
        height: calc(100vh - 100px) !important;
    }
    """
