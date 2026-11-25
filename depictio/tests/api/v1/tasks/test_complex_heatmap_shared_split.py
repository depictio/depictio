"""A complex heatmap dealt into split panels reads as one figure cut in pieces.

A sample group never narrows the ROWS of a feature-by-sample matrix, only its
columns, so the panels would each cluster their rows on their own few samples
and be drawn on their own colour range: the same feature in a different place,
the same value in a different colour. A panel therefore carries
``shared_from_filters`` (the filters without its own constraints) and takes its
row order and colour range from the matrix of every sample in view.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import polars as pl
import pytest

import depictio.api.v1.celery_tasks as tasks
from depictio.api.v1.celery_tasks import (
    _apply_shared_heatmap_reference,
    _build_shared_heatmap_reference,
    _narrow_wide_matrix_columns,
)

SAMPLES = ["a1", "a2", "a3", "b1", "b2", "b3"]


def _matrix() -> pl.DataFrame:
    rng = np.random.default_rng(7)
    data: dict[str, Any] = {"gene": [f"g{i:02d}" for i in range(12)]}
    for j, s in enumerate(SAMPLES):
        # Group B has a wider range than group A, so a panel drawn on its own
        # range would differ from the view's.
        scale = 1.0 if s.startswith("a") else 25.0
        data[s] = (rng.random(12) * scale + j).tolist()
    return pl.DataFrame(data)


def _panel_constraint(values: list[str], *, exclude: bool = False) -> dict:
    meta: dict[str, Any] = {"column_name": "ID", "interactive_component_type": "MultiSelect"}
    if exclude:
        meta["exclude"] = True
    return {
        "index": "__depictio_group__:panel:g",
        "value": values,
        "column_name": "ID",
        "interactive_component_type": "MultiSelect",
        "source": "group_filter",
        "metadata": meta,
    }


class TestNarrowing:
    def test_a_filter_flagged_exclude_keeps_the_other_columns(self) -> None:
        out = _narrow_wide_matrix_columns(SAMPLES, [_panel_constraint(["a1", "b2"], exclude=True)])
        assert out == ["a2", "a3", "b1", "b3"]

    def test_the_flag_may_sit_on_the_filter_itself(self) -> None:
        flt = {**_panel_constraint(["a1"]), "exclude": True}
        flt["metadata"] = {"column_name": "ID"}
        assert _narrow_wide_matrix_columns(SAMPLES, [flt]) == SAMPLES[1:]

    def test_an_exclusion_naming_nothing_here_is_unrelated(self) -> None:
        assert (
            _narrow_wide_matrix_columns(SAMPLES, [_panel_constraint(["zz"], exclude=True)]) is None
        )

    def test_a_sample_pick_and_a_panel_group_compose(self) -> None:
        pick = {"column_name": "ID", "value": ["a1", "a2", "b1"]}
        group = _panel_constraint(["a1", "a2", "a3"])
        assert _narrow_wide_matrix_columns(SAMPLES, [pick, group]) == ["a1", "a2"]

    def test_an_excluded_group_inside_a_pick(self) -> None:
        pick = {"column_name": "ID", "value": ["a1", "a2", "b1"]}
        other = _panel_constraint(["a1", "a2"], exclude=True)
        assert _narrow_wide_matrix_columns(SAMPLES, [pick, other]) == ["b1"]

    def test_a_group_with_no_sample_in_view_leaves_no_column(self) -> None:
        pick = {"column_name": "ID", "value": ["a1", "a2"]}
        group = _panel_constraint(["b1", "b2"])
        assert _narrow_wide_matrix_columns(SAMPLES, [pick, group]) == []


def _drawn(df: pl.DataFrame, columns: list[str], ref: dict | None, normalize: str):
    """The heatmap a panel draws, as the task builds it."""
    from plotly_complexheatmap import ComplexHeatmap

    pdf = df.select(["gene"] + columns).to_pandas()
    lib_normalize = {"none": "none", "row_z": "row"}[normalize]
    cluster_rows = True
    if ref is not None:
        pdf, lib_normalize = _apply_shared_heatmap_reference(
            pdf, "gene", columns, ref, lib_normalize
        )
        cluster_rows = False
    fig = ComplexHeatmap.from_dataframe(
        pdf,
        index_column="gene",
        value_columns=columns,
        cluster_rows=cluster_rows,
        cluster_cols=True,
        normalize=lib_normalize,
    ).to_plotly()
    if ref is not None:
        tasks._pin_heatmap_colour_range(fig, ref["zmin"], ref["zmax"])
    main = next(t for t in fig.data if str(getattr(t, "hovertemplate", "")).startswith("row: "))
    return fig, main


@pytest.mark.parametrize("normalize", ["none", "row_z"])
def test_panels_with_other_samples_share_row_order_and_range(normalize: str) -> None:
    df = _matrix()
    ref = _build_shared_heatmap_reference(
        df,
        index_column="gene",
        value_columns=SAMPLES,
        cluster_rows=True,
        cluster_method="ward",
        cluster_metric="euclidean",
        normalize=normalize,
    )
    assert ref is not None

    _, left = _drawn(df, ["a1", "a2", "a3"], ref, normalize)
    _, right = _drawn(df, ["b1", "b2", "b3"], ref, normalize)

    def rows(trace: Any) -> list[str]:
        return [str(r[0][0]) for r in trace.customdata]

    assert rows(left) == rows(right) == ref["order"]
    assert (left.zmin, left.zmax) == (right.zmin, right.zmax) == (ref["zmin"], ref["zmax"])
    # The columns are the panel's own.
    assert len(left.x) == len(right.x) == 3

    # Unshared, the two panels would have been drawn differently.
    _, alone_left = _drawn(df, ["a1", "a2", "a3"], None, normalize)
    _, alone_right = _drawn(df, ["b1", "b2", "b3"], None, normalize)
    assert rows(alone_left) != rows(alone_right) or alone_left.zmin is None


def test_the_range_is_the_whole_views_not_the_panels() -> None:
    df = _matrix()
    ref = _build_shared_heatmap_reference(
        df,
        index_column="gene",
        value_columns=SAMPLES,
        cluster_rows=True,
        cluster_method="ward",
        cluster_metric="euclidean",
        normalize="none",
    )
    assert ref is not None
    assert ref["zmin"] == pytest.approx(float(df.select(SAMPLES).to_numpy().min()))
    assert ref["zmax"] == pytest.approx(float(df.select(SAMPLES).to_numpy().max()))


def test_the_row_z_score_is_taken_over_every_sample_in_view() -> None:
    df = _matrix()
    ref = _build_shared_heatmap_reference(
        df,
        index_column="gene",
        value_columns=SAMPLES,
        cluster_rows=False,
        cluster_method="ward",
        cluster_metric="euclidean",
        normalize="row_z",
    )
    assert ref is not None
    pdf = df.select(["gene", "a1", "a2"]).to_pandas()
    out, lib = _apply_shared_heatmap_reference(pdf, "gene", ["a1", "a2"], ref, "row")
    assert lib == "none"
    full = df.select(SAMPLES).to_numpy()
    expected = (full - full.mean(axis=1, keepdims=True)) / full.std(axis=1, keepdims=True)
    np.testing.assert_allclose(out[["a1", "a2"]].to_numpy(), expected[:, :2])


class _Collection:
    def find_one(self, *_a: Any, **_k: Any) -> dict:
        return {"delta_table_location": "s3://bucket/dc"}


def _run_task(
    monkeypatch: pytest.MonkeyPatch, df: pl.DataFrame, payload: dict
) -> tuple[dict, list]:
    import depictio.api.v1.db as db
    import depictio.api.v1.deltatables_utils as dtu

    calls: list[Any] = []

    def fake_load(**kwargs: Any) -> pl.DataFrame:
        calls.append(kwargs.get("metadata"))
        return df

    monkeypatch.setattr(db, "deltatables_collection", _Collection(), raising=False)
    monkeypatch.setattr(dtu, "load_deltatable_lite", fake_load)
    return tasks.compute_complex_heatmap(payload), calls


def _payload(shared: list, panel: list, normalize: str = "none") -> dict:
    return {
        "wf_id": "6a1d0c3b0000000000000001",
        "dc_id": "6a1d0c3b0000000000000002",
        "index_column": "gene",
        "value_columns": None,
        "cluster_rows": True,
        "cluster_cols": True,
        "normalize": normalize,
        "filter_metadata": panel,
        "shared_from_filters": shared,
    }


@pytest.mark.parametrize("normalize", ["none", "row_z"])
def test_two_panel_computes_agree_on_rows_and_range(
    monkeypatch: pytest.MonkeyPatch, normalize: str
) -> None:
    tasks._SHARED_HEATMAP_CACHE.clear()
    df = _matrix()
    out_a, calls_a = _run_task(
        monkeypatch, df, _payload([], [_panel_constraint(["a1", "a2", "a3"])], normalize)
    )
    out_b, calls_b = _run_task(
        monkeypatch, df, _payload([], [_panel_constraint(["b1", "b2", "b3"])], normalize)
    )

    assert out_a["columns"] == ["a1", "a2", "a3"]
    assert out_b["columns"] == ["b1", "b2", "b3"]

    def main_trace(out: dict) -> dict:
        return next(
            t for t in out["figure"]["data"] if str(t.get("hovertemplate", "")).startswith("row: ")
        )

    ta, tb = main_trace(out_a), main_trace(out_b)
    rows_a = [r[0][0] for r in ta["customdata"]]
    rows_b = [r[0][0] for r in tb["customdata"]]
    assert rows_a == rows_b
    assert (ta["zmin"], ta["zmax"]) == (tb["zmin"], tb["zmax"])
    # One shared load for the two panels: (panel + shared) then (panel only).
    assert len(calls_a) == 2
    assert len(calls_b) == 1


def test_a_panel_without_a_sample_in_view_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    tasks._SHARED_HEATMAP_CACHE.clear()
    pick = {"column_name": "ID", "value": ["a1", "a2"]}
    out, _ = _run_task(
        monkeypatch,
        _matrix(),
        _payload([pick], [pick, _panel_constraint(["b1", "b2"])]),
    )
    assert out["columns"] == []
    assert out["col_count"] == 0
    # The result is a Celery result: it travels as JSON, figure included.
    json.dumps(out)
    assert isinstance(out["figure"], dict)
