# nf-core/rnaseq 3.26.0: Depictio dashboards

This template turns the output of [nf-core/rnaseq](https://nf-co.re/rnaseq) 3.26.0 into a
single three-tab Depictio dashboard. rnaseq takes bulk RNA sequencing libraries, trims them,
aligns them with STAR, quantifies transcripts with Salmon and merges the per-sample estimates
into gene-level TPM and count matrices. The template surfaces the pipeline's own MultiQC
funnel next to two views built on the pipeline's outputs: how the libraries relate to each
other, and which genes separate them and what any one gene does across conditions.

Data comes from the AWS megatest run
`results-e7ca46272c8f9d5ceee3f71759f4ba551d3217a4` (the 3.26.0 release tag): eight libraries
from four ENCODE cell lines, two replicates each, Trim Galore then STAR + Salmon.

---

## How the dashboard is built

- **One funnel, three tabs.** MultiQC, then Expression overview, then Gene explorer. Each tab
  answers the question the previous one raises: are the libraries usable, how do they relate
  to each other, and which genes drive that.
- **Persistent sample filter.** `Sample scope` (sample, condition, replicate) is pinned to the
  top of every tab's filter panel and reads the samplesheet, which links to every other
  collection. One pick there narrows the MultiQC panels, the DESeq2 PCA, the distance matrix
  and the gene explorer at once. `Reference scope` (persistent) narrows the pinned count
  matrix. Each tab adds its own scope on top: `Library scope` on Expression overview and
  `Gene scope` on Gene explorer.
- **Pinned sample sheet and reference tables.** The samplesheet sits in a collapsed,
  persistent `Sample sheet` section pinned to every tab; the raw merged count matrix sits in a
  collapsed `Reference tables` section pinned to the bottom. The design cards over the sheet
  open the MultiQC tab in `Run at a glance`.
- **Catalog provenance.** Every expression panel is a catalog render (`use: salmon/...`,
  `use: deseq2/...`) and every tool-level MultiQC tile names its module
  (`use: multiqc/star`, `use: multiqc/qualimap`, …). The tiles that read nf-core/rnaseq's own
  custom-content MultiQC sections carry no `use:`, because those module ids belong to the
  pipeline rather than to a tool.
- **The condition comes from the sample name.** The nf-core/rnaseq samplesheet schema is
  `sample,fastq_1,fastq_2,strandedness` and has no condition column, so the samplesheet recipe
  reads `condition` and `replicate` out of the `<condition>_REP<n>` names the pipeline's own
  test data and docs use. Everything the dashboard groups or colours by comes from that.
- **One sample view.** The only sample embedding is the pipeline's own DESeq2 QC PCA. The
  earlier TPM PCA recomputed the same picture from a different matrix and was dropped, as
  were the MultiQC copies of the DESeq2 PCA, the RSeQC distribution and the Qualimap genomic
  origin, which the Expression overview tab already draws from the raw files.

---

## MultiQC

The main tab, and the pipeline in the order it ran. `General statistics` opens with the
MultiQC general statistics table, one row per library pooling every module's headline
numbers. `Read quality` pairs FastQC on the raw reads with Trim Galore's filtered-read counts
and FastQC again after trimming, so the same two measurements sit side by side before and
after. `Alignment` carries STAR's summary statistics, samtools' percent mapped and Picard's
duplicate marking.

`Quantification and strandedness` is where the run's two most common failure modes show up:
Salmon's fragment length distribution, then the pipeline's own strandedness inference against
what the samplesheet declared, then its read strand composition. A library whose inferred
strandedness disagrees with the sheet was quantified against the wrong library type and every
number downstream of it is suspect.

`Transcript QC` (collapsed) holds Qualimap's gene body coverage, dupRadar's duplication
against expression and RSeQC's inner distance. Coverage that falls away at the 5' end is
degraded RNA; duplication that rises with expression is normal, duplication that is flat and
high is a library problem.

`Run at a glance` is the design: samples, conditions, replicates per condition (a top-N
breakdown by condition) and the declared strandedness, over the samplesheet.

![MultiQC](screenshots/qc.png)

## Expression overview

`Libraries at a glance` puts four strips on one row: the uniquely mapped share per library,
median TPM, genes expressed and genes detected, each as a median with a Tukey box plot. No
fixed threshold is drawn, because the right floor depends on the organism and the library
type.

`Sample relationships` is the signature panel. On the left, the pipeline's **own** DESeq2 QC
PCA: nf-core/rnaseq runs `deseq2_qc.r` over the count matrix and publishes the component
coordinates as `deseq2_qc/*pca.vals.txt`, which the `deseq2/qc_pca` recipe reads instead of
recomputing, so the tile carries exactly the points MultiQC draws as a picture. The variance
each component explains is parsed out of the file's own header and kept as a column, and a
`pca_set` column names the file each block came from. On the right, the sample distance
matrix `deseq2_qc.r` clusters its dendrogram on, read through `deseq2/qc_sample_dists` and
clustered in the browser with Ward linkage. Because `sample` is a real column of that matrix,
the sample filter narrows it on **both** axes and it stays square under a selection.

Replicates of one condition should sit together and away from the others. The library
summary table at the foot selects rows on the same `sample_id`, so picking points and picking
rows are the same act. A library record card sits beside that table and stays a thin rail
until a library is picked there or on the PCA, then shows its group, expression summary and
position on the first three components. On the MultiQC tab the pinned samplesheet also
selects rows on `sample`, which narrows the MultiQC panels through the sample mapping.

`Library composition` puts the featureCounts biotype composition and a bar of genes expressed
per library on the first row and, below them, the RSeQC read distribution read straight out of
the per-sample `*.read_distribution.txt` reports. RSeQC publishes its upstream and downstream
bands **nested** inside each other, so the recipe differences them into disjoint rings and
adds the tags that fall in no feature as an explicit `Other_intergenic` row, which is what
makes the composition sum to one.

`Library QC profile` draws every library as one line across the MultiQC general statistics,
coloured by condition, each axis rescaled to its own range. The pipeline-local recipe
`nf-core/rnaseq/general_stats.py` reads `multiqc_general_stats.txt` and folds the per-read-file
FastQC and Cutadapt rows onto their library. Brushing an axis filters the libraries.

![Expression overview](screenshots/expression-overview.png)

## Gene explorer

The former Expression heatmap tab is folded in here, so the gene questions live on one tab.
`Picked genes` reports what the current selection covers: genes in view, genes by the
condition they peak in, libraries in view and log2(TPM + 1) as a median with a box plot.

`Top variable genes` draws the most variable genes across the run as a clustered heatmap, row
z-normalised on the log2(TPM + 1) scale, with the condition annotation strip above the
columns. The gene filter in `Gene scope` narrows its rows; the sample columns follow the
pinned `Sample scope`.

`Expression by condition` is the one code-mode figure in the template. It takes the genes
with the highest spread of log2(TPM + 1) left after filtering and draws one box per gene and
condition. Selecting boxes filters on `gene_name`, and the `Gene rows` table below selects
rows on the same column.

`Gene detail` is the master/detail pair. The pipeline runs no differential test, so the
picking surface is the mean-variance plane: one point per expressed gene, mean log2(TPM + 1)
against its standard deviation across the libraries, coloured by the condition it peaks in
(recipe `nf-core/rnaseq/gene_summary.py`). The record card sits on the same row and is linked
to the plane: it stays a thin rail until a point is clicked, which fills it and, through the `gene_summary` to `gene_expression` link on `gene_id`, narrows the
box plot and the gene rows below. `Gene rows` and `Matrix rows` (both collapsed) hold the
long and wide forms of the same matrix.

![Gene explorer](screenshots/gene-explorer.png)

---

## Catalog module

The recipes ship as three catalog modules. `depictio/catalog/salmon/` holds `module.yaml` plus
four output definitions; Salmon is an nf-core module, so `module.yaml` points at its nf-core
`meta.yml` rather than restating the identity. `depictio/catalog/deseq2/` and
`depictio/catalog/rseqc/` carry the two QC outputs the pipeline was already writing and
nothing was reading.

| Output | What it is | Renders as |
|---|---|---|
| `salmon_sample_pca` | One row per sample: PCA coordinates of the log2(TPM + 1) matrix, genes detected and expressed, median TPM | 4 cards, table |
| `salmon_expression_heatmap` | The 500 most variable genes, wide, with a condition annotation strip | Clustered heatmap (`use: salmon/top_variable_heatmap`), table |
| `salmon_gene_expression` | The merged TPMs as one row per gene and sample, expressed genes only | Box figure, 2 cards, gene filter, table |
| `salmon_merged_gene_counts` | The raw merged count matrix tximport writes next to the TPM matrix | Table |
| `deseq2_qc_pca` | The pipeline's own DESeq2 QC principal components, with the variance each explains and a `pca_set` label per source file | Embedding (`use: deseq2/qc_pca_embedding`), gauge card, table |
| `deseq2_qc_sample_dists` | The square sample-to-sample Euclidean distance matrix the QC dendrogram is clustered on | Clustered heatmap (`use: deseq2/qc_distance_heatmap`), table |
| `rseqc_read_distribution` | Share of each library's tags per annotation feature, at two resolutions | Stacked composition (`use: rseqc/distribution_composition`), card, table |

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
depictio-cli run --template nf-core/rnaseq/3.26.0 \
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

`--project-name` is safe for `run` itself, but leave it off anyway. The dashboard carries
`project_tag: RNA-seq Expression Analysis`, and the standalone `depictio dashboard import`
resolves that tag by name, so a renamed project cannot take a re-imported dashboard later.

Re-running over a project that already exists needs `--update-config --overwrite`; with both,
the dashboard is updated in place rather than accumulating duplicates.

Non-default routes need their flag passed by hand, since the CLI does not yet read rnaseq's
own `params.json` for them: `--var PSEUDOALIGNER_ONLY=true` for `--skip_alignment`,
`--var SKIP_MULTIQC=true` for `--skip_multiqc` or `--skip_qc`, and
`--var SKIP_QUANTIFICATION_MERGE=true` for `--skip_quantification_merge`.
