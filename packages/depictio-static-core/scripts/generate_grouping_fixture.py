"""Regenerate fixtures/grouping-expected.json (grouped figure parity).

The server colours a figure by the reader's selection groups (or a column) and
splits it into panels by running plotly-express over a frame annotated with a
group column (``depictio/api/v1/services/figure/groups.py``, applied by
``build_figure_preview``). The static runtime redraws the same figure in the
browser from a bound scaffold (``packages/depictio-static-core/src/grouping.ts``).

This script builds, for each case, the figure BOTH ways:

* the binding the producer would ship (``build_binding_with_reason`` over the
  unfiltered frame), which the TypeScript refills with the request; and
* the figure the server would answer: the same kwargs through
  ``apply_group_coloring_kwargs`` / ``apply_column_coloring_kwargs`` /
  ``apply_facet_kwargs`` over the filtered, annotated frame, tidied by
  ``tidy_facet_layout``.

and writes the frame, the cases and the server's figures for
``test/grouping.test.ts``:

    DEPICTIO_CONTEXT=cli uv run --extra dev python \\
        packages/depictio-static-core/scripts/generate_grouping_fixture.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import plotly.express as px
import polars as pl

from depictio.api.v1.services.figure.figure_builder import create_figure_from_data
from depictio.api.v1.services.figure.groups import (
    GROUP_COLUMN,
    MAX_FACET_CATEGORIES,
    OTHER_LABEL,
    apply_column_coloring_kwargs,
    apply_facet_kwargs,
    apply_group_coloring_kwargs,
    group_annotation_expr,
    sanitize_color_by_column,
    sanitize_group_defs,
    tidy_facet_layout,
)
from depictio.serverless.binding import build_binding_with_reason

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "packages/depictio-static-core/fixtures/grouping-expected.json"

SPECIES_COLORS = {"setosa": "#12b886", "versicolor": "#fd7e14", "virginica": "#7950f2"}


def frame() -> pl.DataFrame:
    """A small iris with a sample id, an integer bucket and a nullable grade."""
    rng = random.Random(7)
    iris = pl.from_pandas(px.data.iris()).drop("species_id")
    keep = pl.concat([iris.filter(pl.col("species") == s).head(20) for s in SPECIES_COLORS])
    n = keep.height
    grades = [None if i % 7 == 0 else rng.choice(["low", "mid", "high"]) for i in range(n)]
    return keep.with_columns(
        pl.Series("sid", [f"s{i:02d}" for i in range(n)]),
        pl.Series("bucket", [i % 5 for i in range(n)], dtype=pl.Int64),
        pl.Series("grade", grades, dtype=pl.String),
    )


def sid(*rows: int) -> list[str]:
    return [f"s{i:02d}" for i in rows]


def groups_by_sid(*specs: tuple[str, str, list[int]]) -> list[dict[str, Any]]:
    return [
        {"name": name, "color": color, "column_name": "sid", "values": sid(*rows)}
        for name, color, rows in specs
    ]


G2 = groups_by_sid(
    ("North", "#e03131", list(range(0, 14))), ("South", "#1971c2", list(range(25, 40)))
)
G5 = groups_by_sid(
    ("A", "#e03131", list(range(0, 6))),
    ("B", "#1971c2", list(range(8, 14))),
    ("C", "#2f9e44", list(range(20, 26))),
    ("D", "#f08c00", list(range(30, 36))),
    ("E", "#ae3ec9", list(range(44, 50))),
)
G_BUCKET = [
    {"name": "Low", "color": "#e03131", "column_name": "bucket", "values": ["0", "1"]},
    {"name": "High", "color": "#1971c2", "column_name": "bucket", "values": ["4"]},
]
G_OVERLAP = groups_by_sid(
    ("First", "#e03131", list(range(0, 20))), ("Second", "#1971c2", list(range(10, 30)))
)

XY = {"x": "sepal_width", "y": "sepal_length"}
BOX = {"x": "species", "y": "sepal_length"}

#: name, visu_type, dict_kwargs, request, optional kept-row slice (mask)
CASES: list[dict[str, Any]] = [
    {
        "name": "scatter coloured by species, groups",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G2},
    },
    {
        "name": "scatter, no colour, groups",
        "visu": "scatter",
        "kwargs": dict(XY),
        "request": {"groups": G2},
    },
    {
        "name": "scatter, groups, other dropped",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G2, "showOther": False},
    },
    {
        "name": "scatter, overlapping groups first wins",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G_OVERLAP},
    },
    {
        "name": "scatter with a symbol column",
        "visu": "scatter",
        "kwargs": {**XY, "symbol": "species"},
        "request": {"groups": G2},
    },
    {
        "name": "scatter with colour and symbol",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species", "symbol": "grade"},
        "request": {"groups": G2},
    },
    {
        "name": "scatter, groups on a numeric column",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G_BUCKET},
    },
    {
        "name": "scatter, masked rows",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G2},
        "keep": [i for i in range(60) if i % 3 != 0],
    },
    {
        "name": "scatter, a group with no row left",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G2},
        "keep": list(range(14, 60)),
    },
    {
        "name": "box coloured by its own x",
        "visu": "box",
        "kwargs": {**BOX, "color": "species"},
        "request": {"groups": G2},
    },
    {"name": "box, no colour", "visu": "box", "kwargs": dict(BOX), "request": {"groups": G2}},
    {"name": "violin, no colour", "visu": "violin", "kwargs": dict(BOX), "request": {"groups": G2}},
    {
        "name": "strip coloured by species",
        "visu": "strip",
        "kwargs": {**BOX, "color": "species"},
        "request": {"groups": G2},
    },
    {
        "name": "bar coloured by species",
        "visu": "bar",
        "kwargs": {**BOX, "color": "species"},
        "request": {"groups": G2},
    },
    {
        "name": "histogram coloured by species",
        "visu": "histogram",
        "kwargs": {"x": "sepal_length", "color": "species"},
        "request": {"groups": G2},
    },
    {
        "name": "line coloured by species",
        "visu": "line",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G2},
    },
    {
        "name": "split, three panels",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G2, "display": "facet"},
    },
    {
        "name": "split, one row of four",
        "visu": "scatter",
        "kwargs": dict(XY),
        "request": {
            "groups": groups_by_sid(
                ("A", "#e03131", [0, 1, 2]),
                ("B", "#1971c2", [20, 21, 22]),
                ("C", "#2f9e44", [40, 41, 42]),
            ),
            "display": "facet",
        },
    },
    {
        "name": "split, two rows",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G5, "display": "facet"},
    },
    {
        "name": "split, other dropped",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G5, "display": "facet", "showOther": False},
    },
    {
        "name": "split, empty panel",
        "visu": "scatter",
        "kwargs": {**XY, "color": "species"},
        "request": {"groups": G2, "display": "facet"},
        "keep": list(range(14, 60)),
    },
    {
        "name": "split, box",
        "visu": "box",
        "kwargs": {**BOX, "color": "species"},
        "request": {"groups": G2, "display": "facet"},
    },
    {
        "name": "split, histogram",
        "visu": "histogram",
        "kwargs": {"x": "sepal_length"},
        "request": {"groups": G2, "display": "facet"},
    },
    {
        "name": "split, one group only and no other",
        "visu": "scatter",
        "kwargs": dict(XY),
        "request": {"groups": G2[:1], "display": "facet", "showOther": False},
    },
    {
        "name": "column colour with a stable palette",
        "visu": "scatter",
        "kwargs": dict(XY),
        "request": {"column": "species", "colorMap": SPECIES_COLORS},
    },
    {
        "name": "column colour replaces the figure's own",
        "visu": "scatter",
        "kwargs": {**XY, "color": "grade"},
        "request": {"column": "species", "colorMap": SPECIES_COLORS},
    },
    {
        "name": "column colour, masked",
        "visu": "box",
        "kwargs": {**BOX, "color": "species"},
        "request": {
            "column": "grade",
            "colorMap": {"low": "#e03131", "mid": "#f08c00", "high": "#2f9e44"},
        },
        "keep": [i for i in range(60) if i % 2 == 0],
    },
    {
        "name": "column colour with nulls",
        "visu": "scatter",
        "kwargs": dict(XY),
        "request": {
            "column": "grade",
            "colorMap": {"low": "#e03131", "mid": "#f08c00", "high": "#2f9e44"},
        },
    },
    {
        "name": "column colour, split",
        "visu": "scatter",
        "kwargs": dict(XY),
        "request": {"column": "species", "colorMap": SPECIES_COLORS, "display": "facet"},
    },
    {
        "name": "column colour without a palette",
        "visu": "scatter",
        "kwargs": dict(XY),
        "request": {"column": "species"},
    },
    {
        "name": "column colour without a palette, split stays one panel",
        "visu": "scatter",
        "kwargs": dict(XY),
        "request": {"column": "species", "display": "facet"},
    },
]


def server_figure(df: pl.DataFrame, case: dict[str, Any]) -> dict[str, Any]:
    """The figure the render endpoint answers for this request (celery_tasks.py)."""
    request = case["request"]
    kwargs = dict(case["kwargs"])
    display = request.get("display", "color")
    if "groups" in request:
        groups = sanitize_group_defs(request["groups"])
        include_other = request.get("showOther", True)
        expr = group_annotation_expr(groups, df.columns, dict(df.schema))
        frame_df = df.with_columns(expr)
        if not include_other:
            frame_df = frame_df.filter(pl.col(GROUP_COLUMN) != OTHER_LABEL)
        kwargs = apply_group_coloring_kwargs(kwargs, groups, include_other=include_other)
        panels = len(groups) + (1 if include_other else 0)
        if display == "facet" and panels <= MAX_FACET_CATEGORIES:
            kwargs = apply_facet_kwargs(kwargs, GROUP_COLUMN)
    else:
        by_column = sanitize_color_by_column(
            {"column_name": request["column"], "color_map": request.get("colorMap", {})}
        )
        assert by_column is not None
        frame_df = df
        kwargs = apply_column_coloring_kwargs(
            kwargs, by_column["column_name"], by_column["color_map"]
        )
        n = len(by_column["color_map"]) if by_column["color_map"] else None
        if display == "facet" and n is not None and n <= MAX_FACET_CATEGORIES:
            kwargs = apply_facet_kwargs(kwargs, by_column["column_name"])
    fig = create_figure_from_data(
        df=frame_df, visu_type=case["visu"], dict_kwargs=kwargs, theme="light", max_points=-1
    )
    tidy_facet_layout(fig)
    out = fig.to_plotly_json()
    out["layout"].pop("template", None)
    return plain(out)


def plain(value: Any) -> Any:
    """JSON-ready: numpy arrays and plotly's ``{dtype, bdata}`` blobs as lists."""
    if isinstance(value, dict):
        if set(value) >= {"dtype", "bdata"}:
            import base64

            import numpy as np

            raw = np.frombuffer(base64.b64decode(value["bdata"]), dtype=np.dtype(value["dtype"]))
            return raw.tolist()
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    return value


def main() -> None:
    df = frame()
    cases = []
    for case in CASES:
        keep = case.get("keep")
        filtered = df if keep is None else df[keep]
        binding, miss = build_binding_with_reason(
            {"visu_type": case["visu"], "dict_kwargs": case["kwargs"]}, df
        )
        assert binding is not None, f"{case['name']}: no binding ({miss})"
        figure = server_figure(filtered, case)
        scaffold = binding.model_dump(mode="json")
        cases.append(
            {
                "name": case["name"],
                "visu": case["visu"],
                "binding": scaffold,
                "request": case["request"],
                "keep": keep,
                "expected": figure,
            }
        )
        print(f"{case['name']}: {len(figure['data'])} traces")
    columns = {c: df[c].to_list() for c in df.columns}
    OUT.write_text(json.dumps({"columns": columns, "cases": cases}, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
