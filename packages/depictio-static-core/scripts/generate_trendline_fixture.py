"""Regenerate fixtures/trendline-expected.json (browser trendline refit parity).

For every case the REAL pipeline runs twice: ``build_binding`` on the full
frame (the binding a bundle ships, scaffold left out), then
``create_figure_from_data`` (px + statsmodels + pandas, as pinned in uv.lock)
on the frame each mask keeps, whose trendline traces are the expected output.
``test/trendline.test.ts`` refills the shipped binding under the same mask and
must draw the same vertices:

    DEPICTIO_CONTEXT=cli uv run --extra dev python \\
        packages/depictio-static-core/scripts/generate_trendline_fixture.py

``depictio/tests/unit/serverless/test_trendline_fixture.py`` regenerates it in
memory and fails when the committed file is stale (a plotly, statsmodels or
pandas bump that changes a fit shows up there first).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "packages/depictio-static-core/fixtures/trendline-expected.json"
PENGUINS = ROOT / "depictio/projects/init/penguins/data"
PENGUINS_DASHBOARD = ROOT / "depictio/projects/init/penguins/dashboards/species_analysis.yaml"

_TREND = "trendline</b>"


def _noisy(seed: int = 7, n: int = 90) -> pl.DataFrame:
    """Two groups, rows shuffled, tied x values, nulls on both axes, outliers."""
    rng = np.random.default_rng(seed)
    x = np.round(rng.uniform(0, 20, n), 0 if seed == 7 else 1)  # integer x → many ties
    y = np.sin(x / 3) * 10 + rng.normal(0, 2, n)
    y[rng.choice(n, 4, replace=False)] += 40  # outliers lowess must down-weight
    xs: list[float | None] = [float(v) for v in x]
    ys: list[float | None] = [float(v) for v in y]
    for i in rng.choice(n, 5, replace=False):
        xs[int(i)] = None
    for i in rng.choice(n, 6, replace=False):
        ys[int(i)] = None
    return pl.DataFrame(
        {"g": rng.choice(["a", "b"], n).tolist(), "x": xs, "y": ys},
        schema={"g": pl.Utf8, "x": pl.Float64, "y": pl.Float64},
    )


def _positive(seed: int = 11, n: int = 60) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.5, 100, n)
    y = 3 * x**0.7 * rng.lognormal(0, 0.2, n)
    return pl.DataFrame({"g": rng.choice(["a", "b"], n).tolist(), "x": x, "y": y})


def _dates(seed: int = 3, n: int = 70) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    day0 = datetime(2024, 1, 1)
    days = rng.choice(200, n, replace=False)
    t = [day0 + timedelta(days=int(d), hours=int(h)) for d, h in zip(days, rng.integers(0, 24, n))]
    y: list[float | None] = [float(v) for v in np.cumsum(rng.normal(0, 1, n))]
    for i in rng.choice(n, 4, replace=False):
        y[int(i)] = None
    return pl.DataFrame(
        {"g": rng.choice(["a", "b"], n).tolist(), "x": t, "y": y},
        schema={"g": pl.Utf8, "x": pl.Datetime("us"), "y": pl.Float64},
    )


def _penguins() -> pl.DataFrame:
    parts = []
    for run in sorted(p for p in PENGUINS.iterdir() if p.is_dir()):
        demographic = pl.read_csv(run / "demographic_data.csv")
        physical = pl.read_csv(run / "physical_features.csv")
        parts.append(demographic.join(physical, on="individual_id", how="inner"))
    return pl.concat(parts)


def _penguins_kwargs() -> dict[str, Any]:
    """The dashboard's own "Body Mass vs Flipper Length" kwargs, verbatim."""
    import yaml

    spec = yaml.safe_load(PENGUINS_DASHBOARD.read_text())
    for comp in spec["components"]:
        if comp.get("title") == "Body Mass vs Flipper Length":
            return dict(comp["dict_kwargs"])
    raise LookupError("penguins body-mass scatter not found")


def _xy(**extra: Any) -> dict[str, Any]:
    return {"x": "x", "y": "y", "color": "g", **extra}


# (name, frame, dict_kwargs)
CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("ols", "noisy", _xy(trendline="ols")),
    (
        "ols through the origin",
        "noisy",
        _xy(trendline="ols", trendline_options={"add_constant": False}),
    ),
    ("ols log_x", "positive", _xy(trendline="ols", trendline_options={"log_x": True})),
    ("ols log_y", "positive", _xy(trendline="ols", trendline_options={"log_y": True})),
    (
        "ols log-log",
        "positive",
        _xy(trendline="ols", trendline_options={"log_x": True, "log_y": True}),
    ),
    ("ols over dates", "dates", _xy(trendline="ols")),
    ("lowess", "noisy", _xy(trendline="lowess")),
    ("lowess frac 0.25", "noisy", _xy(trendline="lowess", trendline_options={"frac": 0.25})),
    ("lowess, fine x", "fine", _xy(trendline="lowess")),
    ("lowess over dates", "dates", _xy(trendline="lowess")),
    ("lowess, penguins dashboard", "penguins", _penguins_kwargs()),
    ("rolling mean", "noisy", _xy(trendline="rolling", trendline_options={"window": 5})),
    (
        "rolling mean, centred, min_periods",
        "noisy",
        _xy(trendline="rolling", trendline_options={"window": 7, "center": True, "min_periods": 1}),
    ),
    (
        "rolling sum, closed both",
        "noisy",
        _xy(
            trendline="rolling",
            trendline_options={"window": 4, "closed": "both", "function": "sum"},
        ),
    ),
    (
        "rolling median",
        "noisy",
        _xy(
            trendline="rolling",
            trendline_options={"window": 6, "min_periods": 2, "function": "median"},
        ),
    ),
    (
        "rolling std ddof 0",
        "noisy",
        _xy(
            trendline="rolling",
            trendline_options={
                "window": 5,
                "min_periods": 2,
                "function": "std",
                "function_args": {"ddof": 0},
            },
        ),
    ),
    (
        "rolling var",
        "noisy",
        _xy(trendline="rolling", trendline_options={"window": 5, "function": "var"}),
    ),
    (
        "rolling min",
        "noisy",
        _xy(
            trendline="rolling",
            trendline_options={"window": 5, "min_periods": 1, "function": "min"},
        ),
    ),
    (
        "rolling max",
        "noisy",
        _xy(trendline="rolling", trendline_options={"window": 3, "function": "max"}),
    ),
    (
        "rolling count",
        "noisy",
        _xy(trendline="rolling", trendline_options={"window": 4, "function": "count"}),
    ),
    ("rolling over dates", "dates", _xy(trendline="rolling", trendline_options={"window": 7})),
    ("expanding mean", "noisy", _xy(trendline="expanding")),
    (
        "expanding std, min_periods",
        "noisy",
        _xy(trendline="expanding", trendline_options={"min_periods": 3, "function": "std"}),
    ),
    ("expanding max", "noisy", _xy(trendline="expanding", trendline_options={"function": "max"})),
    (
        "expanding median",
        "noisy",
        _xy(trendline="expanding", trendline_options={"function": "median"}),
    ),
    ("ewm alpha", "noisy", _xy(trendline="ewm", trendline_options={"alpha": 0.3})),
    (
        "ewm span, adjust off",
        "noisy",
        _xy(trendline="ewm", trendline_options={"span": 5, "adjust": False}),
    ),
    (
        "ewm com 1, adjust off",
        "noisy",
        _xy(trendline="ewm", trendline_options={"com": 1, "adjust": False}),
    ),
    (
        "ewm halflife, ignore_na",
        "noisy",
        _xy(trendline="ewm", trendline_options={"halflife": 2, "ignore_na": True}),
    ),
    ("ewm sum", "noisy", _xy(trendline="ewm", trendline_options={"com": 2, "function": "sum"})),
    ("ewm std", "noisy", _xy(trendline="ewm", trendline_options={"alpha": 0.2, "function": "std"})),
    (
        "ewm var, bias",
        "noisy",
        _xy(
            trendline="ewm",
            trendline_options={"halflife": 3, "function": "var", "function_args": {"bias": True}},
        ),
    ),
    (
        "ewm over dates, min_periods",
        "dates",
        _xy(trendline="ewm", trendline_options={"span": 4, "min_periods": 3}),
    ),
]

FRAMES = {
    "noisy": _noisy,
    "fine": lambda: _noisy(seed=19, n=120),
    "positive": _positive,
    "dates": _dates,
    "penguins": _penguins,
}


def _masks(height: int, groups: list[Any]) -> list[tuple[str, list[int] | None]]:
    rng = np.random.default_rng(height)
    keep = (rng.uniform(size=height) < 0.65).astype(int).tolist()
    # Every row of the first group but one: its trendline must hide (px emits
    # it empty), the others refit as usual.
    first = [i for i, g in enumerate(groups) if g == groups[0]]
    lone = [1] * height
    for i in first[1:]:
        lone[i] = 0
    return [("unfiltered", None), ("random 65%", keep), ("one group down to a row", lone)]


def _identity(trace: dict[str, Any]) -> str:
    return "|".join(str(trace.get(k) or "") for k in ("name", "legendgroup", "xaxis", "yaxis"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, np.datetime64):
        return str(value.astype("datetime64[us]"))
    if isinstance(value, (np.floating, np.integer)):
        return _jsonable(value.item())
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _trendlines(fig: Any) -> dict[str, dict[str, Any] | None]:
    out: dict[str, dict[str, Any] | None] = {}
    for trace in fig.data:
        if _TREND not in (trace.hovertemplate or ""):
            continue
        x, y = trace.x, trace.y
        key = _identity(trace.to_plotly_json())
        if x is None or len(x) == 0:
            out[key] = None
            continue
        out[key] = {"x": [_jsonable(v) for v in x], "y": [_jsonable(v) for v in y]}
    return out


def _column(series: pl.Series) -> list[Any]:
    if series.dtype.is_temporal():
        return [None if v is None else v.isoformat() for v in series.to_list()]
    return series.to_list()


def build() -> dict[str, Any]:
    from depictio.api.v1.services.figure.figure_builder import create_figure_from_data
    from depictio.serverless.binding import build_binding_with_reason

    frames = {name: make() for name, make in FRAMES.items()}
    cases = []
    used: dict[str, set[str]] = {}
    for name, frame_name, kwargs in CASES:
        df = frames[frame_name]
        component = {"component_type": "figure", "visu_type": "scatter", "dict_kwargs": kwargs}
        table, miss = build_binding_with_reason(component, df)
        if table is None:
            raise AssertionError(f"{name}: the binder refused it ({miss})")
        scaffold = table.scaffold["data"]
        identities = {t.i: _identity(scaffold[t.i]) for t in table.trendlines}
        columns = sorted({c for t in table.traces for c in [*t.fields.values(), *t.group]})
        color = kwargs["color"]
        masks = []
        for mask_name, mask in _masks(df.height, df[color].to_list()):
            frame = df if mask is None else df.filter(pl.Series([bool(m) for m in mask]))
            fig = create_figure_from_data(frame, "scatter", kwargs, theme="light", max_points=-1)
            got = _trendlines(fig)
            expected = {str(i): got.get(identity) for i, identity in identities.items()}
            masks.append({"name": mask_name, "mask": mask, "expected": expected})
        used.setdefault(frame_name, set()).update(columns)
        cases.append(
            {
                "name": name,
                "frame": frame_name,
                "temporal_x": df.schema[kwargs["x"]].is_temporal(),
                "traces": len(scaffold),
                "binding": {
                    "group_cols": table.group_cols,
                    "traces": [t.model_dump(mode="json") for t in table.traces],
                    "trendlines": [t.model_dump(mode="json") for t in table.trendlines],
                },
                "masks": masks,
            }
        )
    columns_by_frame = {
        frame_name: {c: _column(frames[frame_name][c]) for c in sorted(names)}
        for frame_name, names in used.items()
    }
    return {"frames": columns_by_frame, "cases": cases}


def render() -> str:
    # Compact: the file is data for a test, ~200 kB even so.
    return json.dumps(build(), sort_keys=True, separators=(",", ":")) + "\n"


if __name__ == "__main__":
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(ROOT)}")
