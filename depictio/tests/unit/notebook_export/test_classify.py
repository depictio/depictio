"""Every component type (and advanced-viz kind) has a verdict."""

from typing import get_args

import pytest

from depictio.api.v1.services.notebook_export.classify import (
    ADVANCED_VIZ_RENDERING,
    ALL_ADVANCED_VIZ_KINDS,
    ALL_COMPONENT_TYPES,
    COMPONENT_COVERAGE,
    SERVER_PLOTLY_KINDS,
    advanced_viz_delivery,
    classify,
)
from depictio.models.components.types import AdvancedVizKind, ComponentType


def test_coverage_table_names_every_component_type():
    assert set(COMPONENT_COVERAGE) == set(get_args(ComponentType)) | {"multiqc", "highlight"}
    assert set(ALL_COMPONENT_TYPES) == set(COMPONENT_COVERAGE)


def test_every_advanced_viz_kind_has_an_explicit_rendering_verdict():
    """A new kind must be classified by hand: no kind reaches a report by default."""
    kinds = set(get_args(AdvancedVizKind))
    assert set(ALL_ADVANCED_VIZ_KINDS) == kinds
    assert set(ADVANCED_VIZ_RENDERING) == kinds
    assert set(ADVANCED_VIZ_RENDERING.values()) <= {"plotly", "snapshot"}
    assert SERVER_PLOTLY_KINDS <= kinds
    for kind in kinds:
        verdict = classify({"component_type": "advanced_viz", "viz_kind": kind})
        assert verdict.status == "api"
        assert verdict.kind == kind
        expected = "snapshot" if ADVANCED_VIZ_RENDERING[kind] == "snapshot" else "interactive"
        assert verdict.output == expected, kind


# The verdicts the audit established by reading each renderer. Pinned by name
# so a table edit that flips one is a visible, reviewed change.
NOT_PLOTLY = {
    "genome_view",
    "genome_chord",
    "ideogram",
    "record_card",
    "ranked_table",
    "molecule_3d",
    "msa",
    "sequence_track",
    "hmm_logo",
    "secondary_structure",
    "domain_architecture",
    "pae_matrix",
    "allele_grid",
    "pedigree",
}


def test_non_plotly_kinds_are_snapshots():
    assert {k for k, v in ADVANCED_VIZ_RENDERING.items() if v == "snapshot"} == NOT_PLOTLY


@pytest.mark.parametrize(
    "meta,delivery",
    [
        ({"viz_kind": "complex_heatmap"}, "server"),
        ({"viz_kind": "volcano"}, "server"),
        ({"viz_kind": "rarefaction"}, "extracted"),
        ({"viz_kind": "record_card"}, "snapshot"),
        ({"viz_kind": "coverage_track", "config": {"view": "locus"}}, "snapshot"),
        ({"viz_kind": "cnv_profile", "config": {"view": "locus"}}, "snapshot"),
        ({"viz_kind": "sashimi", "config": {"view": "genomespy"}}, "snapshot"),
        ({"viz_kind": "phylogenetic"}, "extracted"),
        ({"viz_kind": "phylogenetic", "config": {"collapse_rank": "Phylum"}}, "snapshot"),
        ({"viz_kind": "hologram"}, None),
    ],
)
def test_delivery_honours_the_view_a_tile_opens_on(meta, delivery):
    assert advanced_viz_delivery({"component_type": "advanced_viz", **meta}) == delivery


def test_an_unknown_kind_is_omitted_not_sent_to_a_renderer():
    verdict = classify({"component_type": "advanced_viz", "viz_kind": "hologram"})
    assert verdict.status == "omitted"
    assert "hologram" in verdict.reason


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
