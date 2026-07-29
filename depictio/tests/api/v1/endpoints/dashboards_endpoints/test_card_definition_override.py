"""Recomputing a card's value against a past version of itself.

The component-history modal needs two things at once: the card *definition*
from a stored version, and the data from that version's Delta commit. Applying
today's aggregation to yesterday's data would answer a question nobody asked,
and would do so without any visible sign.

The override is client-supplied, so the boundary matters as much as the
behaviour: a card's *definition* is versioned and safe to take from the
request, but the fields deciding *which collection is read* are not — those
were permission-checked against the live dashboard.
"""

from __future__ import annotations

from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    _CARD_DEFINITION_FIELDS,
    _card_definition_override,
)


def test_definition_fields_are_honoured():
    """The point: a version's column/aggregation drives the recomputation."""
    override = _card_definition_override({"column_name": "petal.length", "aggregation": "mean"})

    assert override == {"column_name": "petal.length", "aggregation": "mean"}


def test_collection_identity_cannot_be_overridden():
    """`dc_id`/`wf_id` decide which data is read, and were access-checked
    against the live dashboard. Accepting them from the request would let a
    caller compute over a collection this dashboard never references."""
    override = _card_definition_override(
        {
            "column_name": "variety",
            "dc_id": "646b0f3c1e4a2d7f8e5b8c9c",
            "wf_id": "646b0f3c1e4a2d7f8e5b8c9b",
            "dc_config": {"delta_location": "s3://somewhere/else"},
        }
    )

    assert override == {"column_name": "variety"}
    assert "dc_id" not in _CARD_DEFINITION_FIELDS
    assert "wf_id" not in _CARD_DEFINITION_FIELDS
    assert "dc_config" not in _CARD_DEFINITION_FIELDS


def test_malformed_override_falls_back_rather_than_failing():
    """One broken card in a modal must not blank the rest of the dashboard."""
    assert _card_definition_override("not-a-dict") == {}
    assert _card_definition_override(None) == {}
    assert _card_definition_override([]) == {}


def test_null_values_do_not_erase_the_live_definition():
    """A snapshot omitting a field must leave the live one in place — merging
    `None` over `aggregation` would produce a card that computes nothing."""
    override = _card_definition_override({"column_name": "x", "aggregation": None})

    assert override == {"column_name": "x"}


def test_unknown_keys_are_dropped():
    """The allowlist is closed, so a new stored field cannot silently become
    an injection point when snapshots gain one."""
    override = _card_definition_override({"column_name": "x", "surprise": "value"})

    assert override == {"column_name": "x"}


def test_secondary_aggregations_survive():
    """Multi-metric cards carry their aggregation list in the definition;
    dropping it would silently reduce a card to its hero value."""
    override = _card_definition_override(
        {"aggregations": ["mean", "max"], "breakdown_col": "variety"}
    )

    assert override == {"aggregations": ["mean", "max"], "breakdown_col": "variety"}


# ── the same allow-list, for figures and tables ─────────────────────────────
#
# Component history renders a past version of *any* component, not just cards.
# Figures and tables previously had no override at all, so the modal drew a
# past version's data with today's chart definition and labelled it as the
# past — the one failure this whole feature exists to prevent.


def test_figure_definition_fields_are_honoured() -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _definition_override

    override = _definition_override(
        {"visu_type": "histogram", "dict_kwargs": {"x": "petal.length"}},
        "figure",
    )

    assert override == {"visu_type": "histogram", "dict_kwargs": {"x": "petal.length"}}


def test_table_definition_fields_are_honoured() -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _definition_override

    override = _definition_override({"columns": ["a", "b"]}, "table")

    assert override == {"columns": ["a", "b"]}


def test_no_type_can_redirect_which_collection_is_read() -> None:
    """The security boundary, asserted for every type at once.

    `dc_id` / `wf_id` / `dc_config` decide which data is read, and were
    permission-checked against the *live* dashboard. Honouring them from a
    request would let a caller compute over a collection this dashboard does
    not reference.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _DEFINITION_FIELDS,
        _definition_override,
    )

    forbidden = {"dc_id": "deadbeef", "wf_id": "cafe", "dc_config": {"type": "table"}}

    for component_type in _DEFINITION_FIELDS:
        assert _definition_override(forbidden, component_type) == {}, component_type


def test_an_unknown_component_type_overrides_nothing() -> None:
    """Allow-list per type, so a new type is inert until deliberately added.

    Defaulting to "allow everything" for an unrecognised type would silently
    widen the boundary each time a component type is introduced.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _definition_override

    assert _definition_override({"title": "x"}, "multiqc") == {}
    assert _definition_override({"title": "x"}, "") == {}


def test_the_type_comes_from_the_live_component_not_the_request() -> None:
    """Otherwise a caller picks which allow-list judges them.

    A figure declaring itself a card would be judged by the card list, so
    `column_name` and `aggregation` would pass on a component that is not one.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _apply_component_override,
    )

    live = {"index": "a", "component_type": "figure", "visu_type": "box"}
    request = {
        "component_overrides": {
            "a": {"component_type": "card", "aggregation": "count", "visu_type": "histogram"}
        }
    }

    result = _apply_component_override(live, request)

    # The figure field applies; the card-only field does not, and the type
    # itself is not overridable.
    assert result["visu_type"] == "histogram"
    assert "aggregation" not in result
    assert result["component_type"] == "figure"


def test_a_component_with_no_override_is_returned_unchanged() -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _apply_component_override,
    )

    live = {"index": "a", "component_type": "figure", "visu_type": "box"}

    assert _apply_component_override(live, {}) is live
    assert _apply_component_override(live, {"component_overrides": {"other": {}}}) is live
