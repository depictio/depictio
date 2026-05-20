"""Reshape the raw nf-core fixtures into tidy form for advanced viz.

Source: dev/advanced_viz_docs_screenshots/fixtures/<viz>/<file>
Target: depictio/projects/init/nfcore_megatests_showcase/data/

Drop-in fixtures (volcano, ma, qq, coverage_track) are copied straight by
extract_nfcore_fixtures.py — they aren't touched here. This script handles
the ones whose raw nf-core output needs reshape before depictio's column
schema can accept them:

    PCA enrichment       — add `condition` from sample naming convention
    DESeq2 vst top-N     — filter ~25k genes down to top-N most variable
    Rarefaction          — melt wide depth-N_iter-M cols to (depth, iter)
    Feature table        — strip `#` BIOM comment + melt sample cols
    DA barplot           — join lfc + q-val slices, melt contrast cols
    Sunburst (Bracken)   — keep as-is but copy into project data dir
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "dev" / "advanced_viz_docs_screenshots" / "fixtures"
DST = ROOT / "depictio" / "projects" / "init" / "nfcore_megatests_showcase" / "data"
DST.mkdir(parents=True, exist_ok=True)


def enrich_pca_with_condition() -> None:
    """Add a `condition` column to the rnaseq DESeq2 PCA so the embedding
    can colour by cluster. The megatest sample naming is `<COND>_REP<N>`."""
    df = pl.read_csv(SRC / "embedding" / "rnaseq_deseq2_pca.txt", separator="\t")
    df = df.with_columns(pl.col("Sample").str.replace(r"_REP\d+$", "").alias("condition"))
    out = DST / "rnaseq_pca.tsv"
    df.write_csv(out, separator="\t")
    print(f"  rnaseq_pca.tsv ({df.height} samples, {df['condition'].n_unique()} conditions)")


def top_n_variable_vst(n: int = 100) -> None:
    """Pick the top-N most-variable genes from the 25k×24 vst matrix.
    ComplexHeatmap chokes on 25k rows — and 100 is plenty for a demo."""
    df = pl.read_csv(SRC / "hierarchical_heatmap" / "deseq2_vst_matrix.tsv", separator="\t")
    sample_cols = [c for c in df.columns if c != "gene_id"]
    df = (
        df.with_columns(pl.concat_list([pl.col(c) for c in sample_cols]).list.var().alias("_var"))
        .sort("_var", descending=True)
        .head(n)
        .drop("_var")
    )
    out = DST / f"deseq2_vst_top{n}.tsv"
    df.write_csv(out, separator="\t")
    print(f"  {out.name} (top-{n} of 25k genes × {len(sample_cols)} samples)")


def melt_rarefaction() -> None:
    """QIIME2 alpha-rarefaction is wide: columns `depth-N_iter-M`.
    Melt to long form with depth + iter as separate columns."""
    df = pl.read_csv(SRC / "rarefaction" / "qiime2_alpha_rarefaction_shannon.csv")
    id_cols = [c for c in df.columns if not c.startswith("depth-")]
    melted = df.unpivot(index=id_cols, variable_name="depth_iter", value_name="metric")
    melted = melted.with_columns(
        [
            pl.col("depth_iter")
            .str.extract(r"depth-(\d+)_iter-\d+", 1)
            .cast(pl.Int64)
            .alias("depth"),
            pl.col("depth_iter")
            .str.extract(r"depth-\d+_iter-(\d+)", 1)
            .cast(pl.Int64)
            .alias("iter"),
        ]
    ).drop("depth_iter")
    melted = melted.rename({"sample-id": "sample_id"}).drop_nulls("metric")
    out = DST / "qiime2_rarefaction_tidy.tsv"
    melted.write_csv(out, separator="\t")
    print(f"  {out.name} ({melted.height} (sample, depth, iter) rows)")


def melt_feature_table() -> None:
    """QIIME2 feature-table has `# Constructed from biom file` then a `#OTU ID`
    column. Strip the comment and melt sample columns to (taxon, abundance)."""
    df = pl.read_csv(
        SRC / "stacked_taxonomy" / "qiime2_feature_table.tsv",
        separator="\t",
        comment_prefix="# ",  # the BIOM header line, but NOT the column header
        skip_rows=1,  # explicitly skip the BIOM comment line
    )
    # First column header in the file is `#OTU ID` (preserved as a column name).
    otu_col = df.columns[0]
    melted = (
        df.unpivot(index=[otu_col], variable_name="sample_id", value_name="abundance")
        .rename({otu_col: "taxon"})
        # Single-rank since the feature-table has no lineage — depictio's
        # stacked_taxonomy CANONICAL_SCHEMA requires `rank` so we stub it.
        .with_columns(pl.lit("OTU").alias("rank"))
        .filter(pl.col("abundance") > 0)
    )
    out = DST / "qiime2_stacked_taxonomy_tidy.tsv"
    melted.write_csv(out, separator="\t")
    print(f"  {out.name} ({melted.height} non-zero (sample, taxon) rows)")


def reshape_ancombc_da() -> None:
    """ANCOM-BC differentials ship as separate lfc + q_val files, each wide
    (one column per contrast). Join on `id`, melt contrast cols, rename."""
    lfc = pl.read_csv(SRC / "da_barplot_lfc" / "ancombc_lfc.csv")
    qval = pl.read_csv(SRC / "da_barplot_qval" / "ancombc_qval.csv")
    contrast_cols = [c for c in lfc.columns if c != "id"]
    lfc_m = lfc.unpivot(index=["id"], on=contrast_cols, variable_name="contrast", value_name="lfc")
    qval_m = qval.unpivot(
        index=["id"], on=contrast_cols, variable_name="contrast", value_name="significance"
    )
    combined = lfc_m.join(qval_m, on=["id", "contrast"]).rename({"id": "feature_id"})
    out = DST / "ancombc_da_barplot_tidy.tsv"
    combined.write_csv(out, separator="\t")
    print(f"  {out.name} ({combined.height} (feature, contrast) rows)")


def copy_bracken_for_sunburst() -> None:
    """Bracken per-sample TSV — used as-is with `taxonomy_lvl` as a
    single-level rank for the sunburst (the underlying Bracken format
    has no lineage hierarchy without further taxonkit lookup)."""
    src = SRC / "sunburst" / "bracken_sample.tsv"
    dst = DST / "bracken_sample.tsv"
    dst.write_bytes(src.read_bytes())
    print(f"  {dst.name} (copied as-is, single-rank sunburst)")


def main() -> None:
    print(f"Reshaping fixtures from {SRC.relative_to(ROOT)} → {DST.relative_to(ROOT)}\n")
    enrich_pca_with_condition()
    top_n_variable_vst()
    melt_rarefaction()
    melt_feature_table()
    reshape_ancombc_da()
    copy_bracken_for_sunburst()
    print(f"\nAll fixtures landed in {DST}")


if __name__ == "__main__":
    main()
