"""Fullscreen functionality for dashboard charts."""

from typing import Any

from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger

# Helper function used by both the toggle callback and the ESC handler in
# fullscreen-global.js to resize Plotly charts after layout changes.
_RESIZE_PLOTLY_SNIPPET = """
    setTimeout(() => {
        const plotlyDiv = gridItem.querySelector('.js-plotly-plot');
        if (plotlyDiv && window.Plotly) {
            window.Plotly.Plots.resize(plotlyDiv);
        }
    }, 100);
"""


def register_fullscreen_callbacks(app: Any) -> None:
    """Register clientside callback for chart fullscreen toggle."""
    logger.info("Registering fullscreen callbacks")

    app.clientside_callback(
        """
        function(n_clicks, button_id) {
            if (!n_clicks || n_clicks === 0) {
                return window.dash_clientside.no_update;
            }

            // Find the clicked button by matching its parsed id index
            const componentIndex = button_id.index;
            const allButtons = document.querySelectorAll('button[id*="chart-fullscreen-btn"]');

            let button = null;
            for (const btn of allButtons) {
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

            if (!button) return window.dash_clientside.no_update;

            // Apply fullscreen to the grid item (not a child) because grid items
            // have CSS transforms that break position:fixed behavior.
            const gridItem = button.closest('.react-grid-item');
            if (!gridItem) return window.dash_clientside.no_update;

            // Toggle fullscreen class and body overflow lock
            gridItem.classList.toggle('chart-fullscreen-active');
            document.body.classList.toggle('fullscreen-mode');

            // Resize Plotly chart after the layout change settles
            """
        + _RESIZE_PLOTLY_SNIPPET
        + """
            return window.dash_clientside.no_update;
        }
        """,
        Output({"type": "chart-fullscreen-btn", "index": MATCH}, "n_clicks"),
        Input({"type": "chart-fullscreen-btn", "index": MATCH}, "n_clicks"),
        State({"type": "chart-fullscreen-btn", "index": MATCH}, "id"),
        prevent_initial_call=True,
    )
