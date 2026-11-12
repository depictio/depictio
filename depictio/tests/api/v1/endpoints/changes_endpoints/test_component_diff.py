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


def test_a_first_visit_has_nothing_to_compare(ctx):  # noqa: F811
    out = ctx["client"].post(f"{API}/component_diff/{ctx['family']}/fig-1", json={}).json()
    assert out["supported"] is False
