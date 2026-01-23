"""
Dashboard HTML Export Module

This module provides functionality to export dashboards as standalone HTML files
with embedded Plotly charts, metrics cards, and responsive styling.
"""

import html as html_escape
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from depictio.api.v1.configs.logging_init import logger


def create_standalone_html(
    dashboard_data: dict[str, Any],
    charts_json: list[dict[str, Any]],
    cards_data: list[dict[str, Any]],
    title: str = "Dashboard Export",
) -> str:
    """
    Create a standalone HTML file with embedded Plotly charts.

    Args:
        dashboard_data: Dictionary containing dashboard metadata
        charts_json: List of Plotly figure JSON data (fig.to_json())
        cards_data: List of card component data with metrics
        title: Dashboard title for the HTML page

    Returns:
        str: Complete HTML content as a string
    """
    logger.info(
        f"Creating standalone HTML with {len(charts_json)} charts and {len(cards_data)} cards"
    )

    # Generate unique IDs for charts
    chart_ids = [f"chart-{uuid.uuid4().hex[:8]}" for _ in charts_json]

    # Build chart containers HTML
    charts_html = ""
    for chart_id, chart_json in zip(chart_ids, charts_json):
        chart_title = ""
        if isinstance(chart_json, dict):
            layout = chart_json.get("layout", {})
            chart_title = layout.get("title", {})
            if isinstance(chart_title, dict):
                chart_title = chart_title.get("text", "")

        charts_html += f"""
        <div class="chart-container">
            <div class="chart-title">{html_escape.escape(str(chart_title))}</div>
            <div id="{chart_id}" class="chart-plot"></div>
        </div>
        """

    # Build cards HTML
    cards_html = ""
    for card in cards_data:
        card_title = html_escape.escape(str(card.get("title", "Metric")))
        card_value = html_escape.escape(str(card.get("value", "N/A")))
        card_subtitle = html_escape.escape(str(card.get("subtitle", "")))

        cards_html += f"""
        <div class="metric-card">
            <div class="metric-title">{card_title}</div>
            <div class="metric-value">{card_value}</div>
            {f'<div class="metric-subtitle">{card_subtitle}</div>' if card_subtitle else ""}
        </div>
        """

    # Build chart initialization JavaScript
    chart_init_js = ""
    for chart_id, chart_json in zip(chart_ids, charts_json):
        chart_json_str = json.dumps(chart_json) if isinstance(chart_json, dict) else "{}"
        chart_init_js += f"""
        try {{
            var chartData_{chart_id.replace("-", "_")} = {chart_json_str};
            Plotly.newPlot(
                '{chart_id}',
                chartData_{chart_id.replace("-", "_")}.data || [],
                chartData_{chart_id.replace("-", "_")}.layout || {{}},
                {{responsive: true, displayModeBar: true}}
            );
            console.log('Initialized chart: {chart_id}');
        }} catch (e) {{
            console.error('Failed to initialize chart {chart_id}:', e);
        }}
        """

    # Format export timestamp
    export_timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    dashboard_id = dashboard_data.get("dashboard_id", "unknown")
    total_components = len(charts_json) + len(cards_data)

    # Create the complete HTML template
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html_escape.escape(title)}</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        :root {{
            --primary-color: #339af0;
            --success-color: #51cf66;
            --warning-color: #fcc419;
            --text-color: #212529;
            --text-muted: #868e96;
            --bg-color: #f8f9fa;
            --card-bg: #ffffff;
            --border-color: #dee2e6;
            --shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            line-height: 1.6;
            padding: 20px;
        }}

        .dashboard-container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .dashboard-header {{
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
            background: var(--card-bg);
            border-radius: 12px;
            box-shadow: var(--shadow);
        }}

        .dashboard-title {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--text-color);
            margin-bottom: 8px;
        }}

        .dashboard-meta {{
            font-size: 0.9rem;
            color: var(--text-muted);
        }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 30px;
        }}

        .metric-card {{
            background: var(--card-bg);
            padding: 20px;
            border-radius: 12px;
            box-shadow: var(--shadow);
            text-align: center;
            transition: transform 0.2s ease;
        }}

        .metric-card:hover {{
            transform: translateY(-2px);
        }}

        .metric-title {{
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }}

        .metric-value {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--primary-color);
            margin-bottom: 4px;
        }}

        .metric-subtitle {{
            font-size: 0.85rem;
            color: var(--text-muted);
        }}

        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 24px;
            margin-bottom: 30px;
        }}

        .chart-container {{
            background: var(--card-bg);
            padding: 20px;
            border-radius: 12px;
            box-shadow: var(--shadow);
        }}

        .chart-title {{
            font-size: 1rem;
            font-weight: 600;
            color: var(--text-color);
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border-color);
        }}

        .chart-plot {{
            width: 100%;
            min-height: 400px;
        }}

        .export-footer {{
            text-align: center;
            padding: 20px;
            color: var(--text-muted);
            font-size: 0.85rem;
            border-top: 1px solid var(--border-color);
            margin-top: 30px;
        }}

        .export-footer a {{
            color: var(--primary-color);
            text-decoration: none;
        }}

        .export-footer a:hover {{
            text-decoration: underline;
        }}

        /* Responsive design */
        @media (max-width: 768px) {{
            .dashboard-title {{
                font-size: 1.5rem;
            }}

            .charts-grid {{
                grid-template-columns: 1fr;
            }}

            .chart-plot {{
                min-height: 300px;
            }}

            .metrics-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}

        @media (max-width: 480px) {{
            body {{
                padding: 10px;
            }}

            .metrics-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        /* Print styles */
        @media print {{
            body {{
                background: white;
                padding: 0;
            }}

            .dashboard-container {{
                max-width: 100%;
            }}

            .chart-container, .metric-card, .dashboard-header {{
                box-shadow: none;
                border: 1px solid #ddd;
                page-break-inside: avoid;
            }}

            .export-footer {{
                display: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="dashboard-container">
        <div class="dashboard-header">
            <h1 class="dashboard-title">{html_escape.escape(title)}</h1>
            <div class="dashboard-meta">
                Exported on {export_timestamp} | {total_components} components
            </div>
        </div>

        {f'<div class="metrics-grid">{cards_html}</div>' if cards_html else ""}

        {f'<div class="charts-grid">{charts_html}</div>' if charts_html else ""}

        <div class="export-footer">
            Generated by <a href="https://depictio.github.io/depictio-docs/" target="_blank">Depictio</a> Dashboard System<br>
            <small>Dashboard ID: {html_escape.escape(str(dashboard_id))}</small>
        </div>
    </div>

    <script>
        // Initialize all charts when DOM is ready
        document.addEventListener('DOMContentLoaded', function() {{
            console.log('Initializing exported dashboard charts...');

            {chart_init_js}

            console.log('All charts initialized successfully');

            // Handle window resize for responsive charts
            window.addEventListener('resize', function() {{
                var plotDivs = document.querySelectorAll('.chart-plot');
                plotDivs.forEach(function(div) {{
                    if (div.id) {{
                        Plotly.Plots.resize(div.id);
                    }}
                }});
            }});
        }});
    </script>
</body>
</html>"""

    logger.info(f"Generated HTML content: {len(html_content)} characters")
    return html_content


def export_dashboard_to_file(
    dashboard_data: dict[str, Any],
    charts_json: list[dict[str, Any]],
    cards_data: list[dict[str, Any]],
    export_path: Path | None = None,
    title: str = "Dashboard Export",
) -> Path:
    """
    Export dashboard to HTML file.

    Args:
        dashboard_data: Dictionary containing dashboard metadata
        charts_json: List of Plotly figure JSON data
        cards_data: List of card component data
        export_path: Optional path for the output file
        title: Dashboard title

    Returns:
        Path: Path to the exported HTML file
    """
    if export_path is None:
        dashboard_id = dashboard_data.get("dashboard_id", "unknown")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = Path(f"dashboard_{dashboard_id}_export_{timestamp}.html")

    html_content = create_standalone_html(dashboard_data, charts_json, cards_data, title)

    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(html_content, encoding="utf-8")

    logger.info(f"Dashboard exported to: {export_path}")
    return export_path


def extract_charts_from_stored_metadata(
    stored_metadata: list[dict[str, Any]],
    figure_map: dict[str, dict[str, Any]] | None = None,
    card_value_map: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Extract chart data and card data from stored metadata.

    This function processes the stored_metadata from a dashboard and extracts
    the necessary data for HTML export, using the current rendered state.

    Args:
        stored_metadata: List of component metadata dictionaries
        figure_map: Dictionary mapping component indices to rendered figure data
        card_value_map: Dictionary mapping component indices to rendered card values

    Returns:
        tuple: (charts_json, cards_data) - Lists of chart JSON and card data
    """
    charts_json: list[dict[str, Any]] = []
    cards_data: list[dict[str, Any]] = []

    if figure_map is None:
        figure_map = {}
    if card_value_map is None:
        card_value_map = {}

    for component in stored_metadata:
        component_type = component.get("component_type", "")
        component_index = str(component.get("index", ""))

        if component_type == "figure":
            # Try to get the rendered figure from the figure_map
            fig_data = figure_map.get(component_index)

            if fig_data and isinstance(fig_data, dict) and fig_data.get("data"):
                # Use the actual rendered figure (respects current filters)
                logger.info(f"Using rendered figure for component {component_index}")
                charts_json.append(fig_data)
            else:
                # Log warning and skip empty figures
                logger.warning(f"No rendered figure data for component {component_index}, skipping")

        elif component_type == "card":
            # Try to get the rendered card value (respects current filters)
            card_value = card_value_map.get(component_index)

            # If no rendered value, fall back to metadata value
            if card_value is None:
                card_value = component.get("value")
                logger.info(f"Using metadata value for card {component_index}: {card_value}")
            else:
                logger.info(f"Using rendered value for card {component_index}: {card_value}")

            # Handle None/empty values
            if card_value is None or card_value == "":
                card_value = "N/A"

            # Format the value if it's a number
            if isinstance(card_value, (int, float)):
                card_value = f"{card_value:,.2f}"

            card_info = {
                "title": component.get("title", "Metric"),
                "value": str(card_value),
                "subtitle": "",  # Cards don't have subtitle in current implementation
            }
            cards_data.append(card_info)

    logger.info(f"Extracted {len(charts_json)} charts and {len(cards_data)} cards from metadata")
    return charts_json, cards_data


def register_export_callbacks(app: Any) -> None:
    """
    Register dashboard export callbacks.

    This function registers the callback that handles the export button click
    and generates the HTML download.

    Args:
        app: Dash application instance
    """
    import dash
    from dash import ALL, Input, Output, State, no_update
    from dash.exceptions import PreventUpdate

    from depictio.dash.api_calls import api_call_get_dashboard

    @app.callback(
        Output({"type": "dashboard-export-download", "dashboard_id": ALL}, "data"),
        Input({"type": "export-dashboard-button", "dashboard_id": ALL}, "n_clicks"),
        [
            State("url", "pathname"),
            State("local-store", "data"),
            State({"type": "stored-metadata-component", "index": ALL}, "data"),
            State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
            State({"type": "figure-graph", "index": ALL}, "figure"),
            State({"type": "figure-graph", "index": ALL}, "id"),
            State({"type": "card-value", "index": ALL}, "children"),
            State({"type": "card-value", "index": ALL}, "id"),
        ],
        prevent_initial_call=True,
    )
    def export_dashboard_html(
        n_clicks_list: list[int | None],
        pathname: str,
        local_store: dict[str, Any] | None,
        stored_metadata: list[dict[str, Any]],
        interactive_metadata: list[dict[str, Any]],
        figure_data: list[dict[str, Any]],
        figure_ids: list[dict[str, Any]],
        card_values: list[Any],
        card_ids: list[dict[str, Any]],
    ) -> list[dict[str, Any] | None]:
        """
        Export the current dashboard state as a standalone HTML file.

        This callback listens to the export button click and generates an HTML file
        containing all dashboard components with embedded Plotly charts.

        Args:
            n_clicks_list: List of click counts for export buttons
            pathname: Current URL pathname
            local_store: Local storage data with access token
            stored_metadata: List of component metadata
            interactive_metadata: List of interactive component metadata

        Returns:
            List of download data dictionaries (one per dashboard)
        """
        # Check if any button was clicked
        ctx = dash.callback_context
        if not ctx.triggered or not any(n_clicks_list):
            raise PreventUpdate

        # Find which button was clicked
        triggered_id = ctx.triggered[0]["prop_id"]
        triggered_value = ctx.triggered[0]["value"]

        logger.info(f"Export triggered by: {triggered_id}, value: {triggered_value}")

        # Skip if no actual click
        if not triggered_value or triggered_value == 0:
            raise PreventUpdate

        # Validate local store
        if not local_store or "access_token" not in local_store:
            logger.warning("Cannot export: user not logged in")
            raise PreventUpdate

        TOKEN = local_store["access_token"]

        # Extract dashboard ID from pathname
        path_parts = pathname.split("/")
        if path_parts[-1] == "edit":
            dashboard_id = path_parts[-2]
        else:
            dashboard_id = path_parts[-1]

        logger.info(f"Exporting dashboard: {dashboard_id}")

        try:
            # Fetch dashboard data
            dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
            if not dashboard_data:
                logger.error(f"Failed to fetch dashboard data for {dashboard_id}")
                raise PreventUpdate

            # Combine all metadata
            all_metadata = (stored_metadata or []) + (interactive_metadata or [])
            logger.info(f"Processing {len(all_metadata)} components for export")
            logger.info(f"Stored metadata count: {len(stored_metadata or [])}")
            logger.info(f"Interactive metadata count: {len(interactive_metadata or [])}")

            # Create a mapping of component indices to figure data
            figure_map = {}
            for fig_id, fig_data in zip(figure_ids, figure_data):
                if fig_id and fig_data:
                    index = fig_id.get("index")
                    if index:
                        figure_map[str(index)] = fig_data
                        logger.info(f"Mapped figure index: {index}")

            logger.info(f"Found {len(figure_map)} rendered figures: {list(figure_map.keys())}")

            # Create a mapping of component indices to card values
            card_value_map = {}
            for card_id, card_value in zip(card_ids, card_values):
                if card_id:
                    index = card_id.get("index")
                    if index:
                        card_value_map[str(index)] = card_value
                        logger.info(f"Mapped card index: {index}, value: {card_value}")

            logger.info(
                f"Found {len(card_value_map)} rendered cards: {list(card_value_map.keys())}"
            )

            # Extract charts and cards from metadata
            charts_json, cards_data = extract_charts_from_stored_metadata(
                all_metadata, figure_map, card_value_map
            )

            # Generate HTML content
            title = dashboard_data.get("title", f"Dashboard {dashboard_id}")
            html_content = create_standalone_html(
                dashboard_data=dashboard_data,
                charts_json=charts_json,
                cards_data=cards_data,
                title=title,
            )

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"dashboard_{dashboard_id}_export_{timestamp}.html"

            logger.info(f"Export successful: {len(charts_json)} charts, {len(cards_data)} cards")

            # Return download data for all buttons (only the triggered one will have data)
            result: list[dict[str, Any] | None] = []
            for i, n_clicks in enumerate(n_clicks_list):
                if n_clicks and n_clicks > 0 and i == 0:  # First match
                    result.append(
                        {
                            "content": html_content,
                            "filename": filename,
                            "type": "text/html",
                        }
                    )
                else:
                    result.append(no_update)

            return result

        except Exception as e:
            logger.error(f"Export failed: {e}")

            # Return error HTML as fallback
            error_html = f"""<!DOCTYPE html>
<html>
<head><title>Export Error</title></head>
<body>
    <h1>Dashboard Export Error</h1>
    <p>Failed to export dashboard: {str(e)}</p>
    <p>Please try again or contact support if the issue persists.</p>
</body>
</html>"""

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            result = []
            for i, n_clicks in enumerate(n_clicks_list):
                if n_clicks and n_clicks > 0 and i == 0:
                    result.append(
                        {
                            "content": error_html,
                            "filename": f"dashboard_{dashboard_id}_export_error_{timestamp}.html",
                            "type": "text/html",
                        }
                    )
                else:
                    result.append(no_update)

            return result
