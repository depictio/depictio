"""
Dashboard Quarto Export Module

This module provides functionality to export dashboards as Quarto (.qmd) documents
with embedded Plotly figures (reconstructed from JSON) and metric cards as HTML blocks.
The exported .qmd files can be rendered by Quarto to HTML, PDF, or other formats.
"""

import html as html_escape
import json
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any

from depictio.api.v1.configs.logging_init import logger


def _build_yaml_front_matter(
    title: str,
    export_timestamp: str,
    dashboard_id: str,
    total_components: int,
) -> str:
    """Build the YAML front matter for a Quarto document.

    Args:
        title: Dashboard title.
        export_timestamp: Formatted export timestamp string.
        dashboard_id: Dashboard identifier.
        total_components: Total number of exported components.

    Returns:
        YAML front matter string (including ``---`` delimiters).
    """
    return textwrap.dedent(f"""\
        ---
        title: "{title}"
        subtitle: "Exported on {export_timestamp} — {total_components} components"
        format:
          html:
            code-fold: true
            code-tools: true
            self-contained: true
            theme: cosmo
            toc: true
            toc-depth: 2
        execute:
          echo: true
          warning: false
        jupyter: python3
        dashboard-id: "{dashboard_id}"
        ---
    """)


def _build_card_html_block(card: dict[str, Any]) -> str:
    """Build an HTML block for a single metric card.

    The card is rendered as a styled ``<div>`` with an Iconify icon, title, value
    and optional subtitle.  Quarto passes raw HTML blocks through unchanged when
    rendering to HTML output.

    Args:
        card: Dictionary with card metadata (title, value, colors, icon, etc.).

    Returns:
        Raw HTML block string suitable for embedding in a ``.qmd`` file.
    """
    card_title = html_escape.escape(str(card.get("title", "Metric")))
    card_value = html_escape.escape(str(card.get("value", "N/A")))
    card_subtitle = html_escape.escape(str(card.get("subtitle", "")))
    background_color = card.get("background_color", "#ffffff")
    title_color = card.get("title_color", "#000000")
    icon_name = card.get("icon_name", "mdi:chart-line")
    icon_color = card.get("icon_color", "#339af0")
    title_font_size = card.get("title_font_size", "12px")
    value_font_size = card.get("value_font_size", "32px")

    subtitle_html = ""
    if card_subtitle:
        subtitle_html = (
            f'<div style="font-size:0.85rem; opacity:0.8; color:{title_color};">'
            f"{card_subtitle}</div>"
        )

    return (
        f'<div style="background:{background_color}; padding:16px; border-radius:8px; '
        f"box-shadow:0 2px 8px rgba(0,0,0,0.1); border:1px solid #dee2e6; "
        f"position:relative; min-height:120px; display:flex; flex-direction:column; "
        f'justify-content:center; gap:4px;">\n'
        f'  <iconify-icon icon="{icon_name}" style="position:absolute; right:10px; '
        f"top:10px; color:{icon_color}; font-size:40px; "
        f'opacity:0.3;"></iconify-icon>\n'
        f'  <div style="font-size:{title_font_size}; font-weight:700; '
        f'color:{title_color};">{card_title}</div>\n'
        f'  <div style="font-size:{value_font_size}; font-weight:700; '
        f'line-height:1.2; color:{title_color};">{card_value}</div>\n'
        f"  {subtitle_html}\n"
        f"</div>\n"
    )


def _build_cards_section(cards_data: list[dict[str, Any]]) -> str:
    """Build the cards section with a responsive grid layout.

    Uses Quarto's raw HTML block syntax to embed styled metric cards in a CSS grid.

    Args:
        cards_data: List of card metadata dictionaries.

    Returns:
        Quarto-compatible section string with cards, or empty string if no cards.
    """
    if not cards_data:
        return ""

    cards_html_parts: list[str] = []
    for card in cards_data:
        cards_html_parts.append(_build_card_html_block(card))

    grid_items = "\n".join(cards_html_parts)

    return (
        "## Metrics\n\n"
        "```{=html}\n"
        "<script "
        'src="https://code.iconify.design/iconify-icon/1.0.7/iconify-icon.min.js">'
        "</script>\n"
        '<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); '
        'gap:16px; margin-bottom:30px;">\n'
        f"{grid_items}"
        "</div>\n"
        "```\n\n"
    )


def _build_figure_code_cell(
    chart_json: dict[str, Any],
    figure_index: int,
) -> str:
    """Build a Python code cell that reconstructs a Plotly figure from its JSON.

    The generated cell uses ``plotly.io.from_json`` to rebuild the figure and
    calls ``fig.show()`` so Quarto captures the interactive output.

    Args:
        chart_json: Plotly figure data as a dictionary (``data`` + ``layout``).
        figure_index: Sequential figure number (for labelling).

    Returns:
        Quarto Python code cell string.
    """
    # Extract title for the section heading
    chart_title = ""
    if isinstance(chart_json, dict):
        layout = chart_json.get("layout", {})
        title_field = layout.get("title", {})
        if isinstance(title_field, dict):
            chart_title = title_field.get("text", "")
        elif isinstance(title_field, str):
            chart_title = title_field

    heading = chart_title if chart_title else f"Figure {figure_index + 1}"
    escaped_heading = html_escape.escape(heading)

    # Serialise figure JSON — compact but valid
    fig_json_str = json.dumps(chart_json, separators=(",", ":"))

    return (
        f"### {heading}\n\n"
        f"```{{python}}\n"
        f"#| label: fig-{figure_index}\n"
        f'#| fig-cap: "{escaped_heading}"\n'
        f"import plotly.io as pio\n\n"
        f"fig = pio.from_json('''{fig_json_str}''')\n"
        f"fig.show()\n"
        f"```\n\n"
    )


def _build_figures_section(charts_json: list[dict[str, Any]]) -> str:
    """Build the figures section with all Plotly code cells.

    Args:
        charts_json: List of Plotly figure JSON dictionaries.

    Returns:
        Quarto-compatible section string with figure code cells.
    """
    if not charts_json:
        return ""

    parts: list[str] = ["## Figures\n\n"]
    for i, chart_json in enumerate(charts_json):
        parts.append(_build_figure_code_cell(chart_json, i))

    return "".join(parts)


def create_quarto_document(
    dashboard_data: dict[str, Any],
    charts_json: list[dict[str, Any]],
    cards_data: list[dict[str, Any]],
    title: str = "Dashboard Export",
) -> str:
    """Create a Quarto (.qmd) document with embedded Plotly figures and metric cards.

    Figures are embedded as Python code cells that reconstruct the interactive
    Plotly figure from its JSON representation.  Cards are rendered as styled
    HTML blocks.

    Args:
        dashboard_data: Dictionary containing dashboard metadata.
        charts_json: List of Plotly figure JSON data dictionaries.
        cards_data: List of card component data with metrics.
        title: Dashboard title for the document.

    Returns:
        Complete ``.qmd`` file content as a string.

    Raises:
        ValueError: If ``dashboard_data`` is ``None``.
    """
    if dashboard_data is None:
        raise ValueError("dashboard_data must not be None")

    logger.info(
        f"Creating Quarto document with {len(charts_json)} charts and {len(cards_data)} cards"
    )

    export_timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    dashboard_id = str(dashboard_data.get("dashboard_id", "unknown"))
    total_components = len(charts_json) + len(cards_data)

    # Assemble document
    parts: list[str] = [
        _build_yaml_front_matter(title, export_timestamp, dashboard_id, total_components),
    ]

    # Cards section (HTML blocks)
    cards_section = _build_cards_section(cards_data)
    if cards_section:
        parts.append(cards_section)

    # Figures section (Python code cells)
    figures_section = _build_figures_section(charts_json)
    if figures_section:
        parts.append(figures_section)

    # Footer
    parts.append(
        "---\n\n"
        "*Generated by [Depictio](https://depictio.github.io/depictio-docs/) "
        f"— Dashboard ID: `{html_escape.escape(dashboard_id)}`*\n"
    )

    qmd_content = "\n".join(parts)
    logger.info(f"Generated Quarto document: {len(qmd_content)} characters")
    return qmd_content


def export_dashboard_to_file(
    dashboard_data: dict[str, Any],
    charts_json: list[dict[str, Any]],
    cards_data: list[dict[str, Any]],
    export_path: Path | None = None,
    title: str = "Dashboard Export",
) -> Path:
    """Export dashboard to a Quarto (.qmd) file.

    Args:
        dashboard_data: Dictionary containing dashboard metadata.
        charts_json: List of Plotly figure JSON data.
        cards_data: List of card component data.
        export_path: Optional path for the output file.  Defaults to
            ``dashboard_<id>_export_<timestamp>.qmd`` in the current directory.
        title: Dashboard title.

    Returns:
        Path to the exported ``.qmd`` file.
    """
    if export_path is None:
        dashboard_id = dashboard_data.get("dashboard_id", "unknown")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = Path(f"dashboard_{dashboard_id}_export_{timestamp}.qmd")

    qmd_content = create_quarto_document(dashboard_data, charts_json, cards_data, title)

    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(qmd_content, encoding="utf-8")

    logger.info(f"Dashboard exported to: {export_path}")
    return export_path


def extract_charts_from_stored_metadata(
    stored_metadata: list[dict[str, Any]],
    figure_map: dict[str, dict[str, Any]] | None = None,
    card_value_map: dict[str, Any] | None = None,
    card_comparison_map: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract chart data and card data from stored metadata.

    This function processes the ``stored_metadata`` from a dashboard and extracts
    the necessary data for Quarto export, using the current rendered state.

    Args:
        stored_metadata: List of component metadata dictionaries.
        figure_map: Dictionary mapping component indices to rendered figure data.
        card_value_map: Dictionary mapping component indices to rendered card values.
        card_comparison_map: Dictionary mapping component indices to comparison/trend info.

    Returns:
        Tuple of ``(charts_json, cards_data)`` — lists of chart JSON and card data.
    """
    charts_json: list[dict[str, Any]] = []
    cards_data: list[dict[str, Any]] = []

    if figure_map is None:
        figure_map = {}
    if card_value_map is None:
        card_value_map = {}
    if card_comparison_map is None:
        card_comparison_map = {}

    for component in stored_metadata:
        component_type = component.get("component_type", "")
        component_index = str(component.get("index", ""))

        if component_type == "figure":
            fig_data = figure_map.get(component_index)

            if fig_data and isinstance(fig_data, dict) and fig_data.get("data"):
                logger.info(f"Using rendered figure for component {component_index}")
                charts_json.append(fig_data)
            else:
                logger.warning(f"No rendered figure data for component {component_index}, skipping")

        elif component_type == "card":
            card_value = card_value_map.get(component_index)

            if card_value is None:
                card_value = component.get("value")
                logger.info(f"Using metadata value for card {component_index}: {card_value}")
            else:
                logger.info(f"Using rendered value for card {component_index}: {card_value}")

            if card_value is None or card_value == "":
                card_value = "N/A"

            if isinstance(card_value, (int, float)):
                card_value = f"{card_value:,.2f}"

            comparison_text = ""
            comparison_data = card_comparison_map.get(component_index)
            if comparison_data:
                if isinstance(comparison_data, str):
                    comparison_text = comparison_data
                elif isinstance(comparison_data, list):
                    for item in comparison_data:
                        if isinstance(item, dict) and "props" in item:
                            children = item.get("props", {}).get("children", "")
                            if children:
                                comparison_text += str(children) + " "

            background_color = component.get("background_color", "#ffffff")
            title_color = component.get("title_color", "#000000")
            icon_name = component.get("icon_name", "mdi:chart-line")
            icon_color = component.get("icon_color", "#339af0")
            title_font_size = component.get("title_font_size", "12px")
            value_font_size = component.get("value_font_size", "32px")

            card_info = {
                "title": component.get("title", "Metric"),
                "value": str(card_value),
                "subtitle": comparison_text.strip(),
                "background_color": background_color,
                "title_color": title_color,
                "icon_name": icon_name,
                "icon_color": icon_color,
                "title_font_size": title_font_size,
                "value_font_size": value_font_size,
            }
            cards_data.append(card_info)

    logger.info(f"Extracted {len(charts_json)} charts and {len(cards_data)} cards from metadata")
    return charts_json, cards_data


def register_export_callbacks(app: Any) -> None:
    """Register dashboard export callbacks for Quarto (.qmd) download.

    This function registers the callback that handles the export button click
    and generates the Quarto document download.

    Args:
        app: Dash application instance.
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
            State({"type": "card-comparison", "index": ALL}, "children"),
            State({"type": "card-comparison", "index": ALL}, "id"),
        ],
        prevent_initial_call=True,
    )
    def export_dashboard_quarto(
        n_clicks_list: list[int | None],
        pathname: str,
        local_store: dict[str, Any] | None,
        stored_metadata: list[dict[str, Any]],
        interactive_metadata: list[dict[str, Any]],
        figure_data: list[dict[str, Any]],
        figure_ids: list[dict[str, Any]],
        card_values: list[Any],
        card_ids: list[dict[str, Any]],
        card_comparisons: list[Any],
        card_comparison_ids: list[dict[str, Any]],
    ) -> list[dict[str, Any] | None]:
        """Export the current dashboard state as a Quarto (.qmd) document.

        This callback listens to the export button click and generates a ``.qmd``
        file containing all dashboard components with embedded Plotly code cells.

        Args:
            n_clicks_list: List of click counts for export buttons.
            pathname: Current URL pathname.
            local_store: Local storage data with access token.
            stored_metadata: List of component metadata.
            interactive_metadata: List of interactive component metadata.
            figure_data: List of rendered Plotly figure dictionaries.
            figure_ids: List of figure component IDs.
            card_values: List of rendered card values.
            card_ids: List of card component IDs.
            card_comparisons: List of card comparison/trend data.
            card_comparison_ids: List of card comparison component IDs.

        Returns:
            List of download data dictionaries (one per dashboard).
        """
        ctx = dash.callback_context
        if not ctx.triggered or not any(n_clicks_list):
            raise PreventUpdate

        triggered_id = ctx.triggered[0]["prop_id"]
        triggered_value = ctx.triggered[0]["value"]

        logger.info(f"Quarto export triggered by: {triggered_id}, value: {triggered_value}")

        if not triggered_value or triggered_value == 0:
            raise PreventUpdate

        if not local_store or "access_token" not in local_store:
            logger.warning("Cannot export: user not logged in")
            raise PreventUpdate

        TOKEN = local_store["access_token"]

        path_parts = pathname.split("/")
        if path_parts[-1] == "edit":
            dashboard_id = path_parts[-2]
        else:
            dashboard_id = path_parts[-1]

        logger.info(f"Exporting dashboard as Quarto: {dashboard_id}")

        try:
            dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
            if not dashboard_data:
                logger.error(f"Failed to fetch dashboard data for {dashboard_id}")
                raise PreventUpdate

            all_metadata = (stored_metadata or []) + (interactive_metadata or [])
            logger.info(f"Processing {len(all_metadata)} components for Quarto export")

            # Build figure mapping
            figure_map: dict[str, dict[str, Any]] = {}
            for fig_id, fig_data in zip(figure_ids, figure_data):
                if fig_id:
                    index = fig_id.get("index")
                    if index and fig_data and isinstance(fig_data, dict) and fig_data.get("data"):
                        figure_map[str(index)] = fig_data

            logger.info(f"Found {len(figure_map)} rendered figures")

            # Build card value mapping
            card_value_map: dict[str, Any] = {}
            for card_id, card_value in zip(card_ids, card_values):
                if card_id:
                    index = card_id.get("index")
                    if index:
                        card_value_map[str(index)] = card_value

            # Build card comparison mapping
            card_comparison_map: dict[str, Any] = {}
            for comp_id, comp_value in zip(card_comparison_ids, card_comparisons):
                if comp_id:
                    index = comp_id.get("index")
                    if index:
                        card_comparison_map[str(index)] = comp_value

            # Extract charts and cards from metadata
            charts_json, cards_data = extract_charts_from_stored_metadata(
                all_metadata, figure_map, card_value_map, card_comparison_map
            )

            # Generate Quarto content
            title = dashboard_data.get("title", f"Dashboard {dashboard_id}")
            qmd_content = create_quarto_document(
                dashboard_data=dashboard_data,
                charts_json=charts_json,
                cards_data=cards_data,
                title=title,
            )

            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"dashboard_{dashboard_id}_export_{timestamp}.qmd"

            logger.info(
                f"Quarto export successful: {len(charts_json)} charts, {len(cards_data)} cards"
            )

            # Return download data
            result: list[dict[str, Any] | None] = []
            for i, n_clicks in enumerate(n_clicks_list):
                if n_clicks and n_clicks > 0 and i == 0:
                    result.append(
                        {
                            "content": qmd_content,
                            "filename": filename,
                            "type": "text/plain",
                        }
                    )
                else:
                    result.append(no_update)

            return result

        except PreventUpdate:
            raise
        except Exception as e:
            logger.error(f"Quarto export failed: {e}")

            error_qmd = (
                "---\n"
                'title: "Export Error"\n'
                "format: html\n"
                "---\n\n"
                "## Dashboard Export Error\n\n"
                f"Failed to export dashboard: {e!s}\n\n"
                "Please try again or contact support if the issue persists.\n"
            )

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            result = []
            for i, n_clicks in enumerate(n_clicks_list):
                if n_clicks and n_clicks > 0 and i == 0:
                    result.append(
                        {
                            "content": error_qmd,
                            "filename": (f"dashboard_{dashboard_id}_export_error_{timestamp}.qmd"),
                            "type": "text/plain",
                        }
                    )
                else:
                    result.append(no_update)

            return result
