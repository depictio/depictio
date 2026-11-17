"""The binned strand windows with their libraries in time order.

``bedtools_strand_windows`` (catalog ``bedtools/strand_bins.py``) lists the windows
library by library in name order: ``GM_0h``, ``GM_12h``, ``GM_18h``, ``GM_1h``, ...
That is the order the lanes of the binned view stack in (it draws them in the order
it meets them), so 30 min landed after 2 h and the first lanes on screen were 0 h and
12 h. This recipe returns the same rows with the libraries sorted by the time
points of the sample hub, earliest first, and the windows of a library in their
original order (chromosome, then start). A library without a time point goes last,
by name. Nothing else changes.

Sources:
    windows  ``bedtools_strand_windows`` (catalog ``bedtools/strand_bins.py``)
    samples  ``samples`` (the sample hub)

Output schema: that of ``bedtools/strand_bins.py``.
    sample, chromosome : Utf8
    start, end, position : Int64
    plus_rpm, minus_rpm, signal_rpm, log2_signal, plus_share_pct : Float64
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="windows",
        dc_ref="bedtools_strand_windows",
        input_schema={"sample": pl.Utf8, "chromosome": pl.Utf8, "start": pl.Int64},
    ),
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={"sample": pl.Utf8, "time_order": pl.Int64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "chromosome": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "position": pl.Int64,
    "plus_rpm": pl.Float64,
    "minus_rpm": pl.Float64,
    "signal_rpm": pl.Float64,
    "log2_signal": pl.Float64,
    "plus_share_pct": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Sort the windows by the time point of their library, keeping each library's own order."""
    times = sources["samples"].select("sample", "time_order").unique(subset="sample")
    return (
        sources["windows"]
        .with_row_index("_row")
        .join(times, on="sample", how="left")
        .sort(["time_order", "sample", "_row"], nulls_last=True, maintain_order=True)
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
    )
