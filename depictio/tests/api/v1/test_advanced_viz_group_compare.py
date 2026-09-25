"""The statistics behind the ``group_compare`` kind, and its endpoint guard.

Two levels, because two different things can break. The pure function is
tested against a matrix whose answer is known by construction (markers planted
at a fixed fold change, everything else drawn from one distribution), which is
what makes "the volcano found the right genes" a statement a test can make.
The endpoint is tested only for the contract the worker cannot defend itself
against: a payload naming no column or no values would reach Celery, fail
there, and surface as a cached failure rather than a 400.
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import _group_selector
from depictio.api.v1.services.group_compare import (
    GroupCompareError,
    benjamini_hochberg,
    group_compare_from_frame,
    resolve_feature_columns,
    top_features_by_variance,
)

MARKERS_A = ("gene_01", "gene_02")
MARKERS_B = ("gene_03", "gene_04")


def _matrix(n_per_group: int = 60, n_genes: int = 24, seed: int = 11) -> pl.DataFrame:
    """A cell x gene matrix with two clusters and two markers each."""
    rng = np.random.default_rng(seed)
    n = n_per_group * 2
    cluster = np.array(["A"] * n_per_group + ["B"] * n_per_group)
    data: dict[str, object] = {
        "cell_id": [f"c{i:04d}" for i in range(n)],
        "cluster": cluster,
        # A numeric column that is metadata, not a feature: it must never be
        # tested, which is what `resolve_feature_columns`' exclusions are for.
        "n_umi": rng.integers(1000, 5000, n),
    }
    for j in range(1, n_genes + 1):
        values = rng.lognormal(1.0, 0.5, n)
        name = f"gene_{j:02d}"
        if name in MARKERS_A:
            values[:n_per_group] *= 8.0
        elif name in MARKERS_B:
            values[n_per_group:] *= 8.0
        data[name] = np.round(values, 3)
    return pl.DataFrame(data)


def _selector(label: str) -> dict[str, object]:
    return {"label": label, "column": "cluster", "values": [label]}


def test_finds_the_planted_markers_and_nothing_else():
    result = group_compare_from_frame(
        _matrix(),
        index_col="cell_id",
        group_a=_selector("A"),
        group_b=_selector("B"),
    )
    significant = {r["feature"] for r in result["rows"] if r["significant"]}
    assert significant == set(MARKERS_A) | set(MARKERS_B)
    # Direction is A relative to B, so A's markers are up and B's are down.
    by_feature = {r["feature"]: r for r in result["rows"]}
    assert all(by_feature[m]["direction"] == "up" for m in MARKERS_A)
    assert all(by_feature[m]["direction"] == "down" for m in MARKERS_B)
    assert result["group_a"] == {"label": "A", "n": 60}
    assert result["group_b"] == {"label": "B", "n": 60}


def test_rows_are_ranked_by_raw_p_value():
    rows = group_compare_from_frame(
        _matrix(), index_col="cell_id", group_a=_selector("A"), group_b=_selector("B")
    )["rows"]
    p_values = [r["p_value"] for r in rows]
    assert p_values == sorted(p_values)


def test_the_label_column_and_the_row_id_are_never_tested():
    df = _matrix()
    result = group_compare_from_frame(
        df, index_col="cell_id", group_a=_selector("A"), group_b=_selector("B")
    )
    tested = {r["feature"] for r in result["rows"]}
    assert "cluster" not in tested
    assert "cell_id" not in tested
    # `n_umi` is numeric and not excluded by anything the config names, so it
    # IS tested. That is the documented behaviour of an inferred matrix, and
    # the reason the kind's suggestion gate wants eight float columns.
    assert "n_umi" in tested


def test_the_rank_sum_test_is_invariant_under_log1p():
    """Documented in the config: `log_transform` moves the Welch test only."""
    df = _matrix()
    kwargs = dict(index_col="cell_id", group_a=_selector("A"), group_b=_selector("B"))
    plain = group_compare_from_frame(df, log_transform=False, **kwargs)  # type: ignore[arg-type]
    logged = group_compare_from_frame(df, log_transform=True, **kwargs)  # type: ignore[arg-type]
    assert [r["p_value"] for r in plain["rows"]] == [r["p_value"] for r in logged["rows"]]

    welch_plain = group_compare_from_frame(df, test="t_test", log_transform=False, **kwargs)  # type: ignore[arg-type]
    welch_logged = group_compare_from_frame(df, test="t_test", log_transform=True, **kwargs)  # type: ignore[arg-type]
    assert [r["p_value"] for r in welch_plain["rows"]] != [
        r["p_value"] for r in welch_logged["rows"]
    ]


def test_means_are_reported_on_the_frames_own_scale():
    df = _matrix()
    result = group_compare_from_frame(
        df, index_col="cell_id", group_a=_selector("A"), group_b=_selector("B")
    )
    row = next(r for r in result["rows"] if r["feature"] == "gene_01")
    expected = df.filter(pl.col("cluster") == "A")["gene_01"].mean()
    assert row["mean_a"] == pytest.approx(expected)


def test_a_constant_feature_is_scored_rather_than_dropped():
    df = _matrix().with_columns(pl.lit(4.0).alias("gene_flat"))
    result = group_compare_from_frame(
        df,
        index_col="cell_id",
        group_a=_selector("A"),
        group_b=_selector("B"),
        max_features=100,
    )
    flat = next(r for r in result["rows"] if r["feature"] == "gene_flat")
    assert flat["p_value"] == 1.0
    assert flat["log2fc"] == 0.0
    assert flat["significant"] is False


def test_max_features_keeps_the_most_variable_columns():
    result = group_compare_from_frame(
        _matrix(),
        index_col="cell_id",
        group_a=_selector("A"),
        group_b=_selector("B"),
        max_features=5,
    )
    assert result["tested_features"] == 5
    assert result["feature_count"] == 25  # 24 genes + n_umi
    # The four markers move by a factor of eight between the groups, so they
    # are among the most variable columns of the union and must survive a cap
    # that drops most of the matrix.
    assert set(MARKERS_A) | set(MARKERS_B) <= {r["feature"] for r in result["rows"]}


def test_an_observation_in_both_groups_is_dropped_from_both():
    """A sloppy lasso that caught ten cells of cluster A must not count twice.

    Left in both arms those ten rows sit on either side of the test, which
    shrinks every difference towards nothing without saying so.
    """
    df = _matrix()
    # Ten cells of cluster A (c0000-c0009) plus ten of cluster B.
    sloppy = {
        "label": "sloppy lasso",
        "column": "cell_id",
        "values": [f"c{i:04d}" for i in range(10)] + [f"c{i:04d}" for i in range(60, 70)],
    }
    result = group_compare_from_frame(
        df, index_col="cell_id", group_a=_selector("A"), group_b=sloppy
    )
    assert result["overlap_dropped"] == 10
    assert result["group_a"]["n"] == 50
    assert result["group_b"]["n"] == 10


@pytest.mark.parametrize(
    ("dtype", "value_a", "value_b", "captured_a", "captured_b"),
    [
        # Python's str(1) is "1"; Polars casts Float64 1.0 to "1.0".
        (pl.Float64, 1.0, 2.0, "1", "2"),
        # ... and the other way round for an Int64 column captured as "1.0".
        (pl.Int64, 1, 2, "1.0", "2.0"),
        # Python's str(True) is "True"; Polars casts Boolean True to "true".
        (pl.Boolean, True, False, "True", "False"),
    ],
)
def test_a_group_captured_on_a_numeric_or_boolean_column_still_matches(
    dtype, value_a, value_b, captured_a, captured_b
):
    """The values a group captured come back as strings; the column did not.

    Matching on ``cast(Utf8)`` alone silently selects zero rows on a Float64
    or Boolean column, which then surfaces as "needs at least 3 observations"
    for a group the reader can see has sixty.
    """
    df = _matrix().with_columns(
        pl.when(pl.col("cluster") == "A")
        .then(pl.lit(value_a))
        .otherwise(pl.lit(value_b))
        .cast(dtype)
        .alias("flag")
    )
    result = group_compare_from_frame(
        df,
        index_col="cell_id",
        group_a={"label": "A", "column": "flag", "values": [captured_a]},
        group_b={"label": "B", "column": "flag", "values": [captured_b]},
    )
    assert result["group_a"]["n"] == 60
    assert result["group_b"]["n"] == 60
    significant = {r["feature"] for r in result["rows"] if r["significant"]}
    assert significant == set(MARKERS_A) | set(MARKERS_B)
    # The grouping column is excluded from the features whatever its dtype.
    assert "flag" not in {r["feature"] for r in result["rows"]}


def test_min_observations_is_clamped_to_the_models_floor():
    """`GroupCompareConfig.min_observations` is ``ge=2``; the service enforces it too.

    The endpoint takes a plain dict, so a payload with ``min_observations: 0``
    reaches the worker unvalidated. Below two observations there is nothing to
    test, and the caller must get the refusal rather than a table of nulls.
    """
    df = _matrix()
    lone = {"label": "lone", "column": "cell_id", "values": ["c0000"]}
    with pytest.raises(GroupCompareError, match="at least 2 observations"):
        group_compare_from_frame(
            df, index_col="cell_id", group_a=lone, group_b=_selector("B"), min_observations=0
        )
    # A group of exactly two passes the clamped floor.
    pair = {"label": "pair", "column": "cell_id", "values": ["c0000", "c0001"]}
    result = group_compare_from_frame(
        df, index_col="cell_id", group_a=pair, group_b=_selector("B"), min_observations=0
    )
    assert result["group_a"]["n"] == 2


def test_a_group_too_small_to_test_is_refused_with_a_readable_message():
    df = _matrix()
    tiny = {"label": "tiny", "column": "cell_id", "values": ["c0000", "c0001"]}
    with pytest.raises(GroupCompareError, match="at least 3 observations"):
        group_compare_from_frame(df, index_col="cell_id", group_a=tiny, group_b=_selector("B"))


def test_unknown_columns_and_empty_selections_are_refused():
    df = _matrix()
    with pytest.raises(GroupCompareError, match="not in this data collection"):
        group_compare_from_frame(
            df,
            index_col="cell_id",
            group_a={"label": "x", "column": "nope", "values": ["A"]},
            group_b=_selector("B"),
        )
    with pytest.raises(GroupCompareError, match="captured no values"):
        group_compare_from_frame(
            df,
            index_col="cell_id",
            group_a={"label": "x", "column": "cluster", "values": []},
            group_b=_selector("B"),
        )
    with pytest.raises(GroupCompareError, match="index column"):
        group_compare_from_frame(
            df, index_col="missing", group_a=_selector("A"), group_b=_selector("B")
        )
    with pytest.raises(GroupCompareError, match="unknown test"):
        group_compare_from_frame(
            df,
            index_col="cell_id",
            group_a=_selector("A"),
            group_b=_selector("B"),
            test="anova",
        )


def test_every_reported_statistic_is_json_safe():
    """NaN and infinity are not JSON, and the result is cached as a Mongo doc."""
    result = group_compare_from_frame(
        _matrix(), index_col="cell_id", group_a=_selector("A"), group_b=_selector("B")
    )
    for row in result["rows"]:
        for key in ("mean_a", "mean_b", "log2fc", "p_value", "fdr"):
            value = row[key]
            assert value is None or math.isfinite(value)


def test_benjamini_hochberg_is_monotone_and_bounded():
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.9]
    adjusted = benjamini_hochberg(p)
    assert np.all(adjusted >= np.asarray(p) - 1e-12)
    assert np.all(adjusted <= 1.0)
    # Adjusting in the same order as the input p-values keeps the ranking.
    assert list(adjusted) == sorted(adjusted)
    # The classic worked example: the third and following share one value
    # because of the monotone step-up.
    assert adjusted[2] == pytest.approx(adjusted[4])


def test_benjamini_hochberg_reads_a_non_finite_p_as_one():
    assert list(benjamini_hochberg([float("nan")])) == [1.0]
    assert benjamini_hochberg([]).size == 0


def test_resolve_feature_columns_skips_strings_and_named_exclusions():
    df = _matrix(n_per_group=5, n_genes=3)
    features = resolve_feature_columns(df, "cell_id", ["cluster", "n_umi"])
    assert features == ["gene_01", "gene_02", "gene_03"]


def test_top_features_by_variance_returns_frame_order():
    df = pl.DataFrame({"a": [1.0, 1.0, 1.0], "b": [0.0, 5.0, 10.0], "c": [0.0, 1.0, 2.0]})
    assert top_features_by_variance(df, ["a", "b", "c"], 2) == ["b", "c"]
    assert top_features_by_variance(df, ["a", "b", "c"], 10) == ["a", "b", "c"]


def test_the_endpoint_refuses_a_selector_with_nothing_to_select():
    assert _group_selector({"label": "A", "column": "cluster", "values": ["x"]}, "a") == {
        "label": "A",
        "column": "cluster",
        "values": ["x"],
    }
    # Values arrive as strings whatever the frame's dtype is, because they
    # travelled through JSON and localStorage on the way here.
    assert _group_selector({"column": "cluster", "values": [1, 2]}, "b")["values"] == ["1", "2"]
    for bad in (None, {}, {"column": "cluster"}, {"values": ["x"]}):
        with pytest.raises(HTTPException) as excinfo:
            _group_selector(bad, "a")
        assert excinfo.value.status_code == 400
