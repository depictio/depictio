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
| Expression | Gene Explorer | Where does a gene peak, and what do its reads look like? |

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
  the genes four-fold higher in one condition (at 10 TPM or more, split by the condition they
  peak in) and the median uniquely mapped share (a coverage bar). A condition and a sample filter above them
  narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: the genes four-fold higher in one condition (at 10 TPM or more) and the
  condition most of them peak in, the variance on the first principal component (DESeq2 QC on all libraries, so no
  filter changes it), the genes expressed, and the largest RSeQC region class with its share
  of the tags. Below them, four figures in two rows, each linking its tab: the most variable
  genes (a dot per library, a bar at each condition's mean) beside the DESeq2 QC PCA, then
  the mean-variance plane beside the RSeQC read distribution. The sample distance matrix labels
  both axes with library ids and renders blank at a third of the row, so the PCA stands for the
  Sample Space tab. The bar of this section filters by condition and sample.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (condition, sample, replicate) sit in the collapsed left
panel and narrow every tab through the samplesheet links. The `Sample sheet` section is
pinned to the bottom of every child tab, collapsed, and absent from the Overview.

nf-core/rnaseq runs no differential test. The gene numbers are rankings (spread across the
libraries, or the mean of the top condition against the others, at least four-fold and
reaching 10 TPM: with two replicates per condition a one log2 lead kept most genes, which ranks
nothing), and every tile that shows one says so. `gene_summary` is computed over all libraries, so the sample filters do not
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
transcript QC (Qualimap gene body coverage, dupRadar, RSeQC inner distance). The pinned sample
filters narrow its panels, though the report's library names carry read suffixes.

**Library QC.** Strip: reads received by STAR (split by condition), the uniquely mapped
share on a 0 to 100 gauge, the duplication share with its spread and the exonic share with
its distribution (the duplication card says to judge a library against its replicates). Then
the per-library QC profile, six MultiQC general statistics as parallel coordinates coloured
by condition (reads, uniquely mapped, Salmon mapped, duplication, exonic share and the
5 prime to 3 prime bias, with the good direction of each in the tile's description; the other
five metrics of the `general_stats` collection are in the MultiQC tab), and the RSeQC read
distribution per library,
switchable between the five region classes and the individual features. Filters: uniquely
mapped and duplication ranges.

**Sample Space.** Strip: libraries in the TPM matrix (a ring by condition), genes expressed
with their spread, genes detected with their distribution and the median TPM (ranked by
condition). The same four cards open the Sample Space tab of nf-core/rnasplice. Then the
pipeline's own DESeq2 QC PCA above the sample distance matrix it clusters on (`ward`,
`Blues`), both full width: the matrix labels both axes with library ids. Collapsed: the library summary table with the library record card beside it.
Filters: genes expressed and median TPM ranges.

**Variable Genes.** Strip: genes at 1 TPM or more (counted per condition), the median log2(TPM + 1)
with its spread, the genes four-fold higher in one condition (at 10 TPM or more, split by that condition) and
the most variable gene, with the genes that vary most (it replaced a ranking by peak TPM, which
lists the same housekeeping transcripts on every run). Then the 500 most variable genes as a
clustered, row z-scored heatmap with the design strips on top (condition, replicate, read
type, strandedness), and the twelve most variable genes in view as a dot per library with a
bar at each condition's mean (a condition holds two or three libraries, too few for a box).
Collapsed: the top variable gene matrix as rows. Filters: a top variable gene picker and a
log2(TPM + 1) range.

**Gene Explorer.** Strip: expressed genes (a ring by the condition they peak in), the
median of their mean expression (a distribution) and of their spread (a box plot), and the
median lead of the top condition over the others, for genes at 10 TPM or more (the genes
four-fold or more ahead pass).
Then the gene detail: the mean-variance plane (its description reads it: average expression
left to right, change between libraries bottom to top), one point per expressed gene coloured
by the condition it peaks in and unlabelled (the most variable genes sit too close to name), beside
the gene record card (its id links to Ensembl), and under them the genome browser at full
width. The plane is the gene picker: a picked gene narrows the record card and the browser
to it, and the browser frames its span. Unpicked, it opens on the gene whose top condition
leads most, and its next and previous buttons walk the genes in that order (a ranking, not
a test). Collapsed: the gene rows (one per gene and library) and the merged count matrix.
Filters: a gene picker and a mean log2(TPM + 1) range.

## Routes and pruning

| Route | What changes |
|---|---|
| `--skip_multiqc` or `--skip_qc` (`SKIP_MULTIQC`) | No MultiQC tab. Library QC keeps only the RSeQC read distribution; the uniquely mapped key figure is dropped. |
| `--skip_quantification_merge` (`SKIP_QUANTIFICATION_MERGE`) | No Variable Genes or Gene Explorer tab. Sample Space keeps the DESeq2 QC PCA and distances, without its strip or library table. The expression key figures, the gene rows of Findings and their two highlights are dropped. |
| `--skip_alignment` (`PSEUDOALIGNER_ONLY`) | The expression collections read `salmon/` instead of `star_salmon/`. STAR, samtools, Picard, Qualimap and RSeQC panels have nothing to show; the RSeQC figure and row are dropped. |
| `--skip_deseq2_qc`, or fewer than three samples | No DESeq2 PCA, distances, variance row or PCA highlight. |

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

## Genome tracks

A JBrowse genome browser, in the Gene Explorer tab (a template has one browser, in the tab that
works at a locus), over the `tracks` collection, a manifest the project-local recipe
`depictio/projects/nf-core/rnaseq/recipes/tracks.py` spells out from the samplesheet: per
sample the forward and reverse strand bigWig coverage and the duplicate-marked STAR BAM under
`star_salmon/` (24 rows on the megatest). The manifest writes no colour: the tile colours by
`condition` (`color_by`), in the colours the Overview's `category_colors` declares for it, so a
condition has one hue in the bars, the heatmap strip and the browser (a manifest colour would
win over the declared one). The gene track is the assembly's own preset (`show_annotation`);
no UCSC gene track of that assembly is a bigBed or VCF file JBrowse can read, and dbSNP or
ClinVar say nothing about expression, so there is no `ucsc_tracks`. The megatest was aligned to Ensembl GRCh37, whose bare chromosome names
(`1`, `2`, ...) the `hg19` preset maps through UCSC's chromAlias. Junction arcs (sashimi) draw
over the coverage. Rows are ordered per sample (forward, reverse, then the BAM), replicate 1 of
every condition first, so the twelve opening tracks hold the first replicate of four
conditions with their reads and splice arcs (stranded libraries put a gene's signal on one
strand, so both strands open); the other tracks are a pick away (at most 24 open).

**Where it opens.** The matrix of Salmon TPMs has no coordinates, so `gene_summary` takes
`chrom`, `start` and `end` from StringTie's per-library gene tables
(`star_salmon/stringtie/*.gene.abundance.txt`, written unless the run skips StringTie): the
widest span a gene shows over the libraries, on the contig most libraries name. The browser's
`locus_from` reads them, ordered by the lead of each gene's top condition, with the gene name as
the stepper label and the peak condition and lead in the picker. The run publishes no GTF, so
StringTie is the only source of coordinates; a run with `--skip_stringtie` leaves the three
columns empty, the browser cannot frame a picked gene and opens on the first region that holds
data. The StringTie gene tables must be present under DATA_ROOT when the run is ingested (the
megatest fetch lists them); without them the same fallback applies.

The samplesheet links to the manifest both ways on `sample`: the sample scope of the left
panel (and the pinned `Samples` table) picks which tracks are open, and clicking a feature in
the browser filters every other tab on its sample. The `sample_overview -> tracks` link opens the
coverage of the samples picked on the Sample Space PCA. A `PSEUDOALIGNER_ONLY` run has no BAM and
no bigWig, so that route drops the collection and the browser with it.

The tables-only megatest subset holds none of the track files (it does hold the StringTie
gene tables, about 4 MB each). Pass
`--var TRACKS_URI=s3://nf-core-awsmegatests/rnaseq/results-e7ca46272c8f9d5ceee3f71759f4ba551d3217a4/aligner_star_salmon`
and the collection reads them in place, by range; without it the recipe keeps only the files
DATA_ROOT holds and the CLI uploads them at ingestion.

## Changes from the second review

- The browser's manifest colour is gone, and its `color_by: condition` reads the dashboard's
  palette. Its opening tracks gained the BAMs (junction arcs on open).
- The sample distance matrix is full width on its tab and no longer a highlight (blank at w4);
  the Overview shows the PCA for that tab.
- The per-library QC profile has six axes, each with a reading direction.
- The Variable Genes plot is a dot per library with a mean bar (two replicates make no box).
- "Two-fold in one condition" became four-fold at 10 TPM or more.

## Changes from the first review

- The `Genome tracks` tab is gone: its browser moved into the Gene Explorer, where a picked gene
  sets the locus. Its four cards and two scatters repeated the Sample Space tab (the same
  `sample_overview` cards and PCA), so they were dropped rather than moved.
- The Variable Genes `Highest TPM` card ranked housekeeping transcripts; it is now the most
  variable gene.
- The Overview names the browser in the pipeline step and in the Gene Explorer finding.

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
| `salmon_gene_expression` | The merged TPMs as one row per gene and sample, expressed genes only | Dot figure (a code figure), 3 cards, log2(TPM + 1) range, table |
| `salmon_merged_gene_counts` | The raw merged count matrix tximport writes next to the TPM matrix | Table |
| `deseq2_qc_pca` | The pipeline's own DESeq2 QC principal components, with the variance each explains and a `pca_set` label per source file | Embedding (`use: deseq2/qc_pca_embedding`), a findings row, a highlight |
| `deseq2_qc_sample_dists` | The square sample-to-sample Euclidean distance matrix the QC dendrogram is clustered on | Clustered heatmap (`use: deseq2/qc_distance_heatmap`) |
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
