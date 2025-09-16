"""
Dashboard Export Utilities

This module provides functionality to export dashboards in various formats:
- Static HTML with embedded charts
- Standalone HTML files
- Individual chart exports
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import plotly
import plotly.graph_objects as go
from dash import dcc

from depictio.api.v1.configs.logging_init import logger


def create_standalone_html(
    dashboard_data: Dict[str, Any],
    charts: List[go.Figure],
    title: str = "Dashboard Export",
    include_interactive: bool = True,
) -> str:
    """
    Create a standalone HTML file with embedded Plotly charts.

    Args:
        dashboard_data: Dashboard configuration and data
        charts: List of Plotly figures
        title: HTML page title
        include_interactive: Whether to include interactive features

    Returns:
        str: Complete HTML string
    """

    # Generate unique IDs for charts
    chart_ids = [f"chart-{uuid.uuid4().hex[:8]}" for _ in charts]

    # Convert charts to JSON
    chart_configs = []
    for i, fig in enumerate(charts):
        chart_config = {
            "data": fig.data,
            "layout": fig.layout,
            "config": {
                "displayModeBar": include_interactive,
                "displaylogo": False,
                "responsive": True,
            },
        }
        chart_configs.append(chart_config)

    # Create HTML template
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}

            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
                background-color: #f8f9fa;
                color: #212529;
                line-height: 1.6;
            }}

            .dashboard-container {{
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
            }}

            .dashboard-header {{
                text-align: center;
                margin-bottom: 30px;
                padding: 20px;
                background: white;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}

            .dashboard-title {{
                font-size: 2.5rem;
                font-weight: 600;
                color: #2c3e50;
                margin-bottom: 10px;
            }}

            .dashboard-meta {{
                color: #6c757d;
                font-size: 0.9rem;
            }}

            .metrics-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }}

            .metric-card {{
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                text-align: center;
            }}

            .metric-title {{
                font-size: 0.9rem;
                color: #6c757d;
                margin-bottom: 10px;
                text-transform: uppercase;
                font-weight: 600;
            }}

            .metric-value {{
                font-size: 2rem;
                font-weight: 700;
                color: #2c3e50;
                margin-bottom: 5px;
            }}

            .metric-change {{
                font-size: 0.8rem;
                color: #28a745;
                font-weight: 500;
            }}

            .charts-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
                gap: 30px;
            }}

            .chart-container {{
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}

            .chart-title {{
                font-size: 1.2rem;
                font-weight: 600;
                color: #2c3e50;
                margin-bottom: 15px;
                text-align: center;
            }}

            .chart-plot {{
                width: 100%;
                height: 400px;
            }}

            .export-footer {{
                margin-top: 40px;
                padding: 20px;
                text-align: center;
                background: white;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                color: #6c757d;
                font-size: 0.9rem;
            }}

            @media (max-width: 768px) {{
                .dashboard-container {{
                    padding: 10px;
                }}

                .dashboard-title {{
                    font-size: 2rem;
                }}

                .charts-grid {{
                    grid-template-columns: 1fr;
                }}

                .metrics-grid {{
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                }}

                .chart-plot {{
                    height: 300px;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="dashboard-container">
            <!-- Header -->
            <div class="dashboard-header">
                <h1 class="dashboard-title">{title}</h1>
                <div class="dashboard-meta">
                    Exported on {datetime.now().strftime("%B %d, %Y at %I:%M %p")}
                </div>
            </div>

            <!-- Metrics Section -->
            <div class="metrics-grid">
                {generate_metrics_html(dashboard_data)}
            </div>

            <!-- Charts Section -->
            <div class="charts-grid">
                {generate_charts_html(chart_ids)}
            </div>

            <!-- Footer -->
            <div class="export-footer">
                Generated by Depictio Dashboard System<br>
                <small>This is a static export. Interactive features may be limited.</small>
            </div>
        </div>

        <script>
            // Initialize all charts
            {generate_chart_scripts(chart_configs, chart_ids)}

            // Make charts responsive
            window.addEventListener('resize', function() {{
                {generate_resize_scripts(chart_ids)}
            }});
        </script>
    </body>
    </html>
    """

    return html_template


def generate_metrics_html(dashboard_data: Dict[str, Any]) -> str:
    """Generate HTML for metric cards."""
    metrics_html = ""

    # Sample metrics - in production, extract from dashboard_data
    sample_metrics = [
        {"title": "Total Users", "value": "12,543", "change": "+12.5%"},
        {"title": "Revenue", "value": "$45,231", "change": "+8.2%"},
        {"title": "Conversion Rate", "value": "3.4%", "change": "+0.8%"},
        {"title": "Active Sessions", "value": "1,892", "change": "+15.3%"},
    ]

    for metric in sample_metrics:
        metrics_html += f"""
        <div class="metric-card">
            <div class="metric-title">{metric["title"]}</div>
            <div class="metric-value">{metric["value"]}</div>
            <div class="metric-change">{metric["change"]} vs last month</div>
        </div>
        """

    return metrics_html


def generate_charts_html(chart_ids: List[str]) -> str:
    """Generate HTML containers for charts."""
    charts_html = ""

    chart_titles = [
        "User Activity Trends",
        "Revenue by Category",
        "Conversion Distribution",
        "Session Analytics",
    ]

    for i, chart_id in enumerate(chart_ids):
        title = chart_titles[i] if i < len(chart_titles) else f"Chart {i + 1}"
        charts_html += f"""
        <div class="chart-container">
            <div class="chart-title">{title}</div>
            <div id="{chart_id}" class="chart-plot"></div>
        </div>
        """

    return charts_html


def generate_chart_scripts(chart_configs: List[Dict], chart_ids: List[str]) -> str:
    """Generate JavaScript to initialize charts."""
    scripts = []

    for i, (config, chart_id) in enumerate(zip(chart_configs, chart_ids)):
        config_json = json.dumps(config, cls=plotly.utils.PlotlyJSONEncoder)
        script = f"""
        Plotly.newPlot('{chart_id}', {config_json}.data, {config_json}.layout, {config_json}.config);
        """
        scripts.append(script)

    return "\n".join(scripts)


def generate_resize_scripts(chart_ids: List[str]) -> str:
    """Generate JavaScript for responsive chart resizing."""
    scripts = []

    for chart_id in chart_ids:
        scripts.append(f"Plotly.Plots.resize('{chart_id}');")

    return "\n".join(scripts)


def export_dashboard_to_file(
    dashboard_data: Dict[str, Any],
    charts: List[go.Figure],
    export_path: Optional[Path] = None,
    title: str = "Dashboard Export",
) -> Path:
    """
    Export dashboard to HTML file.

    Args:
        dashboard_data: Dashboard configuration and data
        charts: List of Plotly figures
        export_path: Optional path for export file
        title: Dashboard title

    Returns:
        Path: Path to exported HTML file
    """

    if export_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = Path(f"dashboard_export_{timestamp}.html")

    # Create standalone HTML
    html_content = create_standalone_html(dashboard_data, charts, title)

    # Write to file
    export_path.write_text(html_content, encoding="utf-8")

    logger.info(f"✅ DASHBOARD EXPORT: Exported to {export_path}")
    return export_path


def create_export_download_component(file_path: Path, dashboard_id: str) -> dcc.Download:
    """Create a Dash Download component for the exported file."""

    return dcc.Download(
        id={"type": "dashboard-export-download", "dashboard_id": dashboard_id},
        base64=False,
        data=None,
    )


logger.info("✅ DASHBOARD EXPORT: Module loaded successfully")
