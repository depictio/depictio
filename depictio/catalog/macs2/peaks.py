"""Concatenate MACS2 narrowPeak calls into one tidy peak table.

Each ``<sample>_peaks.narrowPeak`` is a headerless BED6+4: chrom, start, end,
name, score, strand, signalValue (fold enrichment at the summit), pValue and
qValue (both -log10) and the summit offset from ``start``. The sample is not a
column of the file, but MACS2 stamps its ``--name`` into every peak name
(``<sample>_peak_12``), which is where the ``sample`` column comes from. That
keeps the recipe independent of file names, which the glob loader does not
expose.

Only narrow peaks are read. ``--broad`` writes ``*_peaks.broadPeak``, a BED6+3
with no summit column, so it needs its own output rather than a widened schema.

Output schema:
    sample : Utf8               sample the peak was called in
    peak_id : Utf8              MACS2 peak name, unique across samples
    chr : Utf8                  chromosome
    start : Int64               peak start (0-based, as narrowPeak reports it)
    end : Int64                 peak end
    width : Int64               end - start, the peak width in bp
    summit : Int64              1-based genomic position of the summit
    score : Int64               MACS2 integer score (min(-10*log10 q, 1000))
    fold_enrichment : Float64   fold enrichment at the summit over the control
    neg_log10_pvalue : Float64  -log10 of the peak p-value
    neg_log10_qvalue : Float64  -log10 of the peak q-value (FDR)
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

_NARROWPEAK_COLUMNS = [
    "chr",
    "start",
    "end",
    "peak_id",
    "score",
    "strand",
    "fold_enrichment",
    "neg_log10_pvalue",
    "neg_log10_qvalue",
    "summit_offset",
]

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="narrowpeak",
        glob_pattern="**/*_peaks.narrowPeak",
        format="TSV",
        read_kwargs={
            "has_header": False,
            "new_columns": _NARROWPEAK_COLUMNS,
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
    "summit": pl.Int64,
    "score": pl.Int64,
    "fold_enrichment": pl.Float64,
    "neg_log10_pvalue": pl.Float64,
    "neg_log10_qvalue": pl.Float64,
}

# MACS2 names peaks `<name>_peak_<n>` and sub-peaks `<name>_peak_<n><letter>`.
_PEAK_SUFFIX = r"_peak_\d+[a-z]*$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Type the BED columns, derive sample / width / summit and order the output."""
    df = sources["narrowpeak"]
    missing = [c for c in _NARROWPEAK_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"macs2_peaks: narrowPeak input lacks columns {missing}")

    df = df.with_columns(
        pl.col("chr").cast(pl.Utf8),
        pl.col("peak_id").cast(pl.Utf8),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
        pl.col("score").cast(pl.Int64, strict=False),
        pl.col("fold_enrichment").cast(pl.Float64, strict=False),
        pl.col("neg_log10_pvalue").cast(pl.Float64, strict=False),
        pl.col("neg_log10_qvalue").cast(pl.Float64, strict=False),
        pl.col("summit_offset").cast(pl.Int64, strict=False),
    )
    df = df.with_columns(
        pl.col("peak_id").str.replace(_PEAK_SUFFIX, "").alias("sample"),
        (pl.col("end") - pl.col("start")).alias("width"),
        # narrowPeak start is 0-based; the summit offset is relative to it.
        (pl.col("start") + pl.col("summit_offset") + 1).alias("summit"),
    )
    return df.select(list(EXPECTED_SCHEMA)).sort(["sample", "chr", "start"])
