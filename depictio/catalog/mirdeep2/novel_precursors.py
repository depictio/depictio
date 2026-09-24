"""Novel miRNA precursors merged across samples, one row per locus.

miRDeep2 runs once per sample, so the same novel hairpin is reported once per
sample that expresses it, each time under a different provisional id and with
slightly different ends (the consensus precursor is drawn from that sample's
reads). A reader asking "which novel miRNAs did this run find" wants one row
per hairpin, with how many samples support it, not one row per call.

Calls are merged when their precursor intervals overlap on the same chromosome
and strand; the merged interval is the union. The row keeps the strongest call
(highest miRDeep2 score) for the sequences and its sample, and aggregates the
rest: how many samples reported the locus, the score range, the reads summed
over samples, and the share of calls with a significant randfold test. Recurrence
across samples and a significant randfold together are the usual first filter
on novel predictions; a hit on an Rfam family (rRNA, tRNA) is the usual reason
to discard one.

Source: the ``mirdeep2_predictions`` collection (``mirdeep2/predictions.py``),
novel rows only.

Output schema:
    precursor_id : Utf8            chromosome:start-end:strand of the merged locus
    chromosome : Utf8
    start : Int64
    end : Int64
    strand : Utf8
    samples_detected : Int64       samples with a call on the locus
    detection_pct : Float64        of the samples miRDeep2 ran on, %
    calls : Int64                  calls merged into the locus
    max_score : Float64            best miRDeep2 score among the calls
    median_score : Float64
    max_true_positive_pct : Float64  best estimated true-positive probability, %
    total_reads : Int64            reads on the precursor, summed over samples
    mature_reads : Int64
    star_reads : Int64
    loop_reads : Int64
    star_support : Utf8            yes when any call has star-arm reads
    randfold_pct : Float64         calls with a significant randfold test, %
    rfam_alert : Utf8              Rfam family any call matched, or "-"
    seed_match : Utf8              a miRBase miRNA sharing the seed, or "-"
    best_sample : Utf8             sample of the best-scoring call
    mature_sequence : Utf8         consensus mature sequence of that call
    star_sequence : Utf8
    precursor_sequence : Utf8
    precursor_length : Int64
    genome_position : Utf8         chrN:start-end, the spelling genome browsers search on
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="predictions", dc_ref="mirdeep2_predictions"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "precursor_id": pl.Utf8,
    "chromosome": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "samples_detected": pl.Int64,
    "detection_pct": pl.Float64,
    "calls": pl.Int64,
    "max_score": pl.Float64,
    "median_score": pl.Float64,
    "max_true_positive_pct": pl.Float64,
    "total_reads": pl.Int64,
    "mature_reads": pl.Int64,
    "star_reads": pl.Int64,
    "loop_reads": pl.Int64,
    "star_support": pl.Utf8,
    "randfold_pct": pl.Float64,
    "rfam_alert": pl.Utf8,
    "seed_match": pl.Utf8,
    "best_sample": pl.Utf8,
    "mature_sequence": pl.Utf8,
    "star_sequence": pl.Utf8,
    "precursor_sequence": pl.Utf8,
    "precursor_length": pl.Int64,
    "genome_position": pl.Utf8,
}


def _first_informative(column: str) -> pl.Expr:
    """First value that is not the '-' placeholder, else '-'."""
    return (
        pl.col(column)
        .filter(pl.col(column).is_not_null() & (pl.col(column) != "-"))
        .first()
        .fill_null("-")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Merge overlapping novel calls into loci."""
    calls = sources["predictions"]
    n_samples = max(calls["sample"].n_unique(), 1)
    novel = calls.filter(
        (pl.col("category") == "novel")
        & pl.col("chromosome").is_not_null()
        & pl.col("start").is_not_null()
        & pl.col("end").is_not_null()
    ).sort(["chromosome", "strand", "start", "end"])
    if novel.is_empty():
        return pl.DataFrame(schema=EXPECTED_SCHEMA)

    # Interval merge: a call opens a new locus when it starts past the running
    # end of the current one (per chromosome and strand).
    running_end = pl.col("end").cum_max().shift(1).over(["chromosome", "strand"]).fill_null(-1)
    novel = novel.with_columns(
        (pl.col("start") > running_end).cast(pl.Int64).cum_sum().alias("_locus")
    )

    best = (
        novel.sort("score", descending=True, nulls_last=True)
        .group_by("_locus", maintain_order=True)
        .first()
        .select(
            "_locus",
            pl.col("sample").alias("best_sample"),
            "mature_sequence",
            "star_sequence",
            "precursor_sequence",
            "precursor_length",
        )
    )
    merged = novel.group_by("_locus").agg(
        pl.col("chromosome").first(),
        pl.col("strand").first(),
        pl.col("start").min(),
        pl.col("end").max(),
        pl.col("sample").n_unique().cast(pl.Int64).alias("samples_detected"),
        pl.len().cast(pl.Int64).alias("calls"),
        pl.col("score").max().alias("max_score"),
        pl.col("score").median().alias("median_score"),
        pl.col("true_positive_pct").max().alias("max_true_positive_pct"),
        pl.col("total_reads").sum().cast(pl.Int64),
        pl.col("mature_reads").sum().cast(pl.Int64),
        pl.col("star_reads").sum().cast(pl.Int64),
        pl.col("loop_reads").sum().cast(pl.Int64),
        (pl.col("randfold_significant") == "yes").mean().mul(100.0).alias("randfold_pct"),
        _first_informative("rfam_alert").alias("rfam_alert"),
        _first_informative("seed_match").alias("seed_match"),
    )
    out = merged.join(best, on="_locus", how="left").with_columns(
        (
            pl.col("chromosome")
            + ":"
            + pl.col("start").cast(pl.Utf8)
            + "-"
            + pl.col("end").cast(pl.Utf8)
            + ":"
            + pl.col("strand")
        ).alias("precursor_id"),
        (pl.col("samples_detected") * 100.0 / n_samples).alias("detection_pct"),
        # Ensembl-style references name chromosomes 1..22, X, MT; browsers
        # search on chr1..chr22, chrX, chrM.
        (
            pl.when(pl.col("chromosome").str.starts_with("chr"))
            .then(pl.col("chromosome"))
            .when(pl.col("chromosome") == "MT")
            .then(pl.lit("chrM"))
            .otherwise(pl.lit("chr") + pl.col("chromosome"))
            + ":"
            + pl.col("start").cast(pl.Utf8)
            + "-"
            + pl.col("end").cast(pl.Utf8)
        ).alias("genome_position"),
        pl.when(pl.col("star_reads") > 0)
        .then(pl.lit("yes"))
        .otherwise(pl.lit("no"))
        .alias("star_support"),
    )
    out = out.with_columns([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()])
    return out.select(list(EXPECTED_SCHEMA)).sort(
        ["samples_detected", "max_score"], descending=[True, True]
    )
