"""Before/after of one component (#1397): points, groups, samples and rows.

The frames mirror the iris_versioned fixture's trap: batches 2 and 3 have the
same row count and differ only in values, so a diff that compares counts, or
silently reads the live data twice, finds nothing.
"""

from __future__ import annotations

import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1.services.changes import advanced_diff, figure_diff
from depictio.tests.api.v1.endpoints.changes_endpoints.test_changes_since import (  # noqa: F401
    API,
    EDITOR,
    READER,
    ctx,
)

BEFORE = pl.DataFrame(
    {
        "id": ["a", "b", "c"],
        "sepal_length": [5.1, 4.9, 4.7],
        "petal_length": [1.4, 1.4, 1.3],
        "variety": ["Setosa", "Setosa", "Versicolor"],
    }
)
# Same row count; "b" moved, "c" left, "d" arrived.
AFTER = pl.DataFrame(
    {
        "id": ["a", "b", "d"],
        "sepal_length": [5.1, 5.6, 6.3],
        "petal_length": [1.4, 1.4, 4.9],
        "variety": ["Setosa", "Setosa", "Virginica"],
    }
)


def _figure(visu_type: str, **kwargs) -> dict:
    return {"component_type": "figure", "visu_type": visu_type, "dict_kwargs": kwargs}


# ── points ──────────────────────────────────────────────────────────────────


def test_points_are_matched_by_their_key():
    out = figure_diff.frame_diff(
        BEFORE, AFTER, _figure("scatter", x="sepal_length", y="petal_length")
    )
    assert out["shape"] == "points" and out["key_column"] == "id"
    assert [p["key"] for p in out["added"]] == ["d"]
    assert [p["key"] for p in out["removed"]] == ["c"]
    [moved] = out["changed"]
    assert moved["key"] == "b"
    assert (moved["before"]["x"], moved["after"]["x"]) == (4.9, 5.6)
    assert out["counts"]["before"] == out["counts"]["after"] == 3


def test_points_without_a_key_compare_value_pairs():
    no_id = figure_diff.frame_diff(
        BEFORE.drop("id"), AFTER.drop("id"), _figure("scatter", x="sepal_length", y="petal_length")
    )
    assert no_id["key_column"] is None
    assert sorted(p["x"] for p in no_id["added"]) == [5.6, 6.3]
    assert sorted(p["x"] for p in no_id["removed"]) == [4.7, 4.9]


def test_an_axis_is_never_the_key():
    df = pl.DataFrame({"sample_id": ["s1", "s2"], "reads": [1, 2]})
    out = figure_diff.frame_diff(df, df, _figure("scatter", x="sample_id", y="reads"))
    assert out["key_column"] is None


# ── groups ──────────────────────────────────────────────────────────────────


def test_bars_compare_the_sum_per_group():
    out = figure_diff.frame_diff(BEFORE, AFTER, _figure("bar", x="variety", y="sepal_length"))
    assert out["shape"] == "groups" and out["metric"] == "sum"
    by = {g["group"]["variety"]: g for g in out["groups"]}
    assert by["Setosa"]["status"] == "changed"
    assert by["Setosa"]["before"] == pytest.approx(10.0)
    assert by["Setosa"]["after"] == pytest.approx(10.7)
    assert by["Versicolor"]["status"] == "removed"
    assert by["Virginica"]["status"] == "added"


def test_histograms_count_rows():
    out = figure_diff.frame_diff(BEFORE, AFTER, _figure("histogram", x="variety"))
    assert out["metric"] == "count"
    assert {g["group"]["variety"]: g["status"] for g in out["groups"]} == {
        "Versicolor": "removed",
        "Virginica": "added",
    }


def test_box_plots_compare_medians():
    out = figure_diff.frame_diff(BEFORE, AFTER, _figure("box", x="variety", y="sepal_length"))
    setosa = next(g for g in out["groups"] if g["group"]["variety"] == "Setosa")
    assert (setosa["before"], setosa["after"]) == (pytest.approx(5.0), pytest.approx(5.35))


def test_x_and_colour_on_the_same_column_group_once():
    out = figure_diff.frame_diff(
        BEFORE, AFTER, _figure("box", x="variety", y="sepal_length", color="variety")
    )
    assert out["supported"] is True
    assert {g["group"]["variety"] for g in out["groups"]} == {"Setosa", "Versicolor", "Virginica"}


def test_code_mode_is_not_compared():
    component = {**_figure("scatter", x="sepal_length", y="petal_length"), "mode": "code"}
    assert figure_diff.frame_diff(BEFORE, AFTER, component)["supported"] is False


# ── samples and rows ────────────────────────────────────────────────────────


def test_samples_added_and_removed():
    out = figure_diff.sample_diff({"SRR1", "SRR2"}, {"SRR1", "SRR2", "SRR3"})
    assert out["added"] == ["SRR3"] and out["removed"] == []


def test_advanced_rows_are_matched_on_the_id_role():
    config = {"viz_kind": "volcano", "feature_id_col": "id", "effect_size_col": "sepal_length"}
    role, key = advanced_diff.key_role(config)
    assert (role, key) == ("feature_id_col", "id")
    out = advanced_diff.rows_diff(BEFORE, AFTER, key, ["id", "sepal_length"])
    assert [r["key"] for r in out["added"]] == ["d"]
    assert [r["key"] for r in out["changed"]] == ["b"]


def test_advanced_rows_without_a_unique_key_are_a_multiset_difference():
    # A long table repeats its id (one row per sample and taxon), so rows are
    # compared as value tuples: a duplicate counts once per occurrence, added
    # rows keep the new table's order and removed rows the old one's.
    before = pl.DataFrame({"sample_id": ["s1", "s1", "s2", "s3"], "v": [1, 1, 2, 3]})
    after = pl.DataFrame(
        {"sample_id": ["s4", "s1", "s2", "s1", "s1", "s5"], "v": [4, 1, 2, 1, 1, 5]}
    )
    out = advanced_diff.rows_diff(before, after, "sample_id", ["sample_id", "v"])
    assert out["key_column"] is None
    assert [r["values"] for r in out["added"]] == [
        {"sample_id": "s4", "v": "4"},
        {"sample_id": "s1", "v": "1"},
        {"sample_id": "s5", "v": "5"},
    ]
    assert [r["values"] for r in out["removed"]] == [{"sample_id": "s3", "v": "3"}]
    assert out["counts"]["added"] == 3 and out["counts"]["removed"] == 1


def _reference_rows_diff(before, after, values):
    """The keyless diff as plain Python: value tuples as text, matched by count."""
    from collections import Counter

    def rows(df):
        keep = [c for c in values if c in df.columns]
        return [tuple(str(r.get(c)) for c in values) for r in df.select(keep).to_dicts()]

    then, now = rows(before), rows(after)
    unmatched, added = Counter(then), []
    for t in now:
        if unmatched[t] > 0:
            unmatched[t] -= 1
        else:
            added.append(dict(zip(values, t)))
    matched, removed = Counter(then) - unmatched, []
    for t in then:
        if matched[t] > 0:
            matched[t] -= 1
        else:
            removed.append(dict(zip(values, t)))
    return added, removed


@pytest.mark.parametrize("seed", range(6))
def test_the_keyless_diff_matches_a_plain_python_multiset_difference(seed):
    import random

    rng = random.Random(seed)
    pool_f = [0.1, 1e-05, float("nan"), None, -0.0, 0.0, 2.5]
    # No literal "None" text: plain Python matched it with a null (both print
    # "None"); polars keeps them apart, which is the right answer.
    pool_s = ["s1", "s2", None, "s3"]

    def side(n):
        return pl.DataFrame(
            {
                "sample_id": [rng.choice(pool_s) for _ in range(n)],
                "v": [rng.choice(pool_f) for _ in range(n)],
                "n": [rng.choice([1, 2, None]) for _ in range(n)],
            },
            schema={"sample_id": pl.String, "v": pl.Float64, "n": pl.Int64},
        )

    before, after = side(rng.randint(0, 60)), side(rng.randint(0, 60))
    if seed == 5:
        before = before.drop("n")  # a column the old version did not have
    values = ["n", "sample_id", "v"]
    out = advanced_diff.rows_diff(before, after, "sample_id", values)
    added, removed = _reference_rows_diff(before, after, values)
    assert [r["values"] for r in out["added"]] == added
    assert [r["values"] for r in out["removed"]] == removed
    assert out["counts"]["added"] == len(added) and out["counts"]["removed"] == len(removed)


def test_an_advanced_diff_reads_only_its_bound_columns(monkeypatch):
    # Each side is cached per Delta version: a full-width read kept every
    # column of a wide table twice in the process for a few compared ones.
    from depictio.api.v1 import deltatables_utils
    from depictio.models.models.reader_marks import DcSeenState

    asked: list[list[str] | None] = []

    def fake_load(wf_id, dc_id, metadata=None, select_columns=None, delta_version=None):
        asked.append(select_columns)
        return pl.DataFrame({"sample_id": ["s1"], "abundance": [1.0], "unused": [0]})

    monkeypatch.setattr(deltatables_utils, "load_deltatable_lite", fake_load)
    component = {
        "wf_id": str(ObjectId()),
        "config": {"sample_id_col": "sample_id", "value_col": "abundance"},
    }
    advanced_diff.advanced_viz_diff(
        component, str(ObjectId()), DcSeenState(delta_version=1), DcSeenState(delta_version=2), []
    )
    assert asked == [["abundance", "sample_id"], ["abundance", "sample_id"]]


def test_advanced_rows_without_a_key_scale_linearly():
    # The overlay view diffs every marked tile at once, on tables of hundreds
    # of thousands of rows. Matching with list membership was quadratic: about
    # an hour of CPU for one request on a 700k row taxonomy table, in a worker
    # thread nothing cancels once the reader moves on.
    import time

    n = 60_000
    before = pl.DataFrame({"sample_id": [f"s{i % 300}" for i in range(n)], "v": range(n)})
    after = pl.concat([before, before.with_columns(pl.col("v") + n)]).sample(
        fraction=1.0, shuffle=True, seed=1
    )
    started = time.perf_counter()
    out = advanced_diff.rows_diff(before, after, "sample_id", ["sample_id", "v"])
    assert out["counts"]["added"] == n and out["counts"]["removed"] == 0
    assert time.perf_counter() - started < 5


# ── the endpoint ────────────────────────────────────────────────────────────


def test_the_endpoint_diffs_the_baseline_commit_against_now(ctx, monkeypatch):  # noqa: F811
    from depictio.api.v1 import deltatables_utils
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes

    db = ctx["db"]
    db["dashboards"].update_one(
        {"dashboard_id": ObjectId(ctx["family"])},
        {
            "$set": {
                "stored_metadata.0.visu_type": "scatter",
                "stored_metadata.0.wf_id": str(ObjectId()),
                "stored_metadata.0.dict_kwargs": {"x": "sepal_length", "y": "petal_length"},
            }
        },
    )
    ctx["client"].put(f"{API}/dashboard/{ctx['family']}/visit")
    db["deltatables"].update_one(
        {"data_collection_id": ctx["dc_table"]},
        {"$push": {"aggregation": {"aggregation_version": 2, "delta_version": 1, "rows_total": 3}}},
    )

    reads: list[int | None] = []

    def fake_load(_wf, _dc, metadata=None, select_columns=None, delta_version=None, **_):
        reads.append(delta_version)
        return {0: BEFORE, 1: AFTER}[delta_version]

    monkeypatch.setattr(deltatables_utils, "load_deltatable_lite", fake_load)
    monkeypatch.setattr(dash_routes, "_resolve_link_filters_cached", lambda f, *a, **k: f)

    res = ctx["client"].post(f"{API}/component_diff/{ctx['family']}/fig-1", json={})
    assert res.status_code == 200, res.text
    out = res.json()
    assert reads == [0, 1]  # the pinned commit, then the live one; never live twice
    assert (out["delta_from"], out["delta_to"]) == (0, 1)
    assert [p["key"] for p in out["added"]] == ["d"]
    assert out["component_key"] == f"{ctx['family']}:fig-1"


def test_the_endpoint_lists_new_multiqc_samples(ctx):  # noqa: F811
    seen = sorted(
        str(r["_id"]) for r in ctx["db"]["multiqc"].find({"data_collection_id": ctx["dc_mqc"]})
    )
    ctx["client"].put(f"{API}/dashboard/{ctx['family']}/visit")
    ctx["db"]["multiqc"].insert_one(
        {
            "data_collection_id": ctx["dc_mqc"],
            "run_tag": "run_c",
            "metadata": {"samples": ["SRR3_1"]},
        }
    )
    out = ctx["client"].post(f"{API}/component_diff/{ctx['family']}/mqc-1", json={}).json()
    assert out["shape"] == "samples" and out["added"] == ["SRR3_1"]
    # The report set the reader saw, for the Before pane's `report_sets` pin:
    # read from their mark, not from a dashboard version, which may have been
    # saved before those reports existed.
    assert sorted(out["report_ids_before"]) == seen


def test_a_first_visit_has_nothing_to_compare(ctx):  # noqa: F811
    out = ctx["client"].post(f"{API}/component_diff/{ctx['family']}/fig-1", json={}).json()
    assert out["supported"] is False
