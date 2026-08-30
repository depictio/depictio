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
# The name code-mode figures spread to opt into grouping:
#   fig = px.scatter(df.to_pandas(), x=..., y=..., **depictio_group_kwargs)
# It is bound to the output of the same helper UI mode applies, so "Split"
# means the same thing on both paths. Always defined in code mode, empty
# whenever grouping is off, so spreading it is safe unconditionally.
CODE_GROUP_KWARGS = "depictio_group_kwargs"
# Its companion, for a code figure that aggregates before plotting. Spread into
# the grouping keys so the annotation survives the aggregation:
#   df.group_by([*depictio_group_by, "Phylum"]).agg(...)
# Without it a `group_by` silently drops `__depictio_group__` and the px call
# below is then handed a column its frame no longer has. Empty list whenever
# grouping is off, so the same line works ungrouped.
CODE_GROUP_BY = "depictio_group_by"
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


MAX_COLOR_MAP_ENTRIES = 200
MAX_COLUMN_NAME_LENGTH = 200


def sanitize_color_by_column(raw: Any) -> dict | None:
    """Validate the untrusted global "color by column" request payload.

    Returns ``{"column_name": str, "color_map": dict[str, str]}`` (the map may
    be empty) or ``None``. The column name is only ever compared against the
    frame's real schema and passed to px as ``color=`` — it never reaches an
    expression evaluator — so, as with group defs, this shape check is the
    whole trust boundary.
    """
    if not isinstance(raw, dict):
        return None
    column = raw.get("column_name")
    if not isinstance(column, str) or not column.strip():
        return None
    column = column.strip()
    if len(column) > MAX_COLUMN_NAME_LENGTH:
        return None
    color_map: dict[str, str] = {}
    raw_map = raw.get("color_map")
    if isinstance(raw_map, dict):
        for key, value in raw_map.items():
            if len(color_map) >= MAX_COLOR_MAP_ENTRIES:
                break
            if isinstance(key, str) and isinstance(value, str) and _HEX_COLOR_RE.match(value):
                color_map[key] = value
    return {"column_name": column, "color_map": color_map}


def apply_column_coloring_kwargs(dict_kwargs: dict, column: str, color_map: dict) -> dict:
    """Copy of ``dict_kwargs`` with the global color-by-column override applied.

    Overrides any existing ``color`` — same contract as the group override, and
    the client surfaces it via the ``column_colored`` response flag. When the
    client sent a stable color map (built from the column's unfiltered
    universe), pin both the colors and the category order to it so categories
    keep their hue and legend position as filters narrow the data.
    """
    out = dict(dict_kwargs)
    out["color"] = column
    if color_map:
        out["color_discrete_map"] = dict(color_map)
        out["category_orders"] = {
            **(out.get("category_orders") if isinstance(out.get("category_orders"), dict) else {}),
            column: list(color_map),
        }
    else:
        # No stable map from the client: drop any authored map too — it is
        # keyed to the figure's own color column's categories, and overlapping
        # values would repaint the override column with unrelated colors.
        out.pop("color_discrete_map", None)
    return out


def apply_group_coloring_kwargs(
    dict_kwargs: dict, groups: list[dict], include_other: bool = True
) -> dict:
    """Copy of ``dict_kwargs`` with color-by-group applied.

    Overrides any existing ``color`` — that is the point of the compare toggle,
    and the client flags it (``group_colored``) so the override is visible and
    reversible. The map/orders are real dicts: ``create_figure_from_data`` only
    json-parses *string* values for these params, dicts pass through.
    ``Other`` is forced last in the category order so groups keep their
    creation order in legends and grouped axes.

    ``include_other=False`` must also drop the label from ``category_orders``,
    not just rely on the caller filtering the rows: px keeps every listed
    category even when absent from the data, so a leftover entry draws an
    empty gray legend slot — and an empty panel in Split (facet) mode.
    """
    out = dict(dict_kwargs)
    out["color"] = GROUP_COLUMN
    color_map = {g["name"]: g["color"] for g in groups}
    if include_other:
        color_map[OTHER_LABEL] = OTHER_COLOR
    out["color_discrete_map"] = color_map
    out["category_orders"] = {
        **(out.get("category_orders") if isinstance(out.get("category_orders"), dict) else {}),
        GROUP_COLUMN: [g["name"] for g in groups] + ([OTHER_LABEL] if include_other else []),
    }
    return out


# Facet display ("Split" mode): one panel per category, wrapped so a dashboard
# tile doesn't turn into a single unreadable row of panels.
FACET_COL_WRAP = 4
# Column mode can meet high-cardinality columns (the client's picker caps at
# 50 uniques); beyond this many panels a split is unreadable — fall back to
# color-only rather than render confetti.
MAX_FACET_CATEGORIES = 12


def sanitize_grouping_display(raw: Any) -> str:
    """``"facet"`` or the default ``"color"`` — the only two display modes."""
    return "facet" if raw == "facet" else "color"


def apply_facet_kwargs(dict_kwargs: dict, column: str) -> dict:
    """Copy of ``dict_kwargs`` with the "Split" display applied on ``column``.

    Layered on top of the coloring override (callers apply that first): the
    panels keep their category colors, which is what makes each facet
    self-identifying. Overrides any authored ``facet_col`` — same visible,
    reversible contract as the color override — and drops an authored
    ``facet_col_wrap`` in favor of ours, but leaves ``facet_row`` alone so a
    row-faceted figure becomes a grid. ``create_figure_from_data`` filters
    kwargs against the px signature, so visu types without facet support
    silently keep the color-only rendering.
    """
    out = dict(dict_kwargs)
    out["facet_col"] = column
    out["facet_col_wrap"] = FACET_COL_WRAP
    return out


def tidy_facet_layout(fig: Any) -> Any:
    """Make a faceted figure readable inside a dashboard tile.

    Plotly Express lays facets out for a full-page notebook figure, and two of
    its defaults fail badly in a tile:

    * Row labels are drawn rotated 90 degrees against the right-hand border,
      which at tile size reads as a smudge. They move above their band, level.
    * Every facet label is prefixed with the column it came from
      (``__depictio_group__=North``), which is machinery, not information.
    * Rotated tick labels are clipped, because the margin was fixed before the
      labels were known. ``automargin`` measures them instead of guessing.

    Applied to whatever figure the render task ends up with, so a code figure
    that spread the same kwargs is tidied identically to a UI one. Detection is
    on shape alone — whether the axes carry more than one band — so nothing here
    knows what is being plotted, and a figure that facets on its own is tidied
    whether or not the request asked for a split.
    """
    layout = getattr(fig, "layout", None)
    if layout is None:
        return fig

    # Every band, as (low, high) in paper coordinates, read back off the axes.
    # A dual-axis figure stacks two axes on the same full-width domain, so
    # counting *distinct* domains is what separates faceting from that.
    row_bands: list[tuple[float, float]] = []
    col_bands: set[tuple[float, float]] = set()
    for name, axis in layout.to_plotly_json().items():
        if not isinstance(axis, dict):
            continue
        domain = axis.get("domain")
        if not (isinstance(domain, (list, tuple)) and len(domain) == 2):
            continue
        band = (float(domain[0]), float(domain[1]))
        if name.startswith("yaxis"):
            row_bands.append(band)
        elif name.startswith("xaxis"):
            col_bands.add(band)
    row_bands.sort()

    # Not faceted: leave it alone. `automargin` rewrites the whole figure's
    # margins, which has no business firing on a plain single-panel chart.
    if len(set(row_bands)) < 2 and len(col_bands) < 2:
        return fig

    # Let Plotly measure the tick labels rather than living with a margin
    # chosen before they existed. This is what un-clips a rotated axis, and what
    # gives a long categorical label the width it needs.
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)

    def band_top(y: float) -> float:
        """Top of the row band this label sits against, in paper coords."""
        for low, high in row_bands:
            if low - 0.01 <= y <= high + 0.01:
                return high
        return y

    for annotation in layout.annotations or ():
        text = getattr(annotation, "text", None)
        if not isinstance(text, str):
            continue
        # The two defects are independent, and a figure that already stripped
        # its own prefix still needs laying flat — so test for each separately
        # rather than making the prefix the gate for both.
        prefixed = "=" in text
        rotated = getattr(annotation, "textangle", 0) in (90, -90)
        if not (prefixed or rotated):
            continue
        if prefixed:
            # px writes "<column>=<value>"; only the value is worth the space.
            annotation.update(text=text.split("=", 1)[-1])
        annotation.update(font={"size": 12})
        if rotated:
            annotation.update(
                textangle=0,
                x=0,
                xanchor="left",
                yanchor="bottom",
                y=band_top(getattr(annotation, "y", 0.0)),
            )
    return fig
