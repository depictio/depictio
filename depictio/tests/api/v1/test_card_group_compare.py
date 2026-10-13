"""Per-group card comparison ("compare groups in cards", issue #89).

Pins ``compute_group_compare`` in ``depictio/api/v1/services/card_groups.py``:
the card's hero aggregation reduced once per selection group, with an ``Other``
bucket for unassigned rows. The aggregation expression / result coercion are
the card endpoint's own ``_agg_expr`` / ``_coerce_agg_result`` so the per-group
numbers reduce exactly like the hero value they sit under.
"""

import polars as pl

from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    _agg_expr,
    _coerce_agg_result,
)
from depictio.api.v1.services.card_groups import compute_group_compare
from depictio.api.v1.services.figure.groups import sanitize_group_defs


def _df():
    return pl.DataFrame(
        {
            "sample": ["s1", "s2", "s3", "s4", "s5", "s6"],
            "depth": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
        }
    )


def _groups():
    return sanitize_group_defs(
        [
            {"name": "A", "column_name": "sample", "values": ["s1", "s2"], "color": "#1f77b4"},
            {"name": "B", "column_name": "sample", "values": ["s3", "s4"], "color": "#ff7f0e"},
        ]
    )


class TestComputeGroupCompare:
    def test_mean_per_group_with_other_bucket(self):
        out = compute_group_compare(
            _df(), _groups(), "depth", "mean", _agg_expr, _coerce_agg_result
        )
        assert out is not None
        assert out["aggregation"] == "mean"
        assert [g["name"] for g in out["groups"]] == ["A", "B"]
        by_name = {g["name"]: g for g in out["groups"]}
        assert by_name["A"] == {"name": "A", "color": "#1f77b4", "value": 15.0, "count": 2}
        assert by_name["B"] == {"name": "B", "color": "#ff7f0e", "value": 35.0, "count": 2}
        assert out["other"] == {"value": 55.0, "count": 2}

    def test_count_is_int_coerced(self):
        out = compute_group_compare(
            _df(), _groups(), "depth", "count", _agg_expr, _coerce_agg_result
        )
        assert out is not None
        assert all(isinstance(g["value"], int) for g in out["groups"])

    def test_no_other_bucket_when_groups_cover_everything(self):
        groups = sanitize_group_defs(
            [
                {"name": "All", "column_name": "sample", "values": [f"s{i}" for i in range(1, 7)]},
            ]
        )
        out = compute_group_compare(_df(), groups, "depth", "mean", _agg_expr, _coerce_agg_result)
        assert out is not None
        assert out["other"] is None

    def test_empty_group_still_gets_a_chip(self):
        groups = sanitize_group_defs(
            [
                {"name": "A", "column_name": "sample", "values": ["s1"]},
                {"name": "Ghost", "column_name": "sample", "values": ["zzz"]},
            ]
        )
        out = compute_group_compare(_df(), groups, "depth", "mean", _agg_expr, _coerce_agg_result)
        assert out is not None
        by_name = {g["name"]: g for g in out["groups"]}
        assert by_name["Ghost"] == {
            "name": "Ghost",
            "color": by_name["Ghost"]["color"],
            "value": None,
            "count": 0,
        }

    def test_inapplicable_group_omitted_not_zeroed(self):
        # A group made on another DC's column can't be told apart from Other on
        # this frame: it must be omitted entirely, not shown as "0 rows".
        groups = sanitize_group_defs(
            [
                {"name": "A", "column_name": "sample", "values": ["s1", "s2"]},
                {"name": "Foreign", "column_name": "other_dc_col", "values": ["x"]},
            ]
        )
        out = compute_group_compare(_df(), groups, "depth", "mean", _agg_expr, _coerce_agg_result)
        assert out is not None
        assert [g["name"] for g in out["groups"]] == ["A"]

    def test_none_when_group_column_missing(self):
        groups = sanitize_group_defs([{"name": "A", "column_name": "not_here", "values": ["v"]}])
        assert (
            compute_group_compare(_df(), groups, "depth", "mean", _agg_expr, _coerce_agg_result)
            is None
        )

    def test_none_when_value_column_missing(self):
        assert (
            compute_group_compare(
                _df(), _groups(), "not_here", "mean", _agg_expr, _coerce_agg_result
            )
            is None
        )

    def test_none_for_expressionless_aggregation(self):
        # ``box_plot_stats`` has no expression form; the comparison must decline
        # rather than approximate.
        assert (
            compute_group_compare(
                _df(), _groups(), "depth", "box_plot_stats", _agg_expr, _coerce_agg_result
            )
            is None
        )

    def test_input_frame_not_mutated(self):
        df = _df()
        compute_group_compare(df, _groups(), "depth", "mean", _agg_expr, _coerce_agg_result)
        assert df.columns == ["sample", "depth"]

    def test_payload_fn_runs_per_partition(self):
        out = compute_group_compare(
            _df(),
            _groups(),
            "depth",
            "mean",
            _agg_expr,
            _coerce_agg_result,
            payload_fn=lambda part: {"n": part.height},
        )
        assert out is not None
        by_name = {g["name"]: g for g in out["groups"]}
        assert by_name["A"]["payload"] == {"n": 2}
        assert by_name["B"]["payload"] == {"n": 2}
        assert out["other"] is not None and out["other"]["payload"] == {"n": 2}

    def test_no_payload_key_without_payload_fn(self):
        out = compute_group_compare(
            _df(), _groups(), "depth", "mean", _agg_expr, _coerce_agg_result
        )
        assert out is not None
        assert all("payload" not in g for g in out["groups"])

    def test_empty_group_payload_is_none(self):
        groups = sanitize_group_defs(
            [
                {"name": "A", "column_name": "sample", "values": ["s1"]},
                {"name": "Ghost", "column_name": "sample", "values": ["zzz"]},
            ]
        )
        out = compute_group_compare(
            _df(),
            groups,
            "depth",
            "mean",
            _agg_expr,
            _coerce_agg_result,
            payload_fn=lambda part: {"n": part.height},
        )
        assert out is not None
        by_name = {g["name"]: g for g in out["groups"]}
        assert by_name["Ghost"]["payload"] is None
        assert by_name["Ghost"]["count"] == 0

    def test_include_overall_adds_whole_frame_entry(self):
        out = compute_group_compare(
            _df(),
            _groups(),
            "depth",
            "mean",
            _agg_expr,
            _coerce_agg_result,
            payload_fn=lambda part: {"n": part.height},
            include_overall=True,
        )
        assert out is not None
        assert out["overall"] == {"value": 35.0, "count": 6, "payload": {"n": 6}}

    def test_overall_absent_by_default(self):
        out = compute_group_compare(
            _df(), _groups(), "depth", "mean", _agg_expr, _coerce_agg_result
        )
        assert out is not None
        assert "overall" not in out

    def test_agg_value_fn_fallback_for_expressionless_aggregation(self):
        # ``mode`` has no expression form; the Series fallback must serve it
        # instead of refusing the whole comparison.
        def _value_fn(series, aggregation):
            assert aggregation == "mode"
            return float(series.mode()[0])

        out = compute_group_compare(
            _df(), _groups(), "depth", "mode", _agg_expr, _coerce_agg_result, agg_value_fn=_value_fn
        )
        assert out is not None
        assert all(isinstance(g["value"], float) for g in out["groups"])


class TestSharedScaleHelpers:
    def test_histogram_with_domain_pins_the_bin_grid(self):
        import polars as pl

        from depictio.api.v1.services.card_metrics import compute_histogram

        # Two partitions of one dataset, binned on the SAME domain: their bins
        # must land on the same breakpoints even though their extents differ.
        low = pl.DataFrame({"v": [0.0, 1.0, 2.0]})
        high = pl.DataFrame({"v": [8.0, 9.0, 10.0]})
        a = compute_histogram(low, "v", bins=10, domain=(0.0, 10.0))
        b = compute_histogram(high, "v", bins=10, domain=(0.0, 10.0))
        assert a is not None and b is not None
        assert a["breakpoints"] == b["breakpoints"]
        assert sum(a["bins"]) == 3 and sum(b["bins"]) == 3
        # Low values fill the leading bins, high values the trailing ones.
        assert a["bins"][0] > 0 and a["bins"][-1] == 0
        assert b["bins"][-1] > 0 and b["bins"][0] == 0

    def test_histogram_domain_allows_single_value_partition(self):
        import polars as pl

        from depictio.api.v1.services.card_metrics import compute_histogram

        one = compute_histogram(pl.DataFrame({"v": [5.0]}), "v", bins=10, domain=(0.0, 10.0))
        assert one is not None
        assert sum(one["bins"]) == 1

    def test_trend_grid_and_series_alignment(self):
        import polars as pl

        from depictio.api.v1.services.card_metrics import (
            compute_trend_on_grid,
            trend_axis_grid,
        )

        df = pl.DataFrame(
            {
                "year": [2007, 2007, 2008, 2008, 2009, 2009],
                "mass": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
                "sample": ["a", "b", "a", "b", "a", "b"],
            }
        )
        grid = trend_axis_grid(df, "year")
        assert grid is not None and grid["kind"] == "labels"
        # Partition "a" has rows for every year; partition "b" misses none —
        # drop 2008 from one partition to check the null-aligned slot.
        part = df.filter((pl.col("sample") == "a") & (pl.col("year") != 2008))
        series = compute_trend_on_grid(part, "mass", "year", "mean", grid)
        assert series is not None
        assert [p["value"] for p in series["points"]] == [10.0, None, 50.0]

    def test_trend_grid_none_when_axis_constant(self):
        import polars as pl

        from depictio.api.v1.services.card_metrics import trend_axis_grid

        assert trend_axis_grid(pl.DataFrame({"year": [2007, 2007]}), "year") is None


class TestComputeBoxPlotStats:
    def test_basic_stats(self):
        import polars as pl

        from depictio.api.v1.services.card_metrics import compute_box_plot_stats

        out = compute_box_plot_stats(pl.Series([1.0, 2.0, 3.0, 4.0, 5.0]))
        assert out is not None
        assert out["median"] == 3.0
        assert out["q1"] == 2.0
        assert out["q3"] == 4.0
        assert out["min"] == 1.0 and out["max"] == 5.0
        assert out["outlier_count"] == 0

    def test_empty_and_non_numeric_yield_none(self):
        import polars as pl

        from depictio.api.v1.services.card_metrics import compute_box_plot_stats

        assert compute_box_plot_stats(pl.Series([], dtype=pl.Float64)) is None
        assert compute_box_plot_stats(pl.Series(["a", "b"])) is None

    def test_outlier_cap(self):
        import polars as pl

        from depictio.api.v1.services.card_metrics import compute_box_plot_stats

        values = [float(i) for i in range(100)] + [10_000.0] * 8
        out = compute_box_plot_stats(pl.Series(values), max_outliers=5)
        assert out is not None
        assert out["outlier_count"] == 8
        assert len(out["outliers"]) == 5
