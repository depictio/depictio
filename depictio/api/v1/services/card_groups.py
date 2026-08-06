"""Per-group card comparison ("compare groups in cards", issue #89).

When the viewer's "Compare groups in cards" toggle is on, ``bulk_compute_cards``
annotates each card's loaded frame with the selection-group column (the same
``group_annotation_expr`` the figure pipeline uses) and reduces the card's hero
aggregation once per group. Deliberately NOT built on ``compute_breakdown``:
breakdowns only know count/nunique/sum and cap at top-5, while a card's hero
aggregation can be mean/median/std/…, which is exactly what a comparison must
mirror.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import polars as pl

from depictio.api.v1.services.figure.groups import (
    GROUP_COLUMN,
    OTHER_LABEL,
    group_annotation_expr,
)

_VALUE_FIELD = "__value__"


def compute_group_compare(
    df: pl.DataFrame,
    group_defs: list[dict],
    column: str,
    aggregation: str,
    agg_expr_factory: Callable[[str, str], Any],
    coerce_result: Callable[[Any, str], Any],
    agg_value_fn: Callable[[Any, str], Any] | None = None,
    payload_fn: Callable[[pl.DataFrame], dict | None] | None = None,
    include_overall: bool = False,
) -> dict | None:
    """Reduce a card's hero aggregation per selection group.

    ``agg_expr_factory`` / ``coerce_result`` are the caller's ``_agg_expr`` /
    ``_coerce_agg_result`` (passed in to keep this service import-light and the
    card semantics in one place). ``agg_value_fn`` (the caller's ``_agg_value``,
    Series → scalar) is the fallback for aggregations with no expression form
    (``mode``): without it those return ``None`` — never an approximation.

    ``payload_fn`` (frame → dict | None) computes the per-group variant of the
    card's secondary layout over each group's partition — e.g. Tukey box stats
    or a threshold breakdown — and lands under a ``"payload"`` key on every
    entry (``None`` when the partition can't support it). Only present when a
    ``payload_fn`` is given, so chips-only responses keep their shape.

    ``include_overall`` adds an ``"overall"`` entry reduced over the WHOLE
    frame (all rows, grouped or not) — the "All" reference row the client can
    draw above the per-group rows.

    Result shape::

        {"aggregation": str,
         "groups": [{"name", "color", "value", "count"[, "payload"]}, ...],
         "other": {"value", "count"[, "payload"]} | None
         [, "overall": {"value", "count"[, "payload"]}]}

    Groups with no matching rows in this frame still appear (value ``None``,
    count 0) so the client's chip strip keeps one chip per group everywhere —
    but only for groups whose source column exists in the frame. A group made
    on another data collection's column is *omitted* rather than shown as
    "0 rows": its rows can't be told apart from ``Other`` here, and an empty
    chip would misread as "no matches".
    """
    if column not in df.columns:
        return None
    applicable = [g for g in group_defs if g["column_name"] in df.columns]
    if not applicable:
        return None
    expr = group_annotation_expr(applicable, df.columns, dict(df.schema))
    if expr is None:
        return None
    agg = agg_expr_factory(column, aggregation)
    if agg is None and agg_value_fn is None:
        return None

    # One annotation, then per-label partitions. Partitioning (rather than a
    # single group_by) is what lets payload_fn and the expressionless fallback
    # run over each group's rows; the frame was already materialised by the
    # caller, so this is one extra pass over resident data.
    annotated = df.lazy().with_columns(expr).collect()
    partitions: dict[str, pl.DataFrame] = {
        str(key[0] if isinstance(key, tuple) else key): part
        for key, part in annotated.partition_by(GROUP_COLUMN, as_dict=True).items()
    }

    def reduce_frame(part: pl.DataFrame) -> dict:
        if agg is not None:
            value = coerce_result(part.select(agg.alias(_VALUE_FIELD)).item(), aggregation)
        else:
            assert agg_value_fn is not None
            value = agg_value_fn(part[column], aggregation)
        out: dict = {"value": value, "count": part.height}
        if payload_fn is not None:
            out["payload"] = payload_fn(part)
        return out

    def entry(label: str) -> dict | None:
        part = partitions.get(label)
        return reduce_frame(part) if part is not None else None

    empty: dict = {"value": None, "count": 0}
    if payload_fn is not None:
        empty["payload"] = None
    groups_out = [
        {"name": g["name"], "color": g["color"], **(entry(g["name"]) or empty)} for g in applicable
    ]

    result = {"aggregation": aggregation, "groups": groups_out, "other": entry(OTHER_LABEL)}
    if include_overall:
        result["overall"] = reduce_frame(df)
    return result
