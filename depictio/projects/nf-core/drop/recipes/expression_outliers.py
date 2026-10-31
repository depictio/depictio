"""Aberrant expression calls of nf-core/drop: OUTRIDER outliers, one row per sample and gene.

DROP fits an OUTRIDER autoencoder to the gene counts of each aberrant-expression
group and writes ``OUTRIDER_results.tsv`` under
``processed_results/aberrant_expression/<annotation>/outrider/<group>/``: the genes
whose count in a sample is far from what the other samples predict, with the
z-score and the adjusted p-value of that distance. The file holds the rows that
pass the pipeline's own cut-offs (``ae_padj_cutoff``, ``ae_z_score_cutoff``). With the
defaults that is only the significant genes, so a volcano drawn from it has no
background and a sample with no outlier has no row; the per-sample table recounts
those zeros. Run the pipeline with ``--ae_padj_cutoff 1 --ae_z_score_cutoff 0`` and the
file holds every tested gene, which is what the dashboard's volcano, p-value histogram
and z-score spread need.

This recipe reads every group's file, takes the annotation and the group from the
path, applies the dashboard's thresholds (``padj``, ``min_z``) and adds the gene's
coordinates when the run also published its gene table
(``processed_results/mae/gene_name_mapping_<annotation>.tsv``, written by the MAE
sub-workflow). Without it the coordinates are null and the gene has no place on the
genome tabs.

Sources:
    results      every group's ``OUTRIDER_results.tsv``
    gene_models  the MAE gene table (optional): seqnames, start, end, strand, gene_id

A full file is large (every gene of every sample), so the near-null bulk is trimmed
here: a row is kept when it is called, when its adjusted p-value is at most 0.5, or when
it is one of the ``background`` most significant rows (smallest p-value) of its sample.
The kept rows still draw the whole outline of the volcano and the p-value distribution,
and the trimmed ones are the rows with nothing to say.

Params:
    padj        adjusted p-value at or below which a gene is called (default 0.05)
    min_z       absolute z-score at or above which a gene is called (default 0)
    nominal_p   raw p-value at or below which a gene is a nominal hit (default 0.05)
    background  rows per sample kept besides the called ones and those with an adjusted
                p-value of 0.5 or less (default 300; a negative value keeps every row)

Called and nominal. A call needs the adjusted p-value (``padj``, corrected over the
genes of the sample) under ``padj``. A small run, such as a test set of ten samples,
has so little power that every adjusted p-value is 1 and nothing is called, while the
raw p-values still rank the genes. Each row therefore also says whether it is a
**nominal hit** (``nominal``: raw ``p_value`` at or below ``nominal_p``, or called) and
carries ``status``: ``called (adjusted p)``, ``nominal p only`` or ``not significant``.
``neg_log10_p`` is the y of the volcano. A nominal hit is a lead to read with care (at
a 0.05 cut-off about one gene in twenty passes by chance), never a call.
``direction`` gives the sign of the z-score of every nominal hit.

Output schema: see ``OUTPUT_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="results",
        glob_pattern="processed_results/aberrant_expression/*/outrider/*/OUTRIDER_results.tsv",
        format="tsv",
        input_schema={
            "sampleID": pl.Utf8,
            "geneID": pl.Utf8,
            "pValue": pl.Utf8,
            "padjust": pl.Utf8,
            "zScore": pl.Utf8,
            "l2fc": pl.Utf8,
            "rawcounts": pl.Utf8,
        },
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
    # The gene table is comma-separated whatever its extension says.
    RecipeSource(
        ref="gene_models",
        glob_pattern="processed_results/mae/gene_name_mapping_*.tsv",
        format="csv",
        optional=True,
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "call_id": pl.Utf8,
    "sample": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "annotation": pl.Utf8,
    "drop_group": pl.Utf8,
    "status": pl.Utf8,
    "p_value": pl.Float64,
    "padj": pl.Float64,
    "z_score": pl.Float64,
    "abs_z_score": pl.Float64,
    "l2fc": pl.Float64,
    "neg_log10_p": pl.Float64,
    "neg_log10_padj": pl.Float64,
    "avg_log_count": pl.Float64,
    "raw_count": pl.Float64,
    "expected_count": pl.Float64,
    "mean_count": pl.Float64,
    "significant": pl.Boolean,
    "nominal": pl.Boolean,
    "direction": pl.Utf8,
    "hpo_match": pl.Boolean,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "fold_change": pl.Float64,
    "theta": pl.Float64,
    "aberrant_by_sample": pl.Int64,
    "aberrant_by_gene": pl.Int64,
    "hpo_label_overlap": pl.Utf8,
    "locus": pl.Utf8,
}

_MAX_LOG = 300.0
# Rows with an adjusted p-value up to this are always kept (see the module docstring).
KEEP_PADJ = 0.5
DEFAULT_BACKGROUND = 300
#: Raw p-value at or below which a row counts as a nominal hit (see the module docstring).
DEFAULT_NOMINAL_P = 0.05
#: ``status`` vocabulary, strongest first.
STATUS_CALLED = "called (adjusted p)"
STATUS_NOMINAL = "nominal p only"
STATUS_NONE = "not significant"


def _num(name: str) -> pl.Expr:
    """A result column as a number: NA and empty cells are null."""
    return pl.col(name).cast(pl.Float64, strict=False)


def _opt(df: pl.DataFrame, name: str, dtype: pl.DataType = pl.Float64) -> pl.Expr:
    """A column the pipeline may not write, as ``dtype`` (absent: null)."""
    if name not in df.columns:
        return pl.lit(None, dtype=dtype)
    return pl.col(name).cast(dtype, strict=False)


def _gene_coordinates(models: pl.DataFrame | None) -> pl.DataFrame | None:
    """One row per gene id with its chromosome, start and end."""
    if models is None or models.is_empty():
        return None
    needed = {"seqnames", "start", "end", "gene_id"}
    if not needed <= set(models.columns):
        return None
    return (
        models.select(
            pl.col("gene_id").cast(pl.Utf8).alias("gene_id"),
            pl.col("seqnames").cast(pl.Utf8).alias("chrom"),
            pl.col("start").cast(pl.Int64, strict=False).alias("start"),
            pl.col("end").cast(pl.Int64, strict=False).alias("end"),
        )
        .unique(subset="gene_id", keep="first")
        .with_columns(pl.col("chrom").is_not_null().alias("_has_coordinates"))
    )


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """One row per outlier call, thresholds applied, coordinates joined when known."""
    p = params or {}
    padj_cut = float(p.get("padj") or 0.05)
    min_z = float(p.get("min_z") or 0.0)
    nominal_p = float(p.get("nominal_p") or DEFAULT_NOMINAL_P)
    background = int(p.get("background") or DEFAULT_BACKGROUND)

    raw = sources["results"]
    path = pl.col("source_path").str.split("/")
    gene_name = pl.col("hgncSymbol").cast(pl.Utf8) if "hgncSymbol" in raw.columns else pl.lit(None)
    res = raw.select(
        pl.col("sampleID").cast(pl.Utf8).alias("sample"),
        pl.col("geneID").cast(pl.Utf8).alias("gene_id"),
        pl.coalesce(gene_name, pl.col("geneID")).alias("gene_name"),
        path.list.get(2).alias("annotation"),
        path.list.get(4).alias("drop_group"),
        _num("zScore").alias("z_score"),
        _num("l2fc").alias("l2fc"),
        _num("pValue").alias("p_value"),
        _num("padjust").alias("padj"),
        _num("rawcounts").alias("raw_count"),
        _opt(raw, "meanCorrected").alias("expected_count"),
        _opt(raw, "meanRawcounts").alias("mean_count"),
        _opt(raw, "foldChange").alias("fold_change"),
        _opt(raw, "theta").alias("theta"),
        _opt(raw, "AberrantBySample", pl.Int64).alias("aberrant_by_sample"),
        _opt(raw, "AberrantByGene", pl.Int64).alias("aberrant_by_gene"),
        _opt(raw, "HPO_label_overlap", pl.Utf8).alias("hpo_label_overlap"),
        _opt(raw, "HPO_id_overlap", pl.Utf8).alias("_hpo_ids"),
    ).filter(pl.col("sample").is_not_null() & pl.col("gene_id").is_not_null())

    significant = (pl.col("padj") <= padj_cut) & (pl.col("z_score").abs() >= min_z)
    res = (
        res.with_columns(
            (pl.col("sample") + pl.lit(":") + pl.col("gene_id")).alias("call_id"),
            pl.col("z_score").abs().alias("abs_z_score"),
            pl.col("padj")
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
            # The MA view's average abundance: log2 of the count the model expects.
            (pl.col("expected_count").clip(0.0, None) + 1.0).log(2.0).alias("avg_log_count"),
            significant.fill_null(False).alias("significant"),
            (pl.col("_hpo_ids").is_not_null() & (pl.col("_hpo_ids") != "")).alias("hpo_match"),
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
            .when(pl.col("z_score") > 0)
            .then(pl.lit("over-expressed"))
            .otherwise(pl.lit("under-expressed"))
            .alias("direction"),
        )
    )

    if background >= 0:
        # The most significant rows of each sample by raw p-value, then the stronger z-score.
        rank = pl.int_range(pl.len()).over(["drop_group", "sample"])
        res = (
            res.sort(["p_value", "abs_z_score"], descending=[False, True], nulls_last=True)
            .with_columns(rank.alias("_rank"))
            .filter(
                pl.col("nominal") | (pl.col("padj") <= KEEP_PADJ) | (pl.col("_rank") < background)
            )
            .drop("_rank")
        )

    coords = _gene_coordinates(sources.get("gene_models"))
    if coords is not None:
        res = res.join(coords.drop("_has_coordinates"), on="gene_id", how="left")
    else:
        res = res.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("chrom"),
            pl.lit(None, dtype=pl.Int64).alias("start"),
            pl.lit(None, dtype=pl.Int64).alias("end"),
        )
    res = res.with_columns(
        pl.when(pl.col("chrom").is_not_null() & pl.col("start").is_not_null())
        .then(
            pl.col("chrom")
            + pl.lit(":")
            + pl.col("start").cast(pl.Utf8)
            + pl.lit("-")
            + pl.col("end").cast(pl.Utf8)
        )
        .otherwise(None)
        .alias("locus")
    )
    head = list(OUTPUT_SCHEMA)
    optional = [c for c in OPTIONAL_OUTPUT_SCHEMA if c in res.columns]
    # Strongest evidence first: the raw p-value orders rows when every padj is 1.
    return res.select(head + optional).sort(
        ["p_value", "padj", "sample", "gene_name"], nulls_last=True
    )
