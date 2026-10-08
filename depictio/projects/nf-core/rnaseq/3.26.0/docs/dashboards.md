# nf-core/rnaseq 3.26.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in two groups, read as a funnel from the
run to the genes that vary between conditions. It follows the family rules in
`depictio/projects/nf-core/RULES.md`; nf-core/ampliseq 2.18.0 is the reference.
nf-core/rnasplice 1.0.4 shares its `Data & QC` group and its Sample Space tab.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did trimming, alignment and quantification work for every library? |
| Data & QC | Library QC | Which library stands apart on mapping, duplication or read placement? |
| Data & QC | Sample Space | Do the replicates of each condition sit together? |
| Expression | Variable Genes | Which genes vary most between the libraries and conditions? |
| Expression | Gene Explorer | Where does a gene sit, and which condition does it peak in? |

nf-core/rnaseq takes bulk RNA-seq libraries, trims them, aligns them with STAR, quantifies
transcripts with Salmon and merges the per-sample estimates into gene-level TPM and count
matrices. Its sample sheet (`sample,fastq_1,fastq_2,strandedness`) has no design column, so
the project-local samplesheet recipe reads `condition` and `replicate` out of the
`<condition>_REP<n>` sample names the pipeline's own test data and docs use. There is no
`GROUP_COL` variable: everything the dashboard groups or colours by is that `condition`,
copied as `group` into the expression tables and as `top_condition` into the gene table.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples,
  genome, aligner, trimmer), read from the run parameters and the sample sheet.
- **Pipeline**: six steps (trim, align, check, relate, quantify, annotate). Each step opens
  the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples
  (split by condition), the median number of genes a library expresses (with its spread),
  the genes two-fold higher in one condition (split by the condition they peak in) and the
  median uniquely mapped share (a coverage bar). A condition and a sample filter above them
  narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: the genes two-fold higher in one condition and the condition most of them
  peak in, the variance on the first principal component (DESeq2 QC on all libraries, so no
  filter changes it), the genes expressed, and the largest RSeQC region class with its share
  of the tags. Below them, four figures in two rows, each linking its tab: the most variable
  genes per condition beside the clustered sample distances, then the mean-variance plane
  beside the RSeQC read distribution. The bar of this section filters by condition and
  sample.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (condition, sample, replicate) sit in the collapsed left
panel and narrow every tab through the samplesheet links. The `Sample sheet` section is
pinned to the bottom of every child tab, collapsed, and absent from the Overview.

nf-core/rnaseq runs no differential test. The gene numbers are rankings (spread across the
libraries, or the mean of the top condition against the others), and every tile that shows
one says so. `gene_summary` is computed over all libraries, so the sample filters do not
change it: they narrow the per-library collections only.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it (a box plot, a distribution, a gauge, a ranking or a share), then at
most three open sections; tables and details follow, collapsed.

**MultiQC.** MultiQC panels only, no key-number strip. Open: general statistics, FastQC raw
sequence counts beside the reads Trim Galore kept, STAR's summary beside samtools' percent
mapped, then the pipeline's own strandedness inference beside the featureCounts biotype
composition. A library whose inferred strandedness disagrees with the sheet was quantified
against the wrong library type. Collapsed: read quality (FastQC before and after trimming),
alignment details (Picard duplicates, Salmon fragment lengths, read strand composition) and
transcript QC (Qualimap gene body coverage, dupRadar, RSeQC inner distance). Its own sample
filter reads the MultiQC report, whose library names carry read suffixes.

**Library QC.** Strip: reads received by STAR (split by condition), the uniquely mapped
share on a 0 to 100 gauge, the duplication share with its spread and the exonic share with
its distribution. Then the per-library QC profile, eleven MultiQC general statistics as
parallel coordinates coloured by condition, and the RSeQC read distribution per library,
switchable between the five region classes and the individual features. Filters: uniquely
mapped and duplication ranges.

**Sample Space.** Strip: libraries in the TPM matrix (a ring by condition), genes expressed
with their spread, genes detected with their distribution and the median TPM (ranked by
condition). The same four cards open the Sample Space tab of nf-core/rnasplice. Then the
pipeline's own DESeq2 QC PCA beside the sample distance matrix it clusters on (`ward`,
`Blues`). Collapsed: the library summary table with the library record card beside it.
Filters: genes expressed and median TPM ranges.

**Variable Genes.** Strip: genes at 1 TPM or more (counted per condition), the median log2(TPM + 1)
with its spread, the genes two-fold higher in one condition (split by that condition) and
the highest TPM with the genes that reach it. Then the 500 most variable genes as a
clustered, row z-scored heatmap with the design strips on top (condition, replicate, read
type, strandedness), and the twelve most variable genes in view as one box per condition.
Collapsed: the top variable gene matrix as rows. Filters: a top variable gene picker and a
log2(TPM + 1) range.

**Gene Explorer.** Strip: expressed genes (a ring by the condition they peak in), the
median of their mean expression (a distribution) and of their spread (a box plot), and the
median lead of the top condition over the others (the genes two-fold or more ahead pass).
Then the mean-variance plane, one point per expressed gene coloured by the condition it
peaks in and unlabelled (the most variable genes sit too close to name), beside the gene
record card (its id links to Ensembl). Collapsed: the gene rows (one per gene and library) and the merged count matrix,
which moved here from the old pinned reference tables. Filters: a gene picker and a mean
log2(TPM + 1) range.

## Routes and pruning

| Route | What changes |
|---|---|
| `--skip_multiqc` or `--skip_qc` (`SKIP_MULTIQC`) | No MultiQC tab. Library QC keeps only the RSeQC read distribution; the uniquely mapped key figure is dropped. |
| `--skip_quantification_merge` (`SKIP_QUANTIFICATION_MERGE`) | No Variable Genes or Gene Explorer tab. Sample Space keeps the DESeq2 QC PCA and distances, without its strip or library table. The expression key figures, the gene rows of Findings and their two highlights are dropped. |
| `--skip_alignment` (`PSEUDOALIGNER_ONLY`) | The expression collections read `salmon/` instead of `star_salmon/`. STAR, samtools, Picard, Qualimap and RSeQC panels have nothing to show; the RSeQC figure and row are dropped. |
| `--skip_deseq2_qc`, or fewer than three samples | No DESeq2 PCA, distances, variance row or distances highlight. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.
These flags are passed by hand with `--var` (see Reproducing).

## Colours

`category_colors` is declared once, on the Overview, and read by every tab. `condition`,
`group` and `top_condition` are coloured `auto`: they hold the same values, so a condition
takes the same colour in the parallel coordinates, the heatmap strip, the box plot and the
plane.
The five RSeQC region classes are written out, `Other intergenic` in grey. The box plot is
a code figure: it reads the same map and follows Analysis mode's groups when it has some.

## Cross-selection

Tables select rows and the PCA, the box plot and the plane select points; a pick becomes a
dashboard filter that narrows the other tiles of the same collection and, through the
project links, the collections downstream of it. Row selection is on `sample` in the sample
sheet, `sample_id` in the library summary (shared with the PCA), `gene_name` in the gene
rows and the box plot, and `gene_id` on the plane. The two record cards wait for a pick:
the library record reads the library summary table, the gene record reads the plane.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Catalog module

The recipes ship as three catalog modules. `depictio/catalog/salmon/` holds `module.yaml` plus
four output definitions; Salmon is an nf-core module, so `module.yaml` points at its nf-core
`meta.yml` rather than restating the identity. `depictio/catalog/deseq2/` and
`depictio/catalog/rseqc/` carry the two QC outputs the pipeline was already writing and
nothing was reading.

| Output | What it is | Renders as |
|---|---|---|
| `salmon_sample_pca` | One row per sample: PCA coordinates of the log2(TPM + 1) matrix, genes detected and expressed, median TPM | 4 cards, a key figure, table with a record card |
| `salmon_expression_heatmap` | The 500 most variable genes, wide, with a condition annotation strip | Clustered heatmap (`use: salmon/top_variable_heatmap`), gene picker, table |
| `salmon_gene_expression` | The merged TPMs as one row per gene and sample, expressed genes only | Box figure, 3 cards, log2(TPM + 1) range, table |
| `salmon_merged_gene_counts` | The raw merged count matrix tximport writes next to the TPM matrix | Table |
| `deseq2_qc_pca` | The pipeline's own DESeq2 QC principal components, with the variance each explains and a `pca_set` label per source file | Embedding (`use: deseq2/qc_pca_embedding`), a findings row |
| `deseq2_qc_sample_dists` | The square sample-to-sample Euclidean distance matrix the QC dendrogram is clustered on | Clustered heatmap (`use: deseq2/qc_distance_heatmap`), a highlight |
| `rseqc_read_distribution` | Share of each library's tags per annotation feature, at two resolutions | Stacked composition (`use: rseqc/distribution_composition`), a findings row, a highlight |

The two `deseq2` outputs are deliberately **not** pipeline-specific: their globs key on the file
suffix (`**/*pca.vals.txt`, `**/*sample.dists.txt`) rather than on a `star_salmon/` directory,
because nf-core/chipseq and nf-core/atacseq run the same `deseq2_qc.r` and publish the same two
files under their consensus directories. Those two write the MultiQC custom-content flavour
(`*.pca.vals_mqc.tsv`, under a `#` comment header), which the recipes also parse; a template
whose run has only that flavour repoints the source with
`source_overrides: {pca: {glob_pattern: "**/*pca.vals_mqc.tsv"}}`. When a glob matches
several PCA files, the recipe resolves components per file, keeps one
file when both flavours of the same table are present, and labels each block in `pca_set`
(the first path segment that differs between files), so several consensus sets stack
cleanly instead of leaving null coordinates.

`rseqc_read_distribution` is a two-step: the report is fixed-width text, not a table, and the
sample name lives only in the file name, so a recursive scan collection
(`rseqc_read_distribution_raw`) reads every report as raw lines with `include_file_paths`, and
the recipe consumes that collection by tag. `quote_char: null` is required on the scan, because
`5'UTR_Exons` would otherwise open a quoted field that never closes.

All three recipes read the same file, `salmon.merged.gene_tpm.tsv`, and are pipeline-agnostic:
their default source path is `salmon/`, which is where a bare salmon/tximport run and
nf-core's `--skip_alignment` route both write it. nf-core/rnaseq's default route writes it
under `star_salmon/`, so each data collection repoints the source with
`transform.source_overrides`. The samplesheet recipe is project-local
(`depictio/projects/nf-core/rnaseq/recipes/samplesheet.py`) because deriving a condition from
a sample name is an nf-core/rnaseq convention, not a Salmon one.

The MultiQC modules this pipeline emits (`fastqc`, `cutadapt`, `star`, `samtools`, `picard`,
`salmon`, `rseqc`, `qualimap`, `dupradar`) all exist under `depictio/catalog/multiqc/`, which
is what lets a MultiQC tile carry `use: multiqc/<module>` and the catalog badge.

---

## Reproducing

```bash
bash depictio/projects/nf-core/rnaseq/3.26.0/download_test_data.sh
# then follow post_fetch_help in megatest.yaml for the samplesheet curl into input/
depictio-cli ingest --template nf-core/rnaseq/3.26.0 \
  --data-root ~/Data/depictio-nfcore/rnaseq/3.26.0/megatest
```

**DATA_ROOT is the `aligner_star_salmon/` sub-directory of the megatest prefix, not the prefix
root.** The run publishes `aligner_star_salmon/` and `aligner_star_rsem/` side by side, each a
complete output tree with its own `multiqc/`, `star_salmon/` and `salmon/`. The manifest sets
`run_root: aligner_star_salmon/` and mirrors the fetched keys below the destination, so the
directory `download_test_data.sh` writes is already the right DATA_ROOT; point the CLI at the
prefix root instead and every scan becomes ambiguous between the two routes.

This run's MultiQC (1.33) also wrote its data directory as
`multiqc/star_salmon/multiqc_report_data/` rather than `multiqc/multiqc_data/`, and the
template's MultiQC scan regex pins that literal path for the same reason.

`--project-name` is safe for `ingest` itself, but leave it off anyway. The dashboard carries
`project_tag: RNA-seq Expression Analysis`, and the standalone `depictio dashboard import`
resolves that tag by name, so a renamed project cannot take a re-imported dashboard later.

Re-running over a project that already exists needs `--update-config --overwrite`; with both,
the dashboard is updated in place rather than accumulating duplicates.

Non-default routes need their flag passed by hand, since the CLI does not yet read rnaseq's
own `params.json` for them: `--var PSEUDOALIGNER_ONLY=true` for `--skip_alignment`,
`--var SKIP_MULTIQC=true` for `--skip_multiqc` or `--skip_qc`, and
`--var SKIP_QUANTIFICATION_MERGE=true` for `--skip_quantification_merge`.
