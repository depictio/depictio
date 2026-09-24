"""rMATS differential alternative splicing events, all five event types stacked.

rMATS (``rmats.py --task post``) writes, per contrast directory, one table per
event type and read-count model: ``<TYPE>.MATS.JC.txt`` (junction reads only)
and ``<TYPE>.MATS.JCEC.txt`` (junction plus reads on the alternative exon
body), for skipped exons (SE), retained introns (RI), mutually exclusive exons
(MXE) and alternative 3' / 5' splice sites (A3SS / A5SS). Each row is one event:
its gene, coordinates, per-replicate inclusion (IJC) and skipping (SJC) junction
counts, per-replicate PSI (``IncLevel1`` / ``IncLevel2``), their difference and
the likelihood-ratio p-value with its FDR.

This recipe reads the JCEC tables (repoint the glob to ``*.MATS.JC.txt`` for the
junction-only model) and keeps one row per contrast and event. The contrast is
the name of the directory rMATS wrote into (``<contrast>/rmats_post/`` in
nf-core/rnasplice): the file names carry the event type only.

Orientation: rnasplice passes the treatment BAMs as ``--b1``, so
``IncLevelDifference`` (sample 1 minus sample 2) is already treatment minus
control.

Low-coverage events carry a PSI that is mostly noise, so events whose mean
junction read count (inclusion plus skipping, averaged over the replicates)
falls below ``min_reads`` in either condition are dropped. 10 reads is the
customary rMATS post-filter; it is a template variable.

Sources:
    events   every ``*.MATS.JCEC.txt`` under the run root.

Params:
    fdr        FDR cut-off (default 0.05).
    min_dpsi   minimal absolute inclusion difference for a call (default 0.1).
    min_reads  mean junction reads per replicate required in both conditions (default 10).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="events",
        glob_pattern="**/*.MATS.JCEC.txt",
        format="tsv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", "NaN", ""]},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "event_id": pl.Utf8,
    "event_type": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "chrom": pl.Utf8,
    "strand": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "locus": pl.Utf8,
    "psi_treatment": pl.Float64,
    "psi_control": pl.Float64,
    "dpsi": pl.Float64,
    "abs_dpsi": pl.Float64,
    "pvalue": pl.Float64,
    "fdr": pl.Float64,
    "neg_log10_fdr": pl.Float64,
    "reads_treatment": pl.Float64,
    "reads_control": pl.Float64,
    "significant": pl.Boolean,
    "direction": pl.Utf8,
}

DEFAULTS = {"fdr": 0.05, "min_dpsi": 0.1, "min_reads": 10.0}
FDR_ZERO_NEG_LOG10 = 300.0
EVENT_LABELS = {
    "SE": "Skipped exon",
    "RI": "Retained intron",
    "MXE": "Mutually exclusive exons",
    "A3SS": "Alternative 3' splice site",
    "A5SS": "Alternative 5' splice site",
}
_TYPE = r"(SE|RI|MXE|A3SS|A5SS)\.MATS\.JC(?:EC)?\.txt$"
_CONTRAST = r"([^/]+)/(?:rmats_post/)?[^/]+\.MATS\.JC(?:EC)?\.txt$"

# The alternative region of each event type, 0-based start column and end column.
_REGION = {
    "SE": ("exonStart_0base", "exonEnd"),
    "RI": ("upstreamEE", "downstreamES"),
    "MXE": ("1stExonStart_0base", "2ndExonEnd"),
    "A3SS": ("longExonStart_0base", "longExonEnd"),
    "A5SS": ("longExonStart_0base", "longExonEnd"),
}


def param(params: dict[str, str] | None, name: str) -> float:
    raw = str((params or {}).get(name) or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULTS[name]
    return value if value >= 0 else DEFAULTS[name]


def mean_of_list(col: str) -> pl.Expr:
    """Mean of a comma-separated per-replicate field (``414,456,475``), NA skipped."""
    return (
        pl.col(col)
        .cast(pl.Utf8)
        .str.split(",")
        .list.eval(pl.element().cast(pl.Float64, strict=False))
        .list.mean()
    )


def summed_mean(first: str, second: str) -> pl.Expr:
    """Per-replicate ``first + second`` counts, averaged over the replicates."""
    a = pl.col(first).cast(pl.Utf8).str.split(",").list.eval(pl.element().cast(pl.Float64))
    b = pl.col(second).cast(pl.Utf8).str.split(",").list.eval(pl.element().cast(pl.Float64))
    return (a.list.sum() + b.list.sum()) / a.list.len()


def region(df: pl.DataFrame, which: int) -> pl.Expr:
    """``start`` (1-based) or ``end`` of the alternative region, per event type."""
    expr = pl.lit(None, dtype=pl.Int64)
    for event_type, cols in _REGION.items():
        col = cols[which]
        if col not in df.columns:
            continue
        value = pl.col(col).cast(pl.Int64, strict=False) + (1 if which == 0 else 0)
        expr = pl.when(pl.col("_type") == event_type).then(value).otherwise(expr)
    return expr


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """One row per contrast and covered event, with the significance call."""
    fdr, min_dpsi, min_reads = (param(params, k) for k in ("fdr", "min_dpsi", "min_reads"))
    df = sources["events"].with_columns(
        pl.col("source_path").str.extract(_TYPE, 1).alias("_type"),
        pl.col("source_path").str.extract(_CONTRAST, 1).alias("contrast"),
    )
    out = df.select(
        pl.col("contrast"),
        (pl.col("_type") + pl.lit("_") + pl.col("ID").cast(pl.Utf8)).alias("event_id"),
        pl.col("_type").replace_strict(EVENT_LABELS, default=pl.col("_type")).alias("event_type"),
        pl.col("GeneID").cast(pl.Utf8).str.strip_chars('"').alias("gene_id"),
        pl.col("geneSymbol").cast(pl.Utf8).str.strip_chars('"').alias("gene_name"),
        pl.col("chr").cast(pl.Utf8).alias("chrom"),
        pl.col("strand").cast(pl.Utf8),
        region(df, 0).alias("start"),
        region(df, 1).alias("end"),
        mean_of_list("IncLevel1").alias("psi_treatment"),
        mean_of_list("IncLevel2").alias("psi_control"),
        pl.col("IncLevelDifference").cast(pl.Float64, strict=False).alias("dpsi"),
        pl.col("PValue").cast(pl.Float64, strict=False).alias("pvalue"),
        pl.col("FDR").cast(pl.Float64, strict=False).alias("fdr"),
        summed_mean("IJC_SAMPLE_1", "SJC_SAMPLE_1").alias("reads_treatment"),
        summed_mean("IJC_SAMPLE_2", "SJC_SAMPLE_2").alias("reads_control"),
    )
    out = out.filter(
        pl.col("dpsi").is_not_null()
        & (pl.col("reads_treatment") >= min_reads)
        & (pl.col("reads_control") >= min_reads)
    )
    significant = (pl.col("fdr") < fdr) & (pl.col("dpsi").abs() >= min_dpsi)
    out = out.with_columns(
        pl.col("gene_name").replace("NA", None).fill_null(pl.col("gene_id")),
        (
            pl.col("chrom")
            + pl.lit(":")
            + pl.col("start").cast(pl.Utf8)
            + pl.lit("-")
            + pl.col("end").cast(pl.Utf8)
        ).alias("locus"),
        pl.col("dpsi").abs().alias("abs_dpsi"),
        pl.when(pl.col("fdr") > 0)
        .then(-pl.col("fdr").log10())
        .when(pl.col("fdr") == 0)
        .then(pl.lit(FDR_ZERO_NEG_LOG10))
        .otherwise(None)
        .alias("neg_log10_fdr"),
        significant.fill_null(False).alias("significant"),
    ).with_columns(
        pl.when(~pl.col("significant"))
        .then(pl.lit("not significant"))
        .when(pl.col("dpsi") > 0)
        .then(pl.lit("up"))
        .otherwise(pl.lit("down"))
        .alias("direction")
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(["contrast", "fdr"], nulls_last=True)
