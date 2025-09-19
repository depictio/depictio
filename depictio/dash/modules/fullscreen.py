"""
Fullscreen functionality for dashboard charts.

This module handles:
- Fullscreen toggle buttons for charts
- Fullscreen mode CSS styling
- Graph resizing for fullscreen mode
- Exit fullscreen functionality
"""

from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger


def register_fullscreen_callbacks(app):
    """
    Register callbacks for chart fullscreen functionality.

    Args:
        app (dash.Dash): The Dash application instance
    """
    logger.info("📺 REGISTERING FULLSCREEN CALLBACKS")

    # Simple fullscreen toggle callback
    app.clientside_callback(
        """
        function(n_clicks, button_id) {
            console.log('🖥️ Fullscreen button clicked:', n_clicks, 'Button ID:', button_id);

            if (!n_clicks || n_clicks === 0) {
                return window.dash_clientside.no_update;
            }

            const button = document.querySelector(`[id='${JSON.stringify(button_id)}']`);
            if (!button) {
                console.error('🖥️ Button not found:', button_id);
                return window.dash_clientside.no_update;
            }

            console.log('🖥️ Button found:', button);

            // Navigate up the DOM to find the chart paper container
            let paper = button.parentElement;
            while (paper && !paper.classList.contains('mantine-Paper-root') && paper.tagName !== 'BODY') {
                paper = paper.parentElement;
            }

            if (!paper || paper.tagName === 'BODY') {
                // Fallback - look for any parent that could be the chart container
                paper = button.parentElement;
            }

            // Toggle fullscreen
            if (paper.classList.contains('chart-fullscreen')) {
                // Exit fullscreen
                console.log('Exiting fullscreen');
                paper.classList.remove('chart-fullscreen');

                // Reset all styles to original state
                paper.style.cssText = paper.getAttribute('data-original-style') || 'position: relative;';

                // Reset body overflow
                document.body.style.overflow = '';

                // Find all graphs in the container
                const graphs = paper.querySelectorAll('.js-plotly-plot');
                console.log('Found graphs for exit fullscreen:', graphs.length);

                graphs.forEach((graph, index) => {
                    // Get stored original dimensions
                    const storedWidth = paper.getAttribute(`data-graph-${index}-width`);
                    const storedHeight = paper.getAttribute(`data-graph-${index}-height`);

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
                        paper.removeAttribute(`data-graph-${index}-width`);
                        paper.removeAttribute(`data-graph-${index}-height`);
                    });
                }, 500);

            } else {
                // Enter fullscreen
                console.log('Entering fullscreen');

                // Store original styles AND graph dimensions before modifying
                paper.setAttribute('data-original-style', paper.style.cssText);

                // Store current graph dimensions
                const graphs = paper.querySelectorAll('.js-plotly-plot');
                graphs.forEach((graph, index) => {
                    const rect = graph.getBoundingClientRect();
                    paper.setAttribute(`data-graph-${index}-width`, rect.width);
                    paper.setAttribute(`data-graph-${index}-height`, rect.height);
                    console.log(`Storing graph ${index} current size before fullscreen:`, rect.width, 'x', rect.height);
                    console.log(`Graph ${index} current style:`, graph.style.cssText);
                });

                paper.classList.add('chart-fullscreen');
                paper.style.position = 'fixed';
                paper.style.top = '0';
                paper.style.left = '0';
                paper.style.width = '100vw';
                paper.style.height = '100vh';
                paper.style.zIndex = '9999';
                paper.style.backgroundColor = 'var(--app-bg-color, #ffffff)';
                paper.style.padding = '20px';

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


def create_fullscreen_button(chart_index):
    """
    Create a fullscreen button for a chart component.

    Args:
        chart_index: Index of the chart component

    Returns:
        html.Button: Fullscreen button component
    """
    from dash import html
    from dash_iconify import DashIconify

    return html.Button(
        DashIconify(icon="mdi:fullscreen", width=18),
        id={"type": "chart-fullscreen-btn", "index": chart_index},
        n_clicks=0,
        style={
            "position": "absolute",
            "top": "10px",
            "right": "10px",
            "background": "rgba(255, 255, 255, 0.9)",
            "border": "1px solid #ddd",
            "borderRadius": "4px",
            "padding": "5px",
            "cursor": "pointer",
            "fontSize": "16px",
            "color": "#333",
            "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
            "zIndex": "10",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "width": "32px",
            "height": "32px",
            "opacity": "0",
            "transition": "opacity 0.2s ease",
        },
        className="chart-fullscreen-btn",
    )


def get_fullscreen_css():
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
    .mantine-Paper-root:hover .chart-fullscreen-btn {
        opacity: 1 !important;
    }

    /* Fullscreen button hover effect */
    .chart-fullscreen-btn:hover {
        background: rgba(255, 255, 255, 1) !important;
        border-color: #007bff !important;
        color: #007bff !important;
    }

    /* Ensure fullscreen charts take full space */
    .chart-fullscreen .js-plotly-plot {
        width: 100% !important;
        height: calc(100vh - 100px) !important;
    }
    """
