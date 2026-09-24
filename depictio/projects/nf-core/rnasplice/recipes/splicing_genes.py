"""Cross-tool differential splicing per gene: which tools call each gene.

nf-core/rnasplice answers "which genes are spliced differently?" with up to
five tools, each at its own resolution: DEXSeq on exonic bins, edgeR
``diffSpliceDGE`` on exons, DEXSeq on transcripts (DTU), rMATS and SUPPA2 on
local events. This recipe brings them to one row per contrast and gene, with
one boolean per tool (the gene is called by that tool), how many tools tested
and called it, and each tool's strongest evidence, so an UpSet plot can show
where the tools agree and a gene record can show the evidence side by side.

A gene is called by:
    dexseq_exon  its DEXSeq gene q-value is significant (``dexseq/exon_genes.py``)
    dexseq_dtu   its DEXSeq DTU gene q-value is significant (``dexseq/dtu.py``)
    edger        its edgeR gene-level F-test FDR is significant (``edger/diffsplice_genes.py``)
    rmats        at least one of its rMATS events is significant (``rmats/events.py``)
    suppa        at least one of its SUPPA2 local events is significant (``suppa/local_events.py``)
Each source recipe applies the run's thresholds; this one only aggregates.

Every source is optional (a run may skip any tool); a missing tool leaves its
column false and its evidence null. Overlapping loci that a tool could not
separate (DEXSeq ``ENSG1+ENSG2``, SUPPA ``ENSG1_and_ENSG2``) count for each
gene they name. Gene symbols come from rMATS, the only tool that reports them.

Output schema: see ``EXPECTED_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="dexseq_exon", dc_ref="dexseq_exon_genes", optional=True),
    RecipeSource(ref="dexseq_dtu", dc_ref="dexseq_dtu", optional=True),
    RecipeSource(ref="edger", dc_ref="edger_genes", optional=True),
    RecipeSource(ref="rmats", dc_ref="rmats_events", optional=True),
    RecipeSource(ref="suppa", dc_ref="suppa_events", optional=True),
]

TOOLS: dict[str, str] = {
    "dexseq_exon": "DEXSeq exon",
    "dexseq_dtu": "DEXSeq DTU",
    "edger": "edgeR",
    "rmats": "rMATS",
    "suppa": "SUPPA2",
}

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "dexseq_exon": pl.Boolean,
    "dexseq_dtu": pl.Boolean,
    "edger": pl.Boolean,
    "rmats": pl.Boolean,
    "suppa": pl.Boolean,
    "tools_tested": pl.Int64,
    "tools_significant": pl.Int64,
    "tools": pl.Utf8,
    "dexseq_exon_padj": pl.Float64,
    "dexseq_exon_log2fc": pl.Float64,
    "dexseq_dtu_padj": pl.Float64,
    "edger_fdr": pl.Float64,
    "edger_log2fc": pl.Float64,
    "rmats_events_significant": pl.Int64,
    "rmats_max_abs_dpsi": pl.Float64,
    "rmats_min_fdr": pl.Float64,
    "suppa_events_significant": pl.Int64,
    "suppa_max_abs_dpsi": pl.Float64,
    "suppa_min_pvalue": pl.Float64,
}

_SPLIT = r"\+|_and_"


def _explode_genes(df: pl.DataFrame) -> pl.DataFrame:
    """One row per gene a (possibly aggregated) gene id names."""
    return df.with_columns(
        pl.col("gene_id").cast(pl.Utf8).str.replace_all(_SPLIT, "|").str.split("|")
    ).explode("gene_id")


def _usable(df: pl.DataFrame | None, *cols: str) -> bool:
    return df is not None and not df.is_empty() and all(c in df.columns for c in cols)


def _per_tool(sources: dict[str, pl.DataFrame | None]) -> list[pl.DataFrame]:
    """One (contrast, gene_id, <tool>, evidence...) frame per tool that ran."""
    frames: list[pl.DataFrame] = []
    df = sources.get("dexseq_exon")
    if _usable(df, "contrast", "gene_id", "padj", "significant"):
        frames.append(
            _explode_genes(df)
            .group_by("contrast", "gene_id")
            .agg(
                pl.col("significant").any().alias("dexseq_exon"),
                pl.col("padj").min().alias("dexseq_exon_padj"),
                pl.col("log2fc").sort_by(pl.col("padj")).first().alias("dexseq_exon_log2fc"),
            )
        )
    df = sources.get("dexseq_dtu")
    if _usable(df, "contrast", "gene_id", "gene_padj", "gene_significant"):
        frames.append(
            _explode_genes(df)
            .group_by("contrast", "gene_id")
            .agg(
                pl.col("gene_significant").any().alias("dexseq_dtu"),
                pl.col("gene_padj").min().alias("dexseq_dtu_padj"),
            )
        )
    df = sources.get("edger")
    if _usable(df, "contrast", "gene_id", "fdr", "significant"):
        frames.append(
            _explode_genes(df)
            .group_by("contrast", "gene_id")
            .agg(
                pl.col("significant").any().alias("edger"),
                pl.col("fdr").min().alias("edger_fdr"),
                pl.col("log2fc").sort_by(pl.col("fdr")).first().alias("edger_log2fc"),
            )
        )
    df = sources.get("rmats")
    if _usable(df, "contrast", "gene_id", "fdr", "abs_dpsi", "significant"):
        frames.append(
            _explode_genes(df)
            .group_by("contrast", "gene_id")
            .agg(
                pl.col("significant").any().alias("rmats"),
                pl.col("significant").sum().cast(pl.Int64).alias("rmats_events_significant"),
                pl.col("abs_dpsi").filter(pl.col("significant")).max().alias("rmats_max_abs_dpsi"),
                pl.col("fdr").min().alias("rmats_min_fdr"),
            )
        )
    df = sources.get("suppa")
    if _usable(df, "contrast", "gene_id", "pvalue", "abs_dpsi", "significant"):
        frames.append(
            _explode_genes(df)
            .group_by("contrast", "gene_id")
            .agg(
                pl.col("significant").any().alias("suppa"),
                pl.col("significant").sum().cast(pl.Int64).alias("suppa_events_significant"),
                pl.col("abs_dpsi").filter(pl.col("significant")).max().alias("suppa_max_abs_dpsi"),
                pl.col("pvalue").min().alias("suppa_min_pvalue"),
            )
        )
    return frames


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per contrast and gene with the per-tool calls and evidence."""
    frames = _per_tool(sources)
    if not frames:
        raise ValueError("rnasplice splicing_genes: no differential splicing tool output")
    out = frames[0]
    for frame in frames[1:]:
        out = out.join(frame, on=["contrast", "gene_id"], how="full", coalesce=True)

    tested = [pl.col(t).is_not_null().cast(pl.Int64) for t in TOOLS if t in out.columns]
    out = out.with_columns(pl.sum_horizontal(tested).alias("tools_tested"))
    out = out.with_columns(
        [
            (pl.col(c).fill_null(False) if c in out.columns else pl.lit(False)).alias(c)
            for c in TOOLS
        ]
    )
    out = out.with_columns(
        pl.sum_horizontal([pl.col(t).cast(pl.Int64) for t in TOOLS]).alias("tools_significant"),
        pl.concat_str(
            [pl.when(pl.col(t)).then(pl.lit(label)) for t, label in TOOLS.items()],
            separator=", ",
            ignore_nulls=True,
        ).alias("tools"),
    ).with_columns(
        pl.when(pl.col("tools") == "")
        .then(pl.lit("none"))
        .otherwise(pl.col("tools"))
        .alias("tools")
    )

    rmats = sources.get("rmats")
    if _usable(rmats, "gene_id", "gene_name"):
        names = (
            _explode_genes(rmats.select("gene_id", "gene_name"))
            .filter(pl.col("gene_name") != pl.col("gene_id"))
            .unique(subset="gene_id", keep="first")
        )
        out = out.join(names, on="gene_id", how="left")
    if "gene_name" not in out.columns:
        out = out.with_columns(pl.lit(None, dtype=pl.Utf8).alias("gene_name"))
    out = out.with_columns(pl.col("gene_name").fill_null(pl.col("gene_id")))

    out = out.with_columns(
        [pl.lit(None, dtype=t).alias(c) for c, t in EXPECTED_SCHEMA.items() if c not in out.columns]
    ).with_columns([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()])
    return out.select(list(EXPECTED_SCHEMA)).sort(
        ["contrast", "tools_significant", "gene_id"], descending=[False, True, False]
    )
