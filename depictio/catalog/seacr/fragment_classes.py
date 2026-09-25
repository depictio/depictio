"""The fragment-length histogram binned into nucleosome classes.

The raw ladder (``seacr/fragment_lengths``) is a curve with 600-odd points per
sample, which is the right shape for "does this look like chromatin" and the
wrong one for "how much of this library is nucleosome-free". MNase and
protein-A-MNase cut around nucleosomes, so the lengths fall into classes with a
biological reading:

  ====================  ===========  ==================================
  class                 length (bp)  what it is
  ====================  ===========  ==================================
  Sub-nucleosomal       < 120        free DNA and transcription-factor
                                     footprints, the CUT&RUN signal for
                                     a sharp mark
  Mononucleosomal       120 to 250   one nucleosome plus its linker
  Dinucleosomal         251 to 450   two nucleosomes, the first rung of
                                     the ladder
  Multi-nucleosomal     > 450        three or more, or undigested
                                     chromatin
  ====================  ===========  ==================================

The boundaries are the conventional MNase ones (a mononucleosome protects
about 147 bp, plus a linker of tens of bases). They are class constants so a
pipeline with a different digestion can re-cut them without touching the
aggregation.

A sharp mark such as H3K4me3 is expected to be sub-nucleosome heavy, a broad
one such as H3K27me3 mononucleosome heavy, and ``mono_to_sub`` is that contrast
as one number per sample: the mononucleosomal fragments divided by the
sub-nucleosomal ones.

Reads the tidy fragment collection through ``dc_ref`` rather than the raw
histogram files, so the sample naming and the per-sample normalisation are
already done.

Output schema:
    sample : Utf8            sample the fragments came from
    target : Utf8            group the sample belongs to
    fragment_class : Utf8    one of the four classes above
    class_order : Int64      1 to 4, so a stacked bar orders by length
    n_fragments : Int64      fragments of the sample in that class
    fraction : Float64       share of the sample's fragments in that class
    median_length : Float64  median fragment length inside the class
    mono_to_sub : Float64    mononucleosomal / sub-nucleosomal, per sample
    sample_median_length : Float64  median fragment length of the whole sample,
                                    weighted by fragment count (repeated on its
                                    four class rows, like ``mono_to_sub``)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads: the output of `seacr/fragment_lengths.py`.
FRAGMENTS_DC_TAG = "seacr_fragment_lengths"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="fragments", dc_ref=FRAGMENTS_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "target": pl.Utf8,
    "fragment_class": pl.Utf8,
    "class_order": pl.Int64,
    "n_fragments": pl.Int64,
    "fraction": pl.Float64,
    "median_length": pl.Float64,
    "mono_to_sub": pl.Float64,
    "sample_median_length": pl.Float64,
}

SUB_NUCLEOSOMAL = "Sub-nucleosomal"
MONONUCLEOSOMAL = "Mononucleosomal"
DINUCLEOSOMAL = "Dinucleosomal"
MULTINUCLEOSOMAL = "Multi-nucleosomal"

#: Upper bound (inclusive) of each class, and the order a stacked bar uses.
SUB_MAX_BP = 119
MONO_MAX_BP = 250
DI_MAX_BP = 450

_CLASS_ORDER: dict[str, int] = {
    SUB_NUCLEOSOMAL: 1,
    MONONUCLEOSOMAL: 2,
    DINUCLEOSOMAL: 3,
    MULTINUCLEOSOMAL: 4,
}


def _class_expr() -> pl.Expr:
    """Label one fragment-length row with its nucleosome class."""
    length = pl.col("fragment_length")
    return (
        pl.when(length <= SUB_MAX_BP)
        .then(pl.lit(SUB_NUCLEOSOMAL))
        .when(length <= MONO_MAX_BP)
        .then(pl.lit(MONONUCLEOSOMAL))
        .when(length <= DI_MAX_BP)
        .then(pl.lit(DINUCLEOSOMAL))
        .otherwise(pl.lit(MULTINUCLEOSOMAL))
        .alias("fragment_class")
    )


def _median_length(weights: pl.Expr, lengths: pl.Expr) -> pl.Expr:
    """Median of a length histogram, i.e. the length at half the fragments."""
    order = lengths.arg_sort()
    running = weights.gather(order).cum_sum()
    half = weights.sum() / 2.0
    return lengths.gather(order).filter(running >= half).first().cast(pl.Float64)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Bin the per-sample histogram into the four nucleosome classes."""
    df = sources["fragments"]
    missing = [c for c in ("sample", "fragment_length", "count") if c not in df.columns]
    if missing:
        raise ValueError(f"seacr_fragment_classes: the fragment collection lacks columns {missing}")

    target = (
        pl.col("target").cast(pl.Utf8).first()
        if "target" in df.columns
        else pl.lit(None, pl.Utf8).first()
    )
    df = df.with_columns(
        pl.col("fragment_length").cast(pl.Int64),
        pl.col("count").cast(pl.Int64),
        _class_expr(),
    )

    grouped = df.group_by(["sample", "fragment_class"]).agg(
        target.alias("target"),
        pl.col("count").sum().cast(pl.Int64).alias("n_fragments"),
        _median_length(pl.col("count"), pl.col("fragment_length")).alias("median_length"),
    )

    # Every sample gets all four classes, including the empty ones: a library
    # with no dinucleosomal fragments at all is a finding, not a missing row.
    grid = (
        grouped.select("sample")
        .unique()
        .join(pl.DataFrame({"fragment_class": list(_CLASS_ORDER)}), how="cross")
    )
    grouped = (
        grid.join(grouped, on=["sample", "fragment_class"], how="left")
        .with_columns(
            pl.col("n_fragments").fill_null(0),
            # After the cross join `first()` can land on a padded (null) row, so
            # the fill takes the sample's first real target instead.
            pl.col("target").fill_null(pl.col("target").drop_nulls().first().over("sample")),
        )
        .with_columns(
            pl.col("fragment_class")
            .replace_strict(_CLASS_ORDER, return_dtype=pl.Int64)
            .alias("class_order"),
            (pl.col("n_fragments") / pl.col("n_fragments").sum().over("sample"))
            .round(4)
            .alias("fraction"),
        )
    )

    sub = pl.col("n_fragments").filter(pl.col("fragment_class") == SUB_NUCLEOSOMAL).sum()
    mono = pl.col("n_fragments").filter(pl.col("fragment_class") == MONONUCLEOSOMAL).sum()
    ratios = grouped.group_by("sample").agg(
        pl.when(sub > 0)
        .then((mono / sub).round(3))
        .otherwise(None)
        .cast(pl.Float64)
        .alias("mono_to_sub")
    )
    # The per-sample median over the whole ladder. The histogram has one row per
    # length, so a card median over `seacr_fragment_lengths.fragment_length`
    # would be the middle of the x axis; this is the length at half the
    # fragments. Every sample has exactly four rows here, so a card median or
    # box plot over this column weighs every sample once.
    medians = df.group_by("sample").agg(
        _median_length(pl.col("count"), pl.col("fragment_length")).alias("sample_median_length")
    )
    grouped = grouped.join(ratios, on="sample", how="left").join(medians, on="sample", how="left")
    return grouped.select(list(EXPECTED_SCHEMA)).sort(["sample", "class_order"])
