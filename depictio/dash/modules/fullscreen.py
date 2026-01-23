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

    # Simple fullscreen toggle callback
    app.clientside_callback(
        """
        function(n_clicks, button_id) {
            console.log('🖥️ Fullscreen button clicked:', n_clicks, 'Button ID:', button_id);

            if (!n_clicks || n_clicks === 0) {
                console.log('🖥️ No clicks yet, skipping');
                return window.dash_clientside.no_update;
            }

            // Extract the index from the button_id object
            const componentIndex = button_id.index;
            console.log('🖥️ Component index:', componentIndex);

            // Find all buttons with type "chart-fullscreen-btn" and match by index
            // Dash renders pattern-matching IDs as JSON strings in the id attribute
            const allButtons = document.querySelectorAll('button[id*="chart-fullscreen-btn"]');
            console.log('🖥️ Found', allButtons.length, 'fullscreen buttons');

            let button = null;
            for (let btn of allButtons) {
                const btnIdStr = btn.getAttribute('id');
                try {
                    const btnId = JSON.parse(btnIdStr);
                    if (btnId.index === componentIndex) {
                        button = btn;
                        break;
                    }
                } catch (e) {
                    // Skip if not valid JSON
                    continue;
                }
            }

            if (!button) {
                console.error('🖥️ Button not found for index:', componentIndex);
                return window.dash_clientside.no_update;
            }

            console.log('🖥️ Button element found:', button);

            // Find the react-grid-item parent (button is now in ActionIconGroup in edit mode)
            let gridItem = button.closest('.react-grid-item');

            if (!gridItem) {
                console.error('🖥️ Could not find react-grid-item parent');
                // Try finding it differently - maybe we're in a different structure
                gridItem = button.closest('[id^="box-"]');
                if (!gridItem) {
                    console.error('🖥️ Still could not find grid item');
                    return window.dash_clientside.no_update;
                }
            }

            console.log('🖥️ Grid item found:', gridItem);

            // Find the figure container within the grid item
            // Priority: figure-container > dashboard-component-hover > content div
            let container = gridItem.querySelector('.figure-container');

            if (!container) {
                console.log('🖥️ No .figure-container, trying .dashboard-component-hover');
                container = gridItem.querySelector('.dashboard-component-hover');
            }

            if (!container) {
                console.log('🖥️ No .dashboard-component-hover, trying content div');
                container = gridItem.querySelector('[id^="content-"]');
            }

            if (!container) {
                console.error('🖥️ Could not find any suitable container');
                return window.dash_clientside.no_update;
            }

            console.log('🖥️ Container found:', container.className, container.id);

            // Toggle fullscreen - apply to gridItem for true fullscreen
            if (gridItem.classList.contains('chart-fullscreen')) {
                // Exit fullscreen
                console.log('Exiting fullscreen');
                gridItem.classList.remove('chart-fullscreen');
                gridItem.classList.remove('fullscreen-active');
                document.body.classList.remove('fullscreen-mode');

                // Reset all styles to original state
                gridItem.style.cssText = gridItem.getAttribute('data-original-style') || '';

                // Reset body overflow
                document.body.style.overflow = '';

                // Find all graphs in the container
                const graphs = container.querySelectorAll('.js-plotly-plot');
                console.log('Found graphs for exit fullscreen:', graphs.length);

                graphs.forEach((graph, index) => {
                    // Get stored original dimensions
                    const storedWidth = gridItem.getAttribute(`data-graph-${index}-width`);
                    const storedHeight = gridItem.getAttribute(`data-graph-${index}-height`);

                    console.log(`Restoring graph ${index} to stored size:`, storedWidth, 'x', storedHeight);

                    // Reset graph styles
                    graph.style.width = storedWidth ? storedWidth + 'px' : '';
                    graph.style.height = storedHeight ? storedHeight + 'px' : '';

                    // Force Plotly to resize to original dimensions
                    if (window.Plotly) {
                        console.log('Forcing Plotly resize for exit fullscreen');

                        // Use stored dimensions for relayout
                        const layoutUpdate = {
                            autosize: true
                        };

                        if (storedWidth && storedHeight) {
                            layoutUpdate.width = parseInt(storedWidth);
                            layoutUpdate.height = parseInt(storedHeight);
                        }

                        window.Plotly.relayout(graph, layoutUpdate).then(() => {
                            console.log('Plotly relayout completed for exit fullscreen');

                            // Final resize call to ensure proper sizing
                            setTimeout(() => {
                                window.Plotly.Plots.resize(graph);
                                console.log('Final resize completed for exit fullscreen');
                            }, 100);
                        });
                    }
                });

                // Clean up stored dimensions after a delay
                setTimeout(() => {
                    graphs.forEach((_, index) => {
                        gridItem.removeAttribute(`data-graph-${index}-width`);
                        gridItem.removeAttribute(`data-graph-${index}-height`);
                    });
                }, 500);

            } else {
                // Enter fullscreen
                console.log('Entering fullscreen');

                // Store original styles AND graph dimensions before modifying
                gridItem.setAttribute('data-original-style', gridItem.style.cssText);

                // Store current graph dimensions
                const graphs = container.querySelectorAll('.js-plotly-plot');
                graphs.forEach((graph, index) => {
                    const rect = graph.getBoundingClientRect();
                    gridItem.setAttribute(`data-graph-${index}-width`, rect.width);
                    gridItem.setAttribute(`data-graph-${index}-height`, rect.height);
                    console.log(`Storing graph ${index} current size before fullscreen:`, rect.width, 'x', rect.height);
                });

                // Apply fullscreen to gridItem (not container) to break out of grid layout
                gridItem.classList.add('chart-fullscreen');
                gridItem.classList.add('fullscreen-active');
                document.body.classList.add('fullscreen-mode');

                // Apply fullscreen styles to gridItem
                gridItem.style.position = 'fixed';
                gridItem.style.top = '0';
                gridItem.style.left = '0';
                gridItem.style.width = '100vw';
                gridItem.style.height = '100vh';
                gridItem.style.zIndex = '9999';
                gridItem.style.backgroundColor = 'var(--app-bg-color, #ffffff)';
                gridItem.style.padding = '20px';
                gridItem.style.margin = '0';
                gridItem.style.transform = 'none';  // Override grid transform

                document.body.style.overflow = 'hidden';

                // Force graph resize for fullscreen - more aggressive approach
                setTimeout(() => {
                    graphs.forEach(graph => {
                        console.log('Resizing graph for fullscreen, current dimensions:', graph.offsetWidth, 'x', graph.offsetHeight);

                        // Set graph to take full container size in fullscreen
                        graph.style.width = '100%';
                        graph.style.height = 'calc(100vh - 100px)';  // Account for padding and title

                        if (window.Plotly) {
                            // Re-enable autosize for fullscreen mode
                            window.Plotly.relayout(graph, {
                                autosize: true,
                                'xaxis.autorange': true,
                                'yaxis.autorange': true,
                                width: null,  // Let autosize handle it
                                height: null  // Let autosize handle it
                            }).then(() => {
                                console.log('Plotly relayout completed for fullscreen');
                                window.Plotly.Plots.resize(graph);
                            });
                        }
                    });
                }, 100);

                // Additional resize attempt after DOM settles
                setTimeout(() => {
                    graphs.forEach(graph => {
                        if (window.Plotly) {
                            console.log('Second resize attempt for fullscreen');
                            window.Plotly.Plots.resize(graph);
                        }
                    });
                }, 300);
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
