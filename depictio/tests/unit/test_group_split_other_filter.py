"""A split's "Other" panel: the samples in none of the analysis groups (#1476).

The panel is a group filter carrying ``metadata.exclude``: its values are every
group's values, and the rows it keeps are the ones those values do not name.
"""

import polars as pl
import pytest

from depictio.api.v1 import filter_links
from depictio.api.v1.deltatables_utils import (
    _generate_filter_hash,
    filter_excludes,
    process_metadata_and_filter,
)

pytestmark = pytest.mark.no_db

PCOA = "6a1954189fa2f2d1ffc39c76"
META = "6a19541e70f089f587c39c99"


def _group(values, exclude=False, dc_id=PCOA, column="sample"):
    meta = {"dc_id": dc_id, "column_name": column, "interactive_component_type": "MultiSelect"}
    if exclude:
        meta["exclude"] = True
    return {
        "index": "__depictio_group__:panel:Other",
        "value": list(values),
        "source": "group_filter",
        "metadata": meta,
    }


FRAME = pl.DataFrame({"sample": ["s1", "s2", "s3", "s4", None]})


def _kept(filters):
    exprs = process_metadata_and_filter(filters)
    df = FRAME
    for expr in exprs:
        df = df.filter(expr)
    return df.get_column("sample").to_list()


def test_other_keeps_the_rows_no_group_names_including_missing_ones():
    assert _kept([_group(["s1", "s2"])]) == ["s1", "s2"]
    assert _kept([_group(["s1", "s2"], exclude=True)]) == ["s3", "s4", None]


def test_other_excluding_nothing_keeps_every_row():
    assert _kept([_group([], exclude=True)]) == FRAME.get_column("sample").to_list()


def test_other_and_its_group_are_different_cache_entries():
    """One group: "Other" holds the same values, so only the flag tells them apart."""
    assert filter_excludes(_group(["s1"], exclude=True))
    assert not filter_excludes(_group(["s1"]))
    assert _generate_filter_hash([_group(["s1"])]) != _generate_filter_hash(
        [_group(["s1"], exclude=True)]
    )


def _link():
    return {
        "id": "l1",
        "source_dc_id": PCOA,
        "target_dc_id": META,
        "source_column": "sample",
        "enabled": True,
        "link_config": {"resolver": "direct", "target_field": "sample_id"},
    }


def _project():
    return {"project": {"_id": "p1", "links": [_link()]}}


def test_other_through_a_link_is_resolved_then_excluded(monkeypatch):
    monkeypatch.setattr(filter_links, "_walk_link_path", lambda **_kw: ("sample_id", ["S1", "S2"]))
    extra = filter_links.extend_filters_via_links(
        target_dc_id=META,
        filters_by_dc={PCOA: [_group(["s1", "s2"], exclude=True)]},
        project_metadata=_project(),
        access_token="t",
    )
    assert len(extra) == 1
    assert extra[0]["value"] == ["S1", "S2"]
    assert extra[0]["metadata"]["exclude"] is True


def test_other_through_a_link_that_matched_nothing_adds_no_filter(monkeypatch):
    monkeypatch.setattr(filter_links, "_walk_link_path", lambda **_kw: ("sample_id", []))
    extra = filter_links.extend_filters_via_links(
        target_dc_id=META,
        filters_by_dc={PCOA: [_group(["s1"], exclude=True)]},
        project_metadata=_project(),
        access_token="t",
    )
    assert extra == []
