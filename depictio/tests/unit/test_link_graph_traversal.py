"""Cross-DC filters must travel the whole link graph, not just one hop.

With A -> B -> C declared, a filter on A has to narrow a component reading C.
The original implementation only matched links whose target was the component's
own DC, so a filter two hops away was silently ignored and the component
rendered unfiltered — indistinguishable from "nothing selected".
"""

import pytest

from depictio.api.v1 import filter_links

pytestmark = pytest.mark.no_db


def _link(link_id, source, target, source_column="sample_id", enabled=True):
    return {
        "id": link_id,
        "source_dc_id": source,
        "target_dc_id": target,
        "source_column": source_column,
        "enabled": enabled,
        "link_config": {"resolver": "direct"},
    }


# --------------------------------------------------------------------------
# Path finding
# --------------------------------------------------------------------------


def test_finds_direct_path():
    links = [_link("l1", "A", "B")]
    paths = filter_links._link_paths(links, "A", "B")
    assert [[link["id"] for link in p] for p in paths] == [["l1"]]


def test_finds_two_hop_chain():
    links = [_link("l1", "A", "B"), _link("l2", "B", "C")]
    paths = filter_links._link_paths(links, "A", "C")
    assert [[link["id"] for link in p] for p in paths] == [["l1", "l2"]]


def test_star_topology_keeps_every_source():
    """Two sources pointing at one target: both must contribute."""
    links = [_link("l1", "A", "C"), _link("l2", "B", "C")]
    assert len(filter_links._link_paths(links, "A", "C")) == 1
    assert len(filter_links._link_paths(links, "B", "C")) == 1


def test_multiple_routes_to_same_target_are_all_returned():
    links = [_link("l1", "A", "B"), _link("l2", "B", "D"), _link("l3", "A", "D")]
    paths = filter_links._link_paths(links, "A", "D")
    routes = sorted(["".join(link["id"] for link in p) for p in paths])
    assert routes == ["l1l2", "l3"]
    # Breadth-first: the direct route is discovered before the two-hop one.
    assert len(paths[0]) == 1


def test_cycles_terminate():
    links = [_link("l1", "A", "B"), _link("l2", "B", "A"), _link("l3", "B", "C")]
    paths = filter_links._link_paths(links, "A", "C")
    assert [[link["id"] for link in p] for p in paths] == [["l1", "l3"]]


def test_depth_is_bounded():
    links = [_link(f"l{i}", chr(65 + i), chr(66 + i)) for i in range(6)]  # A->B->...->G
    assert filter_links._link_paths(links, "A", "G", max_hops=3) == []
    assert len(filter_links._link_paths(links, "A", "D", max_hops=3)) == 1


def test_disabled_links_are_not_traversed():
    links = [_link("l1", "A", "B"), _link("l2", "B", "C", enabled=False)]
    assert filter_links._link_paths(links, "A", "C") == []


def test_same_dc_has_no_path():
    assert filter_links._link_paths([_link("l1", "A", "B")], "A", "A") == []


# --------------------------------------------------------------------------
# Walking a path
# --------------------------------------------------------------------------


def test_walk_composes_hops(monkeypatch):
    """Each hop's output is the next hop's input."""
    seen = []

    def fake_resolve(
        *, project_id, source_dc_id, source_column, filter_values, target_dc_id, token
    ):
        seen.append((source_dc_id, source_column, tuple(filter_values), target_dc_id))
        return {"resolved_values": [f"{v}@{target_dc_id}" for v in filter_values]}

    monkeypatch.setattr(filter_links, "resolve_link_values", fake_resolve)

    path = [_link("l1", "A", "B"), _link("l2", "B", "C")]
    column, values = filter_links._walk_link_path(
        path=path,
        project_id="p1",
        origin_column="habitat",
        origin_values=["Groundwater"],
        access_token="tok",
        component_type="figure",
    )

    assert seen == [
        ("A", "habitat", ("Groundwater",), "B"),
        # hop 2 filters on the link's join column, not the user's column
        ("B", "sample_id", ("Groundwater@B",), "C"),
    ]
    assert column == "sample_id"
    assert values == ["Groundwater@B@C"]


def test_chain_that_matches_nothing_reports_the_final_column(monkeypatch):
    """A hop resolving to nothing is an answer: no rows, on the final column.

    It must be distinguishable from an unusable chain, because the caller has to
    emit a filter for it. Dropping it instead would render every row — the exact
    failure that looks like success.
    """

    def fake_resolve(*, target_dc_id, **kwargs):
        return {"resolved_values": ["x"]} if target_dc_id == "B" else {"resolved_values": []}

    monkeypatch.setattr(filter_links, "resolve_link_values", fake_resolve)

    column, values = filter_links._walk_link_path(
        path=[_link("l1", "A", "B"), _link("l2", "B", "C")],
        project_id="p1",
        origin_column="habitat",
        origin_values=["Groundwater"],
        access_token="tok",
        component_type="figure",
    )
    assert (column, values) == ("sample_id", [])


def test_missing_link_is_unusable_not_empty(monkeypatch):
    """A 404 (no such link) yields no result at all — not an empty match."""
    monkeypatch.setattr(filter_links, "resolve_link_values", lambda **kw: None)

    assert filter_links._walk_link_path(
        path=[_link("l1", "A", "B")],
        project_id="p1",
        origin_column="habitat",
        origin_values=["Groundwater"],
        access_token="tok",
        component_type="figure",
    ) == (None, [])


def test_resolution_failure_propagates(monkeypatch):
    """A timeout must reach the caller, never degrade into 'no filter'."""

    def boom(**kwargs):
        raise filter_links.LinkResolutionError("timed out")

    monkeypatch.setattr(filter_links, "resolve_link_values", boom)

    with pytest.raises(filter_links.LinkResolutionError):
        filter_links._walk_link_path(
            path=[_link("l1", "A", "B")],
            project_id="p1",
            origin_column="habitat",
            origin_values=["Groundwater"],
            access_token="tok",
            component_type="figure",
        )


# --------------------------------------------------------------------------
# End to end through extend_filters_via_links
# --------------------------------------------------------------------------


def _project(links):
    return {"project": {"_id": "p1", "links": links}}


def test_two_hop_filter_reaches_the_far_dc(monkeypatch):
    def fake_resolve(*, filter_values, target_dc_id, **kwargs):
        return {"resolved_values": [f"{v}->{target_dc_id}" for v in filter_values]}

    monkeypatch.setattr(filter_links, "resolve_link_values", fake_resolve)

    out = filter_links.extend_filters_via_links(
        target_dc_id="C",
        filters_by_dc={
            "A": [{"index": "i1", "value": ["Groundwater"], "metadata": {"column_name": "habitat"}}]
        },
        project_metadata=_project([_link("l1", "A", "B"), _link("l2", "B", "C")]),
        access_token="tok",
        component_type="figure",
    )

    assert len(out) == 1
    assert out[0]["metadata"]["dc_id"] == "C"
    assert out[0]["metadata"]["column_name"] == "sample_id"
    assert out[0]["value"] == ["Groundwater->B->C"]


def test_single_hop_behaviour_is_unchanged(monkeypatch):
    monkeypatch.setattr(
        filter_links,
        "resolve_link_values",
        lambda **kw: {"resolved_values": ["s1", "s2"]},
    )
    out = filter_links.extend_filters_via_links(
        target_dc_id="B",
        filters_by_dc={
            "A": [{"index": "i1", "value": ["Groundwater"], "metadata": {"column_name": "habitat"}}]
        },
        project_metadata=_project([_link("l1", "A", "B")]),
        access_token="tok",
        component_type="figure",
    )
    assert len(out) == 1
    assert out[0]["value"] == ["s1", "s2"]
    assert out[0]["metadata"]["column_name"] == "sample_id"


def test_three_sources_all_reach_one_target(monkeypatch):
    """More than two linked DCs: every filtered source contributes its own filter."""
    monkeypatch.setattr(
        filter_links,
        "resolve_link_values",
        lambda **kw: {"resolved_values": [f"from_{kw['source_dc_id']}"]},
    )
    out = filter_links.extend_filters_via_links(
        target_dc_id="D",
        filters_by_dc={
            "A": [{"index": "a", "value": ["x"], "metadata": {"column_name": "habitat"}}],
            "B": [{"index": "b", "value": ["y"], "metadata": {"column_name": "batch"}}],
            "C": [{"index": "c", "value": ["z"], "metadata": {"column_name": "site"}}],
        },
        project_metadata=_project(
            [_link("l1", "A", "D"), _link("l2", "B", "D"), _link("l3", "C", "D")]
        ),
        access_token="tok",
        component_type="figure",
    )
    assert sorted(f["value"][0] for f in out) == ["from_A", "from_B", "from_C"]
    assert len({f["index"] for f in out}) == 3, "synthetic filters must not collide on index"


def test_filters_on_the_component_own_dc_are_not_re_resolved(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("resolved a filter that already applies natively")

    monkeypatch.setattr(filter_links, "resolve_link_values", boom)
    assert (
        filter_links.extend_filters_via_links(
            target_dc_id="A",
            filters_by_dc={
                "A": [{"index": "i1", "value": ["x"], "metadata": {"column_name": "habitat"}}]
            },
            project_metadata=_project([_link("l1", "A", "B")]),
            access_token="tok",
            component_type="figure",
        )
        == []
    )


def test_empty_resolution_emits_a_no_match_filter(monkeypatch):
    """Zero resolved values must survive as a filter meaning "no rows".

    An empty ``value`` list cannot carry that meaning: every branch of
    ``add_filter`` is guarded by ``if value:``, so it falls through as no filter
    at all and the component renders EVERY row — the user sees an unfiltered
    table and no indication anything went wrong.
    """
    from depictio.api.v1.deltatables_utils import LINK_NO_MATCH

    monkeypatch.setattr(filter_links, "resolve_link_values", lambda **kw: {"resolved_values": []})

    out = filter_links.extend_filters_via_links(
        target_dc_id="B",
        filters_by_dc={
            "A": [{"index": "i1", "value": ["Groundwater"], "metadata": {"column_name": "habitat"}}]
        },
        project_metadata=_project([_link("l1", "A", "B")]),
        access_token="tok",
        component_type="figure",
    )

    assert len(out) == 1, "an empty match must still produce a filter"
    assert out[0]["value"] == []
    assert out[0]["metadata"]["interactive_component_type"] == LINK_NO_MATCH


def test_no_match_filter_yields_no_rows():
    """The sentinel must actually filter everything out downstream."""
    import polars as pl

    from depictio.api.v1.deltatables_utils import LINK_NO_MATCH, add_filter

    filters: list = []
    add_filter(filters, LINK_NO_MATCH, "sample_id", [])
    assert len(filters) == 1, "the sentinel produced no predicate"

    df = pl.DataFrame({"sample_id": ["a", "b", "c"]})
    assert df.filter(filters[0]).height == 0

    # Contrast: an ordinary MultiSelect with an empty list adds nothing, which is
    # why the sentinel has to exist.
    ordinary: list = []
    add_filter(ordinary, "MultiSelect", "sample_id", [])
    assert ordinary == []
