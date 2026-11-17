"""Aberrant splicing calls of nf-core/drop: FRASER outliers, one row per sample and gene.

DROP fits FRASER to the split-read counts of each aberrant-splicing group and writes
``results.tsv`` under
``processed_results/aberrant_splicing/results/<annotation>/fraser/<group>/``: the
junctions whose usage in a sample departs from the other samples, aggregated per
gene (a sample and gene pair is represented by its most significant junction). Each
row carries the junction's coordinates, its usage in the sample (``psiValue``), the
change against the cohort (``deltaPsi``), the gene-level adjusted p-value and the
annotation of the junction's two splice sites.

The file holds the rows that pass the pipeline's cut-offs (``as_padj_cutoff``,
``as_delta_psi_cutoff``). With the defaults that is only the significant junctions, so
a volcano drawn from it has no background; run the pipeline with ``--as_padj_cutoff 1
--as_delta_psi_cutoff 0`` and the file holds every tested junction. This recipe reads
every group's file, takes the annotation and the group from the path, applies the
dashboard's thresholds (``padj``, ``min_dpsi``) and trims the near-null bulk: a row is
kept when it is called, when its gene-level adjusted p-value is at most 0.5, or when it
is one of the ``background`` most significant rows (smallest p-value) of its sample.

Sources:
    results   every group's FRASER ``results.tsv``

Params:
    padj        gene-level adjusted p-value at or below which a gene is called (default 0.1)
    min_dpsi    absolute change in splicing usage at or above which it is called (default 0.3)
    nominal_p   raw junction p-value at or below which a row is a nominal hit (default 0.05)
    background  rows per sample kept besides the called ones and those with a gene-level
                adjusted p-value of 0.5 or less (default 300; a negative value keeps all)

Called and nominal. A call needs the gene-level adjusted p-value under ``padj`` and a
change past ``min_dpsi``. A small run (a test set of ten samples) has so little power
that every adjusted p-value is 1 and nothing is called, while the raw p-values still
rank the junctions. Each row therefore also says whether it is a **nominal hit**
(``nominal``: raw ``p_value`` at or below ``nominal_p``, or called) and carries
``status``: ``called (adjusted p)``, ``nominal p only`` or ``not significant``.
``neg_log10_p`` is the y of the volcano. A nominal hit is a lead to read with care,
never a call. ``direction`` gives the sign of the change of every nominal hit.

Output schema: see ``OUTPUT_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="results",
        glob_pattern="processed_results/aberrant_splicing/results/*/fraser/*/results.tsv",
        format="tsv",
        input_schema={
            "sampleID": pl.Utf8,
            "hgncSymbol": pl.Utf8,
            "seqnames": pl.Utf8,
            "start": pl.Utf8,
            "end": pl.Utf8,
            "type": pl.Utf8,
            "deltaPsi": pl.Utf8,
            "padjust": pl.Utf8,
        },
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "call_id": pl.Utf8,
    "sample": pl.Utf8,
    "gene_name": pl.Utf8,
    "annotation": pl.Utf8,
    "drop_group": pl.Utf8,
    "status": pl.Utf8,
    "p_value": pl.Float64,
    "padj_gene": pl.Float64,
    "delta_psi": pl.Float64,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "locus": pl.Utf8,
    "strand": pl.Utf8,
    "psi_type": pl.Utf8,
    "psi_value": pl.Float64,
    "abs_delta_psi": pl.Float64,
    "padj": pl.Float64,
    "neg_log10_p": pl.Float64,
    "neg_log10_padj": pl.Float64,
    "avg_log_reads": pl.Float64,
    "split_reads": pl.Float64,
    "total_reads": pl.Float64,
    "significant": pl.Boolean,
    "nominal": pl.Boolean,
    "direction": pl.Utf8,
    "hpo_match": pl.Boolean,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "junction_width": pl.Int64,
    "mean_split_reads": pl.Float64,
    "mean_total_reads": pl.Float64,
    "nonsplit_reads": pl.Float64,
    "nonsplit_proportion": pl.Float64,
    "annotated_junction": pl.Utf8,
    "potential_impact": pl.Utf8,
    "causes_frameshift": pl.Utf8,
    "utr_overlap": pl.Utf8,
    "blacklisted": pl.Boolean,
    "hpo_label_overlap": pl.Utf8,
}

_MAX_LOG = 300.0
# Rows with a gene-level adjusted p-value up to this are always kept.
KEEP_PADJ = 0.5
DEFAULT_BACKGROUND = 300
#: Raw p-value at or below which a row counts as a nominal hit (see the module docstring).
DEFAULT_NOMINAL_P = 0.05
#: ``status`` vocabulary, strongest first.
STATUS_CALLED = "called (adjusted p)"
STATUS_NOMINAL = "nominal p only"
STATUS_NONE = "not significant"
_TRUE = ("true", "t", "1", "yes")
_NA = ["", "NA", "nan"]

# FRASER writes the splice type under its own names: psi5 / psi3 / theta (FRASER 1)
# or jaccard (FRASER 2).
_TYPES = {
    "psi5": "psi5 (donor)",
    "psi3": "psi3 (acceptor)",
    "theta": "theta (intron retention)",
    "jaccard": "jaccard (intron usage)",
}


def _num(df: pl.DataFrame, name: str, dtype: pl.DataType = pl.Float64) -> pl.Expr:
    """A result column as a number, NA cells null (absent column: null)."""
    if name not in df.columns:
        return pl.lit(None, dtype=dtype)
    text = pl.col(name).cast(pl.Utf8).str.strip_chars()
    return pl.when(text.is_in(_NA)).then(None).otherwise(text).cast(dtype, strict=False)


def _text(df: pl.DataFrame, name: str) -> pl.Expr:
    """A result column as text, NA cells null (absent column: null)."""
    if name not in df.columns:
        return pl.lit(None, dtype=pl.Utf8)
    text = pl.col(name).cast(pl.Utf8).str.strip_chars()
    return pl.when(text.is_in(_NA)).then(None).otherwise(text)


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """One row per outlier call, thresholds applied."""
    p = params or {}
    padj_cut = float(p.get("padj") or 0.1)
    min_dpsi = float(p.get("min_dpsi") or 0.3)
    nominal_p = float(p.get("nominal_p") or DEFAULT_NOMINAL_P)
    background = int(p.get("background") or DEFAULT_BACKGROUND)

    raw = sources["results"]
    path = pl.col("source_path").str.split("/")
    padj_gene = _num(raw, "padjustGene")
    res = raw.select(
        _text(raw, "sampleID").alias("sample"),
        pl.coalesce(_text(raw, "hgncSymbol"), pl.lit("unannotated")).alias("gene_name"),
        path.list.get(3).alias("annotation"),
        path.list.get(5).alias("drop_group"),
        _text(raw, "seqnames").alias("chrom"),
        _num(raw, "start", pl.Int64).alias("start"),
        _num(raw, "end", pl.Int64).alias("end"),
        _text(raw, "strand").alias("strand"),
        _text(raw, "type").alias("_type"),
        _num(raw, "psiValue").alias("psi_value"),
        _num(raw, "deltaPsi").alias("delta_psi"),
        _num(raw, "pValue").alias("p_value"),
        _num(raw, "padjust").alias("padj"),
        padj_gene.alias("_padj_gene"),
        _num(raw, "counts").alias("split_reads"),
        _num(raw, "totalCounts").alias("total_reads"),
        _num(raw, "width", pl.Int64).alias("junction_width"),
        _num(raw, "meanCounts").alias("mean_split_reads"),
        _num(raw, "meanTotalCounts").alias("mean_total_reads"),
        _num(raw, "nonsplitCounts").alias("nonsplit_reads"),
        _num(raw, "nonsplitProportion").alias("nonsplit_proportion"),
        _text(raw, "annotatedJunction").alias("annotated_junction"),
        _text(raw, "potentialImpact").alias("potential_impact"),
        _text(raw, "causesFrameshift").alias("causes_frameshift"),
        _text(raw, "UTR_overlap").alias("utr_overlap"),
        _text(raw, "blacklist").str.to_lowercase().is_in(list(_TRUE)).alias("blacklisted"),
        _text(raw, "HPO_label_overlap").alias("hpo_label_overlap"),
        _text(raw, "HPO_id_overlap").alias("_hpo_ids"),
    ).filter(pl.col("sample").is_not_null() & pl.col("chrom").is_not_null())

    res = (
        res.with_columns(
            pl.col("_type").replace(_TYPES).alias("psi_type"),
            pl.col("delta_psi").abs().alias("abs_delta_psi"),
            # The gene-level value when the file has it, else the junction's own.
            pl.coalesce(pl.col("_padj_gene"), pl.col("padj")).alias("padj_gene"),
            pl.col("_hpo_ids").is_not_null().alias("hpo_match"),
        )
        .with_columns(
            pl.col("padj_gene")
            .clip(1e-300, 1.0)
            .log10()
            .abs()
            .clip(0.0, _MAX_LOG)
            .alias("neg_log10_padj"),
            pl.col("p_value")
            .clip(1e-300, 1.0)
            .log10()
            .abs()
            .clip(0.0, _MAX_LOG)
            .alias("neg_log10_p"),
            # The MA view's average abundance: log2 of the cohort's mean total reads.
            (pl.col("mean_total_reads").clip(0.0, None) + 1.0).log(2.0).alias("avg_log_reads"),
            ((pl.col("padj_gene") <= padj_cut) & (pl.col("abs_delta_psi") >= min_dpsi))
            .fill_null(False)
            .alias("significant"),
            (
                pl.col("chrom")
                + pl.lit(":")
                + pl.col("start").cast(pl.Utf8)
                + pl.lit("-")
                + pl.col("end").cast(pl.Utf8)
            ).alias("locus"),
        )
        .with_columns(
            # One row per sample, gene and junction: the key a table selection carries.
            (
                pl.col("sample") + pl.lit(":") + pl.col("gene_name") + pl.lit(":") + pl.col("locus")
            ).alias("call_id"),
        )
        .with_columns(
            (pl.col("significant") | (pl.col("p_value") <= nominal_p).fill_null(False)).alias(
                "nominal"
            )
        )
        .with_columns(
            pl.when(pl.col("significant"))
            .then(pl.lit(STATUS_CALLED))
            .when(pl.col("nominal"))
            .then(pl.lit(STATUS_NOMINAL))
            .otherwise(pl.lit(STATUS_NONE))
            .alias("status"),
            pl.when(~pl.col("nominal"))
            .then(pl.lit("not significant"))
            .when(pl.col("delta_psi") > 0)
            .then(pl.lit("more usage"))
            .otherwise(pl.lit("less usage"))
            .alias("direction"),
        )
    )
    if background >= 0:
        # The most significant rows of each sample by raw p-value, then the larger change.
        rank = pl.int_range(pl.len()).over(["drop_group", "sample"])
        res = (
            res.sort(["p_value", "abs_delta_psi"], descending=[False, True], nulls_last=True)
            .with_columns(rank.alias("_rank"))
            .filter(
                pl.col("nominal")
                | (pl.col("padj_gene") <= KEEP_PADJ)
                | (pl.col("_rank") < background)
            )
            .drop("_rank")
        )
    head = list(OUTPUT_SCHEMA)
    optional = [c for c in OPTIONAL_OUTPUT_SCHEMA if c in res.columns]
    # Strongest evidence first: the raw p-value orders rows when every padj is 1.
    return res.select(head + optional).sort(
        ["p_value", "padj_gene", "sample", "gene_name"], nulls_last=True
    )
