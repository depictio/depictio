"""Cross-DC filters must travel the whole link graph, not just one hop.

With A -> B -> C declared, a filter on A has to narrow a component reading C.
The original implementation only matched links whose target was the component's
own DC, so a filter two hops away was silently ignored and the component
rendered unfiltered — indistinguishable from "nothing selected".
"""

import pytest

from depictio.api.v1 import filter_links

pytestmark = pytest.mark.no_db


def _link(
    link_id,
    source,
    target,
    source_column="sample_id",
    enabled=True,
    resolver="direct",
    target_field=None,
):
    link_config = {"resolver": resolver}
    if target_field:
        link_config["target_field"] = target_field
    return {
        "id": link_id,
        "source_dc_id": source,
        "target_dc_id": target,
        "source_column": source_column,
        "enabled": enabled,
        "link_config": link_config,
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
        *, project_id, source_dc_id, source_column, filter_values, target_dc_id, token, reverse
    ):
        seen.append((source_dc_id, source_column, tuple(filter_values), target_dc_id, reverse))
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
        ("A", "habitat", ("Groundwater",), "B", False),
        # hop 2 filters on the link's join column, not the user's column
        ("B", "sample_id", ("Groundwater@B",), "C", False),
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


# --------------------------------------------------------------------------
# Walking a direct link backwards (selection groups only)
# --------------------------------------------------------------------------


def _hops(paths):
    return [[(link["id"], filter_links._is_reversed(link)) for link in p] for p in paths]


def test_reverse_edge_only_when_allowed():
    links = [_link("l1", "B", "A")]
    assert filter_links._link_paths(links, "A", "B") == []
    assert _hops(filter_links._link_paths(links, "A", "B", allow_reverse=True)) == [[("l1", True)]]


def test_reversing_leaves_the_declared_link_untouched():
    link = _link("l1", "B", "A")
    filter_links._link_paths([link], "A", "B", allow_reverse=True)
    assert not filter_links._is_reversed(link)


def test_declared_direction_wins_at_equal_length():
    links = [_link("rev", "B", "A"), _link("fwd", "A", "B")]
    paths = filter_links._link_paths(links, "A", "B", allow_reverse=True)
    assert _hops(paths) == [[("fwd", False)], [("rev", True)]]


def test_fewer_reversed_hops_win_over_discovery_order():
    # Breadth-first reaches C through B first, a route that walks l2 backwards.
    # The all-declared route through E is found second and must still lead.
    links = [
        _link("l1", "A", "B"),
        _link("l3", "A", "E"),
        _link("l2", "C", "B"),
        _link("l4", "E", "C"),
    ]
    paths = filter_links._link_paths(links, "A", "C", allow_reverse=True)
    assert _hops(paths) == [[("l3", False), ("l4", False)], [("l1", False), ("l2", True)]]


def test_a_shorter_reversed_route_beats_a_longer_declared_one():
    links = [_link("l1", "A", "B"), _link("l2", "B", "C"), _link("l3", "C", "A")]
    paths = filter_links._link_paths(links, "A", "C", allow_reverse=True)
    assert _hops(paths) == [[("l3", True)], [("l1", False), ("l2", False)]]


def test_non_direct_resolvers_are_never_reversed():
    links = [_link("l1", "B", "A", resolver="sample_mapping")]
    assert filter_links._link_paths(links, "A", "B", allow_reverse=True) == []


def test_disabled_links_are_not_reversed_either():
    links = [_link("l1", "B", "A", enabled=False)]
    assert filter_links._link_paths(links, "A", "B", allow_reverse=True) == []


def _star_links():
    """hub.merged_library -> peaks (named ``sample`` there), and hub.sample -> qc."""
    return [
        _link("l1", "hub", "peaks", source_column="merged_library", target_field="sample"),
        _link("l2", "hub", "qc", source_column="sample"),
    ]


def test_walking_a_reversed_hop(monkeypatch):
    """Backwards, a hop asks with ``reverse=True`` and lands on the link's source_column."""
    seen = []

    def fake_resolve(*, source_dc_id, source_column, target_dc_id, reverse, filter_values, **kw):
        seen.append((source_dc_id, source_column, target_dc_id, reverse))
        return {"resolved_values": [f"{v}@{target_dc_id}" for v in filter_values]}

    monkeypatch.setattr(filter_links, "resolve_link_values", fake_resolve)

    (path,) = filter_links._link_paths(_star_links(), "peaks", "qc", allow_reverse=True)
    column, values = filter_links._walk_link_path(
        path=path,
        project_id="p1",
        origin_column="peak_id",
        origin_values=["peak_1"],
        access_token="tok",
        component_type="figure",
    )

    assert seen == [
        ("peaks", "peak_id", "hub", True),
        # the hub's own name for the join, not the peak table's `sample`
        ("hub", "merged_library", "qc", False),
    ]
    assert column == "sample"
    assert values == ["peak_1@hub@qc"]


def test_a_chain_ending_backwards_reports_the_link_source_column(monkeypatch):
    monkeypatch.setattr(filter_links, "resolve_link_values", lambda **kw: {"resolved_values": []})
    (path,) = filter_links._link_paths(_star_links(), "peaks", "hub", allow_reverse=True)
    assert filter_links._walk_link_path(
        path=path,
        project_id="p1",
        origin_column="peak_id",
        origin_values=["peak_1"],
        access_token="tok",
        component_type="figure",
    ) == ("merged_library", [])


def test_dashboard_filters_never_walk_a_link_backwards(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("a dashboard filter walked a link against its direction")

    monkeypatch.setattr(filter_links, "resolve_link_values", boom)
    out = filter_links.extend_filters_via_links(
        target_dc_id="hub",
        filters_by_dc={
            "peaks": [{"index": "i1", "value": ["peak_1"], "metadata": {"column_name": "peak_id"}}]
        },
        project_metadata=_project(_star_links()),
        access_token="tok",
        component_type="figure",
    )
    assert out == []


def test_groups_walk_a_link_backwards(monkeypatch):
    monkeypatch.setattr(
        filter_links, "resolve_link_values", lambda **kw: {"resolved_values": ["LIB1"]}
    )
    hop = filter_links.resolve_values_via_links(
        project_metadata=_project(_star_links()),
        origin_dc_id="peaks",
        origin_column="peak_id",
        values=["peak_1"],
        target_dc_id="hub",
        access_token="tok",
    )
    assert hop == ("merged_library", ["LIB1"])
