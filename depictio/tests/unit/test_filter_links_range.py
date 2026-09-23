"""A RangeSlider filter walks a value link as a span, not as two members.

atacseq's Peak locus tab (AT-D26, 2026-09-23): the navigator's position range
``[26000000, 26300000]`` on ``macs2_broad_peaks`` reached the direct
``peak_id`` link to ``homer_annotated_peaks`` as ``start IN (26000000, 26300000)``,
resolved to no peak at all and emptied the HOMER track. The walk now tells the
resolve endpoint that the first hop's values are a range.
"""

import pytest

from depictio.api.v1 import filter_links

pytestmark = pytest.mark.no_db

PEAKS = "6a1954189fa2f2d1ffc39c76"
HOMER = "6a19541e70f089f587c39c99"
GENES = "6a19541e70f089f587c39caa"


def _direct(link_id, source, target, column):
    return {
        "id": link_id,
        "source_dc_id": source,
        "target_dc_id": target,
        "source_column": column,
        "enabled": True,
        "link_config": {"resolver": "direct", "target_field": column},
    }


def _slider(column="start", value=(26_000_000, 26_300_000), component="RangeSlider"):
    return {
        "index": "rs-1",
        "value": list(value),
        "metadata": {
            "dc_id": PEAKS,
            "column_name": column,
            "interactive_component_type": component,
        },
    }


def test_slider_is_a_range_and_a_multiselect_is_not():
    assert filter_links._is_range_filter(_slider())
    assert filter_links._is_range_filter(_slider(component="DateRangePicker"))
    assert not filter_links._is_range_filter(_slider(component="MultiSelect"))
    assert not filter_links._is_range_filter(_slider(value=(1, 2, 3)))


def test_first_hop_carries_the_range_and_later_hops_do_not(monkeypatch):
    calls = []

    def fake_resolve(**kwargs):
        calls.append(kwargs)
        return {"resolved_values": ["p1", "p2"], "target_column": None}

    monkeypatch.setattr(filter_links, "resolve_link_values", fake_resolve)
    path = [_direct("l1", PEAKS, HOMER, "peak_id"), _direct("l2", HOMER, GENES, "gene_id")]
    column, values = filter_links._walk_link_path(
        path=path,
        project_id="p",
        origin_column="start",
        origin_values=[26_000_000, 26_300_000],
        access_token="t",
        component_type="test",
        range_filter=True,
    )
    assert [c["range_filter"] for c in calls] == [True, False]
    assert calls[0]["source_column"] == "start"
    assert calls[0]["filter_values"] == [26_000_000, 26_300_000]
    assert values == ["p1", "p2"]


def test_extend_filters_flags_the_slider_hop(monkeypatch):
    seen = []

    def fake_walk(**kwargs):
        seen.append(kwargs["range_filter"])
        return "peak_id", ["p1"]

    monkeypatch.setattr(filter_links, "_walk_link_path", fake_walk)
    project = {"project": {"_id": "p", "links": [_direct("l1", PEAKS, HOMER, "peak_id")]}}
    out = filter_links.extend_filters_via_links(
        filters_by_dc={
            PEAKS: [_slider(), _slider(column="name", value=("a", "b"), component="MultiSelect")]
        },
        target_dc_id=HOMER,
        project_metadata=project,
        access_token="t",
        component_type="test",
    )
    assert seen == [True, False]
    assert all(f["metadata"]["column_name"] == "peak_id" for f in out)
