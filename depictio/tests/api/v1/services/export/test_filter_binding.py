"""Filters built from the manifest must reach every render path.

The manifest publishes a control as ``{component_id, filter: {column_name, …}}``,
so that is what a host page has to work with. Inside Depictio the MultiQC path
resolves a filter by ``index`` — the dashboard-internal component id — and finds
nothing when a filter carries only a column name, returning the *unfiltered*
figure while still reporting ``filter_applied: true``.

These tests assert on the binding rather than on a rendered figure, because the
figure paths need MultiQC report fixtures and object storage. What can go wrong
here is the mapping: a column bound to the wrong control, an explicit id
overwritten, or an unmatched column silently swallowed.
"""

from depictio.api.v1.services.export.filter_binding import bind_filters

SAMPLE_CONTROL = {
    "index": "mqc-sample-filter",
    "component_type": "interactive",
    "interactive_component_type": "MultiSelect",
    "column_name": "sample",
    "dc_id": "dc-multiqc",
}
LINEAGE_CONTROL = {
    "index": "mqc-lineage-filter",
    "component_type": "interactive",
    "interactive_component_type": "MultiSelect",
    "column_name": "lineage",
    "dc_id": "dc-metadata",
}
FIGURE_COMPONENT = {
    "index": "some-figure",
    "component_type": "figure",
    "dc_id": "dc-multiqc",
}

DASHBOARD = {"stored_metadata": [SAMPLE_CONTROL, LINEAGE_CONTROL, FIGURE_COMPONENT]}


def test_column_only_filter_gains_the_control_index():
    """The shape the manifest implies must work without the caller knowing ids."""
    bound, unmatched = bind_filters(
        DASHBOARD,
        [{"interactive_component_type": "MultiSelect", "column_name": "sample", "value": ["S1"]}],
    )
    assert unmatched == []
    assert bound[0]["index"] == "mqc-sample-filter"
    assert bound[0]["dc_id"] == "dc-multiqc"
    # The caller's own fields survive; binding adds, it does not rewrite.
    assert bound[0]["value"] == ["S1"]


def test_explicit_index_is_left_alone():
    """A payload captured from the dashboard must replay exactly.

    An explicit index is a stronger statement than a column name — two controls
    can drive the same column — so it wins.
    """
    bound, unmatched = bind_filters(
        DASHBOARD,
        [{"column_name": "sample", "index": "some-other-control", "value": ["S1"]}],
    )
    assert unmatched == []
    assert bound[0]["index"] == "some-other-control"


def test_component_id_is_accepted_as_the_index():
    """`component_id` is the manifest's name for the index; honour it directly."""
    bound, _ = bind_filters(
        DASHBOARD,
        [{"column_name": "sample", "component_id": "mqc-sample-filter", "value": ["S1"]}],
    )
    assert bound[0]["index"] == "mqc-sample-filter"


def test_dc_id_disambiguates_two_controls_on_one_column():
    """Two DCs can both have a `sample` column; a caller that knows must be heard."""
    dashboard = {
        "stored_metadata": [
            SAMPLE_CONTROL,
            {**SAMPLE_CONTROL, "index": "other-sample-filter", "dc_id": "dc-other"},
        ]
    }
    bound, _ = bind_filters(
        dashboard,
        [{"column_name": "sample", "dc_id": "dc-other", "value": ["S1"]}],
    )
    assert bound[0]["index"] == "other-sample-filter"


def test_unmatched_column_is_reported_not_swallowed():
    """A filter no control drives is passed through *and* named.

    Passed through because the column-keyed paths (figure, advanced_viz) can
    still apply it; named because otherwise a host cannot tell "filtered to
    nothing" from "this filter never reached anything".
    """
    bound, unmatched = bind_filters(
        DASHBOARD,
        [{"column_name": "not_a_column", "value": ["x"]}],
    )
    assert unmatched == ["not_a_column"]
    assert bound[0]["column_name"] == "not_a_column"
    assert "index" not in bound[0]


def test_non_interactive_components_are_not_matched():
    """A figure on a DC must never be mistaken for that DC's control."""
    dashboard = {"stored_metadata": [{**FIGURE_COMPONENT, "column_name": "sample"}]}
    bound, unmatched = bind_filters(dashboard, [{"column_name": "sample", "value": ["S1"]}])
    assert unmatched == ["sample"]
    assert "index" not in bound[0]


def test_empty_filters_short_circuit():
    assert bind_filters(DASHBOARD, []) == ([], [])
