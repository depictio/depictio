"""What each copy-number profile adds up to: one row per unit, for the tab's key figures.

A card cannot divide one column by another, so the share of the genome that is gained or
lost has to exist as a number before the tab can print it. This reads the called segments
of ``cnv_segments`` (the bins are the evidence, not the call) and sums them per unit:

* ``covered_mb``: megabases inside called segments, the part of the genome CNVkit judged;
* ``gained_mb`` / ``lost_mb`` / ``altered_mb``: megabases in segments whose log2 ratio is
  above ``GAIN_LOG2`` or below ``LOSS_LOG2`` (the cut-offs the profile draws), and both;
* ``fga_pct`` (fraction of the genome altered): ``altered_mb`` over ``covered_mb``, in
  percent, with its gained and lost halves ``gained_pct`` and ``lost_pct``;
* ``altered_contigs``: contigs where at least ``ALTERED_CONTIG_SHARE`` of the called length is
  gained or lost, out of ``contigs``, the contigs the unit has a segment on; a tenth keeps a
  small noisy segment from counting a whole contig as altered;
* ``max_log2`` / ``min_log2``: the strongest gain and the deepest loss, the first place to look
  for a focal amplification or a deletion.

The cut-offs are the conventional 0.3 and -0.3 of the profile, not a property of the run:
they are constants of this recipe, so the tab's cards and the profile's colours agree.

Output schema:
    unit, unit_type, patient, sample, normal, call_source : Utf8   as in ``cnv_segments``
    n_segments, n_gains, n_losses : Int64   called segments, and those past each cut-off
    covered_mb, gained_mb, lost_mb, altered_mb : Float64
    fga_pct, gained_pct, lost_pct : Float64   share of ``covered_mb``, in percent
    contigs, altered_contigs : Int64
    max_log2, min_log2 : Float64
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Log2 ratio above which a segment is a gain, and below which it is a loss.
GAIN_LOG2 = 0.3
LOSS_LOG2 = -0.3
#: Share of a contig's called length that must be gained or lost for the contig to count as altered.
ALTERED_CONTIG_SHARE = 0.10

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="segments",
        dc_ref="cnv_segments",
        input_schema={
            "unit": pl.Utf8,
            "unit_type": pl.Utf8,
            "patient": pl.Utf8,
            "sample": pl.Utf8,
            "normal": pl.Utf8,
            "chrom": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
            "log2": pl.Float64,
            "segment": pl.Utf8,
            "call_source": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "unit": pl.Utf8,
    "unit_type": pl.Utf8,
    "patient": pl.Utf8,
    "sample": pl.Utf8,
    "normal": pl.Utf8,
    "call_source": pl.Utf8,
    "n_segments": pl.Int64,
    "n_gains": pl.Int64,
    "n_losses": pl.Int64,
    "covered_mb": pl.Float64,
    "gained_mb": pl.Float64,
    "lost_mb": pl.Float64,
    "altered_mb": pl.Float64,
    "fga_pct": pl.Float64,
    "gained_pct": pl.Float64,
    "lost_pct": pl.Float64,
    "contigs": pl.Int64,
    "altered_contigs": pl.Int64,
    "max_log2": pl.Float64,
    "min_log2": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per unit: the megabases gained and lost, and the share of the genome they make."""
    segments = sources["segments"].filter(
        (pl.col("segment") == "segment")
        & pl.col("start").is_not_null()
        & pl.col("end").is_not_null()
        & pl.col("log2").is_not_null()
    )
    if segments.is_empty():
        raise ValueError("sarek cnv_summary: no called copy-number segment to summarise")

    gain = pl.col("log2") > GAIN_LOG2
    loss = pl.col("log2") < LOSS_LOG2
    mb = ((pl.col("end") - pl.col("start")) / 1e6).alias("mb")
    segments = segments.with_columns(mb)

    per_contig = (
        segments.group_by(["unit", "chrom"])
        .agg(
            pl.col("mb").sum().alias("covered"),
            pl.col("mb").filter(gain | loss).sum().alias("altered"),
        )
        .group_by("unit")
        .agg(
            pl.len().cast(pl.Int64).alias("contigs"),
            (
                (pl.col("covered") > 0)
                & (pl.col("altered") / pl.col("covered") >= ALTERED_CONTIG_SHARE)
            )
            .sum()
            .cast(pl.Int64)
            .alias("altered_contigs"),
        )
    )

    who = segments.group_by("unit", maintain_order=True).agg(
        pl.col("unit_type").first(),
        pl.col("patient").first(),
        pl.col("sample").first(),
        pl.col("normal").first(),
        pl.col("call_source").first(),
    )
    totals = segments.group_by("unit").agg(
        pl.len().cast(pl.Int64).alias("n_segments"),
        gain.sum().cast(pl.Int64).alias("n_gains"),
        loss.sum().cast(pl.Int64).alias("n_losses"),
        pl.col("mb").sum().alias("covered_mb"),
        pl.col("mb").filter(gain).sum().alias("gained_mb"),
        pl.col("mb").filter(loss).sum().alias("lost_mb"),
        pl.col("log2").max().alias("max_log2"),
        pl.col("log2").min().alias("min_log2"),
    )
    covered = pl.col("covered_mb")
    return (
        who.join(totals, on="unit")
        .join(per_contig, on="unit")
        .with_columns((pl.col("gained_mb") + pl.col("lost_mb")).alias("altered_mb"))
        .with_columns(
            pl.when(covered > 0)
            .then(pl.col("altered_mb") / covered * 100)
            .otherwise(None)
            .alias("fga_pct"),
            pl.when(covered > 0)
            .then(pl.col("gained_mb") / covered * 100)
            .otherwise(None)
            .alias("gained_pct"),
            pl.when(covered > 0)
            .then(pl.col("lost_mb") / covered * 100)
            .otherwise(None)
            .alias("lost_pct"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort("unit")
    )
