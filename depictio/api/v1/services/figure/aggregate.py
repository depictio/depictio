"""Scan-level aggregation for reducing visualisations.

Plotly Express takes a *frame* and reduces it client-of-Polars-side: `px.box`
receives every row and ships every raw value inside the trace, so a 28 M-row box
plot means a 28 M-row collect plus tens of MB of trace JSON. But a box plot is
seven numbers per group, a histogram is one count per bin, a density heatmap is
a count per cell — all of which Polars can compute as a pushdown over parquet
without materialising a single row.

This module plans that reduction from the builder's ``dict_kwargs`` and executes
it against a lazy Delta scan (``deltatables_utils.open_deltatable_scan``).

Design rules:

- **Exactness first.** ``box`` / ``histogram`` / ``density_*`` / ``bar`` /
  ``funnel`` are computed exactly — the aggregate is the same number px would
  have arrived at, just reached without collecting. Only ``violin`` and ``ecdf``
  are approximate (they need the distribution's shape, which has no small exact
  summary), and both say so via ``render_stats["sampled"]``.
- **Bail loudly rather than approximate silently.** ``plan_aggregation`` returns
  ``None`` for anything it can't reproduce faithfully, and the caller falls back
  to the full-load px path. A wrong figure is far worse than a slow one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import plotly.express as px
import plotly.graph_objects as go
import polars as pl

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.multiqc.themes import get_theme_template

# Reducing visualisations this module can serve. Everything else (the scatter
# family, line/area) is a mark-per-row plot handled by sampling in figure_builder.
# ``funnel`` is deliberately absent: its px signature puts the *value* on x and
# the stage on y (inverted relative to bar), and a funnel's input is a handful of
# stages already — there is no frame to reduce, so it would be risk without gain.
AGGREGATED_VISU = frozenset(
    {"box", "histogram", "density_heatmap", "density_contour", "bar", "violin", "ecdf"}
)

# How the plan is executed:
#   "reduce"    — exact Polars aggregate → graph_objects trace (no px involved)
#   "groupby"   — exact Polars group-by → px on the tiny aggregated frame
#   "subsample" — scan-level uniform subsample → px on the sample (approximate)
_MODE_BY_VISU = {
    "box": "reduce",
    "histogram": "reduce",
    "density_heatmap": "reduce",
    "density_contour": "reduce",
    "bar": "groupby",
    "violin": "subsample",
    "ecdf": "subsample",
}

# Kwargs that change what the marks *mean*, in ways an aggregate can't reproduce.
# Presence of any of these aborts planning. Being conservative here is the whole
# safety story: an unrecognised kwarg must never be silently dropped.
_UNSUPPORTED_KWARGS = frozenset(
    {
        # Extra traces derived from the raw rows.
        "marginal", "marginal_x", "marginal_y", "trendline", "trendline_options",
        "trendline_scope", "trendline_color_override",
        # Per-row identity we'd have to carry through the aggregate.
        "hover_data", "custom_data", "hover_name", "text", "base",
        "error_x", "error_y", "error_z", "size", "symbol", "pattern_shape",
        "line_dash", "line_group", "dimensions",
        # Per-frame animation needs the frame column as a group key *and* an
        # ordering; not worth the complexity for the win.
        "animation_frame", "animation_group",
        # Alternate reductions / layouts we don't reimplement.
        "histfunc", "histnorm", "cumulative", "orientation", "barnorm", "groupnorm",
        "ecdfnorm", "ecdfmode",
    }
)  # fmt: skip

# Column-role kwargs the plan understands. Anything else that names a column
# would be dropped by the aggregate, so it lives in _UNSUPPORTED_KWARGS above.
_ROLE_KWARGS = frozenset({"x", "y", "z", "color", "facet_row", "facet_col"})

# Styling kwargs that survive the aggregate untouched (they never reference a
# column). Passed through to px, or onto the layout for the graph_objects paths.
_STYLE_PASSTHROUGH = frozenset(
    {
        "title", "labels", "template", "color_discrete_sequence", "color_discrete_map",
        "color_continuous_scale", "range_color", "category_orders", "log_x", "log_y",
        "range_x", "range_y", "barmode", "boxmode", "violinmode", "points", "notched",
        "height", "width", "opacity", "nbins", "nbinsx", "nbinsy", "text_auto",
    }
)  # fmt: skip

# Default bin counts when the user didn't pick one. px lets Plotly choose in the
# browser; we must choose server-side because we're the one binning.
_DEFAULT_NBINS = 40
_DEFAULT_NBINS_2D = 60

# Upper bound on distinct groups an exact reduction may produce. A group-by on an
# accidentally-high-cardinality column (an ID) would otherwise turn "aggregate to
# something small" into "materialise millions of groups" — the exact failure mode
# this module exists to prevent. Above it we bail to the px path, which at least
# applies its own row cap.
_MAX_GROUPS = 5_000


@dataclass
class AggPlan:
    """A planned reduction: which columns play which role, and how to execute."""

    visu_type: str
    mode: str
    x: str | None = None
    y: str | None = None
    color: str | None = None
    facet_row: str | None = None
    facet_col: str | None = None
    style: dict[str, Any] = field(default_factory=dict)

    @property
    def group_keys(self) -> list[str]:
        """Columns the aggregate groups by, in trace-construction order."""
        keys = [self.x, self.color, self.facet_row, self.facet_col]
        seen: list[str] = []
        for k in keys:
            if k and k not in seen:
                seen.append(k)
        return seen

    @property
    def needed_columns(self) -> list[str]:
        cols = self.group_keys + [c for c in (self.y, self.x) if c]
        seen: list[str] = []
        for c in cols:
            if c not in seen:
                seen.append(c)
        return seen


def plan_aggregation(visu_type: str, dict_kwargs: dict) -> AggPlan | None:
    """Plan a scan-level reduction, or ``None`` if the figure must go through px.

    ``None`` is returned for: a visu type we don't reduce, a non-dict spec, any
    kwarg in ``_UNSUPPORTED_KWARGS``, a column role whose value isn't a plain
    column name, a missing required role, or faceting on a graph_objects path
    (px builds facet subplots for us; hand-rolling them isn't worth it).
    """
    if not isinstance(dict_kwargs, dict):
        return None
    visu = (visu_type or "").lower()
    if visu not in AGGREGATED_VISU:
        return None

    mode = _MODE_BY_VISU[visu]

    style: dict[str, Any] = {}
    roles: dict[str, str | None] = {}
    for key, value in dict_kwargs.items():
        if value is None or value == "" or value == []:
            continue
        if key in _UNSUPPORTED_KWARGS:
            logger.debug(f"plan_aggregation: {visu} not planned — unsupported kwarg {key!r}")
            return None
        if key in _ROLE_KWARGS:
            if not isinstance(value, str):
                logger.debug(f"plan_aggregation: {visu} not planned — {key!r} is not a column name")
                return None
            roles[key] = value
        elif key in _STYLE_PASSTHROUGH:
            style[key] = value
        else:
            # Unknown key: it may well name a column. Refuse rather than guess.
            logger.debug(f"plan_aggregation: {visu} not planned — unrecognised kwarg {key!r}")
            return None

    plan = AggPlan(
        visu_type=visu,
        mode=mode,
        x=roles.get("x"),
        y=roles.get("y"),
        color=roles.get("color"),
        facet_row=roles.get("facet_row"),
        facet_col=roles.get("facet_col"),
        style=style,
    )

    # graph_objects paths build their own traces and have no subplot machinery.
    if mode == "reduce" and (plan.facet_row or plan.facet_col):
        logger.debug(f"plan_aggregation: {visu} not planned — faceting needs the px path")
        return None

    # Required roles per type.
    if visu in ("box", "violin") and not plan.y:
        return None
    if visu in ("histogram", "ecdf") and not plan.x:
        return None
    if visu in ("density_heatmap", "density_contour") and not (plan.x and plan.y):
        return None
    if visu == "bar" and not plan.x:
        return None

    return plan


def build_aggregated_figure(
    scan: pl.LazyFrame,
    plan: AggPlan,
    theme: str = "light",
    render_stats: dict | None = None,
) -> go.Figure | None:
    """Execute ``plan`` against ``scan`` and return the figure.

    Returns ``None`` when the reduction turns out not to be viable after looking
    at the data (missing column, cardinality blow-up); the caller then falls back
    to the px path. Never raises for data reasons — a fallback is always better
    than a failed render.
    """
    from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates

    ensure_mantine_templates()
    template = get_theme_template(theme)

    try:
        available = set(scan.collect_schema().names())
    except Exception as e:
        logger.warning(f"build_aggregated_figure: schema read failed: {e}")
        return None

    missing = [c for c in plan.needed_columns if c not in available]
    if missing:
        logger.debug(f"build_aggregated_figure: columns {missing} absent — falling back")
        return None

    try:
        if plan.mode == "reduce":
            fig = _build_reduce(scan, plan, render_stats)
        elif plan.mode == "groupby":
            fig = _build_groupby(scan, plan, template, render_stats)
        else:
            fig = _build_subsample(scan, plan, template, render_stats)
    except Exception as e:
        logger.warning(
            f"build_aggregated_figure: {plan.visu_type} aggregation failed "
            f"({type(e).__name__}: {e}) — falling back to the full-load path"
        )
        return None

    if fig is None:
        return None

    if plan.mode == "reduce":
        # px applies the template itself; the graph_objects paths must do it here.
        fig.update_layout(template=template, title=plan.style.get("title"))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 50, "r": 20, "t": 40, "b": 40},
        uirevision="persistent",
    )
    if render_stats is not None:
        render_stats["aggregated"] = True
    return fig


# --------------------------------------------------------------------------- #
# Exact reductions → graph_objects
# --------------------------------------------------------------------------- #


def _build_reduce(scan: pl.LazyFrame, plan: AggPlan, render_stats: dict | None) -> go.Figure | None:
    if plan.visu_type == "box":
        return _build_box(scan, plan, render_stats)
    if plan.visu_type == "histogram":
        return _build_histogram(scan, plan, render_stats)
    return _build_density(scan, plan, render_stats)


def _build_box(scan: pl.LazyFrame, plan: AggPlan, render_stats: dict | None) -> go.Figure | None:
    """Box plot from precomputed quartiles.

    Plotly accepts the five-number summary directly (``q1``/``median``/``q3``/
    ``lowerfence``/``upperfence``), which is the whole reason this is cheap: the
    trace carries seven numbers per box instead of every underlying value.

    Fences follow Tukey (1.5·IQR) clipped to the observed min/max, matching what
    px draws for ``boxpoints=False``. Outlier markers are deliberately not
    emitted — they are per-row data, and re-introducing them would re-introduce
    the payload this path exists to avoid. Load-All still shows the exact px box.
    """
    keys = [k for k in (plan.x, plan.color) if k]
    y = plan.y
    assert y is not None  # guaranteed by plan_aggregation

    # ``interpolation="linear"`` is required, not cosmetic: Polars defaults to
    # "nearest", which snaps each quartile to an actual data point and would put
    # the box edges in a slightly different place than px (and than the card
    # path's ``_agg_value``, which also asks for linear). Same figure, two
    # quartile conventions, is exactly the kind of drift this path must not add.
    agg_exprs = [
        pl.col(y).quantile(0.25, interpolation="linear").alias("_q1"),
        pl.col(y).median().alias("_med"),
        pl.col(y).quantile(0.75, interpolation="linear").alias("_q3"),
        pl.col(y).min().alias("_min"),
        pl.col(y).max().alias("_max"),
        pl.col(y).mean().alias("_mean"),
        pl.len().alias("_n"),
    ]
    stats = (
        scan.group_by(keys).agg(agg_exprs).collect() if keys else scan.select(agg_exprs).collect()
    )
    if stats.height == 0:
        return None
    if stats.height > _MAX_GROUPS:
        logger.info(f"_build_box: {stats.height} groups exceeds cap {_MAX_GROUPS} — falling back")
        return None

    stats = stats.with_columns(
        (pl.col("_q3") - pl.col("_q1")).alias("_iqr"),
    ).with_columns(
        pl.max_horizontal(pl.col("_q1") - 1.5 * pl.col("_iqr"), pl.col("_min")).alias("_lf"),
        pl.min_horizontal(pl.col("_q3") + 1.5 * pl.col("_iqr"), pl.col("_max")).alias("_uf"),
    )
    if plan.x:
        stats = stats.sort(plan.x, nulls_last=True)

    fig = go.Figure()
    # One trace per colour value so the legend and grouping match px.box.
    groups = (
        stats.partition_by(plan.color, as_dict=True, include_key=True)
        if plan.color
        else {(None,): stats}
    )
    for key, part in groups.items():
        name = str(key[0]) if isinstance(key, tuple) else str(key)
        fig.add_trace(
            go.Box(
                x=part[plan.x].to_list() if plan.x else None,
                q1=part["_q1"].to_list(),
                median=part["_med"].to_list(),
                q3=part["_q3"].to_list(),
                lowerfence=part["_lf"].to_list(),
                upperfence=part["_uf"].to_list(),
                mean=part["_mean"].to_list(),
                name=name if plan.color else (plan.y or ""),
                boxpoints=False,
                customdata=part["_n"].to_list(),
                hovertemplate="n=%{customdata}<extra></extra>",
            )
        )
    if plan.color:
        fig.update_layout(boxmode=plan.style.get("boxmode", "group"), legend_title_text=plan.color)
    fig.update_layout(
        xaxis_title=plan.x or "",
        yaxis_title=plan.y or "",
    )
    if render_stats is not None:
        render_stats["rows_displayed"] = stats.height
        render_stats["sampled"] = False
    return fig


def _build_histogram(
    scan: pl.LazyFrame, plan: AggPlan, render_stats: dict | None
) -> go.Figure | None:
    """Exact histogram: bin edges from a min/max pushdown, counts from a group-by.

    Emitted as ``go.Bar`` with zero gap rather than ``go.Histogram`` — the latter
    would want the raw values again, defeating the purpose.
    """
    x = plan.x
    assert x is not None
    nbins = int(plan.style.get("nbins") or plan.style.get("nbinsx") or _DEFAULT_NBINS)
    nbins = max(1, min(nbins, 1000))

    bounds = scan.select(
        pl.col(x).min().alias("lo"), pl.col(x).max().alias("hi"), pl.len().alias("n")
    ).collect()
    lo, hi, total = bounds["lo"][0], bounds["hi"][0], bounds["n"][0]
    if lo is None or hi is None or total == 0:
        return None
    if hi == lo:
        # Degenerate: a single value. One bin, width 1, centred on it.
        lo, hi = lo - 0.5, hi + 0.5
    width = (hi - lo) / nbins

    keys = ["_bin"] + ([plan.color] if plan.color else [])
    counts = (
        scan.with_columns(
            ((pl.col(x) - lo) / width).floor().cast(pl.Int64).clip(0, nbins - 1).alias("_bin")
        )
        .group_by(keys)
        .agg(pl.len().alias("_count"))
        .collect()
        .sort("_bin")
    )
    if counts.height == 0:
        return None

    fig = go.Figure()
    groups = (
        counts.partition_by(plan.color, as_dict=True, include_key=True)
        if plan.color
        else {(None,): counts}
    )
    # Bin centres for the *dense* 0..nbins-1 range. A group-by only returns bins
    # that got at least one row, so an empty bin would otherwise vanish and the
    # bars either side would sit adjacent — reading as a continuous distribution
    # where there is actually a gap. Reindex so every bin is present, count 0.
    centres = [lo + (b + 0.5) * width for b in range(nbins)]
    for key, part in groups.items():
        name = str(key[0]) if isinstance(key, tuple) else str(key)
        dense = [0] * nbins
        for b, c in zip(part["_bin"], part["_count"]):
            dense[b] = c
        fig.add_trace(
            go.Bar(
                x=centres,
                y=dense,
                name=name if plan.color else (x or ""),
                width=width,
            )
        )
    fig.update_layout(
        bargap=0,
        barmode=plan.style.get("barmode", "stack" if plan.color else "relative"),
        xaxis_title=x,
        yaxis_title="count",
    )
    if plan.color:
        fig.update_layout(legend_title_text=plan.color)
    if render_stats is not None:
        render_stats["rows_displayed"] = counts.height
        render_stats["rows_scanned"] = int(total)
        render_stats["sampled"] = False
    return fig


def _build_density(
    scan: pl.LazyFrame, plan: AggPlan, render_stats: dict | None
) -> go.Figure | None:
    """2-D bin counts → heatmap / contour. Exact, and the payload is the grid."""
    x, y = plan.x, plan.y
    assert x is not None and y is not None
    nx = max(1, min(int(plan.style.get("nbinsx") or _DEFAULT_NBINS_2D), 500))
    ny = max(1, min(int(plan.style.get("nbinsy") or _DEFAULT_NBINS_2D), 500))

    bounds = scan.select(
        pl.col(x).min().alias("xlo"),
        pl.col(x).max().alias("xhi"),
        pl.col(y).min().alias("ylo"),
        pl.col(y).max().alias("yhi"),
    ).collect()
    xlo, xhi, ylo, yhi = (bounds[c][0] for c in ("xlo", "xhi", "ylo", "yhi"))
    if None in (xlo, xhi, ylo, yhi):
        return None
    if xhi == xlo:
        xlo, xhi = xlo - 0.5, xhi + 0.5
    if yhi == ylo:
        ylo, yhi = ylo - 0.5, yhi + 0.5
    wx, wy = (xhi - xlo) / nx, (yhi - ylo) / ny

    cells = (
        scan.with_columns(
            ((pl.col(x) - xlo) / wx).floor().cast(pl.Int64).clip(0, nx - 1).alias("_bx"),
            ((pl.col(y) - ylo) / wy).floor().cast(pl.Int64).clip(0, ny - 1).alias("_by"),
        )
        .group_by(["_bx", "_by"])
        .agg(pl.len().alias("_count"))
        .collect()
    )
    if cells.height == 0:
        return None

    # Dense z grid — absent cells are 0, which is what a density plot means.
    z = [[0 for _ in range(nx)] for _ in range(ny)]
    for bx, by, count in zip(cells["_bx"], cells["_by"], cells["_count"]):
        z[by][bx] = count

    x_centres = [xlo + (i + 0.5) * wx for i in range(nx)]
    y_centres = [ylo + (j + 0.5) * wy for j in range(ny)]
    trace_cls = go.Heatmap if plan.visu_type == "density_heatmap" else go.Contour
    kwargs: dict[str, Any] = {"z": z, "x": x_centres, "y": y_centres}
    if plan.style.get("color_continuous_scale"):
        kwargs["colorscale"] = plan.style["color_continuous_scale"]
    fig = go.Figure(trace_cls(**kwargs))
    fig.update_layout(xaxis_title=x, yaxis_title=y)
    if render_stats is not None:
        render_stats["rows_displayed"] = cells.height
        render_stats["sampled"] = False
    return fig


# --------------------------------------------------------------------------- #
# Exact group-by → px on the aggregated frame
# --------------------------------------------------------------------------- #


def _build_groupby(
    scan: pl.LazyFrame, plan: AggPlan, template: str, render_stats: dict | None
) -> go.Figure | None:
    """``bar``: sum y per group (or count rows when there's no y).

    px.bar does not aggregate — it stacks one segment per row — so a raw-row bar
    chart over millions of rows is both enormous and, once sampled, wrong. Doing
    the group-by here gives px exactly the frame a reader assumes it's seeing.
    """
    keys = plan.group_keys
    if not keys:
        return None
    agg = pl.col(plan.y).sum().alias(plan.y) if plan.y else pl.len().alias("count")
    frame = scan.group_by(keys).agg(agg).collect()
    if frame.height == 0:
        return None
    if frame.height > _MAX_GROUPS:
        logger.info(
            f"_build_groupby: {frame.height} groups exceeds cap {_MAX_GROUPS} — falling back"
        )
        return None
    if plan.x:
        frame = frame.sort(plan.x, nulls_last=True)

    kwargs = _px_kwargs(plan, template)
    kwargs["y"] = plan.y or "count"
    fig = getattr(px, plan.visu_type)(frame, **kwargs)
    if render_stats is not None:
        render_stats["rows_displayed"] = frame.height
        render_stats["sampled"] = False
    return fig


# --------------------------------------------------------------------------- #
# Approximate: scan-level subsample → px
# --------------------------------------------------------------------------- #


def _build_subsample(
    scan: pl.LazyFrame, plan: AggPlan, template: str, render_stats: dict | None
) -> go.Figure | None:
    """``violin`` / ``ecdf``: shapes of a distribution, which need the values.

    There is no small exact summary for a KDE or an ECDF, so these get a uniform
    scan-level subsample instead of an aggregate — approximate, and flagged as
    sampled so the viewer's reduction badge tells the reader. The sample is drawn
    with a hash filter rather than by collecting and sampling, so the full frame
    is still never materialised.
    """
    from depictio.api.v1.configs.config import settings

    cap = int(settings.performance.figure_max_points)
    total = int(scan.select(pl.len()).collect().item())
    if total == 0:
        return None

    sampled = False
    frame_scan = scan
    if cap > 0 and total > cap:
        # Hash a struct of the projected columns so the keep/drop decision is
        # per-row rather than per-value: hashing a single column would keep or
        # drop *every* row sharing a value, which for a grouped violin would
        # take whole categories in or out.
        stride = -(-total // cap)  # ceil
        frame_scan = scan.filter(pl.struct(plan.needed_columns).hash(seed=0) % stride == 0)
        sampled = True

    frame = frame_scan.collect()
    if frame.height == 0:
        return None

    fig = getattr(px, plan.visu_type)(frame, **_px_kwargs(plan, template))
    if render_stats is not None:
        render_stats["rows_displayed"] = frame.height
        render_stats["rows_scanned"] = total
        render_stats["sampled"] = sampled
        render_stats["total_rows"] = total
    return fig


def _px_kwargs(plan: AggPlan, template: str) -> dict[str, Any]:
    """Rebuild the px call from the plan's roles + the passthrough styling."""
    kwargs: dict[str, Any] = {
        k: v for k, v in plan.style.items() if k not in ("nbins", "nbinsx", "nbinsy")
    }
    kwargs["template"] = template
    for role in ("x", "y", "color", "facet_row", "facet_col"):
        value = getattr(plan, role)
        if value:
            kwargs[role] = value
    return kwargs
