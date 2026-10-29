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
  median depth against genome covered at 10x per sample (it judges coverage only) beside
  Nextclade's QC score of each consensus genome, worst first and coloured by its verdict, so
  a sample that passes on coverage and is rated bad on its consensus shows up; then the
  allele frequency of every call along the genome beside the calls per gene by functional
  class. The figures answer one question each, and none repeats a tab's own figure under a
  different type. The bar of this section filters by sample and genome at 10x.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (lineage, then sample id) sit in the collapsed left panel
and narrow every tab; the persistent `QC thresholds` (genome at 10x, median depth, reads
mapped and variants called) sit collapsed below them. The `Sample sheet` section, the run
summary table, is pinned to the bottom of every child tab, collapsed, and absent from the
Overview. Sample names come from the samplesheet, and the section says what a suffix such as
_PE or _SE marks where a run uses one (paired-end or single-end reads).

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
covered at 10x, one point per sample coloured pass or fail, with the 80% floor and the 10x
depth drawn as dashed lines and the fail corners shaded (a failing sample carries its name;
the markers are large because a run often has few samples), beside the sample record card (it
waits for a pick in the scatter or the Sample sheet); every run's summary carries both
columns, where a run no caller reached writes NA for its calls. The scatter judges coverage
only: a sample can pass it and still be rated mediocre or bad by Nextclade, which also counts
the bases the consensus could not read, and the intro says so. Then the Nextclade reading of
each consensus genome in two panels, because the counts differ by orders of magnitude: the
substitutions and deleted bases it finds against the reference (stacked, above) and the
missing bases (below, log axis), the most missing first, with a dot in the Nextclade QC
colour above each bottom bar; and the genome covered at 1x and 10x per sample. Filters: SNPs
and indels called, and the missing bases of the consensus.

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
histogram, and the mutation matrix
per sample and gene. Collapsed: the per-gene lollipops, calls per gene and per sample, and
the variant table. Filters: gene, effect, functional class, allele frequency and read
depth; a collapsed `Matrix filter` narrows the mutation matrix by mutation type only.

**Genome browser (preview dashboard `v2.yaml`).** The preview dashboard adds a genome
browser to the Variants tab, linked to the allele frequency plot. It has no fixed location:
it opens on the best supported call and lists the calls in its region picker with their gene,
effect and frequency. "Best supported" is the `call_score` column the variant recipe
(`recipes/variants_long.py`) adds: the allele frequency first, the read depth to break the
ties at 1.0, and the calls outside a gene (snpEff's intergenic pseudo-genes) last, so the
first call is never one of those. Picking a dot of the plot or a row of the variant table
narrows the calls to that mutation and centres the browser on it, on the samples that carry
it. The window follows the other genome tiles of the tab. The tracks manifest holds one
variant and one alignment file per sample and no colour of its own: the tracks take the
colour of the sample's Pangolin lineage (`color_by: lineage`, the key of `category_colors`
the plots read) and the variants the colour of their snpEff effect. The manifest leads with
the sample of the best supported call, so the opening tracks are that sample's variants and
reads, then the next sample's. The tile shows the assembly's gene track, the ARTIC primers
and the Nextstrain clade markers.

**Lineage & Clustering.** Strip: the distinct Pangolin lineages (unassigned genomes left
out, the bar splitting the samples by lineage), the distinct Nextclade clades (a ring), the
median Nextclade QC score (Nextclade's own scale: under 30 good, 30 to 100 mediocre, 100 or
more bad, a clean genome 0) and the median missing bases (with its spread). Open below it,
what reads the same on three samples and on a hundred: Nextclade's QC score of each
consensus genome (the worst 40, log axis, coloured by verdict, with the 30 and 100 marks as
dashed lines), and the Pangolin table with its lineage record card (the Scorpio notes a cell
cuts short). Collapsed, because they compare samples with each other and say little on a run
of a few: the classification flow from Pangolin QC verdict to lineage to clade (ribbons
coloured by their target: on most runs every flow leaves the one verdict "pass"), the PCA of
the samples by the mutations they share, the UpSet of the mutations shared across lineages
(no annotation strip, which would list every mutation in its legend), and, in the preview
dashboard, the table of the mutations of a clicked intersection. Also collapsed: samples per
lineage and per clade (the eight largest, the rest as Other) and the Nextclade table.
Filters: lineage, clade and the two QC verdicts.

**Gene and Sample (preview dashboard `v2.yaml`).** The preview dashboard groups its tabs as
Data & QC, Mutations (Variants, Gene, Sample) and Typing (Lineage & Clustering). Gene and
Sample each open on one pick. The Gene picker starts on the gene holding the best supported
call (`default_by: call_score`, which never picks an intergenic pseudo-gene) and shows the
mutations of that gene along it (a lollipop) beside the allele frequency of its calls
sample by sample. The Sample picker starts on the best covered sample and shows its calls
along the genome with a record card for the picked call, then its depth along the genome.

## Routes and pruning

| Route | What changes |
|---|---|
| Nanopore (`platform: nanopore`) | The ivar variant tables are pruned: no Variants tab, PCA, UpSet or missense row. `summary_metrics` stays (the ARTIC summary has every column but `% Mapped reads`, left empty), so the Key figures, the persistent filters and the Sample sheet stay too. Coverage and typing read the ARTIC outputs. |
| A partial run (no caller output, no Pangolin) | The summary writes NA for the calls and the lineage: Variants per sample reads "–", the lineage filter in the left panel offers NA alone, and the Variants and Lineage & Clustering tabs are pruned. The Overview's bars and cards do not split by lineage. |
| No primer scheme (metagenomic) | No amplicon cards, tracks, heatmap or table; the Coverage strip keeps its two window cards, and the amplicon row leaves the Overview. |
| Non-SARS virus, `--skip_pangolin`, `--skip_nextclade` | No typing cards, QC score bars, flow or tables for the missing tool, and its Findings row and figure leave the Overview. |
| `--skip_variants_long_table` | No Variants tab, PCA, UpSet or missense row. |

The import re-packs the Overview grid after a drop, so a lone figure takes the full row.

Two tiles on one grid slot are route alternates only when no run keeps both: the import
packs them as one tile and draws whichever survives. The nanopore route writes no
collection the illumina route lacks (it repoints the same tags at `artic_minion/`), so its
Key figures read the same `summary_metrics` as the illumina route rather than alternates.

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
the allele frequency track and the PCA select points on it, and the Nextclade bars and the
Nextclade QC score bars select a sample.
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
