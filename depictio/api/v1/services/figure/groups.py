"""Server-side support for "color figures by selection groups".

The React viewer lets a user save selections (lasso / table rows / map) as
named, colored groups (see ``packages/depictio-react-core/src/selectionGroups.ts``).
When "Color by group" is on, the render request carries the group definitions
and the figure pipeline annotates every row with a synthetic categorical column
— first matching group wins, everything else labelled ``Other`` — which Plotly
Express then colors by.

Invariant: the annotation is applied AFTER the Delta load (``with_columns`` on
the loaded frame or on the scan returned by ``open_deltatable_scan``), never
inside ``load_deltatable_lite``. Every DataFrame cache tier keys on the load's
filter metadata only, so injecting the column post-load keeps a grouped and an
ungrouped request sharing the same cached frame *and* returning correct
results. Moving the annotation into the loader would require salting all three
cache-key schemes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import polars as pl

from depictio.api.v1.deltatables_utils import _categorical_predicate

GROUP_COLUMN = "__depictio_group__"
OTHER_LABEL = "Other"
# Neutral gray for unassigned rows: context, not a category of its own.
OTHER_COLOR = "#adb5bd"

# Caps mirror the client's (MAX_GROUP_VALUES in selectionGroups.ts) with server
# headroom — the request body is untrusted, so the server enforces its own.
MAX_GROUPS = 24
MAX_VALUES_PER_GROUP = 50_000
MAX_NAME_LENGTH = 80

# matplotlib tab10 — same palette as TAB10_PALETTE client-side, used when a
# group arrives without a (valid) color.
_TAB10 = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
)  # fmt: skip

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def sanitize_group_defs(raw: Any) -> list[dict]:
    """Validate untrusted group definitions from a request body.

    Returns ``[{"name": str, "column_name": str, "values": list[str],
    "color": str}]`` keeping only well-formed entries, deduplicating names
    (first occurrence wins — matching the first-match-wins annotation
    semantics), and enforcing size caps. Group values are only ever used as
    ``is_in`` literals via ``_categorical_predicate`` — they never reach an
    expression evaluator — so this shape check is the whole trust boundary.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    seen_names: set[str] = set()
    for entry in raw:
        if len(out) >= MAX_GROUPS:
            break
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        column = entry.get("column_name")
        values = entry.get("values")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(column, str) or not column.strip():
            continue
        if not isinstance(values, list) or not values:
            continue
        name = name.strip()[:MAX_NAME_LENGTH]
        # The reserved fallback label can't double as a group name — a group
        # literally called "Other" would merge with the unassigned rows.
        if name == OTHER_LABEL or name in seen_names:
            continue
        color = entry.get("color")
        if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
            color = _TAB10[len(out) % len(_TAB10)]
        out.append(
            {
                "name": name,
                "column_name": column.strip(),
                "values": [str(v) for v in values[:MAX_VALUES_PER_GROUP]],
                "color": color,
            }
        )
        seen_names.add(name)
    return out


def group_source_columns(groups: list[dict]) -> set[str]:
    """Real columns the group annotation reads — fold into the projection."""
    return {g["column_name"] for g in groups}


def group_annotation_expr(
    groups: list[dict],
    available_columns: Sequence[str],
    dtypes: Mapping[str, pl.DataType] | None = None,
) -> pl.Expr | None:
    """``when/then`` chain labelling each row with its group (or ``Other``).

    First matching group wins, in list order — a row in two groups takes the
    first one's label, which is deterministic and needs no configuration.
    Groups whose column is absent from the frame are skipped; when none apply
    (e.g. the figure's data collection simply doesn't carry the column) the
    caller gets ``None`` and renders ungrouped.

    Membership predicates reuse ``_categorical_predicate`` so stringified
    values match numeric columns and the bare-column form stays pushable when
    the expression lands on a LazyFrame scan.
    """
    available = set(available_columns)
    expr: Any = None
    for g in groups:
        column = g["column_name"]
        if column not in available:
            continue
        dtype = dtypes.get(column) if dtypes else None
        predicate = _categorical_predicate(column, g["values"], dtype)
        chain = pl.when(predicate) if expr is None else expr.when(predicate)
        expr = chain.then(pl.lit(g["name"]))
    if expr is None:
        return None
    return expr.otherwise(pl.lit(OTHER_LABEL)).alias(GROUP_COLUMN)


def apply_group_coloring_kwargs(dict_kwargs: dict, groups: list[dict]) -> dict:
    """Copy of ``dict_kwargs`` with color-by-group applied.

    Overrides any existing ``color`` — that is the point of the compare toggle,
    and the client flags it (``group_colored``) so the override is visible and
    reversible. The map/orders are real dicts: ``create_figure_from_data`` only
    json-parses *string* values for these params, dicts pass through.
    ``Other`` is forced last in the category order so groups keep their
    creation order in legends and grouped axes.
    """
    out = dict(dict_kwargs)
    out["color"] = GROUP_COLUMN
    color_map = {g["name"]: g["color"] for g in groups}
    color_map[OTHER_LABEL] = OTHER_COLOR
    out["color_discrete_map"] = color_map
    out["category_orders"] = {
        **(out.get("category_orders") if isinstance(out.get("category_orders"), dict) else {}),
        GROUP_COLUMN: [g["name"] for g in groups] + [OTHER_LABEL],
    }
    return out
