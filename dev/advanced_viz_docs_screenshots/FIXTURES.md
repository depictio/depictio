# nf-core fixture manifest

Real outputs pulled from `s3://nf-core-awsmegatests/` via `extract_nfcore_fixtures.py`. Use them to manually verify each viz_kind against actual pipeline output, and as a starter set for future CI `validate_binding()` checks.

## Drop-in (load and bind, no reshape)

These files load straight into depictio as a Table DC. Columns already match (or are within renaming distance of) the documented role schema.

| Viz | Fixture | Bind these columns → roles | Polars kwargs |
|---|---|---|---|
| **volcano** | `volcano/deseq2_results.tsv` | `gene_id` → `feature_id`, `log2FoldChange` → `effect_size`, `padj` → `significance` | — |
| **ma** | `ma/deseq2_results.tsv` *(same file)* | `gene_id` → `feature_id`, `baseMean` → `avg_log_intensity` (log first), `log2FoldChange` → `log2_fold_change`, `padj` → `significance` | — |
| **qq** | `qq/deseq2_results.tsv` *(same file)* | `pvalue` → `p_value` (any single p-value col fits) | — |
| **hierarchical_heatmap** | `hierarchical_heatmap/deseq2_vst_matrix.tsv` | `gene_id` → row label; Sample1..N are the matrix columns | — |
| **coverage_track** | `coverage_track/mosdepth_coverage.tsv` | `chrom` → `chromosome`, `start` → `position`, `coverage` → `value`, `end` → `end`, `sample` → `sample` | — |
| **sunburst** | `sunburst/bracken_sample.tsv` | `taxonomy_lvl` + `name` → rank chain (need to split `name` on `;` if Bracken-style lineage), `new_est_reads` → `abundance` | — |
| **embedding** | `embedding/rnaseq_deseq2_pca.txt` | `Sample` → `sample_id`, `x` → `dim_1`, `y` → `dim_2` | — |
| **phylogenetic** | `phylogenetic/qiime2_tree.nwk` | Newick string — store as a phylogeny DC; bring your own metadata TSV with a `taxon` column joining tip labels | — |

## Needs preprocessing

Files that match the *intent* of the viz but require a polars-kwargs nudge, a column rename, or a melt before binding.

| Viz | Fixture | What it needs | Polars kwargs |
|---|---|---|---|
| **stacked_taxonomy** | `stacked_taxonomy/qiime2_feature_table.tsv` | Skip the `# Constructed from biom file` comment line. The result is wide (sample×taxon); `melt` to long form (sample_id, taxon, abundance) and add a `rank` column. | `comment_prefix: "#"` then polars `.melt` |
| **rarefaction** | `rarefaction/qiime2_alpha_rarefaction_shannon.csv` | WIDE 449-column table (`sample-id`, `depth-N_iter-M` × many). Melt to long form with columns: `sample`, `depth`, `iter`, `metric`. | polars `.melt(id_vars=["sample-id"])` + regex split of variable name |
| **da_barplot** | `da_barplot_lfc/ancombc_lfc.csv` + `da_barplot_qval/ancombc_qval.csv` | Join on `id`, melt across contrast columns (`mix8a`, ...) to get tidy `(feature_id, contrast, lfc, q_value)`. | polars `.join` + `.melt` |
| **lollipop** | `lollipop/ivar_variants.vcf.gz` | VCF with `##` metadata + `#CHROM` column header. Either pre-flatten with `bcftools query -H -f '%CHROM\t%POS\t%INFO/ANN\n'` OR set `comment_prefix: "##"` and rename `#CHROM` → `CHROM`. Then parse the ANN field for `consequence`. | `compression: gzip`, `comment_prefix: "##"`, `new_columns` after rename |

## Not covered (no nf-core source available)

Six viz kinds lack a clean canonical fixture in the pipelines we surveyed:

- **enrichment** — no GSEA / clusterProfiler output in `differentialabundance/tables/gsea/` was a usable single file (subfolders contain HTML reports).
- **manhattan** — GWAS pipelines (`raredisease`, `phaseimpute`) are in nf-core but their megatest outputs don't include a top-level summary-stat TSV.
- **dot_plot** — `scrnaseq` megatest is BAM/sparse matrix only; no rank_genes_groups marker table in the published results.
- **upset_plot** — no canonical set-membership matrix in any surveyed pipeline.
- **sankey** — no canonical ordered-categorical chain in any surveyed pipeline.
- **oncoplot** — sarek megatest doesn't expose a MAF file (only annotated VCFs).

For these, either:
1. Run the pipeline locally with a scrnaseq-marker / vcf2maf module enabled.
2. Build a synthetic fixture instead (`generate_synthetic_fixtures.py` — TBD).

## Regenerating

```bash
python3 dev/advanced_viz_docs_screenshots/extract_nfcore_fixtures.py
```

Idempotent — skips files that already exist. Total payload: ~11 MB across 13 files (most weight in the DESeq2 vst matrix at 7 MB). Bump the `*_RUN` hashes at the top of the script to pull newer megatest outputs.
