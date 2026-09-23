"""One region, one resolution: the server side of a contact map that zooms.

A Hi-C matrix is the one advanced-viz kind whose row count grows with the
*square* of how far you zoom out, so the usual "load the DC, draw it" path only
survives because the renderer coarsens the matrix client-side after paying for
every row. The `cooler/binned_contact_map` recipe now writes one partition per
resolution (``resolution`` column), which lets the server do the opposite: pick
the resolution that matches the visible span, read only the window, and hand
the tile a matrix that is already the size of the screen.

Everything here is pure, so the choice of resolution and the window arithmetic
are testable without Mongo, Celery or a Delta table. The Celery task in
``celery_tasks.compute_contact_map`` is the only caller that touches I/O.

Backward compatibility: a DC with no resolution column is not multi-resolution,
`resolve_resolution_column` returns None, and the task serves the whole frame
for the region exactly as the single-resolution path always did.
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl

#: Column the recipe writes. A config may name another one; this is the name
#: looked for when it does not, which is what makes the feature work on a
#: dashboard whose YAML predates it.
DEFAULT_RESOLUTION_COLUMN = "resolution"

#: Bins per CSS pixel aimed for when picking a resolution. A Hi-C bin drawn
#: smaller than a few pixels is not readable, and drawing more bins than the
#: tile has pixels only costs transfer, so the target is below 1.
DEFAULT_BINS_PER_PIXEL = 0.25

#: Assumed tile width when the client sends none.
DEFAULT_PIXELS = 800

#: Hard ceiling on the cells returned for one window. 40k cells is a 200 x 200
#: matrix, already past what a tile can show.
DEFAULT_MAX_CELLS = 40_000


def resolve_resolution_column(
    available: list[str] | set[str], configured: str | None
) -> str | None:
    """The resolution column to partition on, or None for a flat DC.

    `configured` wins when it is really there; otherwise the recipe's own name
    is tried, so a dashboard that never declared the binding still zooms.
    """
    cols = set(available)
    if configured and configured in cols:
        return configured
    if DEFAULT_RESOLUTION_COLUMN in cols:
        return DEFAULT_RESOLUTION_COLUMN
    return None


def choose_resolution(
    resolutions: list[int],
    span_bp: float | None,
    pixels: int | None = None,
    target_bins_per_pixel: float | None = None,
) -> int | None:
    """The available resolution whose bins-per-pixel is closest to the target.

    Closeness is measured in log space: at a 200 kb ideal, 100 kb and 400 kb
    are equally wrong, which a linear distance would not say. Ties go to the
    coarser level, because it is the cheaper one to read and to send.

    With no span to go on (no region filter yet) the coarsest level is the
    right opening view: a whole chromosome.
    """
    levels = sorted({int(r) for r in resolutions if r and int(r) > 0})
    if not levels:
        return None
    if not span_bp or span_bp <= 0 or not math.isfinite(span_bp):
        return levels[-1]

    px = int(pixels) if pixels and int(pixels) > 0 else DEFAULT_PIXELS
    target = (
        float(target_bins_per_pixel)
        if target_bins_per_pixel and target_bins_per_pixel > 0
        else DEFAULT_BINS_PER_PIXEL
    )
    ideal = span_bp / (px * target)

    best = levels[-1]
    best_distance = float("inf")
    for level in levels:
        distance = abs(math.log(level / ideal))
        # `<=` walks coarse-last, so an exact tie keeps the coarser level.
        if distance <= best_distance:
            best, best_distance = level, distance
    return best


def coarsest_within_budget(
    resolutions: list[int],
    chosen: int | None,
    span_bp: float | None,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> int | None:
    """Step `chosen` coarser until the window's cell count fits the budget.

    An intra-chromosomal window of `n` bins holds `n * (n + 1) / 2` cells, and
    `n` is the span over the resolution. When a run dumped only a fine level
    and the reader is looking at a whole chromosome, the chosen level can still
    be far too dense; this walks up the ladder rather than truncating, because
    a truncated matrix is a wrong matrix, not a coarse one.
    """
    levels = sorted({int(r) for r in resolutions if r and int(r) > 0})
    if not levels:
        return chosen
    if chosen is None:
        chosen = levels[-1]
    if not span_bp or span_bp <= 0 or not math.isfinite(span_bp):
        return levels[-1]

    for level in levels:
        if level < chosen:
            continue
        bins = math.ceil(span_bp / level)
        if bins * (bins + 1) / 2 <= max_cells:
            return level
    return levels[-1]


def window_expr(
    start_col: str,
    end_col: str | None,
    resolution: int | None,
    lo: float,
    hi: float,
) -> pl.Expr:
    """Rows whose bin overlaps ``[lo, hi)`` on one axis of the matrix.

    A bin is kept when it overlaps the window, not when its start is inside it:
    dropping the bin that straddles the left edge leaves a visible notch at the
    start of every zoomed view. The bin's own end column is used when the DC
    has one, and the resolution stands in for it when it does not.
    """
    starts_before_end = pl.col(start_col) < hi
    if end_col:
        ends_after_start = pl.col(end_col) > lo
    elif resolution:
        ends_after_start = (pl.col(start_col) + resolution) > lo
    else:
        ends_after_start = pl.col(start_col) >= lo
    return starts_before_end & ends_after_start


def apply_window(
    df: pl.DataFrame,
    *,
    chrom1_col: str,
    start1_col: str,
    chrom2_col: str,
    start2_col: str,
    end1_col: str | None,
    end2_col: str | None,
    chrom: str | None,
    start: float | None,
    end: float | None,
    resolution: int | None,
) -> pl.DataFrame:
    """Keep the cells of one chromosome inside one square window.

    Both axes are windowed, which is what makes the result a submatrix rather
    than a stripe. A chromosome with no range is the whole contig.
    """
    if chrom:
        df = df.filter((pl.col(chrom1_col) == chrom) & (pl.col(chrom2_col) == chrom))
    if start is None or end is None or not math.isfinite(start) or not math.isfinite(end):
        return df
    if end <= start:
        return df
    return df.filter(
        window_expr(start1_col, end1_col, resolution, start, end)
        & window_expr(start2_col, end2_col, resolution, start, end)
    )


def summarise(
    df: pl.DataFrame,
    *,
    chrom1_col: str,
    start1_col: str,
    resolution_col: str | None,
    sample_col: str | None,
    resolutions: list[int],
    resolution: int | None,
    region: dict[str, Any] | None,
    pixels: int | None,
    truncated: bool,
) -> dict[str, Any]:
    """What the tile needs to label itself and to decide whether to re-fetch."""
    chromosomes = (
        sorted({str(v) for v in df.get_column(chrom1_col).unique().to_list() if v is not None})
        if df.height
        else []
    )
    samples = (
        sorted({str(v) for v in df.get_column(sample_col).unique().to_list() if v is not None})
        if sample_col and df.height
        else []
    )
    bin_count = int(df.get_column(start1_col).n_unique()) if df.height else 0
    span = None
    if region and region.get("start") is not None and region.get("end") is not None:
        span = float(region["end"]) - float(region["start"])
    px = int(pixels) if pixels and int(pixels) > 0 else DEFAULT_PIXELS
    return {
        "row_count": int(df.height),
        "resolutions": resolutions,
        "resolution": resolution,
        "resolution_col": resolution_col,
        "chromosomes": chromosomes,
        "samples": samples,
        "n_samples": len(samples),
        "bin_count": bin_count,
        "region": region,
        "bins_per_pixel": (span / resolution / px) if (span and resolution) else None,
        "multi_resolution": len(resolutions) > 1,
        "truncated": truncated,
    }
