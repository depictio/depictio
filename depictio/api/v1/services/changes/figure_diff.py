"""Before/after of one figure: which points, bars or samples changed.

The "before" is the reader's baseline: the collection's Delta commit or
MultiQC report set at their last visit, drawn through the definition they saw.
The "after" is now. Three shapes, by what the chart draws:

- **points** (scatter, line, strip, scatter_3d): rows matched by a key column,
  so a point can be *added*, *removed* or *moved*. Without a usable key, rows
  are compared as (x, y) value pairs, which still tells added from removed.
- **groups** (bar, box, histogram, violin, ecdf, area, funnel): one value per
  group (x, and colour when there is one), the same reduction the chart draws:
  sum for bar/area/funnel, count for histogram/ecdf, median for box/violin.
- **samples** (MultiQC): the samples of the report set then and now.

Code-mode figures run arbitrary code over the frame, so nothing can say which
mark a row became: they answer ``supported: false``.
"""

from __future__ import annotations

from typing import Any

import polars as pl

POINT_KINDS = frozenset({"scatter", "line", "strip", "scatter_3d", "line_3d"})
GROUP_REDUCTION: dict[str, str] = {
    "bar": "sum",
    "area": "sum",
    "funnel": "sum",
    "histogram": "count",
    "ecdf": "count",
    "box": "median",
    "violin": "median",
}
#: Points listed per bucket. The overlay draws markers, not a table: past this
#: it is noise, and the counts still say how many there were.
MAX_POINTS = 5000
MAX_GROUPS = 500
_ID_NAMES = ("index_index", "id", "ID", "Id", "sample", "Sample", "sample_id", "sample_name")


def unsupported(reason: str) -> dict[str, Any]:
    return {"supported": False, "reason": reason}


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def pick_key_column(columns: list[str], component: dict[str, Any], avoid: set[str]) -> str | None:
    """A column that names a row: the figure's own selection or hover column
    first, then the usual id names, then an ``*_id`` column. Never an axis."""
    kwargs = component.get("dict_kwargs") or {}
    for cand in (component.get("selection_column"), kwargs.get("hover_name")):
        if cand and cand in columns and cand not in avoid:
            return cand
    for cand in _ID_NAMES:
        if cand in columns and cand not in avoid:
            return cand
    for col in columns:
        lower = col.lower()
        if col not in avoid and (lower.endswith("_id") or lower.endswith("_index")):
            return col
    return None


def _unique(df: pl.DataFrame, key: str) -> bool:
    return df.height == 0 or df.get_column(key).n_unique() == df.height


def point_diff(
    before: pl.DataFrame, after: pl.DataFrame, component: dict[str, Any]
) -> dict[str, Any]:
    kwargs = component.get("dict_kwargs") or {}
    x, y = kwargs.get("x"), kwargs.get("y")
    if not x or not y or x not in after.columns or y not in after.columns:
        return unsupported("The figure has no x and y columns to compare.")
    color = kwargs.get("color") if kwargs.get("color") in after.columns else None
    cols = [c for c in (x, y, color) if c]
    key = pick_key_column(list(after.columns), component, set(cols))
    if key and (key not in before.columns or not (_unique(before, key) and _unique(after, key))):
        key = None

    def rows(df: pl.DataFrame) -> list[dict[str, Any]]:
        keep = [c for c in ([key] if key else []) + cols if c in df.columns]
        return df.select(keep).head(MAX_POINTS * 4).to_dicts()

    def point(row: dict[str, Any], k: Any) -> dict[str, Any]:
        out = {"key": _str(k), "x": row.get(x), "y": row.get(y)}
        if color:
            out["color"] = row.get(color)
        return out

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    if key:
        then = {_str(r[key]): r for r in rows(before)}
        now = {_str(r[key]): r for r in rows(after)}
        for k, r in now.items():
            if k not in then:
                added.append(point(r, k))
            elif any(r.get(c) != then[k].get(c) for c in cols):
                changed.append({"key": k, "before": point(then[k], k), "after": point(r, k)})
        removed = [point(r, k) for k, r in then.items() if k not in now]
    else:
        # Multiset difference of value tuples: a moved point shows as one
        # removed and one added, which is what the eye sees anyway.
        def counts(df: pl.DataFrame) -> dict[tuple, list[dict[str, Any]]]:
            out: dict[tuple, list[dict[str, Any]]] = {}
            for r in rows(df):
                out.setdefault(tuple(_str(r.get(c)) for c in cols), []).append(r)
            return out

        then, now = counts(before), counts(after)
        for t, rs in now.items():
            extra = len(rs) - len(then.get(t, []))
            added.extend(point(r, None) for r in rs[: max(extra, 0)])
        for t, rs in then.items():
            extra = len(rs) - len(now.get(t, []))
            removed.extend(point(r, None) for r in rs[: max(extra, 0)])

    return {
        "supported": True,
        "shape": "points",
        "key_column": key,
        "x": x,
        "y": y,
        "color": color,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "before": before.height,
            "after": after.height,
        },
        "added": added[:MAX_POINTS],
        "removed": removed[:MAX_POINTS],
        "changed": changed[:MAX_POINTS],
        "truncated": max(len(added), len(removed), len(changed)) > MAX_POINTS,
    }


def _reduce(df: pl.DataFrame, by: list[str], value: str | None, how: str) -> dict[tuple, float]:
    if df.height == 0:
        return {}
    if how == "count" or not value or value not in df.columns:
        agg = pl.len().alias("v")
    elif how == "median":
        agg = pl.col(value).cast(pl.Float64, strict=False).median().alias("v")
    else:
        agg = pl.col(value).cast(pl.Float64, strict=False).sum().alias("v")
    out = df.group_by(by).agg(agg)
    return {
        tuple(_str(r[c]) for c in by): (float(r["v"]) if r["v"] is not None else None)
        for r in out.to_dicts()
    }


def group_diff(
    before: pl.DataFrame, after: pl.DataFrame, component: dict[str, Any], visu_type: str
) -> dict[str, Any]:
    kwargs = component.get("dict_kwargs") or {}
    how = GROUP_REDUCTION[visu_type]
    x, y = kwargs.get("x"), kwargs.get("y")
    # A box or violin with only y draws one group per colour (or a single box).
    group_axis = x if x in after.columns else None
    if visu_type in ("box", "violin") and group_axis is None and y not in after.columns:
        return unsupported("The figure has no column to compare.")
    if how in ("sum", "median") and (not y or y not in after.columns):
        if visu_type in ("bar", "area", "funnel"):
            how = "count"  # px draws a bar of row counts without y
        else:
            return unsupported("The figure has no value column to compare.")
    if visu_type in ("box", "violin") and x and x not in after.columns:
        group_axis = None
    color = kwargs.get("color") if kwargs.get("color") in after.columns else None
    # dict.fromkeys: x and colour are often the same column (a box per variety,
    # coloured by variety), and polars refuses a duplicate group key.
    by = list(dict.fromkeys(c for c in (group_axis, color) if c))
    value = y if how != "count" else None

    if by:
        then, now = _reduce(before, by, value, how), _reduce(after, by, value, how)
    else:
        then = {
            (): _reduce(before.with_columns(pl.lit("").alias("_all")), ["_all"], value, how).get(
                ("",)
            )
        }
        now = {
            (): _reduce(after.with_columns(pl.lit("").alias("_all")), ["_all"], value, how).get(
                ("",)
            )
        }

    groups: list[dict[str, Any]] = []
    for k in sorted(set(then) | set(now)):
        b, a = then.get(k), now.get(k)
        if k not in then:
            status = "added"
        elif k not in now:
            status = "removed"
        elif b != a:
            status = "changed"
        else:
            status = "same"
        groups.append({"group": dict(zip(by, k)), "before": b, "after": a, "status": status})
    changed = [g for g in groups if g["status"] != "same"]
    return {
        "supported": True,
        "shape": "groups",
        "group_columns": by,
        "x": group_axis,
        "color": color,
        "metric": how,
        "value_column": value,
        "counts": {
            s: sum(1 for g in groups if g["status"] == s)
            for s in ("added", "removed", "changed", "same")
        },
        "groups": changed[:MAX_GROUPS],
        "truncated": len(changed) > MAX_GROUPS,
    }


def frame_diff(
    before: pl.DataFrame, after: pl.DataFrame, component: dict[str, Any]
) -> dict[str, Any]:
    if component.get("mode") == "code":
        return unsupported("A code-mode figure cannot be compared point by point.")
    visu_type = str(component.get("visu_type") or "scatter").lower()
    if visu_type in POINT_KINDS:
        return point_diff(before, after, component)
    if visu_type in GROUP_REDUCTION:
        return group_diff(before, after, component, visu_type)
    return unsupported(f"{visu_type} figures cannot be compared yet.")


def sample_diff(before: set[str], after: set[str]) -> dict[str, Any]:
    added = sorted(after - before)
    removed = sorted(before - after)
    return {
        "supported": True,
        "shape": "samples",
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "before": len(before),
            "after": len(after),
        },
        "added": added[:MAX_POINTS],
        "removed": removed[:MAX_POINTS],
        "truncated": max(len(added), len(removed)) > MAX_POINTS,
    }
