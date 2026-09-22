"""The ancient-DNA authenticity plane: terminal deamination against fragment length.

Two signals decide whether a library is genuinely ancient, and neither is
conclusive alone:

* the **misincorporation** rate at the very first base of a read, where uracils
  from cytosine deamination read as C to T at the 5' end and, on a
  double-stranded library, as G to A at the 3' end;
* the **fragment length**, because ancient DNA is depurination-fragmented and
  rarely survives past ~100 bp.

A modern contaminant has long fragments and no terminal signal, a damaged
ancient extract has short fragments and a steep one, and a library that is
short but undamaged is usually over-sheared modern DNA rather than old. Plotted
against each other the three are separable at a glance, which is what this
output is for; on their own tabs the two signals are the full per-position
profiles and this is their one-row-per-library summary.

Inputs are the two tidied DamageProfiler collections rather than the raw files,
so the position convention (0-based, first base of the read) and the sample-id
recovery are settled once, in those recipes. A template binding this output must
therefore declare them under exactly these tags, and after them: data
collections are ingested in declaration order.

Output schema:
    sample : Utf8                library DamageProfiler ran on
    ct_5p_first : Float64        C to T frequency at the first 5' base
    ga_3p_first : Float64        G to A frequency at the first 3' base
    terminal_damage : Float64    mean of the two, the headline damage number
    background : Float64         every other substitution at the same positions, pooled
    mean_length : Float64        mean mapped fragment length, bp
    median_length : Int64        median mapped fragment length, bp
    fraction_under_70bp : Float64  share of mapped fragments shorter than 70 bp, 0-1
    n_reads : Int64              mapped fragments the length distribution counted
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tags the template must declare, before this one.
MISINCORPORATION_DC_TAG = "damageprofiler_misincorporation"
LGDISTRIBUTION_DC_TAG = "damageprofiler_lgdistribution"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="damage", dc_ref=MISINCORPORATION_DC_TAG),
    RecipeSource(ref="lengths", dc_ref=LGDISTRIBUTION_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "ct_5p_first": pl.Float64,
    "ga_3p_first": pl.Float64,
    "terminal_damage": pl.Float64,
    "background": pl.Float64,
    "mean_length": pl.Float64,
    "median_length": pl.Int64,
    "fraction_under_70bp": pl.Float64,
    "n_reads": pl.Int64,
}

#: Fragments shorter than this are the ancient band; the cut-off is the one
#: aDNA screening papers quote, not a property of the data.
SHORT_FRAGMENT_BP = 70


def _terminal(damage: pl.DataFrame, end: str, base_change: str, name: str) -> pl.DataFrame:
    """One row per sample with the substitution frequency at that end's first base."""
    at_end = damage.filter(pl.col("end") == end)
    if at_end.is_empty():
        return pl.DataFrame({"sample": [], name: []}, schema={"sample": pl.Utf8, name: pl.Float64})
    first = at_end.group_by("sample").agg(pl.col("position").min().alias("first_position"))
    return (
        at_end.join(first, on="sample", how="inner")
        .filter(
            (pl.col("position") == pl.col("first_position"))
            & (pl.col("base_change") == base_change)
        )
        .group_by("sample")
        .agg(pl.col("frequency").mean().alias(name))
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per library, joining the two signals."""
    damage = sources["damage"]
    lengths = sources["lengths"]
    for name, frame, needed in (
        ("damage", damage, {"sample", "end", "position", "base_change", "frequency"}),
        ("lengths", lengths, {"sample", "length", "occurrences"}),
    ):
        if frame is None or frame.is_empty():
            raise ValueError(f"damageprofiler_authenticity: the '{name}' collection is empty")
        missing = needed - set(frame.columns)
        if missing:
            raise ValueError(
                f"damageprofiler_authenticity: '{name}' lacks columns {sorted(missing)}"
            )

    ct = _terminal(damage, "5p", "C>T", "ct_5p_first")
    ga = _terminal(damage, "3p", "G>A", "ga_3p_first")
    background = (
        damage.filter(pl.col("base_change") == "other")
        .join(
            damage.group_by(["sample", "end"]).agg(
                pl.col("position").min().alias("first_position")
            ),
            on=["sample", "end"],
            how="inner",
        )
        .filter(pl.col("position") == pl.col("first_position"))
        .group_by("sample")
        .agg(pl.col("frequency").mean().alias("background"))
    )

    # Length statistics off the occurrence counts: a weighted mean, and a
    # median read off the cumulative count rather than from expanded rows,
    # which would materialise tens of millions of them.
    per_length = (
        lengths.group_by(["sample", "length"])
        .agg(pl.col("occurrences").sum().alias("occurrences"))
        .sort(["sample", "length"])
    )
    totals = per_length.group_by("sample").agg(pl.col("occurrences").sum().alias("n_reads"))
    stats = (
        per_length.join(totals, on="sample", how="inner")
        .with_columns(pl.col("occurrences").cum_sum().over("sample").alias("cumulative"))
        .group_by("sample")
        .agg(
            ((pl.col("length") * pl.col("occurrences")).sum() / pl.col("occurrences").sum()).alias(
                "mean_length"
            ),
            pl.col("length")
            .filter(pl.col("cumulative") >= pl.col("n_reads") / 2)
            .min()
            .alias("median_length"),
            (
                pl.col("occurrences").filter(pl.col("length") < SHORT_FRAGMENT_BP).sum()
                / pl.col("occurrences").sum()
            ).alias("fraction_under_70bp"),
            pl.col("occurrences").sum().alias("n_reads"),
        )
    )

    out = (
        stats.join(ct, on="sample", how="left")
        .join(ga, on="sample", how="left")
        .join(background, on="sample", how="left")
        .with_columns(
            pl.mean_horizontal(pl.col("ct_5p_first"), pl.col("ga_3p_first")).alias(
                "terminal_damage"
            )
        )
        .with_columns(
            pl.col("mean_length").cast(pl.Float64),
            pl.col("median_length").cast(pl.Int64),
            pl.col("fraction_under_70bp").cast(pl.Float64),
            pl.col("n_reads").cast(pl.Int64),
            pl.col("ct_5p_first").cast(pl.Float64),
            pl.col("ga_3p_first").cast(pl.Float64),
            pl.col("background").cast(pl.Float64),
            pl.col("terminal_damage").cast(pl.Float64),
        )
    )
    return out.select(list(EXPECTED_SCHEMA)).sort("sample")
