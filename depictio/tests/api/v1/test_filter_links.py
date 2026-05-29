"""Tests for cross-DC link filter resolution in ``extend_filters_via_links``.

Regression coverage for the bug where a cross-DC link whose ``target_field`` is
null (the common 'direct' table→table case) produced a synthetic filter naming
the *user's filter column* instead of the link's *join column*. The resolved
values were correct but attached to the wrong column, so ``apply_runtime_filters``
silently dropped the filter and every row was returned (component never refreshed).
"""

from unittest.mock import patch

from depictio.api.v1.filter_links import extend_filters_via_links

# DC ids: source = metadata DC the user filters on, target = the canonical
# advanced-viz DC (e.g. rarefaction) we want to filter via the link.
SOURCE_DC = "6a19541470f089f587c39c64"
TARGET_DC = "6a1954189fa2f2d1ffc39c76"


def _project_metadata(*, target_field):
    """Project metadata with a single direct table→table link, mirroring the
    seeded ``sample_id`` link on the devdemo deployment."""
    return {
        "project": {
            "_id": "fcf60afdea2241b493b9c473",
            "links": [
                {
                    "id": "6a19541e70f089f587c39c6a",
                    "enabled": True,
                    "source_dc_id": SOURCE_DC,
                    # The link's join column — same name on both DCs for a
                    # 'direct' link. This is the column that exists on the target.
                    "source_column": "sample_id",
                    "target_dc_id": TARGET_DC,
                    "target_type": "table",
                    "link_config": {"resolver": "direct", "target_field": target_field},
                }
            ],
        }
    }


def _habitat_filter():
    """A MultiSelect filter on the source DC's ``habitat`` column — a column that
    does NOT exist on the target DC, so the link must translate it to ``sample_id``."""
    return {
        SOURCE_DC: [
            {
                "value": ["Groundwater"],
                "metadata": {
                    "column_name": "habitat",
                    "interactive_component_type": "MultiSelect",
                },
            }
        ]
    }


def test_link_filter_uses_join_column_not_filter_column():
    """When the resolver returns target-DC values but no ``target_column`` and the
    link has ``target_field: null``, the synthetic filter must name the link's
    join column (``sample_id``), not the user's filter column (``habitat``)."""
    resolved = {
        "resolved_values": ["SRR10070141", "SRR10070133", "SRR10070132"],
        "resolver_used": "direct",
    }
    with patch(
        "depictio.api.v1.filter_links.resolve_link_values", return_value=resolved
    ) as mock_resolve:
        link_filters = extend_filters_via_links(
            target_dc_id=TARGET_DC,
            filters_by_dc=_habitat_filter(),
            project_metadata=_project_metadata(target_field=None),
            access_token="fake-token",
            component_type="figure",
        )

    mock_resolve.assert_called_once()
    assert len(link_filters) == 1
    meta = link_filters[0]["metadata"]
    # The crux of the regression: column must be the join column, not 'habitat'.
    assert meta["column_name"] == "sample_id"
    assert meta["dc_id"] == TARGET_DC
    assert link_filters[0]["value"] == [
        "SRR10070141",
        "SRR10070133",
        "SRR10070132",
    ]


def test_target_field_override_takes_precedence_over_join_column():
    """If the link explicitly sets ``target_field`` (cross-DC rename, e.g. MultiQC
    sample_mapping), that wins over the join-column fallback."""
    resolved = {"resolved_values": ["s1", "s2"], "resolver_used": "sample_mapping"}
    with patch("depictio.api.v1.filter_links.resolve_link_values", return_value=resolved):
        link_filters = extend_filters_via_links(
            target_dc_id=TARGET_DC,
            filters_by_dc=_habitat_filter(),
            project_metadata=_project_metadata(target_field="sample_name"),
            access_token="fake-token",
            component_type="figure",
        )

    assert len(link_filters) == 1
    assert link_filters[0]["metadata"]["column_name"] == "sample_name"


def test_resolver_target_column_takes_top_precedence():
    """If the resolver ever returns an explicit ``target_column`` it wins over
    everything else."""
    resolved = {
        "resolved_values": ["s1"],
        "resolver_used": "direct",
        "target_column": "explicit_col",
    }
    with patch("depictio.api.v1.filter_links.resolve_link_values", return_value=resolved):
        link_filters = extend_filters_via_links(
            target_dc_id=TARGET_DC,
            filters_by_dc=_habitat_filter(),
            project_metadata=_project_metadata(target_field="sample_name"),
            access_token="fake-token",
            component_type="figure",
        )

    assert link_filters[0]["metadata"]["column_name"] == "explicit_col"


def test_link_skipped_when_no_join_column_resolvable():
    """If none of resolver/target_field/join-column yield a column, the link is
    skipped (not emitted with a None column that would crash downstream)."""
    resolved = {"resolved_values": ["s1"], "resolver_used": "direct"}
    md = _project_metadata(target_field=None)
    # Remove the join column so every fallback is empty.
    md["project"]["links"][0]["source_column"] = ""
    with patch("depictio.api.v1.filter_links.resolve_link_values", return_value=resolved):
        link_filters = extend_filters_via_links(
            target_dc_id=TARGET_DC,
            filters_by_dc=_habitat_filter(),
            project_metadata=md,
            access_token="fake-token",
            component_type="figure",
        )

    assert link_filters == []
