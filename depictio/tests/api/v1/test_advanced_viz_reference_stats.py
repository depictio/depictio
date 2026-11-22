"""References computed from the data on show (median, mean, p75..p99).

RULES.md §17 lets a data-defined reference onto a plot when it is called that.
The statistic must be the table's, not the sample's: the `/advanced_viz/data`
route computes it on the filtered rows *before* any reduction and returns it
in `reference_stats`; a Manhattan / genome view whose threshold is a statistic
has its tail cut at the same value. These tests pin both, plus the shared
helper, the export builder, the UI-figure lines and the catalog preview.
"""

from __future__ import annotations

import math
from typing import Any

import plotly.graph_objects as go
import polars as pl
import pytest

from depictio.api.v1.endpoints.advanced_viz_endpoints import routes
from depictio.api.v1.services.advanced_viz.reference_stats import (
    compute_requests,
    compute_stat,
    config_reference_requests,
    parse_requests,
    reference_label,
)

# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


def test_median_of_known_data() -> None:
    assert compute_stat(pl.Series([5.0, 1.0, 3.0, 2.0, 4.0]), "median") == 3.0
    assert compute_stat(pl.Series([1.0, 2.0, 3.0, 4.0]), "median") == 2.5


def test_nulls_and_non_finite_values_are_ignored() -> None:
    values = [1.0, None, 3.0, float("nan"), float("inf"), 2.0]
    assert compute_stat(values, "median") == 2.0
    assert compute_stat(values, "mean") == 2.0


def test_quantiles_interpolate_linearly() -> None:
    values = pl.Series([float(i) for i in range(101)])  # 0..100
    assert compute_stat(values, "p75") == pytest.approx(75.0)
    assert compute_stat(values, "p95") == pytest.approx(95.0)
    # Between two values: (n - 1) * q = 0.9 * 1 → 0.9 of the way from 10 to 20.
    assert compute_stat([10.0, 20.0], "p90") == pytest.approx(19.0)


def test_no_finite_value_is_none() -> None:
    assert compute_stat([None, float("nan")], "median") is None
    assert compute_stat([], "p95") is None


def test_unknown_stat_is_refused() -> None:
    with pytest.raises(ValueError):
        compute_stat([1.0], "p50")


def test_labels_name_the_statistic() -> None:
    assert reference_label("median") == "median of this table"
    assert reference_label("p95") == "95th percentile of this table"


def test_malformed_requests_are_dropped_not_raised() -> None:
    raw = {
        "reference_value": {"column": "y", "stat": "median"},
        "bad_stat": {"column": "y", "stat": "p50"},
        "no_column": {"stat": "mean"},
        "not_a_dict": "median",
    }
    assert parse_requests(raw) == {"reference_value": ("y", "median")}
    assert parse_requests(None) == {}


def test_a_column_the_frame_lacks_answers_none() -> None:
    frame = pl.DataFrame({"y": [1.0, 2.0, 3.0]})
    out = compute_requests(frame, {"a": ("y", "median"), "b": ("missing", "mean")})
    assert out == {"a": 2.0, "b": None}


@pytest.mark.parametrize(
    ("kind", "config", "expected"),
    [
        (
            "scatter_xy",
            {
                "x_col": "x",
                "y_col": "y",
                "reference_line": "horizontal",
                "reference_stat": "median",
            },
            {"reference_value": ("y", "median")},
        ),
        (
            "scatter_xy",
            {"x_col": "x", "y_col": "y", "reference_line": "vertical", "reference_stat": "p90"},
            {"reference_value": ("x", "p90")},
        ),
        # An explicit value wins: nothing is asked for.
        (
            "scatter_xy",
            {
                "x_col": "x",
                "y_col": "y",
                "reference_line": "horizontal",
                "reference_stat": "median",
                "reference_value": 1.0,
            },
            {},
        ),
        ("profile", {"y_col": "v", "reference_y_stat": "mean"}, {"reference_y": ("v", "mean")}),
        (
            "manhattan",
            {"score_col": "s", "score_threshold_stat": "p95"},
            {"score_threshold": ("s", "p95")},
        ),
        (
            "genome_view",
            {"score_col": "s", "score_threshold_stat": "p99", "score_threshold": 4.0},
            {},
        ),
        ("volcano", {"score_threshold_stat": "p95"}, {}),
    ],
)
def test_config_requests(kind: str, config: dict, expected: dict) -> None:
    assert config_reference_requests(kind, config) == expected


# ---------------------------------------------------------------------------
# The models
# ---------------------------------------------------------------------------


def test_stat_fields_take_the_shared_vocabulary() -> None:
    from pydantic import ValidationError

    from depictio.models.components.advanced_viz.configs import (
        GenomeViewConfig,
        ManhattanConfig,
        ProfileConfig,
        ScatterXyConfig,
    )

    assert ManhattanConfig(score_threshold_stat="p95").score_threshold_stat == "p95"
    assert GenomeViewConfig(score_threshold_stat="median").score_threshold_stat == "median"
    profile = ProfileConfig(reference_y_stat="mean", reference_y_label="mean depth")
    assert profile.reference_y is None and profile.reference_y_stat == "mean"
    assert (
        ScatterXyConfig(reference_line="horizontal", reference_stat="p75").reference_stat == "p75"
    )
    with pytest.raises(ValidationError):
        ManhattanConfig(score_threshold_stat="p50")
    # A statistic has no place on the diagonal, or with no line at all.
    with pytest.raises(ValidationError):
        ScatterXyConfig(reference_line="diagonal", reference_stat="median")
    with pytest.raises(ValidationError):
        ScatterXyConfig(reference_stat="median")


def _figure(**kwargs: Any):
    from depictio.models.components.lite import FigureLiteComponent

    return FigureLiteComponent(
        tag="f",
        workflow_tag="w",
        data_collection_tag="d",
        visu_type="box",
        dict_kwargs={"x": "g", "y": "v"},
        **kwargs,
    )


def test_figure_reference_line_takes_exactly_one_of_value_or_stat() -> None:
    from pydantic import ValidationError

    fig = _figure(reference_lines=[{"axis": "y", "stat": "median", "column": "v"}])
    assert fig.reference_lines[0].stat == "median"
    assert _figure(reference_lines=[{"axis": "x", "value": 2.5}]).reference_lines[0].value == 2.5
    for bad in (
        {"axis": "y"},
        {"axis": "y", "value": 1.0, "stat": "median", "column": "v"},
        {"axis": "y", "stat": "median"},  # a statistic of which column?
        {"axis": "z", "value": 1.0},
        {"axis": "y", "value": 1.0, "colour": "red"},
    ):
        with pytest.raises(ValidationError):
            _figure(reference_lines=[bad])


def test_render_reference_lines_are_figure_only_and_grounded() -> None:
    from pydantic import ValidationError

    from depictio.models.components.advanced_viz.catalog import Render

    render = Render(
        component="figure",
        visu_type="box",
        dict_kwargs={"x": "sample", "y": "depth"},
        reference_lines=[{"axis": "y", "stat": "median", "column": "coverage"}],
    )
    assert "coverage" in render.bound_columns()
    with pytest.raises(ValidationError):
        Render(
            component="table",
            reference_lines=[{"axis": "y", "value": 1.0}],
        )
    with pytest.raises(ValidationError):  # code mode draws its own lines
        Render(
            component="figure",
            code="fig = None",
            reference_lines=[{"axis": "y", "value": 1.0}],
        )


# ---------------------------------------------------------------------------
# The data route
# ---------------------------------------------------------------------------


def _install_route(monkeypatch: pytest.MonkeyPatch, frame: pl.DataFrame, cap: int) -> None:
    """Run `fetch_advanced_viz_data` over `frame` with no Mongo and no Delta.

    The fake scan honours `{column_name, value: [...]}` filters, the shape the
    route hands `open_deltatable_scan`, so the frame the statistic sees is the
    filtered one.
    """

    def fake_open(**kwargs: Any) -> pl.LazyFrame:
        scan = frame.lazy()
        for f in kwargs.get("metadata") or []:
            scan = scan.filter(pl.col(f["column_name"]).is_in(f["value"]))
        return scan.select(kwargs["select_columns"])

    class _Deltatables:
        @staticmethod
        def find_one(_query: dict) -> dict:
            return {"delta_table_location": "s3://bucket/dc", "flexible_metadata": {}}

    from depictio.api.v1.configs.config import settings

    monkeypatch.setattr(settings.performance, "figure_max_points", cap)
    monkeypatch.setattr("depictio.api.v1.deltatables_utils.open_deltatable_scan", fake_open)
    monkeypatch.setattr(
        "depictio.api.v1.deltatables_utils.get_cached_column_names",
        lambda _dc, _factory: list(frame.columns),
    )
    monkeypatch.setattr("depictio.api.v1.db.deltatables_collection", _Deltatables())
    monkeypatch.setattr(routes, "_assert_dc_access", lambda *_a, **_k: None)
    monkeypatch.setattr(routes, "_resolve_link_filters_for_dc", lambda filters, **_k: filters)


def _call_route(payload: dict) -> dict:
    from fastapi import Response

    return routes.fetch_advanced_viz_data(
        response=Response(), payload=payload, current_user=None, access_token=None
    )


_WF = "0123456789abcdef01234567"
_DC = "0123456789abcdef01234568"


def _gwas(n: int = 20_000) -> pl.DataFrame:
    """Two cohorts with different score ranges, so a filter moves the quantile."""
    return pl.DataFrame(
        {
            "chr": [f"chr{1 + i % 5}" for i in range(n)],
            "pos": list(range(n)),
            "score": [float(i % 1000) / 100.0 + (10.0 if i % 2 else 0.0) for i in range(n)],
            "cohort": ["B" if i % 2 else "A" for i in range(n)],
        }
    )


def test_route_returns_the_statistic_of_the_filtered_unsampled_rows(monkeypatch) -> None:
    frame = _gwas()
    _install_route(monkeypatch, frame, cap=500)
    payload = {
        "wf_id": _WF,
        "dc_id": _DC,
        "columns": ["x", "score"],
        "viz_kind": "scatter_xy",
        "filter_metadata": [{"column_name": "cohort", "value": ["A"]}],
        "reference_stats": {"reference_value": {"column": "score", "stat": "median"}},
    }
    out = _call_route(payload)

    expected = frame.filter(pl.col("cohort") == "A")["score"].median()
    assert out["sampled"] is True, "the test must exercise a reduced frame"
    assert out["reference_stats"]["reference_value"] == pytest.approx(expected, rel=1e-5)
    # Not the median of what came back, and not the unfiltered table's either.
    assert expected != pytest.approx(frame["score"].median())


def test_route_without_a_request_answers_no_stats(monkeypatch) -> None:
    _install_route(monkeypatch, _gwas(1_000), cap=500)
    out = _call_route({"wf_id": _WF, "dc_id": _DC, "columns": ["score"]})
    assert "reference_stats" not in out


def test_a_tail_named_by_a_statistic_is_cut_at_its_value(monkeypatch) -> None:
    frame = _gwas()
    _install_route(monkeypatch, frame, cap=4_000)
    payload = {
        "wf_id": _WF,
        "dc_id": _DC,
        "columns": ["chr", "pos", "score"],
        "viz_kind": "manhattan",
        "roles": {"chr": "chr", "pos": "pos", "score": "score"},
        "tail": {"column": "score", "direction": "high", "threshold_stat": "p95"},
        "reference_stats": {"score_threshold": {"column": "score", "stat": "p95"}},
    }
    out = _call_route(payload)

    p95 = frame["score"].quantile(0.95, interpolation="linear")
    assert out["sampling"]["policy"] == "tail"
    assert out["row_count"] < frame.height, "the test must exercise a reduced frame"
    assert out["reference_stats"]["score_threshold"] == pytest.approx(p95, rel=1e-5)
    kept = sum(1 for s in out["rows"]["score"] if s >= p95)
    assert kept == frame.filter(pl.col("score") >= p95).height, "the tail must arrive whole"


def test_tail_with_stat_threshold_reuses_the_reference_value() -> None:
    frame = pl.DataFrame({"s": [1.0, 2.0, 3.0]}).lazy()
    tail = {"column": "s", "direction": "high", "threshold_stat": "median"}
    resolved = routes._tail_with_stat_threshold(
        frame, tail, {"score_threshold": ("s", "median")}, {"score_threshold": 42.0}
    )
    assert resolved == {"column": "s", "direction": "high", "threshold": 42.0}
    # An explicit threshold is left alone.
    explicit = {"column": "s", "direction": "high", "threshold": 1.5}
    assert routes._tail_with_stat_threshold(frame, explicit) is explicit


# ---------------------------------------------------------------------------
# Export builder, UI figures, catalog preview
# ---------------------------------------------------------------------------


def test_manhattan_export_draws_the_statistic_and_names_it() -> None:
    from depictio.api.v1.services.advanced_viz.kinds import manhattan

    scores = [float(i) for i in range(101)]
    fig = manhattan.build(
        rows={"chr": ["1"] * 101, "pos": list(range(101)), "score": scores},
        config={"score_threshold_stat": "p95", "top_n_labels": 0},
        controls={},
        theme="light",
    )
    lines = [s for s in fig["layout"]["shapes"] if s.get("type") == "line"]
    assert lines and lines[0]["y0"] == pytest.approx(95.0)
    texts = [a["text"] for a in fig["layout"]["annotations"]]
    assert "95th percentile of this table" in texts


def test_figure_reference_lines_are_drawn_and_named() -> None:
    from depictio.api.v1.services.figure.reference_lines import (
        apply_reference_lines,
        normalise_reference_lines,
        resolve_reference_lines,
    )

    frame = pl.DataFrame({"g": ["a", "a", "b", "b", "b"], "v": [1.0, 2.0, 3.0, 4.0, 100.0]})
    lines = normalise_reference_lines(
        [
            {"axis": "y", "stat": "median", "column": "v"},
            {"axis": "x", "value": 0.5, "label": "cut-off"},
            {"axis": "y", "stat": "mean", "column": "missing"},  # dropped, not drawn wrong
        ]
    )
    resolved = resolve_reference_lines(lines, frame)
    assert resolved == [
        {"axis": "y", "value": 3.0, "label": "median of this table"},
        {"axis": "x", "value": 0.5, "label": "cut-off"},
    ]
    fig = apply_reference_lines(go.Figure(go.Box(x=frame["g"], y=frame["v"])), resolved)
    shapes = fig.layout.shapes
    assert len(shapes) == 2
    assert shapes[0].y0 == 3.0 and shapes[0].line.dash == "dash"
    texts = {a.text for a in fig.layout.annotations}
    assert {"median of this table", "cut-off"} <= texts


def test_a_line_source_is_named_in_its_label() -> None:
    """RULES.md §17: where a threshold comes from is on the plot, not only in YAML."""
    from depictio.api.v1.services.figure.reference_lines import resolve_reference_lines

    resolved = resolve_reference_lines(
        [
            {"axis": "y", "value": 30.0, "label": "Q30", "source": "Illumina spec"},
            {"axis": "y", "value": 0.5, "source": "FastQC default"},
        ],
        None,
    )
    assert [r["label"] for r in resolved] == [
        "Q30 (Illumina spec)",
        "y = 0.5 (FastQC default)",
    ]


def test_figure_dict_path_keeps_existing_shapes() -> None:
    from depictio.api.v1.services.figure.reference_lines import apply_reference_lines

    fig = {"data": [], "layout": {"shapes": [{"type": "rect"}]}}
    apply_reference_lines(fig, [{"axis": "y", "value": 1.0, "label": "y = 1"}], theme="dark")
    assert len(fig["layout"]["shapes"]) == 2
    assert fig["layout"]["annotations"][0]["text"] == "y = 1"


def test_catalog_figure_preview_draws_reference_lines(tmp_path) -> None:
    from depictio.catalog.payload import _figure_payload
    from depictio.models.components.advanced_viz.catalog import Render

    df = pl.DataFrame({"sample": ["a", "b", "c", "d"], "depth": [10.0, 20.0, 30.0, 40.0]})
    render = Render(
        component="figure",
        visu_type="bar",
        dict_kwargs={"x": "sample", "y": "depth"},
        reference_lines=[{"axis": "y", "stat": "median", "column": "depth"}],
    )
    fig = _figure_payload(df, render)["figure"]
    shapes = fig["layout"]["shapes"]
    assert any(math.isclose(s["y0"], 25.0) for s in shapes)
    assert any(a["text"] == "median of this table" for a in fig["layout"]["annotations"])


def test_catalog_preview_carries_reference_stats() -> None:
    from depictio.catalog.payload import _advanced_viz_defaults, _reference_stats
    from depictio.models.components.advanced_viz.catalog import Render

    df = pl.DataFrame(
        {"chr": ["1"] * 101, "pos": list(range(101)), "score": [float(i) for i in range(101)]}
    )
    render = Render(
        component="advanced_viz",
        kind="manhattan",
        roles={"chr": "chr", "pos": "pos", "score": "score"},
    )
    config = {"viz_kind": "manhattan", "chr_col": "chr", "pos_col": "pos", "score_col": "score"}
    _advanced_viz_defaults(df, render, config)
    # No fixed number taken off the fixture: the line follows the rows on show.
    assert "score_threshold" not in config
    assert config["score_threshold_stat"] == "p95"
    assert config["top_n_labels"] == 8
    stats = _reference_stats(df, config)
    assert stats is not None
    assert stats["reference_stats"]["score_threshold"] == pytest.approx(95.0)
    assert stats["reference_stat_requests"]["score_threshold"] == {
        "column": "score",
        "stat": "p95",
    }

    explicit = {"viz_kind": "manhattan", "score_col": "score", "score_threshold": 3.0}
    _advanced_viz_defaults(df, render, explicit)
    assert "score_threshold_stat" not in explicit


def test_worker_figure_builder_draws_a_median_of_the_filtered_rows(monkeypatch) -> None:
    """`build_figure_preview` reads the statistic off its own filtered scan."""
    from depictio.api.v1 import celery_tasks, deltatables_utils

    frame = pl.DataFrame(
        {
            "sample": [f"s{i}" for i in range(9)],
            "depth": [1.0, 2.0, 3.0, 4.0, 5.0, 60.0, 70.0, 80.0, 90.0],
            "batch": ["a"] * 5 + ["b"] * 4,
        }
    )

    def _filtered(metadata: list[dict] | None) -> pl.DataFrame:
        out = frame
        for f in metadata or []:
            out = out.filter(pl.col(f["column_name"]).is_in(f["value"]))
        return out

    def fake_scan(**kwargs: Any) -> pl.LazyFrame:
        return _filtered(kwargs.get("metadata")).lazy().select(kwargs["select_columns"])

    def fake_load(**kwargs: Any) -> pl.DataFrame:
        return _filtered(kwargs.get("metadata"))

    monkeypatch.setattr(deltatables_utils, "open_deltatable_scan", fake_scan)
    monkeypatch.setattr(deltatables_utils, "load_deltatable_lite", fake_load)

    # No Mongo here: the brand theme falls back to the env defaults at once.
    def _no_branding() -> None:
        raise RuntimeError("no mongo in this test")

    monkeypatch.setattr(
        "depictio.api.v1.services.branding.resolve_effective_brand_theme", _no_branding
    )

    result = celery_tasks.build_figure_preview.run(
        {
            "metadata": {
                "wf_id": _WF,
                "dc_id": _DC,
                "dc_config": {"delta_location": "s3://bucket/dc"},
                "visu_type": "scatter",
                "dict_kwargs": {"x": "sample", "y": "depth"},
                "mode": "ui",
                "reference_lines": [{"axis": "y", "stat": "median", "column": "depth"}],
            },
            "filter_metadata": [{"column_name": "batch", "value": ["a"]}],
            "theme": "light",
        }
    )
    layout = result["figure"]["layout"]
    assert any(s.get("y0") == 3.0 and s["line"]["dash"] == "dash" for s in layout["shapes"])
    assert any(a.get("text") == "median of this table" for a in layout["annotations"])
