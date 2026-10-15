"""A residue pick (``residue_selection``) is scoped like a genome region."""

from depictio.api.v1.region_scope import is_region_filter, scope_region_filters


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
