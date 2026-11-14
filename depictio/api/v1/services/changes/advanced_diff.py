"""Before/after of an advanced visualisation, row by row.

Every advanced viz config binds roles to columns through ``*_col`` fields.
One of them names the row (``feature_id_col``, ``sample_id_col``,
``region_id_col``, ...): rows are matched on it, and the other bound columns
are the values compared. A kind with no id role is compared on value tuples,
like a figure without a key.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import polars as pl
from bson import ObjectId

from depictio.api.v1.services.changes.figure_diff import MAX_POINTS, unsupported
from depictio.models.models.reader_marks import DcSeenState

#: Id roles, most specific first.
_ID_ROLES = (
    "feature_id_col",
    "sample_id_col",
    "region_id_col",
    "fusion_id_col",
    "variant_id_col",
    "cell_id_col",
    "id_col",
)


def _bound_columns(config: dict[str, Any]) -> dict[str, str]:
    return {
        role: col
        for role, col in config.items()
        if role.endswith("_col") and isinstance(col, str) and col
    }


def key_role(config: dict[str, Any]) -> tuple[str | None, str | None]:
    bound = _bound_columns(config)
    for role in _ID_ROLES:
        if role in bound:
            return role, bound[role]
    for role, col in bound.items():
        if role.endswith("_id_col"):
            return role, col
    return None, None


def rows_diff(
    before: pl.DataFrame, after: pl.DataFrame, key: str | None, values: list[str]
) -> dict[str, Any]:
    if key and (
        key not in before.columns
        or key not in after.columns
        or before.get_column(key).n_unique() != before.height
        or after.get_column(key).n_unique() != after.height
    ):
        # A long table repeats its id: its rows are compared as value tuples,
        # the id among them, or two samples with equal values would match.
        key = None
    values = [c for c in values if c in after.columns and c != key]

    def as_rows(df: pl.DataFrame) -> list[dict[str, Any]]:
        keep = [c for c in ([key] if key else []) + values if c in df.columns]
        return df.select(keep).to_dicts() if keep else []

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    if key:
        then = {str(r[key]): r for r in as_rows(before)}
        now = {str(r[key]): r for r in as_rows(after)}
        added = [{"key": k, "values": r} for k, r in now.items() if k not in then]
        removed = [{"key": k, "values": r} for k, r in then.items() if k not in now]
        changed = [
            {"key": k, "before": then[k], "after": r}
            for k, r in now.items()
            if k in then and any(r.get(c) != then[k].get(c) for c in values)
        ]
        n_added, n_removed = len(added), len(removed)
    elif values:
        try:
            n_added, added = _unmatched(after, before, values)
            n_removed, removed = _unmatched(before, after, values)
        except pl.exceptions.PolarsError:
            # A column polars cannot render as text (a list, a struct).
            added, removed = _unmatched_in_python(as_rows(before), as_rows(after), values)
            n_added, n_removed = len(added), len(removed)
    else:
        n_added = n_removed = 0
    return {
        "supported": True,
        "shape": "rows",
        "key_column": key,
        "value_columns": values,
        "counts": {
            "added": n_added,
            "removed": n_removed,
            "changed": len(changed),
            "before": before.height,
            "after": after.height,
        },
        "added": added[:MAX_POINTS],
        "removed": removed[:MAX_POINTS],
        "changed": changed[:MAX_POINTS],
        "truncated": max(n_added, n_removed, len(changed)) > MAX_POINTS,
    }


_ROW = "__depictio_row"
_OCCURRENCE = "__depictio_occurrence"


def _unmatched(
    left: pl.DataFrame, right: pl.DataFrame, values: list[str]
) -> tuple[int, list[dict[str, Any]]]:
    """Rows of ``left`` no equal row of ``right`` pairs with, in ``left``'s order.

    A multiset difference: a row repeated three times against twice leaves
    its last occurrence. Values compare as text, as the rows are shown, and
    only the first ``MAX_POINTS`` leave polars, so a 700k row table is never
    turned into Python objects whole.
    """

    def keyed(df: pl.DataFrame) -> pl.DataFrame:
        text = df.select(
            pl.col(c).cast(pl.String) if c in df.columns else pl.lit(None, pl.String).alias(c)
            for c in values
        )
        return text.with_columns(pl.int_range(pl.len()).over(values).alias(_OCCURRENCE))

    rest = (
        keyed(left)
        .with_row_index(_ROW)
        .join(
            keyed(right),
            on=[*values, _OCCURRENCE],
            how="anti",
            nulls_equal=True,
            maintain_order="left",
        )
    )
    shown = rest.get_column(_ROW).head(MAX_POINTS)
    present = [c for c in values if c in left.columns]
    rows = left.select(present)[shown].to_dicts() if present else [{} for _ in shown]
    return rest.height, [{"key": None, "values": {c: str(r.get(c)) for c in values}} for r in rows]


def _unmatched_in_python(
    then: list[dict[str, Any]], now: list[dict[str, Any]], values: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The same difference by counts, for values polars cannot cast to text."""
    then_rows = [tuple(str(r.get(c)) for c in values) for r in then]
    now_rows = [tuple(str(r.get(c)) for c in values) for r in now]
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    unmatched = Counter(then_rows)
    for t in now_rows:
        if unmatched[t] > 0:
            unmatched[t] -= 1
        else:
            added.append({"key": None, "values": dict(zip(values, t))})
    matched = Counter(then_rows) - unmatched
    for t in then_rows:
        if matched[t] > 0:
            matched[t] -= 1
        else:
            removed.append({"key": None, "values": dict(zip(values, t))})
    return added, removed


def advanced_viz_diff(
    component: dict[str, Any],
    dc_id: str,
    before: DcSeenState,
    now: DcSeenState,
    filters: list[dict[str, Any]],
) -> dict[str, Any]:
    if before.delta_version is None or now.delta_version is None:
        return unsupported("This collection keeps no version history.")
    config = component.get("config") or {}
    _role, key = key_role(config)
    columns = sorted(set(_bound_columns(config).values()))
    if not columns:
        return unsupported("The visualisation binds no columns to compare.")
    if before.delta_version == now.delta_version:
        return {**rows_diff(pl.DataFrame(), pl.DataFrame(), key, columns), "unchanged": True}

    from depictio.api.v1.deltatables_utils import load_deltatable_lite
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _build_filter_metadata

    metadata = _build_filter_metadata(filters or [])
    wf_id = ObjectId(str(component.get("wf_id")))

    def frame(version: int) -> pl.DataFrame:
        df = load_deltatable_lite(
            wf_id, dc_id, metadata=metadata, select_columns=columns, delta_version=version
        )
        return df.select([c for c in columns if c in df.columns])

    try:
        then, current = frame(before.delta_version), frame(now.delta_version)
    except Exception as exc:
        return unsupported(f"The data could not be read: {exc}")
    return {
        **rows_diff(then, current, key, columns),
        "viz_kind": component.get("viz_kind"),
        "delta_from": before.delta_version,
        "delta_to": now.delta_version,
    }
