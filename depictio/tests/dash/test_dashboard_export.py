"""Tests for the Quarto (.qmd) dashboard export module."""

import json
from typing import Any

import pytest

from depictio.dash.layouts.dashboard_export import (
    _build_card_html_block,
    _build_cards_section,
    _build_figure_code_cell,
    _build_figures_section,
    _build_yaml_front_matter,
    create_quarto_document,
    extract_charts_from_stored_metadata,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_dashboard_data() -> dict[str, Any]:
    """Return minimal dashboard metadata."""
    return {
        "dashboard_id": "abc123",
        "title": "Test Dashboard",
        "project_id": "proj-1",
    }


@pytest.fixture
def sample_chart_json() -> dict[str, Any]:
    """Return a simple Plotly figure JSON dict."""
    return {
        "data": [{"x": [1, 2, 3], "y": [4, 5, 6], "type": "scatter"}],
        "layout": {"title": {"text": "My Scatter Plot"}},
    }


@pytest.fixture
def sample_card_data() -> dict[str, Any]:
    """Return a sample card metadata dict."""
    return {
        "title": "Total Users",
        "value": "1,234",
        "subtitle": "+12%",
        "background_color": "#e3f2fd",
        "title_color": "#1565c0",
        "icon_name": "mdi:account-group",
        "icon_color": "#1e88e5",
        "title_font_size": "12px",
        "value_font_size": "32px",
    }


# ---------------------------------------------------------------------------
# YAML Front Matter
# ---------------------------------------------------------------------------


@pytest.mark.no_db
class TestBuildYamlFrontMatter:
    """Tests for ``_build_yaml_front_matter``."""

    def test_contains_title(self) -> None:
        result = _build_yaml_front_matter("My Title", "Jan 1", "id-1", 5)
        assert 'title: "My Title"' in result

    def test_contains_dashboard_id(self) -> None:
        result = _build_yaml_front_matter("T", "Jan 1", "dash-42", 3)
        assert 'dashboard-id: "dash-42"' in result

    def test_starts_and_ends_with_delimiters(self) -> None:
        result = _build_yaml_front_matter("T", "Jan 1", "id-1", 1)
        assert result.startswith("---\n")
        assert result.strip().endswith("---")


# ---------------------------------------------------------------------------
# Card HTML Blocks
# ---------------------------------------------------------------------------


@pytest.mark.no_db
class TestBuildCardHtmlBlock:
    """Tests for ``_build_card_html_block``."""

    def test_includes_title_and_value(self, sample_card_data: dict[str, Any]) -> None:
        html = _build_card_html_block(sample_card_data)
        assert "Total Users" in html
        assert "1,234" in html

    def test_includes_icon(self, sample_card_data: dict[str, Any]) -> None:
        html = _build_card_html_block(sample_card_data)
        assert "mdi:account-group" in html

    def test_includes_subtitle(self, sample_card_data: dict[str, Any]) -> None:
        html = _build_card_html_block(sample_card_data)
        assert "+12%" in html

    def test_no_subtitle_when_empty(self) -> None:
        card = {"title": "Metric", "value": "42", "subtitle": ""}
        html = _build_card_html_block(card)
        assert "opacity:0.8" not in html


# ---------------------------------------------------------------------------
# Cards Section
# ---------------------------------------------------------------------------


@pytest.mark.no_db
class TestBuildCardsSection:
    """Tests for ``_build_cards_section``."""

    def test_empty_list_returns_empty(self) -> None:
        assert _build_cards_section([]) == ""

    def test_contains_raw_html_fence(self, sample_card_data: dict[str, Any]) -> None:
        result = _build_cards_section([sample_card_data])
        assert "```{=html}" in result
        assert "## Metrics" in result


# ---------------------------------------------------------------------------
# Figure Code Cell
# ---------------------------------------------------------------------------


@pytest.mark.no_db
class TestBuildFigureCodeCell:
    """Tests for ``_build_figure_code_cell``."""

    def test_contains_python_fence(self, sample_chart_json: dict[str, Any]) -> None:
        cell = _build_figure_code_cell(sample_chart_json, 0)
        assert "```{python}" in cell
        assert "fig.show()" in cell

    def test_uses_title_as_heading(self, sample_chart_json: dict[str, Any]) -> None:
        cell = _build_figure_code_cell(sample_chart_json, 0)
        assert "### My Scatter Plot" in cell

    def test_fallback_heading_without_title(self) -> None:
        cell = _build_figure_code_cell({"data": [], "layout": {}}, 2)
        assert "### Figure 3" in cell

    def test_embeds_valid_json(self, sample_chart_json: dict[str, Any]) -> None:
        cell = _build_figure_code_cell(sample_chart_json, 0)
        # Extract the JSON string between triple-quotes
        start = cell.index("'''") + 3
        end = cell.index("'''", start)
        embedded_json = cell[start:end]
        parsed = json.loads(embedded_json)
        assert parsed["data"][0]["type"] == "scatter"


# ---------------------------------------------------------------------------
# Figures Section
# ---------------------------------------------------------------------------


@pytest.mark.no_db
class TestBuildFiguresSection:
    """Tests for ``_build_figures_section``."""

    def test_empty_list_returns_empty(self) -> None:
        assert _build_figures_section([]) == ""

    def test_contains_section_heading(self, sample_chart_json: dict[str, Any]) -> None:
        result = _build_figures_section([sample_chart_json])
        assert "## Figures" in result


# ---------------------------------------------------------------------------
# Full Document Generation
# ---------------------------------------------------------------------------


@pytest.mark.no_db
class TestCreateQuartoDocument:
    """Tests for ``create_quarto_document``."""

    def test_basic_document_structure(
        self,
        sample_dashboard_data: dict[str, Any],
        sample_chart_json: dict[str, Any],
        sample_card_data: dict[str, Any],
    ) -> None:
        qmd = create_quarto_document(
            dashboard_data=sample_dashboard_data,
            charts_json=[sample_chart_json],
            cards_data=[sample_card_data],
            title="Test Dashboard",
        )
        assert qmd.startswith("---\n")
        assert "## Metrics" in qmd
        assert "## Figures" in qmd
        assert "Generated by" in qmd

    def test_no_cards_omits_metrics_section(
        self,
        sample_dashboard_data: dict[str, Any],
        sample_chart_json: dict[str, Any],
    ) -> None:
        qmd = create_quarto_document(
            dashboard_data=sample_dashboard_data,
            charts_json=[sample_chart_json],
            cards_data=[],
        )
        assert "## Metrics" not in qmd
        assert "## Figures" in qmd

    def test_no_figures_omits_figures_section(
        self,
        sample_dashboard_data: dict[str, Any],
        sample_card_data: dict[str, Any],
    ) -> None:
        qmd = create_quarto_document(
            dashboard_data=sample_dashboard_data,
            charts_json=[],
            cards_data=[sample_card_data],
        )
        assert "## Figures" not in qmd
        assert "## Metrics" in qmd

    def test_raises_on_none_dashboard_data(self) -> None:
        with pytest.raises(ValueError, match="must not be None"):
            create_quarto_document(
                dashboard_data=None,  # type: ignore[arg-type]
                charts_json=[],
                cards_data=[],
            )


# ---------------------------------------------------------------------------
# Metadata Extraction
# ---------------------------------------------------------------------------


@pytest.mark.no_db
class TestExtractChartsFromStoredMetadata:
    """Tests for ``extract_charts_from_stored_metadata``."""

    def test_extracts_figure_from_map(self, sample_chart_json: dict[str, Any]) -> None:
        metadata = [{"component_type": "figure", "index": "fig-1"}]
        figure_map = {"fig-1": sample_chart_json}
        charts, cards = extract_charts_from_stored_metadata(metadata, figure_map)
        assert len(charts) == 1
        assert len(cards) == 0

    def test_skips_figure_without_data(self) -> None:
        metadata = [{"component_type": "figure", "index": "fig-1"}]
        charts, cards = extract_charts_from_stored_metadata(metadata, {})
        assert len(charts) == 0

    def test_extracts_card_with_rendered_value(self) -> None:
        metadata = [{"component_type": "card", "index": "card-1", "title": "Users"}]
        card_value_map = {"card-1": "999"}
        charts, cards = extract_charts_from_stored_metadata(metadata, card_value_map=card_value_map)
        assert len(cards) == 1
        assert cards[0]["value"] == "999"

    def test_card_falls_back_to_metadata_value(self) -> None:
        metadata = [{"component_type": "card", "index": "card-1", "title": "X", "value": "42"}]
        charts, cards = extract_charts_from_stored_metadata(metadata)
        assert len(cards) == 1
        assert cards[0]["value"] == "42"

    def test_formats_numeric_card_value(self) -> None:
        metadata = [{"component_type": "card", "index": "c1", "title": "Count"}]
        card_value_map = {"c1": 12345.678}
        _, cards = extract_charts_from_stored_metadata(metadata, card_value_map=card_value_map)
        assert cards[0]["value"] == "12,345.68"
