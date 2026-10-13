"""A genomic region must travel across collections without resolving anything.

A `genome_view` brush publishes a region as two ordinary filters on ITS OWN
columns (a chromosome multi-select, a position range). A second collection
holding the same locus under different column names never sees it: the value
resolvers all answer "which values of the target's join column correspond to
these source values", which for a chromosome name and a base-pair coordinate is
the identity. The `region` resolver says so, and renames the two columns instead
of reading any data.
"""

import pytest

from depictio.api.v1 import filter_links
from depictio.models.models.links import LinkConfig

pytestmark = pytest.mark.no_db


def _region_link(link_id="rl1", source="A", target="B", source_column="chr", **columns):
    return {
        "id": link_id,
        "source_dc_id": source,
        "target_dc_id": target,
        "source_column": source_column,
        "enabled": True,
        "link_config": {
            "resolver": "region",
            "columns": columns or {"chrom": "chromosome", "pos": "position"},
        },
    }


def _brush(
    index="gv-1", chrom="chr7", start=55_000_000, end=56_000_000, chr_col="chr", pos_col="pos"
):
    """The pair `genomeRegionFilters` emits, as the API receives it."""
    return [
        {
            "index": index,
            "value": [chrom],
            "source": "genome_selection",
            "metadata": {
                "dc_id": "A",
                "column_name": chr_col,
                "interactive_component_type": "MultiSelect",
            },
        },
        {
            "index": f"{index}::pos",
            "value": [start, end],
            "source": "genome_selection",
            "metadata": {
                "dc_id": "A",
                "column_name": pos_col,
                "interactive_component_type": "RangeSlider",
            },
        },
    ]


def _project(links):
    return {"project": {"_id": "p1", "links": links}}


# --------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------


def test_region_resolver_needs_both_columns():
    LinkConfig(resolver="region", columns={"chrom": "chromosome", "pos": "position"})
    with pytest.raises(ValueError, match="pos"):
        LinkConfig(resolver="region", columns={"chrom": "chromosome"})
    with pytest.raises(ValueError, match="chrom"):
        LinkConfig(resolver="region")


def test_other_resolvers_ignore_columns():
    """Backward compatible: every existing link validates unchanged."""
    assert LinkConfig().resolver == "direct"
    assert LinkConfig(resolver="sample_mapping", target_field="sample_name").columns is None


# --------------------------------------------------------------------------
# The rewrite
# --------------------------------------------------------------------------


def test_region_pair_lands_on_the_target_columns():
    out = filter_links.region_link_filters(
        target_dc_id="B",
        filters_by_dc={"A": _brush()},
        project_links=[_region_link()],
    )
    by_column = {f["metadata"]["column_name"]: f for f in out}
    assert set(by_column) == {"chromosome", "position"}
    assert by_column["chromosome"]["value"] == ["chr7"]
    assert by_column["chromosome"]["metadata"]["interactive_component_type"] == "MultiSelect"
    assert by_column["position"]["value"] == [55_000_000, 56_000_000]
    assert by_column["position"]["metadata"]["interactive_component_type"] == "RangeSlider"
    assert {f["metadata"]["dc_id"] for f in out} == {"B"}
    assert len({f["index"] for f in out}) == 2, "the two halves must not collide on index"


def test_chromosome_alone_still_travels():
    """A sidebar chromosome select with no range is a whole contig, not nothing."""
    chrom_only = [_brush()[0]]
    out = filter_links.region_link_filters(
        target_dc_id="B", filters_by_dc={"A": chrom_only}, project_links=[_region_link()]
    )
    assert [f["metadata"]["column_name"] for f in out] == ["chromosome"]


def test_a_range_without_its_chromosome_is_dropped():
    """A bare coordinate range would narrow every contig of the target at once."""
    pos_only = [_brush()[1]]
    assert (
        filter_links.region_link_filters(
            target_dc_id="B", filters_by_dc={"A": pos_only}, project_links=[_region_link()]
        )
        == []
    )


def test_the_link_picks_its_binding_by_chromosome_column():
    """A collection with two coordinate bindings links each one separately."""
    links = [_region_link(source_column="coverage_chr", chrom="chromosome", pos="position")]
    assert (
        filter_links.region_link_filters(
            target_dc_id="B",
            filters_by_dc={"A": _brush(chr_col="chr")},
            project_links=links,
        )
        == []
    )
    out = filter_links.region_link_filters(
        target_dc_id="B",
        filters_by_dc={"A": _brush(chr_col="coverage_chr")},
        project_links=links,
    )
    assert len(out) == 2


def test_two_regions_on_one_dc_pair_by_index():
    """The position half carries its chromosome's index plus `::pos`."""
    filters = _brush(index="gv-1", chrom="chr7", chr_col="chr") + _brush(
        index="gv-2", chrom="chr1", start=1, end=2, chr_col="other_chr", pos_col="other_pos"
    )
    out = filter_links.region_link_filters(
        target_dc_id="B",
        filters_by_dc={"A": filters},
        project_links=[_region_link(source_column="other_chr")],
    )
    by_column = {f["metadata"]["column_name"]: f["value"] for f in out}
    assert by_column == {"chromosome": ["chr1"], "position": [1, 2]}


def test_only_genome_selection_filters_are_rewritten():
    ordinary = [
        {
            "index": "i1",
            "value": ["S1"],
            "source": "interactive",
            "metadata": {
                "dc_id": "A",
                "column_name": "sample",
                "interactive_component_type": "MultiSelect",
            },
        }
    ]
    assert (
        filter_links.region_link_filters(
            target_dc_id="B", filters_by_dc={"A": ordinary}, project_links=[_region_link()]
        )
        == []
    )


def test_disabled_and_unrelated_links_are_ignored():
    disabled = _region_link()
    disabled["enabled"] = False
    assert (
        filter_links.region_link_filters(
            target_dc_id="B", filters_by_dc={"A": _brush()}, project_links=[disabled]
        )
        == []
    )
    elsewhere = _region_link(target="C")
    assert (
        filter_links.region_link_filters(
            target_dc_id="B", filters_by_dc={"A": _brush()}, project_links=[elsewhere]
        )
        == []
    )


# --------------------------------------------------------------------------
# Through the public entry point, alongside the value resolvers
# --------------------------------------------------------------------------


def test_region_links_reach_extend_filters_via_links():
    out = filter_links.extend_filters_via_links(
        target_dc_id="B",
        filters_by_dc={"A": _brush()},
        project_metadata=_project([_region_link()]),
        access_token="tok",
        component_type="coverage_track",
    )
    assert sorted(f["metadata"]["column_name"] for f in out) == ["chromosome", "position"]


def test_region_links_are_never_walked_as_value_routes(monkeypatch):
    """A region link resolves nothing, so it must not reach `resolve_link_values`."""

    def explode(**kwargs):
        raise AssertionError("a region link must not be resolved against the data")

    monkeypatch.setattr(filter_links, "resolve_link_values", explode)
    assert filter_links._link_paths([_region_link()], "A", "B") == []
    out = filter_links.extend_filters_via_links(
        target_dc_id="B",
        filters_by_dc={"A": _brush()},
        project_metadata=_project([_region_link()]),
        access_token="tok",
    )
    assert len(out) == 2


def test_value_links_are_untouched_by_the_region_pass(monkeypatch):
    """Backward compatibility: a project with no region link behaves as before."""
    monkeypatch.setattr(
        filter_links,
        "resolve_link_values",
        lambda **kw: {"resolved_values": ["s1", "s2"]},
    )
    direct = {
        "id": "l1",
        "source_dc_id": "A",
        "target_dc_id": "B",
        "source_column": "sample_id",
        "enabled": True,
        "link_config": {"resolver": "direct"},
    }
    out = filter_links.extend_filters_via_links(
        target_dc_id="B",
        filters_by_dc={
            "A": [{"index": "i1", "value": ["x"], "metadata": {"column_name": "habitat"}}]
        },
        project_metadata=_project([direct]),
        access_token="tok",
    )
    assert len(out) == 1
    assert out[0]["value"] == ["s1", "s2"]
