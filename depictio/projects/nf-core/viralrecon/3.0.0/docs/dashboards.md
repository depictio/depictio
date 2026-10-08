# nf-core/viralrecon 3.0.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in two groups, read as a funnel from the
reads to the lineage of each consensus genome. The template follows the family rules in
`depictio/projects/nf-core/RULES.md`, and is one of the two reference templates shipped
with seeded dashboards.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did reads trim, align and cover the genome in every sample? |
| Data & QC | Sample QC | Did each sample yield a well-covered, trustworthy consensus genome? |
| Data & QC | Coverage & Depth | Where along the genome does each sample lose depth? |
| Genomes | Variants | Which mutations does each sample carry, and how well supported? |
| Genomes | Lineage & Clustering | Which lineage and clade is each sample, and do they agree? |

`summary_metrics` (the pipeline's variant summary, one row per sample) is the source of
every project link, so a filter on it reaches every tab. The template names no virus,
primer scheme or reference: texts describe what to read, not what one run found. Route
flags read from `pipeline_info/params.json` prune the data collections a run did not
produce: a tab left without data is dropped, and so are the Overview tiles and rows that
pointed at it.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples,
  platform and protocol, reference, primer scheme, variant and consensus callers), read
  from the run parameters and the run summary.
- **Pipeline**: six steps (trim, align, cover, call, consensus, type). Each step opens the
  parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards on the run summary, each opening the tab that
  explains it. Samples (against the pipeline's default 1,000 mapped reads, the floor for
  variant calling), the median depth per sample (with its spread), the median share of the
  genome covered at 10x (of 100%) and the median variants per sample (with its spread; a
  run no caller reached reads "–", not 0). A sample filter and a genome-at-10x range above
  them narrow these four only. Neither the cards nor the bar split by lineage: the
  summary's lineage is Pangolin's, and a run without Pangolin output writes NA there.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: the consensus genomes Nextclade rates good, the amplicons under 10x in at
  least one sample, the missense share of the calls, and the most common Pangolin lineage
  among the assigned samples. Below them, four figures in two rows, each linking its tab:
  median depth against genome covered at 10x per sample beside the median depth of each
  amplicon along the genome (a summary of the amplicon track, one tick per power of ten),
  then the allele frequency of every call along the genome beside the classification flow
  from QC verdict to lineage and clade. The bar of this section filters by sample and
  genome at 10x.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (lineage, then sample id) sit in the collapsed left panel
and narrow every tab; the persistent `QC thresholds` (genome at 10x, median depth, reads
mapped and variants called) sit collapsed below them. The `Sample sheet` section, the run
summary table, is pinned to the bottom of every child tab, collapsed, and absent from the
Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it, then at most three open sections; tables and details follow,
collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics, the samples that failed
mapping, fastp filtered reads, Bowtie 2 alignments and the mosdepth cumulative coverage.
Collapsed: the read and alignment panels (FastQC, Kraken 2, samtools, mosdepth per contig,
Cutadapt), then the variant and assembly panels (iVar, snpEff, bcftools, QUAST and the
pipeline's own summary tables, the fallback when a route prunes `summary_metrics`). Its
own sample filter reads the MultiQC report.

**Sample QC.** Strip: median reads mapped (samples against the 1,000-read floor), the
median share of reads mapped (a gauge), the median depth (with its spread) and the median
genome at 10x (with its distribution). Then median depth (log axis) against genome
covered at 10x, one point per sample with the 80% floor dashed, beside the sample record
card (it waits for a pick in the scatter or the Sample sheet); every run's summary carries
both columns, where a run no caller reached writes NA for its calls. Then Nextclade
substitutions against deletions per consensus genome (whole-number axes from zero), and
the genome covered at 1x and 10x per sample. Filters: SNPs and indels called, and the
missing bases of the consensus.

**Coverage & Depth.** Strip: the median depth per 200 bp window (with its distribution),
the windows under 10x (their depth, a bar at 0 being a true gap), the median amplicon depth
(sample and amplicon pairs against 10x) and the amplicons under 10x in at least one sample
(with the one that drops out most often). 10x is the depth under which the consensus masks
a position. Then the genome track (one lane per sample), the amplicon track (log axis) and
the clustered amplicon heatmap. The amplicon table is collapsed. Filters: window depth,
amplicon and amplicon depth.

**Variants.** Strip: the calls (by functional class), the distinct mutations (with the one
most samples share), the median allele frequency (calls against the 0.75 consensus cut-off)
and the median read depth (with its spread). Then the allele frequency of every call along
the genome (no point labels: mutation labels pile up over the dots), the allele frequency
histogram beside the reference against alternate depth scatter, and the mutation matrix
per sample and gene. Collapsed: the per-gene lollipops, calls per gene and per sample, and
the variant table. Filters: gene, effect, functional class, allele frequency and read
depth; a collapsed `Matrix filter` narrows the mutation matrix by mutation type only.

**Lineage & Clustering.** Strip: the distinct Pangolin lineages (unassigned genomes left
out, the bar splitting the samples by lineage), the distinct Nextclade clades (a ring), the
median Nextclade QC score (genomes against Nextclade's marks: under 30 good, 100 or more
bad) and the median missing bases (with its spread). Then the classification flow from
Pangolin QC verdict to lineage to clade (ribbons coloured by their target: on most runs
every flow leaves the one verdict "pass"), the PCA of the samples by the mutations they
share, and the UpSet of the mutations shared across lineages (no annotation strip, which
would list every mutation in its legend). Collapsed: samples per lineage and per clade (the
eight largest, the rest as Other), then the Pangolin table with
its lineage record card (the Scorpio notes a cell cuts short) and the Nextclade table.
Filters: lineage, clade and the two QC verdicts.

## Routes and pruning

| Route | What changes |
|---|---|
| Nanopore (`platform: nanopore`) | `summary_metrics` and the variant tables are pruned: no persistent filters, Key figures, Sample sheet or Variants tab, and Sample QC keeps only its Nextclade scatter. Coverage and typing read the ARTIC outputs. No collection of this route alone can stand in a Key figure slot: see below. |
| A partial run (no caller output, no Pangolin) | The summary writes NA for the calls and the lineage: Variants per sample reads "–", the lineage filter in the left panel offers NA alone, and the Variants and Lineage & Clustering tabs are pruned. The Overview's bars and cards do not split by lineage. |
| No primer scheme (metagenomic) | No amplicon cards, tracks, heatmap or table; the Coverage strip keeps its two window cards, and the amplicon row and figure leave the Overview. |
| Non-SARS virus, `--skip_pangolin`, `--skip_nextclade` | No typing cards, flow or tables for the missing tool, and its Findings row and figure leave the Overview. |
| `--skip_variants_long_table` | No Variants tab, PCA, UpSet or missense row. |

The import re-packs the Overview grid after a drop, so a lone figure takes the full row.

Two tiles on one grid slot are route alternates only when no run keeps both: the import
packs them as one tile and draws whichever survives. The nanopore route writes no
collection the illumina route lacks (it repoints the same tags at `artic_minion/`), so the
Key figures cannot take a nanopore alternate. The nanopore `summary_variants_metrics_mqc.csv`
carries every column the Key figures read; what prunes it is the recipe, whose output schema
requires `% Mapped reads`, absent from that file. Making that column optional in
`depictio/catalog/multiqc/summary_metrics.py` and dropping `summary_metrics` from the
`IS_NANOPORE` `remove_dc_tags` in `template.yaml` restores the Key figures, the persistent
filters and the Sample sheet on that route.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab. Lineages are
coloured `auto:pct_genome_covered_1x` and clades `auto:coverage`: the import ranks the
values and gives the eight largest the palette, so the strip, the flow, the PCA and the bar
charts give a lineage the same colour; Unassigned, NA and Other are grey. The QC verdicts,
the snpEff functional classes and the snpEff effects (the same vocabulary in the call
table and the mutation matrix) are written out. Code figures read the same map and follow
Analysis mode's groups when it has some.

## Cross-selection

Every per-sample table (run summary, amplicon depth, Pangolin, Nextclade, variant calls)
selects rows on `sample`, and the depth against breadth scatter, the Nextclade scatter,
the allele frequency track, the read support scatter and the PCA select points on it.
`summary_metrics` links `sample` to every per-sample collection, so a pick narrows the rest
of the tab. The record cards wait for a pick. A lasso on the PCA becomes an analysis group.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Reproducing

```bash
bash depictio/projects/nf-core/viralrecon/3.0.0/download_test_data.sh <DATA_ROOT>
depictio-cli ingest --template nf-core/viralrecon/3.0.0 --data-root <DATA_ROOT>
```
