"""``_text_filter_matches``: what a TextInput pattern catches, counted on the column's distinct values.

The helper reads a Delta scan; the scan and the lookup of its location are
replaced with an in-memory frame, so what is tested is the counting, the
ordering and the cap, not the storage.
"""

from __future__ import annotations

import polars as pl
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes

DC_ID = str(ObjectId())
GUIDES = ["CCAAT", "ccgga", "AACCA", "TTGGG", "CCAAT", None, "CCTTA"]


class _FakeDeltatables:
    def find_one(self, *_args, **_kwargs):
        return {"delta_table_location": "s3://bucket/dc"}


@pytest.fixture
def frame(monkeypatch):
    """Serve `GUIDES` (one repeated, one null) as the data collection's scan."""
    data = pl.LazyFrame({"guide": GUIDES, "n": range(len(GUIDES))})
    monkeypatch.setattr("depictio.api.v1.db.deltatables_collection", _FakeDeltatables())
    monkeypatch.setattr(
        "depictio.api.v1.deltatables_utils.open_deltatable_scan", lambda **_kw: data
    )
    return data


def _matches(**overrides):
    args = {
        "dc_id": DC_ID,
        "dc_info": {"dc_type": "table", "workflow_id": str(ObjectId())},
        "column": "guide",
        "value": "^CC",
        "case_sensitive": False,
        "match_mode": "regex",
        "filter_expr": None,
        "limit": 100,
        "delta_version": None,
    }
    args.update(overrides)
    return routes._text_filter_matches(**args)


class TestCounts:
    def test_counts_distinct_values_not_rows(self, frame):
        out = _matches()
        # CCAAT appears twice, the null is not a value.
        assert out["total"] == 5
        assert out["values"] == ["CCAAT", "CCTTA", "ccgga"]
        assert out["matching"] == 3
        assert out["truncated"] is False
        assert out["invalid"] is False

    def test_case_sensitive_drops_the_lowercase_value(self, frame):
        assert _matches(case_sensitive=True)["values"] == ["CCAAT", "CCTTA"]

    def test_contains_reads_the_pattern_literally(self, frame):
        assert _matches(value="^CC", match_mode="contains")["matching"] == 0
        assert _matches(value="CCA", match_mode="contains")["values"] == ["AACCA", "CCAAT"]

    def test_nothing_caught(self, frame):
        out = _matches(value="^ACG")
        assert (out["matching"], out["values"], out["total"]) == (0, [], 5)

    def test_empty_pattern_keeps_everything(self, frame):
        assert _matches(value="")["matching"] == 5

    def test_invalid_pattern_is_flagged_and_filters_nothing(self, frame):
        out = _matches(value="(")
        assert out["invalid"] is True
        assert out["matching"] == out["total"]

    def test_limit_caps_the_list_not_the_count(self, frame):
        out = _matches(value="C", limit=2)
        assert len(out["values"]) == 2
        assert out["matching"] > 2
        assert out["truncated"] is True

    def test_filter_expr_narrows_the_universe(self, frame):
        out = _matches(value=".", filter_expr="col('n') < 2")
        assert out["total"] == 2


class TestErrors:
    def test_unknown_column_is_a_404(self, frame):
        with pytest.raises(HTTPException) as err:
            _matches(column="nope")
        assert err.value.status_code == 404

    def test_time_travel_on_a_collection_without_a_log_is_a_400(self, frame):
        with pytest.raises(HTTPException) as err:
            _matches(dc_info={"dc_type": "geojson", "workflow_id": "w"}, delta_version=1)
        assert err.value.status_code == 400
