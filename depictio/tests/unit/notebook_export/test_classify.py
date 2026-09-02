"""Every component type (and advanced-viz kind) has a verdict."""

from typing import get_args

from depictio.api.v1.services.notebook_export.classify import (
    ALL_ADVANCED_VIZ_KINDS,
    ALL_COMPONENT_TYPES,
    COMPONENT_COVERAGE,
    SERVER_PLOTLY_KINDS,
    classify,
)
from depictio.models.components.types import AdvancedVizKind, ComponentType


def test_coverage_table_names_every_component_type():
    assert set(COMPONENT_COVERAGE) == set(get_args(ComponentType)) | {"multiqc"}
    assert set(ALL_COMPONENT_TYPES) == set(COMPONENT_COVERAGE)


def test_every_advanced_viz_kind_has_a_figure_strategy():
    kinds = set(get_args(AdvancedVizKind))
    assert set(ALL_ADVANCED_VIZ_KINDS) == kinds
    assert SERVER_PLOTLY_KINDS <= kinds
    for kind in kinds:
        verdict = classify({"component_type": "advanced_viz", "viz_kind": kind})
        assert verdict.status == "api"
        assert verdict.kind == kind


def test_figure_modes():
    # UI-built figures go through the API so the notebook shows Depictio's
    # own render, not a reconstructed px.* call; code-mode figures are the
    # author's own Python, so they stay inlined verbatim.
    assert classify({"component_type": "figure", "mode": "ui", "visu_type": "box"}).status == "api"
    assert classify({"component_type": "figure", "mode": "code"}).status == "code"
    assert classify({"component_type": "figure", "visu_type": "heatmap"}).status == "api"


def test_cards_without_a_closed_form_go_through_the_api():
    assert classify({"component_type": "card", "aggregation": "median"}).status == "code"
    assert classify({"component_type": "card", "aggregation": "box_plot_stats"}).status == "api"
    assert classify({"component_type": "card", "aggregation": "mode"}).status == "api"


def test_multi_metric_cards_go_through_the_api():
    # A closed-form hero aggregation isn't enough on its own: any secondary
    # visualization (breakdown, box plot, trend...) lives in the React card
    # renderer, so a card carrying one renders through the API to keep it
    # rather than showing only the hero number.
    assert (
        classify(
            {
                "component_type": "card",
                "aggregation": "nunique",
                "secondary_layout": "donut",
                "breakdown_col": "species",
            }
        ).status
        == "api"
    )
    assert (
        classify(
            {
                "component_type": "card",
                "aggregation": "median",
                "aggregations": ["box_plot_stats"],
                "secondary_layout": "box_plot",
            }
        ).status
        == "api"
    )
    assert classify({"component_type": "card", "aggregation": "count"}).status == "code"


def test_unknown_type_is_omitted_with_reason():
    verdict = classify({"component_type": "hologram"})
    assert verdict.status == "omitted"
    assert "hologram" in verdict.reason
