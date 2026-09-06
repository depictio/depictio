"""Concatenate MACS2 broadPeak calls into one tidy peak table.

``macs2/peaks.py`` reads ``*_peaks.narrowPeak``, a BED6+4 whose tenth column is
the summit offset. A ``--broad`` run writes ``*_peaks.broadPeak`` instead:
BED6+3, the same first nine columns and NO summit, because a broad region has
no single summit to report. That is a different schema, not a different glob,
so it cannot be reached by repointing the narrow recipe and gets an output of
its own.

The ChIP-family pipelines call peaks on the merged, filtered library, so MACS2
stamps the library name into every peak name
(``GM12878_FAST_R1.mLb.clN_peak_12``). The ``sample`` column keeps that
spelling, which is the one the HOMER annotation and the consensus matrix also
use, so the three tables join without a rewrite.

Output schema:
    sample : Utf8               library the peak was called in
    peak_id : Utf8              MACS2 peak name, unique across samples
    chr : Utf8                  chromosome
    start : Int64               peak start (0-based, as broadPeak reports it)
    end : Int64                 peak end
    width : Int64               end - start, the peak width in bp
    midpoint : Int64            1-based centre of the region, the plot abscissa
    score : Int64               MACS2 integer score (min(-10*log10 q, 1000))
    fold_enrichment : Float64   fold enrichment over the background
    neg_log10_pvalue : Float64  -log10 of the region p-value
    neg_log10_qvalue : Float64  -log10 of the region q-value (FDR)
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

_BROADPEAK_COLUMNS = [
    "chr",
    "start",
    "end",
    "peak_id",
    "score",
    "strand",
    "fold_enrichment",
    "neg_log10_pvalue",
    "neg_log10_qvalue",
]

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="broadpeak",
        glob_pattern="**/*_peaks.broadPeak",
        format="TSV",
        read_kwargs={
            "has_header": False,
            "new_columns": _BROADPEAK_COLUMNS,
            "infer_schema_length": 0,
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "peak_id": pl.Utf8,
    "chr": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "width": pl.Int64,
    "midpoint": pl.Int64,
    "score": pl.Int64,
    "fold_enrichment": pl.Float64,
    "neg_log10_pvalue": pl.Float64,
    "neg_log10_qvalue": pl.Float64,
}

# MACS2 names peaks `<name>_peak_<n>` and sub-peaks `<name>_peak_<n><letter>`.
_PEAK_SUFFIX = r"_peak_\d+[a-z]*$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Type the BED columns, derive sample / width / midpoint and order the output."""
    df = sources["broadpeak"]
    missing = [c for c in _BROADPEAK_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"macs2 broad_peaks: broadPeak input lacks columns {missing}")

    df = df.with_columns(
        pl.col("chr").cast(pl.Utf8),
        pl.col("peak_id").cast(pl.Utf8),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
        pl.col("score").cast(pl.Int64, strict=False),
        pl.col("fold_enrichment").cast(pl.Float64, strict=False),
        pl.col("neg_log10_pvalue").cast(pl.Float64, strict=False),
        pl.col("neg_log10_qvalue").cast(pl.Float64, strict=False),
    )
    df = df.with_columns(
        pl.col("peak_id").str.replace(_PEAK_SUFFIX, "").alias("sample"),
        (pl.col("end") - pl.col("start")).alias("width"),
        # broadPeak start is 0-based; the region centre stands in for the summit
        # a broad call does not have.
        ((pl.col("start") + pl.col("end")) // 2 + 1).alias("midpoint"),
    )
    return df.select(list(EXPECTED_SCHEMA)).sort(["sample", "chr", "start"])
