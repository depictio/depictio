#!/usr/bin/env python
"""Generate the cross-language prologue-IR fixture.

Writes two committed files:

``fixtures/prologue-fixture.json``
    ``{"input": {"columns": {name: [values...]}},
       "cases": [{"name": str, "ops": [<PrologueOp JSON>]}]}``
    — the input table and the IR programs to run.

``fixtures/prologue-expected.json``
    ``{"cases": [{"name": str, "output": {"columns": {...}, "length": int}}]}``
    — the ground truth, produced by **actually executing the IR with Polars**
    (:func:`apply_ops` below). Polars *is* the semantics: the TypeScript
    interpreter in ``packages/depictio-static-core/src/prologue.ts`` is correct
    exactly insofar as it reproduces this file.

Run with the repo venv (its Polars pin is the server's version):

    /home/user/depictio/venv/bin/python \\
        packages/depictio-static-core/scripts/generate_prologue_fixture.py

Pinned semantics exercised by the cases below
---------------------------------------------
* ``filter``   — a null never matches a comparison (Polars default).
* ``group_by`` — ``maintain_order=True`` (first-appearance group order); a null
  key forms its own group; ``std``/``var`` are ddof=1 so a single-row group
  aggregates to null; ``count`` is the non-null count of ``col`` while ``len``
  is the GROUP SIZE (nulls included, no column read); ``nunique`` COUNTS null;
  ``median`` interpolates linearly; ``first``/``last`` are positional.
* ``unpivot``  — one block per ``on`` column in ``on`` order, original row order
  inside each block.
* ``sort``     — ``DataFrame.sort(by, descending=desc)`` with Polars' default
  null placement (nulls first ascending), and Polars' default (unstable) tie
  handling; every sort case here therefore uses a tie-free key set.

Serialisation conventions (both files)
--------------------------------------
* ``event_time`` is emitted as a fixed-width ``%Y-%m-%dT%H:%M:%S`` string. That
  format is lexicographically ordered the same way it is chronologically, so a
  consumer reading the column as plain strings gets identical sort/min/max/
  first/last answers to Polars' ``Datetime``.
* NaN / ±Inf serialise as ``null`` (``json.dumps(..., allow_nan=False)`` then
  guards the invariant).
* Floats go through Python's default ``repr`` shortest-round-trip formatting, so
  no precision is lost.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from depictio.models.models.serverless import (
    AggFn,
    AggSpec,
    AndPred,
    CmpArgs,
    CmpOperator,
    CmpPred,
    ColRef,
    FilterOp,
    GroupByOp,
    IsInArgs,
    IsInPred,
    IsNotNullPred,
    IsNullPred,
    NotPred,
    OrPred,
    RenameOp,
    SortOp,
    UnpivotOp,
)

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures"

N = 50
EPOCH = datetime(2024, 3, 1, 8, 0, 0)
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

HABITATS = ["Riverwater", "Groundwater", "Sediment", "Soil"]


# ---------------------------------------------------------------------------
# the input table
# ---------------------------------------------------------------------------


def build_input() -> pl.DataFrame:
    """A 50-row table shaped to hit every pinned aggregation trap.

    Deliberate structure (asserted at the bottom of :func:`main`):

    * rows 0-41  — the four ordinary habitats, round-robin;
    * rows 42-44 — ``habitat`` is **null** (its own group under Polars);
    * row 45     — ``"Bog"``: a single-row group, so ``std``/``var`` -> null;
    * rows 46-47 — ``"Marsh"``: values ``1.0`` and ``2.0``, so ``median`` must
      interpolate to ``1.5`` rather than pick an element;
    * rows 48-49 — ``"Void"``: every ``value`` null, so ``mean``/``median`` are
      null, ``count`` is 0 and ``nunique`` is 1 (null counts).
    """
    habitat: list[str | None] = []
    for i in range(N):
        if i <= 41:
            habitat.append(HABITATS[i % 4])
        elif i <= 44:
            habitat.append(None)
        elif i == 45:
            habitat.append("Bog")
        elif i <= 47:
            habitat.append("Marsh")
        else:
            habitat.append("Void")

    value: list[float | None] = []
    for i in range(N):
        if i == 45:
            value.append(3.25)
        elif i == 46:
            value.append(1.0)
        elif i == 47:
            value.append(2.0)
        elif i >= 48:
            value.append(None)  # all-null group
        elif i % 9 == 4:
            value.append(None)  # scattered nulls inside ordinary groups
        else:
            # Deterministic spread with a 1/8 step so medians of even-sized
            # groups land between two samples.
            value.append(((i * 37) % 101) / 8.0 - 5.0)

    q_val = [round(((i * 17) % 100) / 1000.0, 6) for i in range(N)]  # 0.000 .. 0.099
    n_reads: list[int | None] = [None if i % 11 == 5 else 1000 + i * 13 for i in range(N)]
    batch: list[int | None] = [None if i == 20 else (i % 3) + 1 for i in range(N)]
    flag: list[bool | None] = [None if i % 13 == 7 else (i % 3 == 0) for i in range(N)]
    sample_id = [f"S{i:02d}" for i in range(N)]
    # Unique-per-row, so `first`/`last` on a string column is observable.
    label = [f"lbl-{(i * 7) % N:02d}" for i in range(N)]
    event_time = [EPOCH + timedelta(minutes=i * 17) for i in range(N)]

    # Three metric columns for `unpivot`, each with its own null pattern so the
    # block order and the per-block row order are both observable.
    shannon: list[float | None] = [
        None if i % 10 == 3 else round(1.0 + (i % 17) / 4.0, 6) for i in range(N)
    ]
    faith_pd: list[float | None] = [
        None if i % 8 == 6 else round(5.0 + (i % 23) / 3.0, 6) for i in range(N)
    ]
    evenness: list[float | None] = [round(0.1 + (i % 9) / 20.0, 6) for i in range(N)]

    return pl.DataFrame(
        {
            "sample_id": pl.Series(sample_id, dtype=pl.String),
            "label": pl.Series(label, dtype=pl.String),
            "habitat": pl.Series(habitat, dtype=pl.String),
            "batch": pl.Series(batch, dtype=pl.Int64),
            "value": pl.Series(value, dtype=pl.Float64),
            "q_val": pl.Series(q_val, dtype=pl.Float64),
            "n_reads": pl.Series(n_reads, dtype=pl.Int64),
            "flag": pl.Series(flag, dtype=pl.Boolean),
            "event_time": pl.Series(event_time, dtype=pl.Datetime("us")),
            "shannon": pl.Series(shannon, dtype=pl.Float64),
            "faith_pd": pl.Series(faith_pd, dtype=pl.Float64),
            "evenness": pl.Series(evenness, dtype=pl.Float64),
        }
    )


# ---------------------------------------------------------------------------
# the reference IR interpreter (Polars)
# ---------------------------------------------------------------------------

_AGG_EXPR = {
    "sum": lambda e: e.sum(),
    "len": lambda e: e.len(),  # GROUP SIZE (nulls included) — see agg_expr()
    "mean": lambda e: e.mean(),
    "median": lambda e: e.median(),
    "min": lambda e: e.min(),
    "max": lambda e: e.max(),
    "count": lambda e: e.count(),  # non-null count
    "nunique": lambda e: e.n_unique(),  # counts null as a value
    "std": lambda e: e.std(),  # ddof=1
    "var": lambda e: e.var(),  # ddof=1
    "first": lambda e: e.first(),
    "last": lambda e: e.last(),
}


def pred_expr(node: dict[str, Any]) -> pl.Expr:
    """Compile one ``Pred`` JSON node to a Polars boolean expression."""
    if "and" in node:
        out = pred_expr(node["and"][0])
        for sub in node["and"][1:]:
            out = out & pred_expr(sub)
        return out
    if "or" in node:
        out = pred_expr(node["or"][0])
        for sub in node["or"][1:]:
            out = out | pred_expr(sub)
        return out
    if "not" in node:
        return ~pred_expr(node["not"])
    if "is_null" in node:
        return pl.col(node["is_null"]["col"]).is_null()
    if "is_not_null" in node:
        return pl.col(node["is_not_null"]["col"]).is_not_null()
    if "is_in" in node:
        return pl.col(node["is_in"]["col"]).is_in(node["is_in"]["values"])
    if "cmp" in node:
        cmp = node["cmp"]
        col, value = pl.col(cmp["col"]), cmp["value"]
        op = cmp["op"]
        if op == "<":
            return col < value
        if op == "<=":
            return col <= value
        if op == ">":
            return col > value
        if op == ">=":
            return col >= value
        if op == "==":
            return col == value
        if op == "!=":
            return col != value
        raise ValueError(f"unknown cmp op {op!r}")
    raise ValueError(f"unknown predicate node {sorted(node)}")


def agg_expr(spec: dict[str, Any]) -> pl.Expr:
    """One ``AggSpec`` JSON node -> the aliased Polars expression it stands for.

    ``len`` is the group size and is the only fn whose ``col`` may be null: the
    bare Polars spellings (``pl.len()`` / the deprecated ``pl.count()``) read no
    column at all, while ``pl.col(c).len()`` returns the same group size but
    keeps ``c`` (polars names the output after it and still raises when it is
    missing). Every other fn requires ``col``.
    """
    col = spec.get("col")
    if spec["fn"] == "len" and col is None:
        return pl.len().alias(spec["alias"])
    return _AGG_EXPR[spec["fn"]](pl.col(col)).alias(spec["alias"])


def apply_ops(df: pl.DataFrame, ops: list[dict[str, Any]]) -> pl.DataFrame:
    """Execute a prologue IR program. This function *is* the contract."""
    for op in ops:
        kind = op["op"]
        if kind == "filter":
            # Polars drops null comparison results: nulls are non-matching.
            df = df.filter(pred_expr(op["pred"]))
        elif kind == "unpivot":
            df = df.unpivot(
                on=op["on"],
                index=op.get("index", []),
                variable_name=op.get("variable", "variable"),
                value_name=op.get("value", "value"),
            )
        elif kind == "group_by":
            df = df.group_by(op["by"], maintain_order=True).agg(
                [agg_expr(spec) for spec in op["agg"]]
            )
        elif kind == "sort":
            df = df.sort(op["by"], descending=op["desc"])
        elif kind == "rename":
            df = df.rename(op["map"])
        else:
            raise ValueError(f"unknown op {kind!r}")
    return df


# ---------------------------------------------------------------------------
# cases
# ---------------------------------------------------------------------------

NUMERIC_AGGS = [
    AggSpec(col="value", fn=AggFn.SUM, alias="sum"),
    AggSpec(col="value", fn=AggFn.MEAN, alias="mean"),
    AggSpec(col="value", fn=AggFn.MEDIAN, alias="median"),
    AggSpec(col="value", fn=AggFn.MIN, alias="min"),
    AggSpec(col="value", fn=AggFn.MAX, alias="max"),
    AggSpec(col="value", fn=AggFn.COUNT, alias="count"),
    AggSpec(col="value", fn=AggFn.NUNIQUE, alias="nunique"),
    AggSpec(col="value", fn=AggFn.STD, alias="std"),
    AggSpec(col="value", fn=AggFn.VAR, alias="var"),
    AggSpec(col="value", fn=AggFn.FIRST, alias="first"),
    AggSpec(col="value", fn=AggFn.LAST, alias="last"),
]


def cases() -> list[tuple[str, list[Any]]]:
    """``(case name, ops)``. Names are the join key with the expected file."""
    return [
        # -- filter ---------------------------------------------------------
        (
            "filter_cmp_lt",
            [FilterOp(pred=CmpPred(cmp=CmpArgs(col="q_val", op=CmpOperator.LT, value=0.05)))],
        ),
        (
            "filter_cmp_eq_string",
            [
                FilterOp(
                    pred=CmpPred(cmp=CmpArgs(col="habitat", op=CmpOperator.EQ, value="Sediment"))
                )
            ],
        ),
        (
            # `!=` against a nullable column: the null rows drop out too.
            "filter_cmp_ne_null_drop",
            [
                FilterOp(
                    pred=CmpPred(cmp=CmpArgs(col="habitat", op=CmpOperator.NE, value="Sediment"))
                )
            ],
        ),
        (
            "filter_is_null",
            [FilterOp(pred=IsNullPred(is_null=ColRef(col="value")))],
        ),
        (
            "filter_is_not_null",
            [FilterOp(pred=IsNotNullPred(is_not_null=ColRef(col="habitat")))],
        ),
        (
            "filter_is_in_int",
            [FilterOp(pred=IsInPred(is_in=IsInArgs(col="batch", values=[1, 3])))],
        ),
        (
            "filter_is_in_bool",
            [FilterOp(pred=IsInPred(is_in=IsInArgs(col="flag", values=[True])))],
        ),
        (
            # and / or / not / is_in in one tree.
            "filter_pred_tree",
            [
                FilterOp(
                    pred=AndPred(
                        and_=[
                            OrPred(
                                or_=[
                                    IsInPred(
                                        is_in=IsInArgs(
                                            col="habitat", values=["Riverwater", "Marsh"]
                                        )
                                    ),
                                    CmpPred(cmp=CmpArgs(col="value", op=CmpOperator.GE, value=2.0)),
                                ]
                            ),
                            NotPred(not_=IsNullPred(is_null=ColRef(col="value"))),
                            CmpPred(cmp=CmpArgs(col="q_val", op=CmpOperator.LE, value=0.08)),
                        ]
                    )
                )
            ],
        ),
        # -- unpivot --------------------------------------------------------
        (
            "unpivot_three_metrics",
            [
                UnpivotOp(
                    on=["shannon", "faith_pd", "evenness"],
                    index=["sample_id", "habitat"],
                    variable="metric",
                    value="value",
                )
            ],
        ),
        (
            # No index columns and the default variable/value names.
            "unpivot_no_index_defaults",
            [UnpivotOp(on=["shannon", "evenness"])],
        ),
        # -- group_by -------------------------------------------------------
        (
            # Null habitat forms its own group; Bog is single-row (std/var null);
            # Marsh has two values (median interpolates); Void is all-null.
            "group_by_habitat_all_aggs",
            [GroupByOp(by=["habitat"], agg=NUMERIC_AGGS)],
        ),
        (
            "group_by_two_keys",
            [
                GroupByOp(
                    by=["habitat", "batch"],
                    agg=[
                        AggSpec(col="value", fn=AggFn.MEAN, alias="value"),
                        AggSpec(col="n_reads", fn=AggFn.SUM, alias="reads"),
                    ],
                )
            ],
        ),
        (
            # Every group is a single row: std/var -> null across the board.
            "group_by_singleton_groups",
            [
                GroupByOp(
                    by=["sample_id"],
                    agg=[
                        AggSpec(col="value", fn=AggFn.STD, alias="std"),
                        AggSpec(col="value", fn=AggFn.VAR, alias="var"),
                        AggSpec(col="value", fn=AggFn.COUNT, alias="count"),
                    ],
                )
            ],
        ),
        (
            # String / datetime / bool reducers.
            "group_by_non_numeric_aggs",
            [
                GroupByOp(
                    by=["batch"],
                    agg=[
                        AggSpec(col="label", fn=AggFn.FIRST, alias="first_label"),
                        AggSpec(col="label", fn=AggFn.LAST, alias="last_label"),
                        AggSpec(col="label", fn=AggFn.MIN, alias="min_label"),
                        AggSpec(col="label", fn=AggFn.MAX, alias="max_label"),
                        AggSpec(col="label", fn=AggFn.NUNIQUE, alias="n_labels"),
                        AggSpec(col="event_time", fn=AggFn.MIN, alias="first_seen"),
                        AggSpec(col="event_time", fn=AggFn.MAX, alias="last_seen"),
                        AggSpec(col="flag", fn=AggFn.COUNT, alias="flag_count"),
                        AggSpec(col="flag", fn=AggFn.NUNIQUE, alias="flag_nunique"),
                    ],
                )
            ],
        ),
        # -- group_by: len (group size) vs count (non-null) ------------------
        (
            # The contrast that motivates a separate `len` fn: `value` has
            # scattered nulls and one all-null group (Void), so group size and
            # non-null count disagree on most groups. `habitat` also carries a
            # null key group, which `len` must count like any other.
            "group_by_len_vs_count_nulls",
            [
                GroupByOp(
                    by=["habitat"],
                    agg=[
                        AggSpec(col=None, fn=AggFn.LEN, alias="n_rows"),
                        AggSpec(col="value", fn=AggFn.COUNT, alias="n_value"),
                        AggSpec(col="n_reads", fn=AggFn.COUNT, alias="n_reads"),
                        AggSpec(col="value", fn=AggFn.LEN, alias="len_value"),
                    ],
                )
            ],
        ),
        (
            # Default (alias-free) output names, pinned per spelling on Polars
            # 1.42.1: bare `pl.len()` -> "len", bare `pl.count()` -> "count",
            # `pl.col("value").len()` -> "value". `batch` has a null key group.
            "group_by_len_default_aliases",
            [
                GroupByOp(
                    by=["batch"],
                    agg=[
                        AggSpec(col=None, fn=AggFn.LEN, alias="len"),
                        AggSpec(col=None, fn=AggFn.LEN, alias="count"),
                        AggSpec(col="value", fn=AggFn.LEN, alias="value"),
                    ],
                )
            ],
        ),
        (
            # len after a filter counts the SURVIVING rows only.
            "group_by_len_after_filter",
            [
                FilterOp(pred=CmpPred(cmp=CmpArgs(col="q_val", op=CmpOperator.LT, value=0.05))),
                GroupByOp(
                    by=["habitat"],
                    agg=[
                        AggSpec(col=None, fn=AggFn.LEN, alias="n_rows"),
                        AggSpec(col="value", fn=AggFn.COUNT, alias="n_value"),
                    ],
                ),
            ],
        ),
        # -- sort -----------------------------------------------------------
        (
            # Tie-free key (`label` is unique) so the ordering is total.
            "sort_label_asc",
            [SortOp(by=["label"], desc=[False])],
        ),
        (
            # `value` has nulls AND ties -> tie-break on the unique `sample_id`.
            "sort_value_nulls_then_id",
            [SortOp(by=["value", "sample_id"], desc=[False, False])],
        ),
        (
            "sort_value_desc_then_id",
            [SortOp(by=["value", "sample_id"], desc=[True, False])],
        ),
        (
            "sort_multi_mixed_direction",
            [SortOp(by=["habitat", "q_val"], desc=[True, False])],
        ),
        (
            "sort_datetime_desc",
            [SortOp(by=["event_time"], desc=[True])],
        ),
        # -- rename ---------------------------------------------------------
        (
            "rename_two_columns",
            [RenameOp(map={"value": "measurement", "habitat": "site"})],
        ),
        # -- chains ---------------------------------------------------------
        (
            # The RFC §7 shape: filter -> unpivot -> group_by -> sort.
            "chain_filter_unpivot_group_sort",
            [
                FilterOp(pred=IsNotNullPred(is_not_null=ColRef(col="habitat"))),
                UnpivotOp(
                    on=["shannon", "faith_pd", "evenness"],
                    index=["sample_id", "habitat"],
                    variable="metric",
                    value="value",
                ),
                GroupByOp(
                    by=["habitat", "metric"],
                    agg=[
                        AggSpec(col="value", fn=AggFn.MEAN, alias="value"),
                        AggSpec(col="value", fn=AggFn.COUNT, alias="n"),
                    ],
                ),
                SortOp(by=["value"], desc=[True]),
            ],
        ),
        (
            "chain_group_rename_sort",
            [
                GroupByOp(
                    by=["habitat"],
                    agg=[AggSpec(col="value", fn=AggFn.MEAN, alias="value")],
                ),
                RenameOp(map={"value": "mean_value"}),
                SortOp(by=["habitat"], desc=[False]),
            ],
        ),
        (
            # The shape four viralrecon seed figures use verbatim:
            # `group_by(k).agg(pl.count().alias('count')).sort('count', desc)`.
            # `habitat` is appended to the sort key because group sizes tie
            # (Marsh and Void are both 2) and Polars' sort is not stable.
            "chain_group_len_sort_desc",
            [
                GroupByOp(
                    by=["habitat"],
                    agg=[AggSpec(col=None, fn=AggFn.LEN, alias="count")],
                ),
                SortOp(by=["count", "habitat"], desc=[True, False]),
            ],
        ),
        (
            # Filter that empties the frame: every downstream op must survive it.
            "chain_empty_after_filter",
            [
                FilterOp(pred=CmpPred(cmp=CmpArgs(col="q_val", op=CmpOperator.GT, value=99.0))),
                GroupByOp(
                    by=["habitat"],
                    agg=[AggSpec(col="value", fn=AggFn.MEAN, alias="value")],
                ),
                SortOp(by=["habitat"], desc=[False]),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------


def json_scalar(value: Any) -> Any:
    """One cell -> a JSON value. NaN/Inf collapse to null; datetimes to ISO."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime(TIME_FORMAT)
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (int, str)):
        return value
    raise TypeError(f"unserialisable cell type {type(value)!r}")


def columns_payload(df: pl.DataFrame) -> dict[str, list[Any]]:
    return {name: [json_scalar(v) for v in df.get_column(name).to_list()] for name in df.columns}


def main() -> None:
    df = build_input()

    # Structural invariants the cases depend on — a silent drift here would turn
    # the fixture into a weaker test rather than a failing one.
    counts = dict(zip(*df.group_by("habitat", maintain_order=True).len().to_dict().values()))
    assert counts["Bog"] == 1, "Bog must stay a single-row group (std/var -> null)"
    assert counts["Marsh"] == 2, "Marsh must stay a two-row group (median interpolation)"
    assert counts[None] == 3, "habitat must keep its null group"
    assert df.filter(pl.col("habitat") == "Void")["value"].null_count() == 2
    marsh = sorted(v for v in df.filter(pl.col("habitat") == "Marsh")["value"].to_list())
    assert marsh == [1.0, 2.0], "Marsh median must interpolate to 1.5, not pick a sample"
    assert df["value"].null_count() > 0 and df["habitat"].null_count() > 0
    assert df["label"].n_unique() == N, "label must stay unique (sort tie-breaker)"

    fixture_cases: list[dict[str, Any]] = []
    expected_cases: list[dict[str, Any]] = []
    for name, ops in cases():
        ops_json = [op.model_dump(mode="json") for op in ops]
        out = apply_ops(df, ops_json)
        fixture_cases.append({"name": name, "ops": ops_json})
        expected_cases.append(
            {
                "name": name,
                "output": {"columns": columns_payload(out), "length": out.height},
            }
        )

    fixture = {"input": {"columns": columns_payload(df)}, "cases": fixture_cases}
    expected = {"cases": expected_cases}

    FIXTURES.mkdir(parents=True, exist_ok=True)
    for path, doc in (
        (FIXTURES / "prologue-fixture.json", fixture),
        (FIXTURES / "prologue-expected.json", expected),
    ):
        # allow_nan=False turns any surviving NaN/Inf into a build failure
        # instead of a `NaN` token no JSON parser would accept.
        path.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n")
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    print(f"{len(fixture_cases)} cases, input {df.height} rows x {len(df.columns)} columns")
    print(f"polars {pl.__version__}")


if __name__ == "__main__":
    main()
