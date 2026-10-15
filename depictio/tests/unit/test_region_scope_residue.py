"""A residue pick (``residue_selection``) is scoped like a genome region."""

from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import (
    _apply_link_filters_to_payload,
)
from depictio.api.v1.region_scope import (
    is_region_filter,
    scope_region_filters,
    scope_residue_filters,
)


def _residue_pair(dc_id: str = "dc-var") -> list[dict]:
    return [
        {
            "index": "mol",
            "value": ["P1"],
            "source": "residue_selection",
            "metadata": {
                "dc_id": dc_id,
                "column_name": "entity",
                "interactive_component_type": "MultiSelect",
            },
        },
        {
            "index": "mol::res",
            "value": [10, 20],
            "source": "residue_selection",
            "metadata": {
                "dc_id": dc_id,
                "column_name": "position",
                "interactive_component_type": "RangeSlider",
            },
        },
    ]


SAMPLE_FILTER = {
    "index": "sidebar-sample",
    "value": ["S1"],
    "metadata": {"dc_id": "dc-var", "column_name": "sample"},
}


def test_both_halves_are_locus_filters():
    assert all(is_region_filter(f) for f in _residue_pair())
    assert not is_region_filter(SAMPLE_FILTER)


def test_card_ignores_a_residue_pick_unless_it_follows_the_region():
    filters = [SAMPLE_FILTER, *_residue_pair()]
    assert scope_region_filters(filters, "card", {"index": "c"}) == [SAMPLE_FILTER]
    card = {"index": "c", "follow_region_filter": True}
    assert scope_region_filters(filters, "card", card) == filters


def test_figure_encoding_the_position_keeps_it():
    figure = {"dict_kwargs": {"x": "position", "y": "plddt"}}
    assert scope_region_filters(_residue_pair(), "figure", figure) == _residue_pair()


def test_tables_and_advanced_viz_keep_it():
    for kind in ("table", "advanced_viz"):
        assert scope_region_filters(_residue_pair(), kind, {}) == _residue_pair()


DOMAIN_LABEL = {
    "index": "arch",
    "value": ["Pkinase"],
    "source": "scatter_selection",
    "paired_with": "residue_selection",
    "metadata": {"dc_id": "dc-var", "column_name": "label"},
}
UNPAIRED_SELECTION = {
    "index": "msa",
    "value": ["P2"],
    "source": "scatter_selection",
    "metadata": {"dc_id": "dc-var", "column_name": "entity"},
}


def test_heatmap_and_upset_ignore_the_whole_residue_gesture():
    filters = [SAMPLE_FILTER, *_residue_pair(), DOMAIN_LABEL]
    for kind in ("complex_heatmap", "upset", "upset_plot"):
        assert scope_residue_filters(filters, kind) == [SAMPLE_FILTER]


def test_heatmap_and_upset_keep_real_filters_and_unpaired_selections():
    filters = [SAMPLE_FILTER, UNPAIRED_SELECTION, *_residue_pair()]
    for kind in ("complex_heatmap", "upset"):
        assert scope_residue_filters(filters, kind) == [SAMPLE_FILTER, UNPAIRED_SELECTION]


def test_source_read_from_metadata_too():
    nested = {"index": "x", "value": ["P1"], "metadata": {"source": "residue_selection"}}
    assert scope_residue_filters([nested, SAMPLE_FILTER], "upset") == [SAMPLE_FILTER]


def test_residue_driven_kinds_still_receive_the_pick():
    filters = [SAMPLE_FILTER, *_residue_pair(), DOMAIN_LABEL]
    kinds = (
        "molecule_3d",
        "sequence_track",
        "msa",
        "hmm_logo",
        "domain_architecture",
        "secondary_structure",
        "coverage_track",
        "embedding",
        None,
    )
    for kind in kinds:
        assert scope_residue_filters(filters, kind) == filters


def test_payload_hook_strips_the_pick_for_heatmap_and_upset_only():
    filters = [SAMPLE_FILTER, *_residue_pair(), DOMAIN_LABEL]
    for kind, expected in (
        ("complex_heatmap", [SAMPLE_FILTER]),
        ("upset", [SAMPLE_FILTER]),
        ("coverage_track", filters),
    ):
        payload = {"wf_id": "w", "dc_id": "d", "filter_metadata": list(filters)}
        # No access token: link resolution is a no-op, only the scoping runs.
        _apply_link_filters_to_payload(payload, None, kind)
        assert payload["filter_metadata"] == expected
